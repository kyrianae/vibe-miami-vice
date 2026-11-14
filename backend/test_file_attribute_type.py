"""Tests ciblés plan-mark3.md action 3 : types d'attribut file/image/csv
(POST /api/write/object/<id>/file/<attribute> multipart, GET /api/read/object
/<id>/file/<attribute>), détail de conception specifications/07-roadmap.md
§10.8.

Même convention que backend/test_model_driven_typing.py : pas de vraie base
Postgres, FakeDB/FakeCursor réutilisés tels quels (toutes les requêtes SQL du
chemin d'écriture sont identiques à write_attribute_value, déjà gérées par le
FakeCursor existant) ; seules trois requêtes nouvelles (lookup d'une version
historique précise, lecture tenant-scopée correcte de l'objet - le FakeCursor
partagé ignore le filtrage tenant/deleted_at sur cette requête, jamais exercé
par les tests existants -, et la requête de correspondance pointeur du sweep
d'orphelins routes_admin.py) sont ajoutées via une sous-classe locale.

FILE_STORAGE_ROOT isolé par test via tmp_path (même pattern que
test_file_storage.py).

Correction post-revue croisée (second passage) : tests pour la création
fusionnée objet+fichier(s) en une seule requête multipart (point A), les
noms de fichiers limites (point D1), la validation csv (point D2) et la
protection XML entity expansion sur SVG (point C) ; voir aussi
test_file_sweep_orphans.py pour le sweep de maintenance (point B).

Lancer avec, depuis la racine du dépôt :
    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/test_file_attribute_type.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import app as miami_app  # noqa: E402
import rbac as miami_rbac  # noqa: E402
from test_model_driven_typing import FakeDB, FakeCursor, FakeRealDictCursor, FakeConn, make_ctx  # noqa: E402


def _set_ctx(monkeypatch, **kwargs):
    """Monkeypatche la même AuthContext simulée des deux côtés : les routes
    d'écriture appellent `app.get_auth_context()` (relu dynamiquement,
    pattern documenté dans app.py), mais `_tenant_read_filter` (rbac.py,
    utilisé par les routes de lecture) appelle le nom `get_auth_context` de
    son PROPRE espace de noms module, jamais via `app.` - monkeypatcher
    seulement `miami_app.get_auth_context` laisserait la lecture utiliser le
    vrai rbac.get_auth_context() (fail-closed, g.auth_claims absent), d'où
    ce double monkeypatch plutôt qu'un seul."""
    ctx = make_ctx(**kwargs)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: ctx)
    monkeypatch.setattr(miami_rbac, "get_auth_context", lambda: ctx)


class FileFakeCursor(FakeCursor):
    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        params = params or ()

        # _build_object_payload (routes_read.py) : requête tenant-scopée,
        # ignorée par le FakeCursor partagé (jamais exercée par ses propres
        # tests) - réimplémentée ici correctement pour pouvoir vérifier
        # qu'un tenant hors périmètre ne peut pas lire un objet/fichier.
        if sql_norm.startswith("SELECT id, meta_class, class, tenants FROM object WHERE id = %s AND deleted_at IS NULL"):
            self._result = None
            self._results = None
            self.rowcount = 0
            obj = self.db.objects.get(params[0])
            if obj is None or obj.get("deleted_at") is not None:
                return
            if len(params) == 2:
                tenants_raw = obj.get("tenants")
                actor_tenants = set(params[1] or [])
                if tenants_raw and not (set(tenants_raw.split(",")) & actor_tenants):
                    return
            self._result = dict(obj)
            return

        # _find_pointer_for_version (routes_files.py) : historique complet
        # (actif + fermé) des pointeurs d'un attribut, nécessaire pour
        # retrouver le nom de fichier d'une version non active.
        if sql_norm.startswith("SELECT av.value_string FROM attribute a"):
            self._result = None
            self._results = None
            self.rowcount = 0
            object_id, name = params
            attr_ids = {
                a["id"] for a in self.db.attributes.values()
                if a["object_id"] == object_id and a["name"] == name
            }
            self._results = [
                (v["value_string"],) for v in self.db.attribute_values.values()
                if v["attribute_id"] in attr_ids and v.get("value_string") is not None
            ]
            return

        # _self_heal_broken_pointer (routes_files.py, plan-mark3.md action 4,
        # point 3) : ferme la valeur active d'UN attribut précis (object_id
        # ET name) UNIQUEMENT si son value_string correspond exactement au
        # pointeur qui a échoué en lecture (correction post-revue, bug 3 -
        # élimine la race où un pointeur réécrit entre-temps serait fermé
        # par erreur). À distinguer du garde-fou plus large de
        # delete_object (routes_write.py) qui ferme TOUS les attributs d'un
        # objet et ne prend qu'un seul paramètre - le préfixe SQL partagé
        # empêcherait un simple startswith de les distinguer, d'où cette
        # branche dédiée, testée AVANT de déléguer au FakeCursor générique.
        if sql_norm.startswith("UPDATE attribute_value av SET valid_to = now() FROM attribute a WHERE av.attribute_id = a.id AND a.object_id = %s AND a.name = %s AND av.valid_to IS NULL AND av.value_string = %s"):
            self._result = None
            self._results = None
            self.rowcount = 0
            object_id, name, failed_pointer = params
            attr_ids = {
                a["id"] for a in self.db.attributes.values()
                if a["object_id"] == object_id and a["name"] == name
            }
            for v in self.db.attribute_values.values():
                if v["attribute_id"] in attr_ids and v["valid_to"] is None and v.get("value_string") == failed_pointer:
                    v["valid_to"] = "now"
            return

        # sweep_orphan_files (routes_admin.py, point B) : existence d'une
        # ligne attribute_value (active OU fermée) dont le pointeur
        # correspond exactement à ce triplet (object_id, nom d'attribut).
        if sql_norm.startswith("SELECT 1 FROM attribute a JOIN attribute_value av ON av.attribute_id = a.id WHERE a.object_id = %s AND a.name = %s AND av.value_string = %s"):
            self._result = None
            self._results = None
            self.rowcount = 0
            object_id, name, pointer = params
            attr_ids = {
                a["id"] for a in self.db.attributes.values()
                if a["object_id"] == object_id and a["name"] == name
            }
            found = any(
                v["value_string"] == pointer for v in self.db.attribute_values.values()
                if v["attribute_id"] in attr_ids
            )
            self._result = (1,) if found else None
            return

        # sweep_orphan_files (routes_admin.py, point 3, plan-mark3.md action
        # 4) : existence d'un pointeur "ref:..." (référence croisée)
        # pointant sur ce fichier, PORTÉ PAR N'IMPORTE QUEL AUTRE objet/
        # attribut - recherche volontairement sans restriction object_id/
        # nom d'attribut, contrairement à la requête ci-dessus.
        if sql_norm.startswith("SELECT 1 FROM attribute_value WHERE value_string = %s LIMIT 1"):
            self._result = None
            self._results = None
            self.rowcount = 0
            (ref_pointer,) = params
            found = any(v["value_string"] == ref_pointer for v in self.db.attribute_values.values())
            self._result = (1,) if found else None
            return

        # list_logos (routes_files.py, plan-mark3.md action 4) : objets
        # actifs portant une valeur active sur un attribut nommé "logo",
        # filtrés par tenant comme les autres routes de lecture.
        if sql_norm.startswith("SELECT o.id, o.class, av.value_string FROM object o JOIN attribute a ON a.object_id = o.id AND a.name = 'logo'"):
            self._result = None
            self._results = None
            self.rowcount = 0
            tenant_filter = set(params[0]) if params else None
            rows = []
            for obj in self.db.objects.values():
                if obj.get("deleted_at") is not None:
                    continue
                if tenant_filter is not None:
                    tenants_raw = obj.get("tenants")
                    obj_tenants = set(tenants_raw.split(",")) if tenants_raw else set()
                    if obj_tenants and not (obj_tenants & tenant_filter):
                        continue
                for attr in self.db.attributes.values():
                    if attr["object_id"] != obj["id"] or attr["name"] != "logo":
                        continue
                    for v in self.db.attribute_values.values():
                        if v["attribute_id"] == attr["id"] and v["valid_to"] is None and v.get("value_string") is not None:
                            rows.append((obj["id"], obj["class"], v["value_string"]))
            rows.sort(key=lambda r: r[0])
            self._results = rows
            return

        super().execute(sql, params)


class FileFakeRealDictCursor(FileFakeCursor, FakeRealDictCursor):
    pass


class FileFakeConn(FakeConn):
    def cursor(self, cursor_factory=None):
        if cursor_factory is not None:
            return FileFakeRealDictCursor(self.db)
        return FileFakeCursor(self.db)


CLASSES = [
    {
        "class": "dossier",
        "attributes": [
            {"domain": "details", "name": "titre", "type": "string"},
            {"domain": "pieces", "name": "piece_jointe", "type": "file"},
            {"domain": "pieces", "name": "photo", "type": "image"},
            {"domain": "pieces", "name": "catalogue", "type": "csv"},
        ],
    },
    {
        # Classe dédiée aux tests de la création fusionnée objet+fichier
        # (point A) devant provoquer un échec APRÈS écriture d'un fichier
        # sur disque (attribut "age" entier, pour une valeur invalide) -
        # isolée de "dossier" pour ne pas affecter les tests existants.
        "class": "dossier_strict",
        "attributes": [
            {"domain": "details", "name": "titre", "type": "string"},
            {"domain": "details", "name": "age", "type": "integer"},
            {"domain": "pieces", "name": "photo", "type": "image"},
        ],
    },
]

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"reste-jpeg"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"reste-png"
SVG_WITH_SCRIPT = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
SVG_BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE svg [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<svg xmlns="http://www.w3.org/2000/svg">&lol4;</svg>
"""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(miami_app.app.before_request_funcs, None, [])
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


@pytest.fixture
def db_and_ctx(monkeypatch):
    db = FakeDB()
    db.seed_definition("classeur", CLASSES)
    monkeypatch.setattr(miami_app, "get_db", lambda: FileFakeConn(db))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))
    return db


@pytest.fixture(autouse=True)
def isolated_storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_ROOT", str(tmp_path))
    return tmp_path


def _create_dossier(client, tenants=None):
    body = {"meta_class": "classeur", "class": "dossier", "attributes": {"titre": "x"}}
    if tenants is not None:
        body["tenants"] = tenants
    resp = client.post("/api/write/object", json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


def _upload(client, object_id, attribute, filename, content, content_type="application/octet-stream"):
    from io import BytesIO
    return client.post(
        f"/api/write/object/{object_id}/file/{attribute}",
        data={"file": (BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


# ---------------------------------------------------------------------
# Round-trip upload/download
# ---------------------------------------------------------------------

def test_upload_download_round_trip_generic_file(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "piece_jointe", "rapport.txt", b"contenu du rapport")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["version"] == 1
    assert body["filename"] == "rapport.txt"
    assert body["value"] == "1:rapport.txt"

    get_resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe")
    assert get_resp.status_code == 200
    assert get_resp.data == b"contenu du rapport"
    assert get_resp.headers["Content-Disposition"].startswith("attachment")
    assert get_resp.headers["Content-Type"] == "application/octet-stream"


def test_upload_download_round_trip_jpeg_image_inline(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "avatar.jpg", JPEG_BYTES)
    assert resp.status_code == 200, resp.get_json()

    get_resp = client.get(f"/api/read/object/{object_id}/file/photo")
    assert get_resp.status_code == 200
    assert get_resp.data == JPEG_BYTES
    assert get_resp.headers["Content-Type"] == "image/jpeg"
    assert get_resp.headers["Content-Disposition"].startswith("inline")


def test_upload_download_round_trip_png_image_inline(client, db_and_ctx):
    object_id = _create_dossier(client)
    _upload(client, object_id, "photo", "avatar.png", PNG_BYTES)

    get_resp = client.get(f"/api/read/object/{object_id}/file/photo")
    assert get_resp.status_code == 200
    assert get_resp.headers["Content-Type"] == "image/png"
    assert get_resp.headers["Content-Disposition"].startswith("inline")


def test_upload_download_round_trip_csv(client, db_and_ctx):
    object_id = _create_dossier(client)
    content = b"a,b,c\n1,2,3\n"
    _upload(client, object_id, "catalogue", "data.csv", content)

    get_resp = client.get(f"/api/read/object/{object_id}/file/catalogue")
    assert get_resp.status_code == 200
    assert get_resp.data == content
    assert get_resp.headers["Content-Type"] == "text/csv"
    assert get_resp.headers["Content-Disposition"].startswith("attachment")


# ---------------------------------------------------------------------
# Versions multiples : historique conservé, valid_from/valid_to corrects.
# ---------------------------------------------------------------------

def test_multiple_versions_history_preserved_and_independently_readable(client, db_and_ctx):
    db = db_and_ctx
    object_id = _create_dossier(client)
    r1 = _upload(client, object_id, "piece_jointe", "v1.txt", b"contenu v1")
    assert r1.get_json()["version"] == 1
    r2 = _upload(client, object_id, "piece_jointe", "v2.txt", b"contenu v2")
    assert r2.get_json()["version"] == 2

    attr_ids = {a["id"] for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == "piece_jointe"}
    rows = sorted((v for v in db.attribute_values.values() if v["attribute_id"] in attr_ids), key=lambda v: v["id"])
    assert len(rows) == 2
    assert rows[0]["value_string"] == "1:v1.txt"
    assert rows[0]["valid_to"] == "now"
    assert rows[1]["value_string"] == "2:v2.txt"
    assert rows[1]["valid_to"] is None

    active = client.get(f"/api/read/object/{object_id}/file/piece_jointe")
    assert active.data == b"contenu v2"

    v1_resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe?version=1")
    assert v1_resp.status_code == 200
    assert v1_resp.data == b"contenu v1"

    v2_resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe?version=2")
    assert v2_resp.status_code == 200
    assert v2_resp.data == b"contenu v2"


def test_read_unknown_version_404(client, db_and_ctx):
    object_id = _create_dossier(client)
    _upload(client, object_id, "piece_jointe", "v1.txt", b"contenu v1")

    resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe?version=99")
    assert resp.status_code == 404


def test_read_unknown_attribute_404(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe")
    assert resp.status_code == 404


def test_read_unknown_object_404(client, db_and_ctx):
    resp = client.get("/api/read/object/999/file/piece_jointe")
    assert resp.status_code == 404


# ---------------------------------------------------------------------
# Limite de taille d'upload.
# ---------------------------------------------------------------------

def test_upload_rejected_when_size_exceeds_limit(client, db_and_ctx, monkeypatch):
    object_id = _create_dossier(client)
    monkeypatch.setitem(miami_app.app.config, "MAX_CONTENT_LENGTH", 20)

    resp = _upload(client, object_id, "piece_jointe", "gros.txt", b"x" * 1000)
    assert resp.status_code == 413


# ---------------------------------------------------------------------
# Validation stricte du type image.
# ---------------------------------------------------------------------

def test_image_upload_rejected_extension_not_allowed(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "notes.txt", b"plain text content")
    assert resp.status_code == 400
    assert "Extension" in resp.get_data(as_text=True)


def test_image_upload_rejected_content_mismatch_png_renamed_text(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "fake.png", b"this is not a real png file")
    assert resp.status_code == 400
    assert "signature" in resp.get_data(as_text=True).lower()


def test_image_upload_accepted_valid_jpeg_signature(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "ok.jpg", JPEG_BYTES)
    assert resp.status_code == 200, resp.get_json()


def test_image_upload_rejected_non_file_image_attribute_type_mismatch(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "titre", "ok.jpg", JPEG_BYTES)
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# SVG : accepté tel quel (pas de sanitization, décision assumée), mais
# toujours servi en Content-Disposition: attachment en lecture.
# ---------------------------------------------------------------------

def test_svg_with_script_accepted_but_served_as_attachment(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "logo.svg", SVG_WITH_SCRIPT)
    assert resp.status_code == 200, resp.get_json()

    get_resp = client.get(f"/api/read/object/{object_id}/file/photo")
    assert get_resp.status_code == 200
    assert get_resp.data == SVG_WITH_SCRIPT
    assert get_resp.headers["Content-Type"] == "image/svg+xml"
    assert get_resp.headers["Content-Disposition"].startswith("attachment")


def test_svg_malformed_xml_rejected(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "broken.svg", b"<svg><unclosed>")
    assert resp.status_code == 400


def test_svg_without_svg_root_rejected(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "notsvg.svg", b"<not-svg></not-svg>")
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# Lecture/écriture tenant-scopée.
# ---------------------------------------------------------------------

def test_write_rejected_for_tenant_admin_out_of_scope(client, db_and_ctx, monkeypatch):
    object_id = _create_dossier(client, tenants=["tenant1"])

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenant2"])
    resp = _upload(client, object_id, "piece_jointe", "x.txt", b"contenu")
    assert resp.status_code == 403


def test_write_allowed_for_tenant_admin_in_scope(client, db_and_ctx, monkeypatch):
    object_id = _create_dossier(client, tenants=["tenant1"])

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenant1"])
    resp = _upload(client, object_id, "piece_jointe", "x.txt", b"contenu")
    assert resp.status_code == 200, resp.get_json()


def test_read_rejected_for_tenant_out_of_scope_returns_404(client, db_and_ctx, monkeypatch):
    object_id = _create_dossier(client, tenants=["tenant1"])
    _upload(client, object_id, "piece_jointe", "x.txt", b"contenu")

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenant2"])
    resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe")
    assert resp.status_code == 404


def test_read_allowed_for_tenant_in_scope(client, db_and_ctx, monkeypatch):
    object_id = _create_dossier(client, tenants=["tenant1"])
    _upload(client, object_id, "piece_jointe", "x.txt", b"contenu")

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenant1"])
    resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe")
    assert resp.status_code == 200
    assert resp.data == b"contenu"


def test_write_rejected_for_tenant_readonly(client, db_and_ctx, monkeypatch):
    object_id = _create_dossier(client)
    _set_ctx(monkeypatch, is_tenant_readonly=True, tenants=["tenant1"])

    resp = _upload(client, object_id, "piece_jointe", "x.txt", b"contenu")
    assert resp.status_code == 403


# ---------------------------------------------------------------------
# Garde-fou : écriture JSON générique refusée sur un attribut file/image/csv
# (routes_write.py) - le pointeur ne doit être construit que par la route
# multipart dédiée, jamais reçu tel quel d'un appelant JSON.
# ---------------------------------------------------------------------

def test_write_object_json_rejected_on_file_type_attribute(client, db_and_ctx):
    resp = client.post("/api/write/object", json={
        "meta_class": "classeur", "class": "dossier",
        "attributes": {"titre": "x", "piece_jointe": "1:fake.txt"},
    })
    assert resp.status_code == 400


def test_write_attribute_value_json_rejected_on_file_type_attribute(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = client.put(f"/api/write/attribute/dossier/{object_id}/piece_jointe/1:fake.txt")
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# model/schema.json : "separator" accepté (optionnel) sur un attribut csv.
# ---------------------------------------------------------------------

def test_schema_accepts_separator_on_csv_attribute():
    import jsonschema
    from db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "csv", "separator": ";"}],
        }],
    }, schema=load_schema())


def test_schema_accepts_csv_attribute_without_separator():
    import jsonschema
    from db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "csv"}],
        }],
    }, schema=load_schema())


# ---------------------------------------------------------------------
# Correction post-revue croisée (second passage), point D1 : noms de
# fichiers limites -> 400 propre, jamais une 500 brute.
# ---------------------------------------------------------------------

def test_upload_filename_dot_rejected_400_not_500(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "piece_jointe", ".", b"contenu")
    assert resp.status_code == 400, resp.get_data(as_text=True)


def test_upload_filename_backslash_rejected_400_not_500(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "piece_jointe", "a\\b.txt", b"contenu")
    assert resp.status_code == 400, resp.get_data(as_text=True)


def test_upload_filename_empty_rejected_400(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "piece_jointe", "", b"contenu")
    assert resp.status_code == 400, resp.get_data(as_text=True)


# ---------------------------------------------------------------------
# Correction post-revue croisée, point D2 : validation du contenu csv
# (extension obligatoire + décodable en texte).
# ---------------------------------------------------------------------

def test_csv_upload_rejected_wrong_extension(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "catalogue", "data.txt", b"a,b,c\n1,2,3\n")
    assert resp.status_code == 400
    assert "Extension" in resp.get_data(as_text=True)


# Acceptation d'un csv utf-8 valide déjà couverte par le round-trip existant
# (test_upload_download_round_trip_csv, plus haut dans ce fichier).


# ---------------------------------------------------------------------
# Correction post-revue croisée, point C : parsing SVG via defusedxml,
# protection contre l'expansion d'entités XML ("billion laughs", CWE-776).
# ---------------------------------------------------------------------

def test_svg_billion_laughs_rejected_400_not_crash_or_timeout(client, db_and_ctx):
    object_id = _create_dossier(client)
    resp = _upload(client, object_id, "photo", "bomb.svg", SVG_BILLION_LAUGHS)
    assert resp.status_code == 400, resp.get_data(as_text=True)


# ---------------------------------------------------------------------
# Correction post-revue croisée, point A : création d'objet + fichier(s) en
# une seule requête multipart /api/write/object - évite la fenêtre
# "objet créé sans fichier" du flux JSON + upload séparé (retry = doublon).
# ---------------------------------------------------------------------

def test_create_object_with_file_single_multipart_request(client, db_and_ctx):
    from io import BytesIO
    metadata = {"meta_class": "classeur", "class": "dossier", "attributes": {"titre": "x"}}
    resp = client.post(
        "/api/write/object",
        data={"metadata": json.dumps(metadata), "photo": (BytesIO(JPEG_BYTES), "avatar.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    get_resp = client.get(f"/api/read/object/{object_id}/file/photo")
    assert get_resp.status_code == 200
    assert get_resp.data == JPEG_BYTES


def test_create_object_multipart_without_any_file_still_works(client, db_and_ctx):
    metadata = {"meta_class": "classeur", "class": "dossier", "attributes": {"titre": "sans fichier"}}
    resp = client.post(
        "/api/write/object",
        data={"metadata": json.dumps(metadata)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()


def test_create_object_multipart_missing_metadata_field_400(client, db_and_ctx):
    from io import BytesIO
    resp = client.post(
        "/api/write/object",
        data={"photo": (BytesIO(JPEG_BYTES), "avatar.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_create_object_multipart_rejects_id_field(client, db_and_ctx):
    object_id = _create_dossier(client)
    metadata = {"id": object_id, "meta_class": "classeur", "class": "dossier", "attributes": {"titre": "y"}}
    resp = client.post(
        "/api/write/object",
        data={"metadata": json.dumps(metadata)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_create_object_multipart_rejects_file_attribute_value_in_metadata(client, db_and_ctx):
    metadata = {
        "meta_class": "classeur", "class": "dossier",
        "attributes": {"titre": "x", "piece_jointe": "1:fake.txt"},
    }
    resp = client.post(
        "/api/write/object",
        data={"metadata": json.dumps(metadata)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_create_object_multipart_invalid_image_content_rejects_without_creating_object(client, db_and_ctx):
    from io import BytesIO
    metadata = {"meta_class": "classeur", "class": "dossier", "attributes": {"titre": "x"}}
    resp = client.post(
        "/api/write/object",
        data={"metadata": json.dumps(metadata), "photo": (BytesIO(b"not a real image"), "fake.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert b'"status": "ok"' not in resp.data


def test_create_object_multipart_failure_after_file_write_cleans_up_disk(client, db_and_ctx, isolated_storage_root):
    """Échec de la transaction APRÈS qu'un fichier a déjà été écrit sur
    disque (attribut scalaire invalide traité après les fichiers, voir
    _write_object_multipart) : le fichier déjà écrit est nettoyé best-effort
    (_cleanup_saved_files), jamais laissé orphelin par cette requête. Le
    FakeConn de ce fichier de test ne modélise pas un vrai ROLLBACK
    Postgres (rollback() est un no-op, comme pour le reste de la suite,
    cf. test_model_driven_typing.py) : seule l'absence du fichier sur le
    vrai système de fichiers est vérifiée ici, pas l'absence de la ligne
    `object` en base (non observable avec ce FakeConn)."""
    from io import BytesIO
    from file_storage import LocalFileStorage

    metadata = {
        "meta_class": "classeur", "class": "dossier_strict",
        "attributes": {"titre": "x", "age": "not-an-integer"},
    }
    resp = client.post(
        "/api/write/object",
        data={"metadata": json.dumps(metadata), "photo": (BytesIO(JPEG_BYTES), "avatar.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400, resp.get_data(as_text=True)

    storage = LocalFileStorage(root=str(isolated_storage_root))
    assert storage.list_all() == [], "fichier écrit avant l'échec de la transaction, jamais nettoyé"

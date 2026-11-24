"""Tests ciblés plan-mark3.md action 21bis : unicité de `attributes[].name`
au sein d'une classe + unicité de `class` au sein d'un même payload
`write_metaclass`, et résolution deny-priority de l'attr_def (secret
prioritaire) partout où un nom d'attribut ambigu (déclaré plusieurs fois,
directement ou via une classe elle-même dupliquée) pouvait auparavant
laisser gagner une déclaration non-secrète trouvée en premier - réplique,
sur les chemins écriture (`routes_write.py`), lecture d'objet et route
suggest (`routes_read.py`), et résolution de type fichier
(`routes_files.py`), du fix déjà prouvé sur `GET /api/search`
(`test_search_action_21.py`, revue 3 de l'action 21).

Section 6 (trou identifié après coup, sur ce même correctif 21bis) : les
garde-fous d'unicité `_check_attribute_names_unique` /
`_check_no_duplicate_class_names_in_payload` ne s'appliquaient qu'à
`write_class`/`write_metaclass`, jamais à `POST /api/init` (chargement direct
d'un fichier `model/*.json` dans la table `definition`, sans passer par ces
deux fonctions) - un fichier modèle sur le host avec un nom dupliqué
réintroduisait silencieusement la cause racine à l'écriture. Pattern de test
"fichier modèle temporaire" repris de `test_model_version_action_5.py` (MODEL_DIR
pointant vers `tmp_path`), FakeDB/FakeConn réutilisés tels quels (`INSERT INTO
definition` y gère déjà `ON CONFLICT`, cf. leur `startswith`).

Même convention que `test_attribute_type_secret.py`/`test_search_action_21.py` :
pas de vraie base Postgres, `FakeDB`/`FakeConn`/`make_ctx` réutilisés tels
quels depuis `test_model_driven_typing.py` (les requêtes SQL nécessaires ici
sont déjà toutes gérées par le socle commun) ; `FileFakeConn` réutilisé
depuis `test_file_attribute_type.py` pour les deux tests touchant
`routes_files.py`. SCHEMA_PATH doit pointer vers le vrai `model/schema.json`
du dépôt.

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_security_action_21bis.py -v
"""
import json
import os
import sys
from io import BytesIO

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as miami_app  # noqa: E402
import auth.rbac as miami_rbac  # noqa: E402
from test_model_driven_typing import FakeDB, FakeConn, make_ctx  # noqa: E402
from test_file_attribute_type import FileFakeConn, JPEG_BYTES  # noqa: E402


@pytest.fixture(autouse=True)
def secret_key_env(monkeypatch):
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(miami_app.app.before_request_funcs, None, [])
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


def _set_ctx(monkeypatch, **kwargs):
    """Double monkeypatch (même pattern que test_attribute_autosuggest.py/
    test_file_attribute_type.py) : les routes d'écriture lisent
    `app.get_auth_context()`, mais `_tenant_read_filter` (routes de lecture)
    lit le nom `get_auth_context` de son PROPRE espace de noms (rbac.py)."""
    ctx = make_ctx(**kwargs)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: ctx)
    monkeypatch.setattr(miami_rbac, "get_auth_context", lambda: ctx)


def _make_db(monkeypatch, **ctx_kwargs):
    db = FakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(db))
    _set_ctx(monkeypatch, **ctx_kwargs)
    return db


def _value_rows(db, object_id, attr_name):
    attr_ids = {a["id"] for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == attr_name}
    return sorted(
        (v for v in db.attribute_values.values() if v["attribute_id"] in attr_ids),
        key=lambda v: v["id"],
    )


# =======================================================================
# 1. Chemin d'écriture (routes_write.py, _coerce_typed_value) : un nom
#    d'attribut déclaré deux fois (une fois non-secret, une fois secret) ou
#    une classe déclarée deux fois dans la même meta-classe ne doit jamais
#    laisser stocker la valeur en clair. Seedé directement via
#    db.seed_definition (simule un schéma déjà en base avant le correctif de
#    blocage à l'écriture, cf. point 4 du plan - aucune migration requise).
# =======================================================================

DUP_ATTR_WRITE_CLASSES = [
    {
        "class": "compte_dup_write",
        "attributes": [
            # Non-secret déclaré EN PREMIER : l'ancienne résolution
            # "première déclaration gagne" aurait stocké en clair.
            {"domain": "details", "name": "pw", "type": "string"},
            {"domain": "details", "name": "pw", "type": "secret"},
        ],
    },
]


def test_write_object_encrypts_value_when_duplicate_attribute_name_has_secret_declaration(client, monkeypatch):
    db = _make_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite_dup_write", DUP_ATTR_WRITE_CLASSES)

    resp = client.post("/api/write/object", json={
        "meta_class": "securite_dup_write", "class": "compte_dup_write",
        "attributes": {"pw": "hunter2"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    rows = _value_rows(db, object_id, "pw")
    assert len(rows) == 1
    assert rows[0]["value_string"] != "hunter2"
    assert "hunter2" not in rows[0]["value_string"]


DUP_CLASS_WRITE_CLASSES = [
    {"class": "compte_twice_write", "attributes": [{"domain": "details", "name": "secretfield", "type": "string"}]},
    {"class": "compte_twice_write", "attributes": [{"domain": "details", "name": "secretfield", "type": "secret"}]},
]


def test_write_object_encrypts_value_when_class_declared_twice_one_secret(client, monkeypatch):
    db = _make_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite_twice_write", DUP_CLASS_WRITE_CLASSES)

    resp = client.post("/api/write/object", json={
        "meta_class": "securite_twice_write", "class": "compte_twice_write",
        "attributes": {"secretfield": "hunter2"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    rows = _value_rows(db, object_id, "secretfield")
    assert len(rows) == 1
    assert rows[0]["value_string"] != "hunter2"
    assert "hunter2" not in rows[0]["value_string"]


def test_write_attribute_url_route_denies_when_duplicate_attribute_name_has_secret_declaration(client, monkeypatch):
    """PUT /api/write/attribute/.../<value> doit refuser (400) dès qu'une
    déclaration `secret` existe pour ce nom, même si une autre déclaration
    non-secrète du même nom existe aussi - jamais un contournement de
    l'interdiction d'écrire un secret par l'URL via la déclaration
    non-secrète trouvée en premier."""
    db = _make_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite_url_dup", [
        {
            "class": "compte_url_dup",
            "attributes": [
                {"domain": "details", "name": "pw", "type": "string"},
                {"domain": "details", "name": "pw", "type": "secret"},
            ],
        },
    ])

    resp = client.post("/api/write/object", json={
        "meta_class": "securite_url_dup", "class": "compte_url_dup", "attributes": {},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/compte_url_dup/{object_id}/pw/leaked-via-url")
    assert put.status_code == 400
    assert "secret" in put.get_data(as_text=True)
    assert _value_rows(db, object_id, "pw") == []


# =======================================================================
# 2. Lecture d'objet (GET /api/read/object/<id>, _build_object_payload) :
#    masquage correct même quand la classe est déclarée deux fois (une
#    occurrence non-secrète, l'autre secrète) - intègre à la fois le fix
#    écriture (ci-dessus) et le fix masquage (_secret_attribute_names).
# =======================================================================

def test_read_object_masks_secret_when_class_declared_twice(client, monkeypatch):
    db = _make_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite_read_twice", DUP_CLASS_WRITE_CLASSES)

    resp = client.post("/api/write/object", json={
        "meta_class": "securite_read_twice", "class": "compte_twice_write",
        "attributes": {"secretfield": "hunter2"},
    })
    object_id = resp.get_json()["id"]

    read = client.get(f"/api/read/object/{object_id}")
    assert read.status_code == 200, read.get_json()
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "secretfield")
    assert values == ["••••••••"]
    body_text = read.get_data(as_text=True)
    assert "hunter2" not in body_text


def test_reveal_secret_resolves_correctly_when_class_declared_twice(client, monkeypatch):
    """Contrepartie en lecture du fix d'écriture : la route reveal doit
    reconnaître le type `secret` même quand la déclaration secrète n'est pas
    la première occurrence de la classe rencontrée (sans quoi un secret
    réellement chiffré en base deviendrait, à tort, indéchiffrable par
    global-admin)."""
    db = _make_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite_reveal_twice", DUP_CLASS_WRITE_CLASSES)

    resp = client.post("/api/write/object", json={
        "meta_class": "securite_reveal_twice", "class": "compte_twice_write",
        "attributes": {"secretfield": "hunter2"},
    })
    object_id = resp.get_json()["id"]

    reveal = client.get(f"/api/read/object/{object_id}/secret/secretfield")
    assert reveal.status_code == 200, reveal.get_json()
    assert reveal.get_json()["value"] == "hunter2"


# =======================================================================
# 3. Route suggest (GET /api/suggest/<meta>/<class>/<attribute>) :
#    masquage/refus correct (400, jamais les valeurs stockées) dès qu'une
#    déclaration `secret` existe pour ce nom - attribut dupliqué ou classe
#    dupliquée.
# =======================================================================

DUP_ATTR_SUGGEST_CLASSES = [
    {
        "class": "site_dup_suggest",
        "attributes": [
            {"domain": "details", "name": "ville", "type": "string", "autosuggest": True},
            {"domain": "details", "name": "ville", "type": "secret"},
        ],
    },
]


def test_suggest_rejects_when_duplicate_attribute_name_has_secret_declaration(client, monkeypatch):
    db = _make_db(monkeypatch, is_global_admin=True)
    db.seed_definition("cmdb_dup_suggest", DUP_ATTR_SUGGEST_CLASSES)

    resp = client.get("/api/suggest/cmdb_dup_suggest/site_dup_suggest/ville")
    assert resp.status_code == 400


DUP_CLASS_SUGGEST_CLASSES = [
    {"class": "site_twice_suggest", "attributes": [{"domain": "d", "name": "ville", "type": "string", "autosuggest": True}]},
    {"class": "site_twice_suggest", "attributes": [{"domain": "d", "name": "ville", "type": "secret"}]},
]


def test_suggest_rejects_when_class_declared_twice_one_secret(client, monkeypatch):
    db = _make_db(monkeypatch, is_global_admin=True)
    db.seed_definition("cmdb_twice_suggest", DUP_CLASS_SUGGEST_CLASSES)

    resp = client.get("/api/suggest/cmdb_twice_suggest/site_twice_suggest/ville")
    assert resp.status_code == 400


# =======================================================================
# 4. Blocage à l'écriture (nouveau, cause racine) : POST avec un attribut
#    dupliqué dans une classe -> 409 ; POST avec une classe dupliquée dans
#    un seul payload write_metaclass -> 409. Même code d'erreur que
#    _check_class_name_unique (action 22).
# =======================================================================

def test_write_metaclass_rejects_duplicate_attribute_name_in_same_class(client, monkeypatch):
    store = FakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    _set_ctx(monkeypatch, is_global_admin=True)

    resp = client.post("/api/write/metaclass", json={
        "meta_class": "mc_attr_dup",
        "classes": [
            {
                "class": "cls1",
                "attributes": [
                    {"domain": "d", "name": "pw", "type": "string"},
                    {"domain": "d", "name": "pw", "type": "secret"},
                ],
            },
        ],
    })
    assert resp.status_code == 409
    assert "mc_attr_dup" not in store.definitions


def test_write_metaclass_rejects_duplicate_class_name_in_same_payload(client, monkeypatch):
    store = FakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    _set_ctx(monkeypatch, is_global_admin=True)

    resp = client.post("/api/write/metaclass", json={
        "meta_class": "mc_class_dup",
        "classes": [
            {"class": "cls_twice", "attributes": [{"domain": "d", "name": "a", "type": "string"}]},
            {"class": "cls_twice", "attributes": [{"domain": "d", "name": "b", "type": "secret"}]},
        ],
    })
    assert resp.status_code == 409
    assert "mc_class_dup" not in store.definitions


def test_write_class_rejects_duplicate_attribute_name_in_payload(client, monkeypatch):
    store = FakeDB()
    store.seed_definition("mc_wc", [])
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    _set_ctx(monkeypatch, is_global_admin=True)

    resp = client.post("/api/write/class", json={
        "meta_class": "mc_wc",
        "class": {
            "class": "cls_dup_attr",
            "attributes": [
                {"domain": "d", "name": "pw", "type": "string"},
                {"domain": "d", "name": "pw", "type": "secret"},
            ],
        },
    })
    assert resp.status_code == 409
    assert "pw" in resp.get_data(as_text=True)


# =======================================================================
# 5. routes_files.py : `_lookup_attr_type` (plan-mark3.md action 21bis,
#    point 4 du plan) résolu via la même fonction deny-priority, et une
#    classe dupliquée où l'attribut fichier n'est déclaré que dans la 2e
#    occurrence doit désormais être correctement reconnue (régression
#    fonctionnelle corrigée, pas seulement une fuite bouchée).
# =======================================================================

DUP_ATTR_FILE_LOOKUP_CLASSES = [
    {
        "class": "doc_dup_lookup",
        "attributes": [
            {"domain": "d", "name": "photo", "type": "image"},
            {"domain": "d", "name": "photo", "type": "secret"},
        ],
    },
]


def test_lookup_attr_type_deny_priority_secret_wins_over_image():
    from routes.routes_files import _lookup_attr_type

    db = FakeDB()
    db.seed_definition("fileclass_dup", DUP_ATTR_FILE_LOOKUP_CLASSES)
    conn = FakeConn(db)
    assert _lookup_attr_type(conn, "fileclass_dup", "doc_dup_lookup", "photo") == "secret"


DUP_CLASS_FILE_UPLOAD_CLASSES = [
    {"class": "dossier_dup_upload", "attributes": [{"domain": "details", "name": "titre", "type": "string"}]},
    {"class": "dossier_dup_upload", "attributes": [{"domain": "pieces", "name": "photo", "type": "image"}]},
]


@pytest.fixture
def file_db_and_ctx(monkeypatch):
    db = FakeDB()
    db.seed_definition("classeur_dup_upload", DUP_CLASS_FILE_UPLOAD_CLASSES)
    monkeypatch.setattr(miami_app, "get_db", lambda: FileFakeConn(db))
    _set_ctx(monkeypatch, is_global_admin=True)
    return db


@pytest.fixture(autouse=True)
def isolated_storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_ROOT", str(tmp_path))
    return tmp_path


def test_write_object_file_resolves_attribute_declared_only_in_second_duplicate_class_occurrence(client, file_db_and_ctx):
    resp = client.post("/api/write/object", json={
        "meta_class": "classeur_dup_upload", "class": "dossier_dup_upload",
        "attributes": {"titre": "x"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    upload = client.post(
        f"/api/write/object/{object_id}/file/photo",
        data={"file": (BytesIO(JPEG_BYTES), "photo.jpg")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200, upload.get_json()


# =======================================================================
# 6. POST /api/init (trou identifié après coup) : un fichier model/*.json
#    avec un attribut dupliqué dans une classe, ou une classe dupliquée dans
#    le même fichier, doit être skippé (jamais chargé, jamais persisté),
#    sans jamais avorter tout le batch multi-fichiers.
# =======================================================================

def _write_model_file(tmp_path, filename, content):
    (tmp_path / filename).write_text(json.dumps(content))


def test_init_skips_file_with_duplicate_attribute_name_in_a_class(client, monkeypatch, tmp_path):
    _write_model_file(tmp_path, "securite_init_dup_attr.json", {
        "meta_class": "securite_init_dup_attr",
        "classes": [
            {
                "class": "compte_init_dup_attr",
                "attributes": [
                    {"domain": "d", "name": "pw", "type": "string"},
                    {"domain": "d", "name": "pw", "type": "secret"},
                ],
            },
        ],
    })

    store = FakeDB()
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    _set_ctx(monkeypatch, is_global_admin=True)

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == []
    assert "securite_init_dup_attr" not in body["versions"]
    assert len(body["skipped"]) == 1
    entry = body["skipped"][0]
    assert entry["meta_class"] == "securite_init_dup_attr"
    assert entry["class"] == "compte_init_dup_attr"
    assert "pw" in entry["reason"]
    assert "securite_init_dup_attr" not in store.definitions


def test_init_skips_file_with_duplicate_class_name_in_same_file(client, monkeypatch, tmp_path):
    _write_model_file(tmp_path, "securite_init_dup_class.json", {
        "meta_class": "securite_init_dup_class",
        "classes": [
            {"class": "compte_init_dup_class", "attributes": [{"domain": "d", "name": "a", "type": "string"}]},
            {"class": "compte_init_dup_class", "attributes": [{"domain": "d", "name": "b", "type": "secret"}]},
        ],
    })

    store = FakeDB()
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    _set_ctx(monkeypatch, is_global_admin=True)

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == []
    assert "securite_init_dup_class" not in body["versions"]
    assert len(body["skipped"]) == 1
    entry = body["skipped"][0]
    assert entry["meta_class"] == "securite_init_dup_class"
    assert "compte_init_dup_class" in entry["reason"]
    assert "securite_init_dup_class" not in store.definitions


def test_init_does_not_abort_other_files_when_one_file_has_duplicate_names(client, monkeypatch, tmp_path):
    _write_model_file(tmp_path, "securite_init_dup_attr_batch.json", {
        "meta_class": "securite_init_dup_attr_batch",
        "classes": [
            {
                "class": "compte_init_dup_attr_batch",
                "attributes": [
                    {"domain": "d", "name": "pw", "type": "string"},
                    {"domain": "d", "name": "pw", "type": "secret"},
                ],
            },
        ],
    })
    _write_model_file(tmp_path, "securite_init_ok_batch.json", {
        "meta_class": "securite_init_ok_batch",
        "classes": [
            {"class": "compte_init_ok_batch", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    store = FakeDB()
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    _set_ctx(monkeypatch, is_global_admin=True)

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == ["securite_init_ok_batch"]
    assert "securite_init_dup_attr_batch" not in store.definitions
    assert "securite_init_ok_batch" in store.definitions

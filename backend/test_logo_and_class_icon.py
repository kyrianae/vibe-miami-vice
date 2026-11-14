"""Tests ciblés plan-mark3.md action 4 (logo surchargeable par objet et
icône par défaut par classe) ; détail de conception :
specifications/07-roadmap.md §10.8.

Réutilise le harnais de test_file_attribute_type.py (FileFakeConn/
FileFakeCursor, fixtures client/db_and_ctx/isolated_storage_root, classe
"dossier" avec l'attribut image "photo") pour les mécanismes de référence
croisée/auto-réparation - attribute-name-agnostiques en pratique (la
convention de nommage "logo"/domaine "display" n'est qu'une convention de
modèle, pas une contrainte du code de routes_files.py). Une meta-classe
dédiée avec un VRAI attribut nommé "logo" est seedée séparément pour les
tests de /api/logos, qui filtre spécifiquement a.name = 'logo'.

Lancer avec, depuis la racine du dépôt :
    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/test_logo_and_class_icon.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import app as miami_app  # noqa: E402
import rbac as miami_rbac  # noqa: E402
from test_model_driven_typing import make_ctx  # noqa: E402
from test_file_attribute_type import (  # noqa: E402,F401
    client,
    db_and_ctx,
    isolated_storage_root,
    _create_dossier,
    _upload,
    JPEG_BYTES,
    PNG_BYTES,
)


def _set_ctx(monkeypatch, **kwargs):
    ctx = make_ctx(**kwargs)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: ctx)
    monkeypatch.setattr(miami_rbac, "get_auth_context", lambda: ctx)


# ---------------------------------------------------------------------
# class_icon.py : génération du SVG de secours (rond + initiales).
# ---------------------------------------------------------------------

def test_fallback_icon_is_well_formed_svg():
    import defusedxml.ElementTree as ET
    from class_icon import generate_class_fallback_icon

    svg = generate_class_fallback_icon("serveur")
    assert svg.startswith("<svg")
    root = ET.fromstring(svg)
    assert root.tag.rsplit("}", 1)[-1] == "svg"


def test_fallback_icon_deterministic_same_class_same_result():
    from class_icon import generate_class_fallback_icon

    first = generate_class_fallback_icon("application")
    second = generate_class_fallback_icon("application")
    assert first == second


def test_fallback_icon_color_deterministic_across_fresh_memory_cache():
    from class_icon import _color_for_class

    assert _color_for_class("serveur") == _color_for_class("serveur")


def test_fallback_icon_uses_initials_for_long_class_name():
    from class_icon import _initials_for_class

    assert _initials_for_class("base_de_donnees") == "BD"
    assert _initials_for_class("srv") == "SRV"


def test_fallback_icon_cached_on_disk(isolated_storage_root):
    from class_icon import generate_class_fallback_icon, _cache_file_path

    generate_class_fallback_icon("contrat_support")
    cache_path = _cache_file_path("contrat_support")
    assert os.path.isfile(cache_path)


def test_fallback_icon_route_serves_svg_for_known_class(client, db_and_ctx):
    resp = client.get("/api/class_icon/classeur/dossier")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("image/svg+xml")
    assert b"<svg" in resp.data


def test_fallback_icon_route_404_unknown_class(client, db_and_ctx):
    resp = client.get("/api/class_icon/classeur/inconnue")
    assert resp.status_code == 404


def test_fallback_icon_route_404_unknown_metaclass(client, db_and_ctx):
    resp = client.get("/api/class_icon/inconnue/dossier")
    assert resp.status_code == 404


# ---------------------------------------------------------------------
# model/schema.json : champ optionnel "icon" sur une classe.
# ---------------------------------------------------------------------

def test_schema_accepts_icon_field_on_class():
    import jsonschema
    from db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{"class": "c", "icon": "server", "attributes": [{"domain": "d", "name": "n", "type": "string"}]}],
    }, schema=load_schema())


def test_real_itil_cmdb_model_includes_valid_icon_and_logo():
    import json
    import jsonschema
    from db import load_schema

    model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model", "itil_cmdb.json")
    with open(model_path) as f:
        data = json.load(f)
    data.pop("$schema", None)
    jsonschema.validate(instance=data, schema=load_schema())

    serveur = next(c for c in data["classes"] if c["class"] == "serveur")
    assert serveur["icon"] == "server"
    assert any(a["name"] == "logo" and a["type"] == "image" and a["domain"] == "display" for a in serveur["attributes"])


# ---------------------------------------------------------------------
# Référence croisée (plan-mark3.md action 4, point 3) : attribute_value
# d'un objet B pointe vers (classe, object_id, attribut, version) de A,
# jamais une duplication d'octets. Mécanique attribute-name-agnostique :
# exercée ici sur l'attribut image "photo" de la classe "dossier".
# ---------------------------------------------------------------------

def test_write_object_file_reference_round_trip(client, db_and_ctx):
    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    b = _create_dossier(client)

    resp = client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 1},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["value"] == "ref:dossier:%d:photo:1:logo_a.jpg" % a

    get_resp = client.get(f"/api/read/object/{b}/file/photo")
    assert get_resp.status_code == 200
    assert get_resp.data == JPEG_BYTES
    assert get_resp.headers["Content-Type"] == "image/jpeg"


def test_write_object_file_reference_flattens_existing_reference_chain(client, db_and_ctx):
    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.png", PNG_BYTES)
    b = _create_dossier(client)
    client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 1},
    )
    c = _create_dossier(client)

    # C référence B, qui lui-même référence A : le pointeur stocké sur C
    # doit pointer directement sur A (aplati), jamais sur B.
    resp = client.post(
        f"/api/write/object/{c}/file/photo/reference",
        json={"class": "dossier", "object_id": b, "attribute": "photo", "version": 1},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["value"] == "ref:dossier:%d:photo:1:logo_a.png" % a

    get_resp = client.get(f"/api/read/object/{c}/file/photo")
    assert get_resp.status_code == 200
    assert get_resp.data == PNG_BYTES


def test_write_object_file_reference_unknown_source_version_400(client, db_and_ctx):
    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    b = _create_dossier(client)

    resp = client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 99},
    )
    assert resp.status_code == 400


def test_write_object_file_reference_missing_fields_400(client, db_and_ctx):
    b = _create_dossier(client)
    resp = client.post(f"/api/write/object/{b}/file/photo/reference", json={"class": "dossier"})
    assert resp.status_code == 400


def test_write_object_file_reference_rejected_for_tenant_readonly(client, db_and_ctx, monkeypatch):
    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    b = _create_dossier(client)

    _set_ctx(monkeypatch, is_tenant_readonly=True, tenants=["tenant1"])
    resp = client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 1},
    )
    assert resp.status_code == 403


def test_write_object_file_reference_source_out_of_tenant_scope_404(client, db_and_ctx, monkeypatch):
    a = _create_dossier(client, tenants=["tenant1"])
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    b = _create_dossier(client, tenants=["tenant2"])

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenant2"])
    resp = client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 1},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------
# Purge référence-consciente (routes_admin.py, sweep_orphan_files) : le
# fichier physique de A n'est jamais supprimé tant que B le référence,
# même quand A n'a plus lui-même de ligne attribute_value propre pointant
# dessus (simulation d'une purge physique complète de A via /api/purge -
# le FakeDB de ce module ne modélise pas le CASCADE SQL réel d'un DELETE
# FROM object, donc la ligne attribute_value propre à A est retirée
# directement du store ici, pour représenter l'état "après purge de A",
# cf. sql/init.sql : FOREIGN KEY attribute_id ... ON DELETE CASCADE).
# ---------------------------------------------------------------------

def test_sweep_keeps_file_referenced_by_another_object_even_after_owner_purged(client, db_and_ctx, isolated_storage_root):
    db = db_and_ctx
    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    b = _create_dossier(client)
    client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 1},
    )

    # Simule la purge physique complète de A (DELETE FROM object CASCADE) :
    # ses propres lignes attribute/attribute_value disparaissent du store,
    # celles de B (qui portent le pointeur "ref:...") restent intactes.
    a_attr_ids = {attr["id"] for attr in db.attributes.values() if attr["object_id"] == a}
    for vid in [vid for vid, v in db.attribute_values.items() if v["attribute_id"] in a_attr_ids]:
        del db.attribute_values[vid]
    for attr_id in list(a_attr_ids):
        del db.attributes[attr_id]
    del db.objects[a]

    sweep_resp = client.post("/api/admin/sweep_orphan_files")
    assert sweep_resp.status_code == 200, sweep_resp.get_data(as_text=True)
    assert sweep_resp.get_json()["purged"] == [], "fichier supprimé alors que B le référence encore"

    get_resp = client.get(f"/api/read/object/{b}/file/photo")
    assert get_resp.status_code == 200
    assert get_resp.data == JPEG_BYTES


def test_sweep_removes_file_once_no_reference_remains(client, db_and_ctx, isolated_storage_root):
    db = db_and_ctx
    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)

    a_attr_ids = {attr["id"] for attr in db.attributes.values() if attr["object_id"] == a}
    for vid in [vid for vid, v in db.attribute_values.items() if v["attribute_id"] in a_attr_ids]:
        del db.attribute_values[vid]
    for attr_id in list(a_attr_ids):
        del db.attributes[attr_id]
    del db.objects[a]

    sweep_resp = client.post("/api/admin/sweep_orphan_files")
    assert sweep_resp.status_code == 200
    purged = sweep_resp.get_json()["purged"]
    assert len(purged) == 1
    assert purged[0]["filename"] == "logo_a.jpg"


# ---------------------------------------------------------------------
# Garde-fou d'auto-réparation (plan-mark3.md action 4, point 3) : fichier
# introuvable sur le storage (référence cassée) -> 404 ET nettoyage côté
# serveur de la valeur active de l'OBJET AFFICHÉ (pas de la source).
# ---------------------------------------------------------------------

def test_read_self_heals_when_referenced_file_missing_on_disk(client, db_and_ctx):
    from file_storage import LocalFileStorage

    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    b = _create_dossier(client)
    client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 1},
    )

    # Supprime physiquement le fichier de A sur disque, sans toucher à la
    # base - simule une suppression manuelle/anormale hors du chemin de
    # purge sécurisé (sweep_orphan_files).
    LocalFileStorage().delete("dossier", a, "photo", version=1)

    get_resp = client.get(f"/api/read/object/{b}/file/photo")
    assert get_resp.status_code == 404

    read_b = client.get(f"/api/read/object/{b}").get_json()
    photo_attr = next((attr for attr in read_b["attributes"] if attr["name"] == "photo"), None)
    assert photo_attr is None or photo_attr["values"] == [], "attribute_value de B pas nettoyé après référence cassée"


def test_read_self_heal_does_not_touch_source_object(client, db_and_ctx):
    from file_storage import LocalFileStorage

    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    b = _create_dossier(client)
    client.post(
        f"/api/write/object/{b}/file/photo/reference",
        json={"class": "dossier", "object_id": a, "attribute": "photo", "version": 1},
    )
    LocalFileStorage().delete("dossier", a, "photo", version=1)
    client.get(f"/api/read/object/{b}/file/photo")

    read_a = client.get(f"/api/read/object/{a}").get_json()
    photo_attr = next((attr for attr in read_a["attributes"] if attr["name"] == "photo"), None)
    assert photo_attr is not None and photo_attr["values"] == ["1:logo_a.jpg"], \
        "l'objet SOURCE ne doit jamais être modifié par l'auto-réparation de l'objet affiché"


def test_read_direct_pointer_missing_file_still_self_heals(client, db_and_ctx):
    """Non-régression : le garde-fou s'applique aussi à un pointeur DIRECT
    (pas seulement une référence croisée) - cas déjà couvert implicitement
    par le comportement 404 existant, vérifié ici explicitement avec le
    nettoyage ajouté par cette action."""
    from file_storage import LocalFileStorage

    a = _create_dossier(client)
    _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    LocalFileStorage().delete("dossier", a, "photo", version=1)

    get_resp = client.get(f"/api/read/object/{a}/file/photo")
    assert get_resp.status_code == 404

    read_a = client.get(f"/api/read/object/{a}").get_json()
    photo_attr = next((attr for attr in read_a["attributes"] if attr["name"] == "photo"), None)
    assert photo_attr is None or photo_attr["values"] == []


def test_self_heal_does_not_close_pointer_rewritten_concurrently(client, db_and_ctx):
    """Correction post-revue (bug 3) : _self_heal_broken_pointer ne doit
    fermer QUE le pointeur exact qui a échoué en lecture, jamais "la" valeur
    active au moment de l'appel sans vérification - sinon un nouveau
    pointeur valide, réécrit par un autre appelant entre l'échec de lecture
    et cet appel, serait fermé par erreur. Simule la race directement :
    appelle _self_heal_broken_pointer avec l'ANCIEN pointeur après qu'une
    réécriture légitime (nouvelle version) a déjà eu lieu."""
    from routes_files import _self_heal_broken_pointer

    a = _create_dossier(client)
    first = _upload(client, a, "photo", "logo_a.jpg", JPEG_BYTES)
    assert first.status_code == 200
    old_pointer = first.get_json()["value"]

    second = _upload(client, a, "photo", "logo_b.png", PNG_BYTES)
    assert second.status_code == 200
    new_pointer = second.get_json()["value"]
    assert new_pointer != old_pointer

    conn = miami_app.get_db()
    _self_heal_broken_pointer(conn, a, "photo", old_pointer)

    read_a = client.get(f"/api/read/object/{a}").get_json()
    photo_attr = next((attr for attr in read_a["attributes"] if attr["name"] == "photo"), None)
    assert photo_attr is not None and photo_attr["values"] == [new_pointer], \
        "self-heal a fermé par erreur le nouveau pointeur valide (race, bug 3)"


# ---------------------------------------------------------------------
# GET /api/logos : liste des objets "à logo" (attribut réservé "logo").
# Meta-classe dédiée seedée séparément (filtre backend a.name = 'logo').
# ---------------------------------------------------------------------

LOGO_CLASSES = [
    {
        "class": "fournisseur_test",
        "attributes": [
            {"domain": "details", "name": "nom", "type": "string"},
            {"domain": "display", "name": "logo", "type": "image"},
        ],
    },
]


@pytest.fixture
def logo_seeded(db_and_ctx):
    db_and_ctx.seed_definition("societe_test", LOGO_CLASSES)
    return db_and_ctx


def _create_fournisseur(client, tenants=None):
    body = {"meta_class": "societe_test", "class": "fournisseur_test", "attributes": {"nom": "x"}}
    if tenants is not None:
        body["tenants"] = tenants
    resp = client.post("/api/write/object", json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


def test_list_logos_returns_active_logo_entries(client, logo_seeded):
    f1 = _create_fournisseur(client)
    _upload(client, f1, "logo", "logo1.png", PNG_BYTES)
    f2 = _create_fournisseur(client)

    resp = client.get("/api/logos")
    assert resp.status_code == 200
    entries = resp.get_json()
    assert len(entries) == 1
    assert entries[0]["class"] == "fournisseur_test"
    assert entries[0]["object_id"] == f1
    assert entries[0]["attribute"] == "logo"
    assert entries[0]["version"] == 1
    assert entries[0]["filename"] == "logo1.png"
    assert entries[0]["display_name"] == f"fournisseur_test #{f1}"
    assert f2 not in [e["object_id"] for e in entries]


def test_list_logos_exposes_physical_source_for_a_reference(client, logo_seeded):
    f1 = _create_fournisseur(client)
    _upload(client, f1, "logo", "logo1.png", PNG_BYTES)
    f2 = _create_fournisseur(client)
    client.post(
        f"/api/write/object/{f2}/file/logo/reference",
        json={"class": "fournisseur_test", "object_id": f1, "attribute": "logo", "version": 1},
    )

    resp = client.get("/api/logos")
    entries = resp.get_json()
    assert len(entries) == 2
    physical_sources = {e["object_id"] for e in entries}
    assert physical_sources == {f1}
    display_names = {e["display_name"] for e in entries}
    assert display_names == {f"fournisseur_test #{f1}", f"fournisseur_test #{f2}"}


def test_list_logos_rbac_filtered_by_tenant(client, logo_seeded, monkeypatch):
    f1 = _create_fournisseur(client, tenants=["tenant1"])
    _upload(client, f1, "logo", "logo1.png", PNG_BYTES)
    f2 = _create_fournisseur(client, tenants=["tenant2"])
    _upload(client, f2, "logo", "logo2.png", PNG_BYTES)

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenant1"])
    resp = client.get("/api/logos")
    entries = resp.get_json()
    assert [e["object_id"] for e in entries] == [f1]

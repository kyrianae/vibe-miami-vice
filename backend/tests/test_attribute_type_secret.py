"""Tests ciblés plan-mark3.md action 8 : type d'attribut `secret` (valeur
sensible chiffrée, Fernet/cryptography - secret_crypto.py), masquage de la
lecture générique (routes_read.py, _build_object_payload) et route dédiée
de révélation réservée global-admin (GET /api/read/object/<id>/secret/
<attribute>).

Même convention que backend/test_attribute_type_select.py : pas de vraie
base Postgres, FakeDB/FakeConn/make_ctx réutilisés tels quels (aucune
requête SQL nouvelle non gérée par le FakeCursor existant), et SCHEMA_PATH
doit pointer vers le vrai model/schema.json du dépôt.

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_attribute_type_secret.py -v
"""
import os
import sys

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as miami_app  # noqa: E402
from test_model_driven_typing import FakeDB, FakeConn, make_ctx  # noqa: E402

TEST_KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def secret_key_env(monkeypatch):
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", TEST_KEY)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(miami_app.app.before_request_funcs, None, [])
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


@pytest.fixture
def db_and_ctx(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(db))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))
    return db


CLASSES = [
    {
        "class": "compte",
        "attributes": [
            {"domain": "details", "name": "mot_de_passe", "type": "secret"},
            {"domain": "details", "name": "login", "type": "string"},
        ],
    },
]


def _seed(db):
    db.seed_definition("securite", CLASSES)


def _value_rows(db, object_id, attr_name):
    attr_ids = {a["id"] for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == attr_name}
    return sorted(
        (v for v in db.attribute_values.values() if v["attribute_id"] in attr_ids),
        key=lambda v: v["id"],
    )


# ---------------------------------------------------------------------
# 1. Round-trip écriture : plaintext envoyé, valeur stockée en DB différente
#    du plaintext (jamais en clair).
# ---------------------------------------------------------------------

def test_write_object_secret_stored_encrypted_not_plaintext(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    rows = _value_rows(db, object_id, "mot_de_passe")
    assert len(rows) == 1
    stored = rows[0]["value_string"]
    assert stored != "hunter2"
    assert "hunter2" not in stored
    assert rows[0]["value_integer"] is None
    assert rows[0]["value_float"] is None


# ---------------------------------------------------------------------
# 2. Lecture générique : placeholder, jamais le texte en clair ni le
#    chiffré brut.
# ---------------------------------------------------------------------

def test_read_object_generic_returns_placeholder_never_plaintext_or_ciphertext(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]
    stored_ciphertext = _value_rows(db, object_id, "mot_de_passe")[0]["value_string"]

    read = client.get(f"/api/read/object/{object_id}")
    assert read.status_code == 200
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "mot_de_passe")
    assert values == ["••••••••"]
    body_text = read.get_data(as_text=True)
    assert "hunter2" not in body_text
    assert stored_ciphertext not in body_text


def test_read_object_generic_secret_without_active_value_is_empty(client, db_and_ctx):
    """Attribut `secret` existant (ligne `attribute` déjà créée) mais sans
    valeur active (toutes fermées) - simulé par fermeture directe en base
    (pas via l'API, le garde-fou write_object interdit désormais de fermer
    un secret par simple omission, voir section 4) : la lecture générique
    doit renvoyer une liste vide, jamais le placeholder sur une valeur
    absente."""
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]
    for row in _value_rows(db, object_id, "mot_de_passe"):
        row["valid_to"] = "now"

    read = client.get(f"/api/read/object/{object_id}")
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "mot_de_passe")
    assert values == []


# ---------------------------------------------------------------------
# 3. Route reveal : global-admin OK (valeur déchiffrée correcte), 403
#    tenant-admin (même périmètre propre), 401 sans token, 404 attribut
#    pas de type secret / inconnu / objet inexistant.
# ---------------------------------------------------------------------

def test_reveal_secret_returns_decrypted_value_for_global_admin(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]

    reveal = client.get(f"/api/read/object/{object_id}/secret/mot_de_passe")
    assert reveal.status_code == 200, reveal.get_json()
    assert reveal.get_json()["value"] == "hunter2"


def test_reveal_secret_forbidden_for_tenant_admin_even_in_own_scope(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"}, "tenants": ["tenant1"],
    })
    object_id = resp.get_json()["id"]

    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))
    reveal = client.get(f"/api/read/object/{object_id}/secret/mot_de_passe")
    assert reveal.status_code == 403


def test_reveal_secret_404_object_not_found(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    reveal = client.get("/api/read/object/999/secret/mot_de_passe")
    assert reveal.status_code == 404


def test_reveal_secret_404_attribute_not_secret_type(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]

    reveal = client.get(f"/api/read/object/{object_id}/secret/login")
    assert reveal.status_code == 404


def test_reveal_secret_404_attribute_unknown(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte", "attributes": {"login": "alice"},
    })
    object_id = resp.get_json()["id"]

    reveal = client.get(f"/api/read/object/{object_id}/secret/inconnu")
    assert reveal.status_code == 404


@pytest.fixture
def real_client():
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


def test_reveal_secret_401_without_token(real_client):
    resp = real_client.get("/api/read/object/1/secret/mot_de_passe")
    assert resp.status_code == 401


# ---------------------------------------------------------------------
# 4. Historisation : l'ancienne valeur reste chiffrée après remplacement,
#    jamais déchiffrée rétroactivement ; un champ secret omis à l'édition
#    ne ferme jamais la valeur active (garde-fou write_object).
# ---------------------------------------------------------------------

def test_history_old_secret_value_stays_encrypted_after_replacement(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]

    update = client.post("/api/write/object", json={
        "id": object_id, "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "trustno1", "login": "alice"},
    })
    assert update.status_code == 200, update.get_json()

    rows = _value_rows(db, object_id, "mot_de_passe")
    assert len(rows) == 2
    assert rows[0]["valid_to"] is not None
    assert rows[1]["valid_to"] is None
    assert rows[0]["value_string"] != "hunter2"
    assert rows[1]["value_string"] != "trustno1"
    assert rows[0]["value_string"] != rows[1]["value_string"]

    reveal = client.get(f"/api/read/object/{object_id}/secret/mot_de_passe")
    assert reveal.get_json()["value"] == "trustno1", "reveal doit déchiffrer la valeur ACTIVE, jamais l'ancienne"


def test_history_secret_omitted_from_update_payload_is_not_closed(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]

    update = client.post("/api/write/object", json={
        "id": object_id, "meta_class": "securite", "class": "compte",
        "attributes": {"login": "bob"},
    })
    assert update.status_code == 200, update.get_json()

    rows = _value_rows(db, object_id, "mot_de_passe")
    assert len(rows) == 1
    assert rows[0]["valid_to"] is None, "un champ secret omis à l'édition ne doit jamais fermer la valeur active"

    reveal = client.get(f"/api/read/object/{object_id}/secret/mot_de_passe")
    assert reveal.get_json()["value"] == "hunter2"


# ---------------------------------------------------------------------
# 5. Clé absente/invalide : jamais de crash silencieux, jamais de valeur en
#    clair stockée, jamais de déchiffrement retourné par erreur.
# ---------------------------------------------------------------------

def test_write_object_secret_without_key_returns_500_not_plaintext(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    monkeypatch.delenv("SECRET_ENCRYPTION_KEY", raising=False)

    # Un seul attribut dans le corps (pas de "login" à côté) : le test
    # client Flask alphabétise les clés JSON (app.json.sort_keys), envoyer
    # deux attributs rendrait l'ordre de traitement par write_object non
    # déterministe dans ce test précis - sans incidence sur le comportement
    # réel HTTP (un client réel n'alphabétise rien).
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2"},
    })
    assert resp.status_code == 500
    assert len(db.attribute_values) == 0, "aucune valeur ne doit être stockée si la clé est absente"


def test_write_object_secret_with_invalid_key_returns_500(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "pas-une-cle-fernet-valide")

    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2"},
    })
    assert resp.status_code == 500
    assert len(db.attribute_values) == 0


def test_reveal_secret_with_wrong_key_returns_500_not_garbage(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]

    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", OTHER_KEY)
    reveal = client.get(f"/api/read/object/{object_id}/secret/mot_de_passe")
    assert reveal.status_code == 500


def test_reveal_secret_without_key_returns_500(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]

    monkeypatch.delenv("SECRET_ENCRYPTION_KEY", raising=False)
    reveal = client.get(f"/api/read/object/{object_id}/secret/mot_de_passe")
    assert reveal.status_code == 500


# ---------------------------------------------------------------------
# 6. model/schema.json : "secret" accepté sans champ complémentaire requis.
# ---------------------------------------------------------------------

def test_schema_accepts_secret_attribute_without_extra_field():
    import jsonschema
    from data.db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "secret"}],
        }],
    }, schema=load_schema())


def test_schema_is_valid_draft7_with_secret():
    import jsonschema
    from data.db import load_schema

    jsonschema.Draft7Validator.check_schema(load_schema())


# ---------------------------------------------------------------------
# 7. Route PUT /api/write/attribute/<cls>/<id>/<attribute>/<value> : jamais
#    pour un attribut `secret` (la valeur transite dans l'URL, en clair dans
#    les logs d'accès reverse-proxy/CDN/APM, avant tout chiffrement).
# ---------------------------------------------------------------------

def test_write_attribute_url_rejects_secret_type(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "alice"},
    })
    object_id = resp.get_json()["id"]
    rows_before = _value_rows(db, object_id, "mot_de_passe")

    put = client.put(f"/api/write/attribute/compte/{object_id}/mot_de_passe/leaked-via-url")
    assert put.status_code == 400
    assert "secret" in put.get_data(as_text=True)

    rows_after = _value_rows(db, object_id, "mot_de_passe")
    assert rows_after == rows_before, "aucune nouvelle valeur ne doit être stockée via cette route pour un secret"

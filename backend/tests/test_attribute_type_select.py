"""Tests ciblés plan-mark3.md action 7 : type d'attribut `select` (liste
fixe de valeurs autorisées), `_coerce_typed_value` (routes_write.py) et
model/schema.json (nouvelle propriété "values", restructuration en
allOf de l'unique couple if/then existant).

Même convention que backend/test_model_driven_typing.py : pas de vraie
base Postgres, FakeDB/FakeCursor/FakeConn/make_ctx réutilisés tels quels
(aucune requête SQL nouvelle, stockage value_string déjà géré par le
FakeCursor existant), et SCHEMA_PATH doit pointer vers le vrai
model/schema.json du dépôt pour les tests de validation de schéma.

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_attribute_type_select.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as miami_app  # noqa: E402
from test_model_driven_typing import FakeDB, FakeConn, make_ctx  # noqa: E402


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
        "class": "ticket",
        "attributes": [
            {"domain": "details", "name": "statut", "type": "select", "values": ["ouvert", "ferme", "en_cours"]},
        ],
    },
]


def _seed(db):
    db.seed_definition("suivi", CLASSES)


def _value_rows(db, object_id, attr_name):
    attr_ids = {a["id"] for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == attr_name}
    return sorted(
        (v for v in db.attribute_values.values() if v["attribute_id"] in attr_ids),
        key=lambda v: v["id"],
    )


# ---------------------------------------------------------------------
# 1. Valeur dans "values" déclaré : acceptée, stockée en value_string.
# ---------------------------------------------------------------------

def test_write_object_select_value_in_list_accepted_and_stored_as_value_string(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "suivi", "class": "ticket",
        "attributes": {"statut": "ouvert"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    rows = _value_rows(db, object_id, "statut")
    assert len(rows) == 1
    assert rows[0]["value_string"] == "ouvert"
    assert rows[0]["value_integer"] is None
    assert rows[0]["value_float"] is None

    read = client.get(f"/api/read/object/{object_id}")
    assert read.status_code == 200
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "statut")
    assert values == ["ouvert"]


# ---------------------------------------------------------------------
# 2. Valeur hors "values" : rejet 400.
# ---------------------------------------------------------------------

def test_write_object_select_value_not_in_list_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "suivi", "class": "ticket",
        "attributes": {"statut": "archive"},
    })
    assert resp.status_code == 400
    assert "select" in resp.get_data(as_text=True)


def test_write_attribute_value_select_value_not_in_list_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "suivi", "class": "ticket", "attributes": {"statut": "ouvert"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/ticket/{object_id}/statut/archive")
    assert put.status_code == 400


def test_write_attribute_value_select_value_in_list_accepted(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "suivi", "class": "ticket", "attributes": {"statut": "ouvert"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/ticket/{object_id}/statut/ferme")
    assert put.status_code == 200, put.get_json()

    rows = _value_rows(db, object_id, "statut")
    assert rows[-1]["value_string"] == "ferme"
    assert rows[-1]["valid_to"] is None


# ---------------------------------------------------------------------
# 3. model/schema.json : validité Draft7, et règles allOf (non-régression
#    joint-1-1/joint-1-n + nouvelle règle select).
# ---------------------------------------------------------------------

def test_schema_is_valid_draft7():
    import jsonschema
    from data.db import load_schema

    jsonschema.Draft7Validator.check_schema(load_schema())


def test_schema_rejects_select_attribute_without_values():
    import jsonschema
    from data.db import load_schema

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance={
            "meta_class": "m",
            "classes": [{
                "class": "c",
                "attributes": [{"domain": "d", "name": "n", "type": "select"}],
            }],
        }, schema=load_schema())


def test_schema_accepts_select_attribute_with_values():
    import jsonschema
    from data.db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "select", "values": ["a", "b"]}],
        }],
    }, schema=load_schema())


def test_schema_still_rejects_joint_1_1_attribute_without_classes():
    """Non-régression de la restructuration if/then -> allOf : la branche
    joint-1-1/joint-1-n reste appliquée telle quelle."""
    import jsonschema
    from data.db import load_schema

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance={
            "meta_class": "m",
            "classes": [{
                "class": "c",
                "attributes": [{"domain": "d", "name": "n", "type": "joint-1-1"}],
            }],
        }, schema=load_schema())


def test_schema_still_accepts_plain_string_attribute():
    import jsonschema
    from data.db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "string"}],
        }],
    }, schema=load_schema())

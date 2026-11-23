"""Tests ciblés plan-mark3.md action 19 : type d'attribut `boolean` (case à
cocher simple), `_coerce_typed_value` (routes_write.py) et model/schema.json
(ajout de `"boolean"` à l'enum `attributes[].type`, aucune branche `allOf`
supplémentaire requise - pas de champ requis type `values`/`classes`/
`separator`, comme `string`/`integer`/`float`).

Stockage : value_string ("true"/"false" en texte), réutilisé tel quel comme
les autres types scalaires - aucune nouvelle colonne SQL, aucune migration.

Deux chemins d'écriture testés, cohérents avec les deux usages frontend
(NavigationPage.tsx - formulaire modal ET édition inline de cellule) :
- POST /api/write/object (corps JSON) : raw_value est un bool Python natif
  après parsing JSON (true/false) - cas nominal de la conception.
- PUT /api/write/attribute/<cls>/<id>/<attribute>/<value> (édition inline,
  valeur dans le chemin d'URL) : raw_value est TOUJOURS une chaîne côté
  Flask (<string:value>), jamais un bool JSON - un bool ne peut pas
  physiquement transiter par un segment d'URL. _coerce_typed_value accepte
  donc aussi la chaîne EXACTE "true"/"false" (pas de parsing permissif type
  "1"/"yes"/"0"), seule façon de rendre l'édition inline fonctionnelle pour
  ce type (même contrainte structurelle déjà résolue différemment pour
  joint-1-1, qui route son édition inline via l'objet complet plutôt que
  cette route URL - boolean reste ici sur l'URL, valeur déjà texte par
  construction de son stockage).

Même convention que backend/test_attribute_type_select.py : pas de vraie
base Postgres, FakeDB/FakeConn/make_ctx réutilisés tels quels (aucune
requête SQL nouvelle, stockage value_string déjà géré par le FakeCursor
existant), et SCHEMA_PATH doit pointer vers le vrai model/schema.json du
dépôt pour les tests de validation de schéma.

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_attribute_type_boolean.py -v
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
        "class": "serveur",
        "attributes": [
            {"domain": "logique", "name": "actif", "type": "boolean"},
        ],
    },
]


def _seed(db):
    db.seed_definition("cmdb_test", CLASSES)


def _value_rows(db, object_id, attr_name):
    attr_ids = {a["id"] for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == attr_name}
    return sorted(
        (v for v in db.attribute_values.values() if v["attribute_id"] in attr_ids),
        key=lambda v: v["id"],
    )


# ---------------------------------------------------------------------
# 1. write_object (POST, JSON) : bool Python natif accepté, stocké en texte.
# ---------------------------------------------------------------------

def test_write_object_boolean_true_accepted_and_stored_as_value_string(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"actif": True},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    rows = _value_rows(db, object_id, "actif")
    assert len(rows) == 1
    assert rows[0]["value_string"] == "true"
    assert rows[0]["value_integer"] is None
    assert rows[0]["value_float"] is None

    read = client.get(f"/api/read/object/{object_id}")
    assert read.status_code == 200
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "actif")
    assert values == ["true"]


def test_write_object_boolean_false_accepted_and_stored_as_value_string(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"actif": False},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    rows = _value_rows(db, object_id, "actif")
    assert len(rows) == 1
    assert rows[0]["value_string"] == "false"


# ---------------------------------------------------------------------
# 2. write_object (POST, JSON) : type invalide -> rejet 400.
# ---------------------------------------------------------------------

@pytest.mark.parametrize("bad_value", ["yes", "1", 1, 0, 1.0, None, {"a": "b"}])
def test_write_object_boolean_invalid_value_rejected_400(client, db_and_ctx, bad_value):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"actif": bad_value},
    })
    assert resp.status_code == 400
    assert "boolean" in resp.get_data(as_text=True)


# ---------------------------------------------------------------------
# 3. write_attribute_value (PUT, édition inline par URL) : la valeur est
#    toujours une chaîne côté Flask - "true"/"false" acceptés, tout le reste
#    rejeté (pas de parsing permissif).
# ---------------------------------------------------------------------

def test_write_attribute_value_boolean_string_true_false_accepted(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "attributes": {"actif": True},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/serveur/{object_id}/actif/false")
    assert put.status_code == 200, put.get_json()

    rows = _value_rows(db, object_id, "actif")
    assert rows[-1]["value_string"] == "false"
    assert rows[-1]["valid_to"] is None


def test_write_attribute_value_boolean_invalid_string_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "attributes": {"actif": True},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/serveur/{object_id}/actif/yes")
    assert put.status_code == 400


# ---------------------------------------------------------------------
# 4. Pas de duplication de ligne historisée si la même valeur est resoumise
#    (continuité historique, _apply_attribute_diff).
# ---------------------------------------------------------------------

def test_write_object_boolean_same_value_resubmitted_no_new_row(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "attributes": {"actif": True},
    })
    object_id = resp.get_json()["id"]

    resp2 = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "id": object_id,
        "attributes": {"actif": True},
    })
    assert resp2.status_code == 200, resp2.get_json()

    rows = _value_rows(db, object_id, "actif")
    assert len(rows) == 1
    assert rows[0]["valid_to"] is None


# ---------------------------------------------------------------------
# 5. model/schema.json : validité Draft7, "boolean" accepté SANS champ
#    requis supplémentaire (contrairement à select/joint-*/datasource).
# ---------------------------------------------------------------------

def test_schema_is_valid_draft7():
    import jsonschema
    from data.db import load_schema

    jsonschema.Draft7Validator.check_schema(load_schema())


def test_schema_accepts_boolean_attribute_without_extra_fields():
    import jsonschema
    from data.db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "boolean"}],
        }],
    }, schema=load_schema())


def test_schema_still_rejects_select_attribute_without_values():
    """Non-régression : l'ajout de "boolean" à l'enum ne touche pas la
    branche allOf existante qui exige `values` pour `select`."""
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


def test_schema_still_rejects_joint_1_1_attribute_without_classes():
    """Non-régression : idem pour la branche joint-1-1/joint-1-n/datasource."""
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

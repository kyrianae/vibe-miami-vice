"""Tests ciblés plan-mark3.md action 9 : type d'attribut `datasource`
(pointeur, value_string = id d'un objet d'une meta-classe `datasource_*`
dédiée), `_coerce_typed_value`/`_apply_attribute_diff` (routes_write.py) et
model/schema.json (ajout de `"datasource"` à l'enum `type`, réutilisation du
champ `classes` déjà requis pour joint-1-1/joint-1-n).

Même convention que backend/test_attribute_type_select.py : pas de vraie
base Postgres, FakeDB/FakeConn/make_ctx réutilisés tels quels (nouvelle
branche SQL "SELECT class, tenants, deleted_at FROM object WHERE id" ajoutée
à FakeCursor dans test_model_driven_typing.py pour la validation de cible),
et SCHEMA_PATH doit pointer vers le vrai model/schema.json du dépôt.

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_attribute_type_datasource.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as miami_app  # noqa: E402
from test_model_driven_typing import FakeDB, FakeConn, FakeCursor, FakeRealDictCursor, make_ctx  # noqa: E402


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


class _CascadeCursor(FakeCursor):
    """FakeCursor étendu localement à CE fichier (jamais test_model_driven_
    typing.py, hors périmètre) : ajoute la seule requête que le socle commun
    ne connaît pas encore, la jointure attribute_value/attribute/object sur
    value_string utilisée par la cascade de suppression datasource
    (delete_object, plan-mark3.md action 9 itération 2). Tout le reste est
    délégué à FakeCursor via super()."""

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT av.id, a.name, o.meta_class, o.class"):
            self._result = None
            self._results = None
            self.rowcount = 0
            value_string = params[0]
            actor_tenants = set(params[1]) if len(params) > 1 else None
            rows = []
            for av in self.db.attribute_values.values():
                if av["value_string"] != value_string or av["valid_to"] is not None:
                    continue
                attr = self.db.attributes.get(av["attribute_id"])
                if attr is None:
                    continue
                owner = self.db.objects.get(attr["object_id"])
                if owner is None:
                    continue
                owner_tenants = owner.get("tenants")
                if actor_tenants is not None and owner_tenants and not (set(owner_tenants.split(",")) & actor_tenants):
                    continue
                rows.append((av["id"], attr["name"], owner["meta_class"], owner["class"]))
            self._results = rows
        else:
            super().execute(sql, params)


class _CascadeConn(FakeConn):
    def cursor(self, cursor_factory=None):
        if cursor_factory is not None:
            return FakeRealDictCursor(self.db)
        return _CascadeCursor(self.db)


@pytest.fixture
def cascade_db_and_ctx(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: _CascadeConn(db))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))
    return db


CLASSES = [
    {
        "class": "serveur",
        "attributes": [
            {"domain": "details", "name": "nom", "type": "string"},
            {"domain": "monitoring", "name": "metriques", "type": "datasource", "classes": ["datasource_prometheus"]},
        ],
    },
    {
        "class": "datasource_prometheus",
        "attributes": [
            {"domain": "connexion", "name": "url", "type": "string"},
            {"domain": "requete", "name": "query", "type": "string"},
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


def _create_prometheus_source(client, tenants=None):
    body = {
        "meta_class": "cmdb_test", "class": "datasource_prometheus",
        "attributes": {"url": "http://prometheus:9090", "query": 'rate(node_cpu_seconds_total{mode="user",cpu="0"}[1m])'},
    }
    if tenants is not None:
        body["tenants"] = tenants
    resp = client.post("/api/write/object", json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


# ---------------------------------------------------------------------
# 1. Round-trip : pointeur vers une source datasource_prometheus existante,
#    stocké en value_string (jamais joint_id), relu identique.
# ---------------------------------------------------------------------

def test_write_object_datasource_valid_target_accepted_and_stored_as_value_string(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    source_id = _create_prometheus_source(client)

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": source_id},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    rows = _value_rows(db, object_id, "metriques")
    assert len(rows) == 1
    assert rows[0]["value_string"] == str(source_id)
    assert rows[0]["joint_id"] is None
    assert rows[0]["value_integer"] is None

    read = client.get(f"/api/read/object/{object_id}")
    assert read.status_code == 200
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "metriques")
    assert values == [str(source_id)]


# ---------------------------------------------------------------------
# 2. Cible inexistante : rejet 400.
# ---------------------------------------------------------------------

def test_write_object_datasource_nonexistent_target_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": 9999},
    })
    assert resp.status_code == 400
    assert "inexistant" in resp.get_data(as_text=True)


# ---------------------------------------------------------------------
# 3. Cible existante mais mauvaise classe (pas une datasource_prometheus) :
#    rejet 400.
# ---------------------------------------------------------------------

def test_write_object_datasource_wrong_class_target_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    other_server = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "attributes": {"nom": "web02"},
    }).get_json()["id"]

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": other_server},
    })
    assert resp.status_code == 400
    assert "classe autorisée" in resp.get_data(as_text=True)


# ---------------------------------------------------------------------
# 4. RBAC tenant : cible existante dans un autre tenant, acteur
#    tenant-admin -> 403 ; même cible acceptée pour un global-admin.
# ---------------------------------------------------------------------

def test_write_object_datasource_target_in_other_tenant_rejected_for_tenant_admin(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    source_id = _create_prometheus_source(client, tenants=["tenant2"])

    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))
    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": source_id}, "tenants": ["tenant1"],
    })
    assert resp.status_code == 403
    assert "périmètre tenant" in resp.get_data(as_text=True)


def test_write_object_datasource_target_in_same_tenant_accepted_for_tenant_admin(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))
    source_id = _create_prometheus_source(client, tenants=["tenant1"])

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": source_id}, "tenants": ["tenant1"],
    })
    assert resp.status_code == 201, resp.get_json()


def test_write_object_datasource_target_in_other_tenant_accepted_for_global_admin(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    source_id = _create_prometheus_source(client, tenants=["tenant2"])

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": source_id},
    })
    assert resp.status_code == 201, resp.get_json()


# ---------------------------------------------------------------------
# 5. write_attribute_value (édition inline de cellule, URL : valeur brute
#    jamais enveloppée dans {'joint_id': ...} - value_string, pas joint_id).
# ---------------------------------------------------------------------

def test_write_attribute_value_datasource_valid_target_accepted(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    source_id = _create_prometheus_source(client)
    object_id = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "attributes": {"nom": "web01"},
    }).get_json()["id"]

    put = client.put(f"/api/write/attribute/serveur/{object_id}/metriques/{source_id}")
    assert put.status_code == 200, put.get_json()

    rows = _value_rows(db, object_id, "metriques")
    assert rows[-1]["value_string"] == str(source_id)
    assert rows[-1]["valid_to"] is None


def test_write_attribute_value_datasource_nonexistent_target_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "attributes": {"nom": "web01"},
    }).get_json()["id"]

    put = client.put(f"/api/write/attribute/serveur/{object_id}/metriques/9999")
    assert put.status_code == 400


def test_write_attribute_value_datasource_non_integer_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur", "attributes": {"nom": "web01"},
    }).get_json()["id"]

    put = client.put(f"/api/write/attribute/serveur/{object_id}/metriques/abc")
    assert put.status_code == 400


# ---------------------------------------------------------------------
# 6. model/schema.json : règles allOf (datasource rejoint joint-1-1/
#    joint-1-n dans la branche "classes" requis).
# ---------------------------------------------------------------------

def test_schema_rejects_datasource_attribute_without_classes():
    import jsonschema
    from data.db import load_schema

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance={
            "meta_class": "m",
            "classes": [{
                "class": "c",
                "attributes": [{"domain": "d", "name": "n", "type": "datasource"}],
            }],
        }, schema=load_schema())


def test_schema_accepts_datasource_attribute_with_classes():
    import jsonschema
    from data.db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "datasource", "classes": ["datasource_prometheus"]}],
        }],
    }, schema=load_schema())


def test_schema_is_valid_draft7_with_datasource_enum_entry():
    import jsonschema
    from data.db import load_schema

    jsonschema.Draft7Validator.check_schema(load_schema())


# ---------------------------------------------------------------------
# 7. delete_object (plan-mark3.md action 9, itération 2, correction 1) :
#    cascade de fermeture sur les attribute_value de type datasource dont
#    value_string pointe vers l'objet supprimé - symétrique à la cascade déjà
#    existante sur joint_id, mais revérifiée contre le modèle (classe de
#    l'objet porteur + attr_def["classes"]) avant fermeture, jamais par
#    simple coïncidence de valeur texte.
# ---------------------------------------------------------------------

def test_delete_object_datasource_cascade_closes_pointer_value(client, cascade_db_and_ctx):
    db = cascade_db_and_ctx
    _seed(db)
    source_id = _create_prometheus_source(client)
    object_id = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": source_id},
    }).get_json()["id"]

    resp = client.delete(f"/api/delete/object/{source_id}")
    assert resp.status_code == 200, resp.get_json()

    rows = _value_rows(db, object_id, "metriques")
    assert rows and all(r["valid_to"] is not None for r in rows)

    read = client.get(f"/api/read/object/{object_id}")
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "metriques")
    assert values == []


def test_delete_object_datasource_cascade_does_not_affect_unrelated_attribute_with_coincidental_value(client, cascade_db_and_ctx):
    db = cascade_db_and_ctx
    _seed(db)
    source_id = _create_prometheus_source(client)

    # "nom" est de type string, jamais datasource : sa valeur coïncide par
    # hasard avec l'id numérique de la source supprimée plus bas, et ne doit
    # jamais être fermée par la cascade datasource.
    object_id = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": str(source_id)},
    }).get_json()["id"]

    resp = client.delete(f"/api/delete/object/{source_id}")
    assert resp.status_code == 200, resp.get_json()

    rows = _value_rows(db, object_id, "nom")
    assert rows and all(r["valid_to"] is None for r in rows)
    assert rows[-1]["value_string"] == str(source_id)

    read = client.get(f"/api/read/object/{object_id}")
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "nom")
    assert values == [str(source_id)]


# ---------------------------------------------------------------------
# 8. _coerce_typed_value, branche datasource (correction 2) : un float non
#    entier doit être rejeté en 400, jamais tronqué silencieusement en int -
#    même garde que joint-1-1. Couvre le chemin write_object (POST, JSON,
#    vrai float), distinct du test existant côté write_attribute_value (PUT,
#    valeur toujours string dans l'URL).
# ---------------------------------------------------------------------

def test_write_object_datasource_non_integer_float_rejected_400(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_test", "class": "serveur",
        "attributes": {"nom": "web01", "metriques": 5.9},
    })
    assert resp.status_code == 400

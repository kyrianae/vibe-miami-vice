"""Tests ciblés sur plan-mark2.md action 5 : validation de schéma JSON +
typage de stockage piloté par le modèle (_store_typed_value), et rejet
Option B d'un attribut non déclaré dans le modèle, pour write_object et
write_attribute_value.

Même convention que backend/test_rbac_class_tenant_scope.py : pas de vraie
base Postgres ni de vrai Keycloak, get_db()/get_auth_context() sont
monkeypatchés, et SCHEMA_PATH doit pointer vers le vrai model/schema.json
du dépôt (sinon load_schema() échoue avec FileNotFoundError, le chemin par
défaut "/model/schema.json" n'existant que dans le conteneur Docker).

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/test_model_driven_typing.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import app as miami_app  # noqa: E402


def make_ctx(is_global_admin=False, is_tenant_admin=False, is_tenant_readonly=False, tenants=None):
    return miami_app.AuthContext(is_global_admin, is_tenant_admin, is_tenant_readonly, tenants or [])


class FakeDB:
    def __init__(self):
        self.definitions = {}  # meta_class -> {"id":.., "data": {...}}
        self.objects = {}  # id -> {"meta_class":.., "class":.., "tenants":..}
        self.attributes = {}  # id -> {"object_id":.., "domain":.., "name":..}
        self.attribute_values = {}  # id -> {"attribute_id":.., "value_integer":.., "value_float":.., "value_string":.., "joint_id":..}
        self._next_def_id = 1
        self._next_obj_id = 1
        self._next_attr_id = 1
        self._next_val_id = 1

    def seed_definition(self, meta_class, classes):
        self.definitions[meta_class] = {"id": self._next_def_id, "data": {"meta_class": meta_class, "classes": classes}}
        self._next_def_id += 1


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self._result = None
        self._results = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        params = params or ()

        if sql_norm.startswith("SELECT data FROM definition WHERE meta_class"):
            row = self.db.definitions.get(params[0])
            self._result = {"data": row["data"]} if row else None

        elif sql_norm.startswith("SELECT id, data FROM definition WHERE meta_class"):
            row = self.db.definitions.get(params[0])
            self._result = {"id": row["id"], "data": row["data"]} if row else None

        elif sql_norm.startswith("UPDATE definition SET data"):
            data_json, row_id = params
            for row in self.db.definitions.values():
                if row["id"] == row_id:
                    row["data"] = json.loads(data_json)
                    break

        elif sql_norm.startswith("INSERT INTO definition"):
            meta_class, data_json = params
            self.db.definitions[meta_class] = {"id": self.db._next_def_id, "data": json.loads(data_json)}
            self.db._next_def_id += 1

        elif sql_norm.startswith("SELECT id, tenants FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            self._result = (obj["id"], obj["tenants"]) if obj else None

        elif sql_norm.startswith("SELECT id, class, meta_class, tenants FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            self._result = dict(obj) if obj else None

        elif sql_norm.startswith("SELECT id, meta_class, class, tenants FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            self._result = dict(obj) if obj else None

        elif sql_norm.startswith("INSERT INTO object"):
            meta_class, cls, tenants = params
            obj_id = self.db._next_obj_id
            self.db._next_obj_id += 1
            self.db.objects[obj_id] = {"id": obj_id, "meta_class": meta_class, "class": cls, "tenants": tenants}
            self._result = (obj_id,)

        elif sql_norm.startswith("UPDATE object SET meta_class"):
            meta_class, cls, tenants, obj_id = params
            self.db.objects[obj_id].update({"meta_class": meta_class, "class": cls, "tenants": tenants})

        elif sql_norm.startswith("DELETE FROM attribute_value WHERE attribute_id IN"):
            object_id = params[0]
            attr_ids = {aid for aid, a in self.db.attributes.items() if a["object_id"] == object_id}
            for vid in [vid for vid, v in self.db.attribute_values.items() if v["attribute_id"] in attr_ids]:
                del self.db.attribute_values[vid]

        elif sql_norm.startswith("DELETE FROM attribute WHERE object_id"):
            object_id = params[0]
            for aid in [aid for aid, a in self.db.attributes.items() if a["object_id"] == object_id]:
                del self.db.attributes[aid]

        elif sql_norm.startswith("DELETE FROM attribute_value WHERE attribute_id ="):
            attribute_id = params[0]
            for vid in [vid for vid, v in self.db.attribute_values.items() if v["attribute_id"] == attribute_id]:
                del self.db.attribute_values[vid]

        elif sql_norm.startswith("UPDATE attribute_value SET valid_to = now() WHERE id ="):
            # Historisation (plan-mark2.md action 6.0) : FakeDB ne modélise
            # pas valid_from/valid_to - une fermeture de valeur est simulée
            # par une suppression de la ligne du store en mémoire, ce qui
            # produit le même résultat observable pour ces tests (plus
            # aucune lecture ultérieure, via la requête active ci-dessous,
            # ne doit la retourner).
            (value_id,) = params
            self.db.attribute_values.pop(value_id, None)

        elif sql_norm.startswith("INSERT INTO attribute (object_id, domain, name)"):
            object_id, domain, name = params
            attr_id = self.db._next_attr_id
            self.db._next_attr_id += 1
            self.db.attributes[attr_id] = {"id": attr_id, "object_id": object_id, "domain": domain, "name": name}
            self._result = (attr_id,) if not isinstance(self, FakeRealDictCursor) else {"id": attr_id}

        elif sql_norm.startswith("SELECT id FROM attribute WHERE object_id"):
            object_id, name = params
            found = None
            for a in self.db.attributes.values():
                if a["object_id"] == object_id and a["name"] == name:
                    found = a
                    break
            self._result = {"id": found["id"]} if found else None

        elif sql_norm.startswith("INSERT INTO attribute_value (attribute_id, joint_id)"):
            attribute_id, joint_id = params
            self._store_value(attribute_id, joint_id=joint_id)

        elif sql_norm.startswith("INSERT INTO attribute_value (attribute_id, value_integer)"):
            attribute_id, value = params
            self._store_value(attribute_id, value_integer=value)

        elif sql_norm.startswith("INSERT INTO attribute_value (attribute_id, value_float)"):
            attribute_id, value = params
            self._store_value(attribute_id, value_float=value)

        elif sql_norm.startswith("INSERT INTO attribute_value (attribute_id, value_string)"):
            attribute_id, value = params
            self._store_value(attribute_id, value_string=value)

        elif sql_norm.startswith("SELECT a.id AS attribute_id"):
            object_id = params[0]
            rows = []
            for a in sorted(self.db.attributes.values(), key=lambda a: a["id"]):
                if a["object_id"] != object_id:
                    continue
                vals = [v for v in self.db.attribute_values.values() if v["attribute_id"] == a["id"]]
                if not vals:
                    rows.append({
                        "attribute_id": a["id"], "domain": a["domain"], "name": a["name"],
                        "value_id": None, "value_integer": None, "value_float": None,
                        "value_string": None, "joint_id": None,
                    })
                for v in sorted(vals, key=lambda v: v["id"]):
                    rows.append({
                        "attribute_id": a["id"], "domain": a["domain"], "name": a["name"],
                        "value_id": v["id"], "value_integer": v.get("value_integer"),
                        "value_float": v.get("value_float"), "value_string": v.get("value_string"),
                        "joint_id": v.get("joint_id"),
                    })
            self._results = rows

        else:
            raise AssertionError(f"SQL non géré par FakeCursor : {sql_norm!r}")

    def _store_value(self, attribute_id, value_integer=None, value_float=None, value_string=None, joint_id=None):
        vid = self.db._next_val_id
        self.db._next_val_id += 1
        self.db.attribute_values[vid] = {
            "id": vid, "attribute_id": attribute_id,
            "value_integer": value_integer, "value_float": value_float,
            "value_string": value_string, "joint_id": joint_id,
        }

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._results or []


class FakeRealDictCursor(FakeCursor):
    pass


class FakeConn:
    def __init__(self, db):
        self.db = db

    def cursor(self, cursor_factory=None):
        if cursor_factory is not None:
            return FakeRealDictCursor(self.db)
        return FakeCursor(self.db)

    def commit(self):
        pass

    def rollback(self):
        pass


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


REGISTRE = [
    {
        "class": "immatriculation",
        "attributes": [
            {"domain": "details", "name": "matricule", "type": "string", "constraint": "^[0-9]{3}$"},
            {"domain": "details", "name": "age", "type": "integer"},
            {"domain": "details", "name": "taux", "type": "float"},
            {"domain": "details", "name": "lien", "type": "joint-1-1", "classes": ["immatriculation"]},
            {"domain": "details", "name": "code_regex_cassee", "type": "string", "constraint": "([0-9]{3}"},
        ],
    },
]


def _seed(db):
    db.seed_definition("registre", REGISTRE)


# ---------------------------------------------------------------------
# 1. Non-régression : string numeric-looking reste string (ni write_object
#    ni write_attribute_value ne doivent la convertir en entier).
# ---------------------------------------------------------------------

def test_write_object_string_numeric_looking_stays_string(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.post("/api/write/object", json={
        "meta_class": "registre",
        "class": "immatriculation",
        "attributes": {"matricule": "007"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    read = client.get(f"/api/read/object/{object_id}")
    assert read.status_code == 200
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "matricule")
    assert values == ["007"]
    assert isinstance(values[0], str)


def test_write_attribute_value_string_numeric_looking_stays_string(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "123"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/042")
    assert put.status_code == 200, put.get_json()

    read = client.get(f"/api/read/object/{object_id}")
    values = next(a["values"] for a in read.get_json()["attributes"] if a["name"] == "matricule")
    assert values == ["042"]
    assert isinstance(values[0], str)


# ---------------------------------------------------------------------
# 2. Non-régression : integer/float valides fonctionnent toujours.
# ---------------------------------------------------------------------

def test_write_object_integer_and_float_ok(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "100", "age": 42, "taux": 3.14},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    read = client.get(f"/api/read/object/{object_id}").get_json()
    age_values = next(a["values"] for a in read["attributes"] if a["name"] == "age")
    taux_values = next(a["values"] for a in read["attributes"] if a["name"] == "taux")
    assert age_values == [42]
    assert taux_values == [3.14]


def test_write_attribute_value_integer_ok(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "100", "age": 1},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/age/99")
    assert put.status_code == 200, put.get_json()
    read = client.get(f"/api/read/object/{object_id}").get_json()
    age_values = next(a["values"] for a in read["attributes"] if a["name"] == "age")
    assert age_values == [99]


def test_write_attribute_value_integer_invalid_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "100", "age": 1},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/age/not-a-number")
    assert put.status_code == 400


# ---------------------------------------------------------------------
# 3. Violation de constraint (regex) sur un attribut multi-valué : détectée
#    par élément.
# ---------------------------------------------------------------------

def test_write_object_constraint_violation_in_list_detected_per_element(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": ["123", "abc"]},
    })
    assert resp.status_code == 400
    assert "matricule" in resp.get_data(as_text=True)


def test_write_object_constraint_ok_for_all_elements_in_list(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": ["123", "456"]},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]
    read = client.get(f"/api/read/object/{object_id}").get_json()
    values = next(a["values"] for a in read["attributes"] if a["name"] == "matricule")
    assert sorted(values) == ["123", "456"]


# ---------------------------------------------------------------------
# 3bis. La validation de "constraint" (regex), auparavant uniquement dans
#    write_object, doit aussi s'appliquer via write_attribute_value (édition
#    inline Mark 1 action 4) - correction plan-mark2.md action 5, point 1.
# ---------------------------------------------------------------------

def test_write_attribute_value_constraint_violation_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "100"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/abc")
    assert put.status_code == 400
    assert "matricule" in put.get_data(as_text=True)


def test_write_attribute_value_constraint_ok(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "100"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/456")
    assert put.status_code == 200, put.get_json()


# ---------------------------------------------------------------------
# 3ter. Une regex "constraint" syntaxiquement malformée dans le modèle ne
#    doit jamais produire un 500 non catché, mais un 400 explicite -
#    correction plan-mark2.md action 5, point 2. Vérifiée sur les deux
#    endpoints qui passent par _store_typed_value.
# ---------------------------------------------------------------------

def test_write_object_malformed_constraint_regex_returns_400_not_500(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "100", "code_regex_cassee": "whatever"},
    })
    assert resp.status_code == 400
    assert "code_regex_cassee" in resp.get_data(as_text=True)


def test_write_attribute_value_malformed_constraint_regex_returns_400_not_500(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "100"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/code_regex_cassee/whatever")
    assert put.status_code == 400
    assert "code_regex_cassee" in put.get_data(as_text=True)


# ---------------------------------------------------------------------
# 4. Classe/meta_class non définie rejetée en 400 par write_object.
# ---------------------------------------------------------------------

def test_write_object_unknown_meta_class_rejected(client, db_and_ctx):
    resp = client.post("/api/write/object", json={
        "meta_class": "inconnue", "class": "whatever", "attributes": {},
    })
    assert resp.status_code == 400


def test_write_object_unknown_class_in_known_meta_class_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "classe_inconnue", "attributes": {},
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# 5. Attribut non déclaré dans le modèle rejeté en 400 (Option B), pas
#    accepté silencieusement - write_object ET write_attribute_value.
# ---------------------------------------------------------------------

def test_write_object_undeclared_attribute_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"attribut_fantome": "valeur"},
    })
    assert resp.status_code == 400
    assert "non déclaré" in resp.get_data(as_text=True)


def test_write_attribute_value_undeclared_attribute_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "100"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/attribut_fantome/valeur")
    assert put.status_code == 400
    assert "non déclaré" in put.get_data(as_text=True)


# ---------------------------------------------------------------------
# 6. write_attribute_value ne doit jamais router un attribut de type
#    jointure (cohérent avec Mark 1 action 4) : 400.
# ---------------------------------------------------------------------

def test_write_attribute_value_joint_type_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": {"matricule": "100"},
    })
    object_id = resp.get_json()["id"]

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/lien/5")
    assert put.status_code == 400


# ---------------------------------------------------------------------
# 7. jsonschema.validate activé sur write_class / write_metaclass : une
#    classe invalide au regard du modèle (type d'attribut inconnu) est
#    rejetée en 400 plutôt qu'acceptée silencieusement.
# ---------------------------------------------------------------------

def test_write_metaclass_invalid_schema_rejected(client, db_and_ctx):
    resp = client.post("/api/write/metaclass", json={
        "meta_class": "cassee",
        "classes": [
            {"class": "x", "attributes": [{"domain": "d", "name": "n", "type": "type_invalide"}]},
        ],
    })
    assert resp.status_code == 400


def test_write_metaclass_valid_schema_accepted(client, db_and_ctx):
    resp = client.post("/api/write/metaclass", json={
        "meta_class": "nouvelle",
        "classes": [
            {"class": "x", "attributes": [{"domain": "d", "name": "n", "type": "string"}]},
        ],
    })
    assert resp.status_code == 201, resp.get_json()


# ---------------------------------------------------------------------
# 8. init_from_model_files : les vrais fichiers model/*.json du dépôt (avec
#    $schema, action 8) doivent être acceptés par la validation désormais
#    active.
# ---------------------------------------------------------------------

def test_init_loads_real_model_files_with_schema_key(client, monkeypatch, db_and_ctx):
    model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model")
    monkeypatch.setenv("MODEL_DIR", model_dir)

    resp = client.post("/api/init")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert "personne" in body["loaded"]
    assert "element_avec_ip" in body["loaded"]
    assert body["skipped"] == []

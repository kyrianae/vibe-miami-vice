"""Tests ciblés sur plan-mark2.md action 5 : validation de schéma JSON +
typage de stockage piloté par le modèle (_coerce_typed_value), et rejet
Option B d'un attribut non déclaré dans le modèle, pour write_object et
write_attribute_value ; action 6.0 : historisation d'attribute_value
(_apply_attribute_diff, partagée par les deux routes d'écriture) ; et
action 6.1 : suppression logique d'un objet (delete_object), RBAC et
cascade sur les jointures entrantes, garde-fou anti-zombie, et mitigation
du deadlock PostgreSQL rare entre delete_object et write_object/
write_attribute_value (DeadlockDetected -> 409).

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

import psycopg2.errors
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import app as miami_app  # noqa: E402


def make_ctx(is_global_admin=False, is_tenant_admin=False, is_tenant_readonly=False, tenants=None):
    return miami_app.AuthContext(is_global_admin, is_tenant_admin, is_tenant_readonly, tenants or [])


class _FakeNow:
    """Sentinel timestamp (action 6.1) : se comporte comme le datetime réel
    renvoyé par `RETURNING deleted_at` (seul point du module où le code
    appelle `.isoformat()` sur une valeur issue du FakeCursor)."""
    def isoformat(self):
        return "now"

    def __eq__(self, other):
        return isinstance(other, _FakeNow) or other == "now"


class FakeDB:
    def __init__(self):
        self.definitions = {}  # meta_class -> {"id":.., "data": {...}}
        self.objects = {}  # id -> {"meta_class":.., "class":.., "tenants":..}
        self.attributes = {}  # id -> {"object_id":.., "domain":.., "name":..}
        # id -> {"attribute_id":.., "value_integer":.., "value_float":..,
        #        "value_string":.., "joint_id":.., "valid_to": None|"now"}
        # valid_to est réellement tracé : une fermeture marque la ligne,
        # elle reste dans le store (l'historique doit être observable).
        self.attribute_values = {}
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
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        # Réinitialisé à chaque execute : un fetchone()/fetchall() après une
        # requête qui ne produit rien (UPDATE, INSERT sans RETURNING) ne doit
        # jamais renvoyer le résultat périmé de la requête précédente.
        self._result = None
        self._results = None
        self.rowcount = 0
        sql_norm = " ".join(sql.split())
        params = params or ()

        if sql_norm.startswith("SELECT data FROM definition WHERE meta_class"):
            row = self.db.definitions.get(params[0])
            if row is None:
                self._result = None
            else:
                self._result = {"data": row["data"]} if self._is_dict_cursor() else (row["data"],)

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

        elif sql_norm.startswith("DELETE FROM definition WHERE meta_class"):
            (meta_class,) = params
            if meta_class in self.db.definitions:
                del self.db.definitions[meta_class]
                self.rowcount = 1
            else:
                self.rowcount = 0

        elif sql_norm.startswith("SELECT id, tenants, deleted_at FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            self._result = (obj["id"], obj["tenants"], obj["deleted_at"]) if obj else None

        elif sql_norm.startswith("SELECT id, class, meta_class, tenants, deleted_at FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            if obj is None:
                self._result = None
            elif self._is_dict_cursor():
                self._result = dict(obj)
            else:
                self._result = (obj["id"], obj["class"], obj["meta_class"], obj["tenants"], obj["deleted_at"])

        elif sql_norm.startswith("SELECT id, meta_class, class, tenants FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            self._result = dict(obj) if obj else None

        elif sql_norm.startswith("SELECT deleted_at FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            self._result = (obj["deleted_at"],) if obj else None

        elif sql_norm.startswith("SELECT id, deleted_at, tenants FROM object WHERE id"):
            obj = self.db.objects.get(params[0])
            self._result = (obj["id"], obj["deleted_at"], obj["tenants"]) if obj else None

        elif sql_norm.startswith("INSERT INTO object"):
            meta_class, cls, tenants = params
            obj_id = self.db._next_obj_id
            self.db._next_obj_id += 1
            self.db.objects[obj_id] = {"id": obj_id, "meta_class": meta_class, "class": cls, "tenants": tenants, "deleted_at": None}
            self._result = (obj_id,)

        elif sql_norm.startswith("UPDATE object SET meta_class"):
            meta_class, cls, tenants, obj_id = params
            self.db.objects[obj_id].update({"meta_class": meta_class, "class": cls, "tenants": tenants})

        elif sql_norm.startswith("UPDATE object SET deleted_at = now() WHERE id = %s RETURNING deleted_at"):
            (obj_id,) = params
            self.db.objects[obj_id]["deleted_at"] = _FakeNow()
            self._result = (self.db.objects[obj_id]["deleted_at"],)

        elif sql_norm.startswith("UPDATE attribute_value SET valid_to = now() WHERE valid_to IS NULL AND attribute_id IN"):
            (object_id,) = params
            attr_ids = {a["id"] for a in self.db.attributes.values() if a["object_id"] == object_id}
            for v in self.db.attribute_values.values():
                if v["attribute_id"] in attr_ids and v["valid_to"] is None:
                    v["valid_to"] = "now"

        elif sql_norm.startswith("UPDATE attribute_value SET valid_to = now() WHERE joint_id = %s AND valid_to IS NULL"):
            (joint_id,) = params
            for v in self.db.attribute_values.values():
                if v["joint_id"] == joint_id and v["valid_to"] is None:
                    v["valid_to"] = "now"

        elif sql_norm.startswith("UPDATE attribute_value av SET valid_to = now() FROM attribute a, object o"):
            joint_id, actor_tenants = params
            actor_tenants = set(actor_tenants or [])
            for v in self.db.attribute_values.values():
                if v["joint_id"] != joint_id or v["valid_to"] is not None:
                    continue
                attr = self.db.attributes.get(v["attribute_id"])
                if attr is None:
                    continue
                src_obj = self.db.objects.get(attr["object_id"])
                if src_obj is None:
                    continue
                src_tenants = src_obj.get("tenants")
                if not src_tenants or set(src_tenants.split(",")) & actor_tenants:
                    v["valid_to"] = "now"

        # Aucune branche DELETE FROM attribute / attribute_value, volontairement :
        # l'historisation (plan-mark2.md action 6.0) interdit toute suppression
        # physique par les routes d'écriture. Une régression vers un DELETE
        # tombe dans le `else` final et lève AssertionError.

        elif sql_norm.startswith("UPDATE attribute_value SET valid_to = now() WHERE id ="):
            (value_id,) = params
            self.db.attribute_values[value_id]["valid_to"] = "now"

        elif sql_norm.startswith("UPDATE attribute SET domain = %s WHERE id ="):
            domain, attr_id = params
            self.db.attributes[attr_id]["domain"] = domain

        elif sql_norm.startswith("INSERT INTO attribute (object_id, domain, name)"):
            object_id, domain, name = params
            if any(a["object_id"] == object_id and a["name"] == name for a in self.db.attributes.values()):
                raise AssertionError(f"UNIQUE (object_id, name) violée : {object_id}/{name}")
            attr_id = self.db._next_attr_id
            self.db._next_attr_id += 1
            self.db.attributes[attr_id] = {"id": attr_id, "object_id": object_id, "domain": domain, "name": name}
            self._result = {"id": attr_id} if self._is_dict_cursor() else (attr_id,)

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
                vals = [
                    v for v in self.db.attribute_values.values()
                    if v["attribute_id"] == a["id"] and v["valid_to"] is None
                ]
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

    def _is_dict_cursor(self):
        return isinstance(self, FakeRealDictCursor)

    def _store_value(self, attribute_id, value_integer=None, value_float=None, value_string=None, joint_id=None):
        vid = self.db._next_val_id
        self.db._next_val_id += 1
        self.db.attribute_values[vid] = {
            "id": vid, "attribute_id": attribute_id,
            "value_integer": value_integer, "value_float": value_float,
            "value_string": value_string, "joint_id": joint_id,
            "valid_to": None,
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
            {"domain": "details", "name": "membres", "type": "joint-1-n", "classes": ["immatriculation"]},
        ],
    },
]


def _seed(db):
    db.seed_definition("registre", REGISTRE)


def _value_rows(db, object_id, attr_name):
    """Toutes les lignes attribute_value (actives ET fermées) de l'attribut
    `attr_name` de l'objet, triées par id - la vue « historique » que les
    routes de lecture ne doivent jamais exposer mais que les tests comptent."""
    attr_ids = {a["id"] for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == attr_name}
    return sorted(
        (v for v in db.attribute_values.values() if v["attribute_id"] in attr_ids),
        key=lambda v: v["id"],
    )


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
#    endpoints qui passent par _coerce_typed_value.
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


# ---------------------------------------------------------------------
# 9. Historisation (plan-mark2.md action 6.0) : les routes d'écriture ne
#    suppriment jamais une ligne attribute_value, elles ferment (valid_to)
#    et insèrent. Les tests comptent les lignes physiques du store, pas
#    seulement ce que la lecture expose - le harnais précédent, qui simulait
#    une fermeture par suppression et acceptait un DELETE, était aveugle à
#    la destruction d'historique par write_attribute_value.
# ---------------------------------------------------------------------

def _create(client, attributes):
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation", "attributes": attributes,
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


def _update(client, object_id, attributes):
    resp = client.post("/api/write/object", json={
        "id": object_id, "meta_class": "registre", "class": "immatriculation", "attributes": attributes,
    })
    assert resp.status_code == 200, resp.get_json()


def _read_values(client, object_id, attr_name):
    read = client.get(f"/api/read/object/{object_id}").get_json()
    return next(a["values"] for a in read["attributes"] if a["name"] == attr_name)


def test_history_three_write_object_on_scalar_keeps_all_rows(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})
    _update(client, object_id, {"matricule": "002"})
    _update(client, object_id, {"matricule": "003"})

    rows = _value_rows(db, object_id, "matricule")
    assert len(rows) == 3
    assert [r["value_string"] for r in rows] == ["001", "002", "003"]
    assert [r["valid_to"] for r in rows] == ["now", "now", None]
    assert len({r["attribute_id"] for r in rows}) == 1
    assert len([a for a in db.attributes.values() if a["object_id"] == object_id]) == 1
    assert _read_values(client, object_id, "matricule") == ["003"]


def test_history_write_attribute_value_preserves_closed_rows(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})
    _update(client, object_id, {"matricule": "002"})

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/003")
    assert put.status_code == 200, put.get_json()

    rows = _value_rows(db, object_id, "matricule")
    assert len(rows) == 3, "write_attribute_value a détruit l'historique"
    assert [r["value_string"] for r in rows] == ["001", "002", "003"]
    assert [r["valid_to"] for r in rows] == ["now", "now", None]
    assert len({r["attribute_id"] for r in rows}) == 1
    assert _read_values(client, object_id, "matricule") == ["003"]


def test_history_identical_value_creates_no_row(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001", "age": 7})
    _update(client, object_id, {"matricule": "001", "age": 7})
    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/001")
    assert put.status_code == 200, put.get_json()
    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/age/7")
    assert put.status_code == 200, put.get_json()

    for attr_name in ("matricule", "age"):
        rows = _value_rows(db, object_id, attr_name)
        assert len(rows) == 1
        assert rows[0]["valid_to"] is None


def test_history_multivalued_remove_and_add_touches_only_two_rows(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    targets = [_create(client, {"matricule": f"{i:03d}"}) for i in range(1, 5)]
    object_id = _create(client, {
        "matricule": "100",
        "membres": [{"joint_id": targets[0]}, {"joint_id": targets[1]}, {"joint_id": targets[2]}],
    })
    before = {r["id"]: dict(r) for r in _value_rows(db, object_id, "membres")}
    assert len(before) == 3

    _update(client, object_id, {
        "matricule": "100",
        "membres": [{"joint_id": targets[0]}, {"joint_id": targets[2]}, {"joint_id": targets[3]}],
    })

    rows = _value_rows(db, object_id, "membres")
    assert len(rows) == 4
    closed = [r for r in rows if r["valid_to"] is not None]
    active = [r for r in rows if r["valid_to"] is None]
    assert [r["joint_id"] for r in closed] == [targets[1]]
    assert sorted(r["joint_id"] for r in active) == sorted([targets[0], targets[2], targets[3]])
    untouched = [r for r in rows if r["id"] in before and r["joint_id"] != targets[1]]
    assert all(r == before[r["id"]] for r in untouched)
    assert sorted(_read_values(client, object_id, "membres"), key=lambda v: v["joint_id"]) == sorted(
        [{"joint_id": targets[0]}, {"joint_id": targets[2]}, {"joint_id": targets[3]}],
        key=lambda v: v["joint_id"],
    )


def test_history_joint_id_string_is_coerced_to_int(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    target = _create(client, {"matricule": "001"})
    object_id = _create(client, {"matricule": "100", "lien": {"joint_id": str(target)}})
    rows = _value_rows(db, object_id, "lien")
    assert rows[0]["joint_id"] == target
    assert isinstance(rows[0]["joint_id"], int)

    _update(client, object_id, {"matricule": "100", "lien": {"joint_id": target}})
    assert len(_value_rows(db, object_id, "lien")) == 1

    bad = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "100", "lien": {"joint_id": "abc"}},
    })
    assert bad.status_code == 400


def test_history_joint_id_bool_is_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    bad = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "100", "lien": {"joint_id": True}},
    })
    assert bad.status_code == 400


def test_history_joint_id_non_integer_float_is_rejected(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    bad = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "100", "lien": {"joint_id": 5.7}},
    })
    assert bad.status_code == 400


def test_history_joint_id_integer_float_is_coerced_to_int(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    target = _create(client, {"matricule": "001"})
    object_id = _create(client, {"matricule": "100", "lien": {"joint_id": float(target)}})
    rows = _value_rows(db, object_id, "lien")
    assert rows[0]["joint_id"] == target
    assert isinstance(rows[0]["joint_id"], int)


def test_history_attribute_domain_realigned_on_model_change(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})
    attr = next(a for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == "matricule")
    assert attr["domain"] == "details"

    moved = json.loads(json.dumps(REGISTRE))
    next(a for a in moved[0]["attributes"] if a["name"] == "matricule")["domain"] = "identite"
    db.seed_definition("registre", moved)

    _update(client, object_id, {"matricule": "001"})
    assert attr["domain"] == "identite"
    assert len([a for a in db.attributes.values() if a["object_id"] == object_id]) == 1
    assert len(_value_rows(db, object_id, "matricule")) == 1


def test_fake_cursor_rejects_any_delete_on_attribute_tables():
    cur = FakeCursor(FakeDB())
    for sql in (
        "DELETE FROM attribute_value WHERE attribute_id = %s",
        "DELETE FROM attribute_value WHERE attribute_id IN (SELECT id FROM attribute WHERE object_id = %s)",
        "DELETE FROM attribute WHERE object_id = %s",
    ):
        with pytest.raises(AssertionError):
            cur.execute(sql, (1,))


# ---------------------------------------------------------------------
# 10. Historisation (plan-mark2.md action 6.0), cas restés sans test :
#     attribut omis du corps (fermeture complète), réécriture d'une valeur
#     déjà historisée (jamais de réouverture), liste vide sur un
#     multi-valué, création de la ligne `attribute` par write_attribute_value.
# ---------------------------------------------------------------------

def test_history_omitted_attribute_closes_all_active_values_without_insert(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    targets = [_create(client, {"matricule": f"{i:03d}"}) for i in range(1, 3)]
    object_id = _create(client, {
        "matricule": "100", "age": 7,
        "membres": [{"joint_id": targets[0]}, {"joint_id": targets[1]}],
    })
    before_ids = sorted(v["id"] for v in db.attribute_values.values())
    assert len(_value_rows(db, object_id, "age")) == 1
    assert len(_value_rows(db, object_id, "membres")) == 2

    _update(client, object_id, {"matricule": "100"})

    assert sorted(v["id"] for v in db.attribute_values.values()) == before_ids, "insertion ou DELETE inattendu"
    assert [r["valid_to"] for r in _value_rows(db, object_id, "age")] == ["now"]
    assert [r["valid_to"] for r in _value_rows(db, object_id, "membres")] == ["now", "now"]
    assert [r["valid_to"] for r in _value_rows(db, object_id, "matricule")] == [None]
    assert len([a for a in db.attributes.values() if a["object_id"] == object_id]) == 3
    assert _read_values(client, object_id, "age") == []
    assert _read_values(client, object_id, "membres") == []
    assert _read_values(client, object_id, "matricule") == ["100"]


def test_history_write_attribute_value_back_to_old_value_never_reopens_closed_row(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"age": 1})
    for value in ("001", "002", "001"):
        put = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/{value}")
        assert put.status_code == 200, put.get_json()

    rows = _value_rows(db, object_id, "matricule")
    assert len(rows) == 3
    assert [r["value_string"] for r in rows] == ["001", "002", "001"]
    assert [r["valid_to"] for r in rows] == ["now", "now", None]
    assert rows[0]["valid_to"] == "now", "la première ligne '001' a été réouverte"
    assert len({r["attribute_id"] for r in rows}) == 1
    assert _read_values(client, object_id, "matricule") == ["001"]


def test_history_multivalued_empty_list_closes_all_without_insert(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    targets = [_create(client, {"matricule": f"{i:03d}"}) for i in range(1, 4)]
    object_id = _create(client, {
        "matricule": "100",
        "membres": [{"joint_id": t} for t in targets],
    })
    before_ids = [r["id"] for r in _value_rows(db, object_id, "membres")]
    assert len(before_ids) == 3

    _update(client, object_id, {"matricule": "100", "membres": []})

    rows = _value_rows(db, object_id, "membres")
    assert [r["id"] for r in rows] == before_ids
    assert [r["valid_to"] for r in rows] == ["now", "now", "now"]
    assert len([a for a in db.attributes.values() if a["object_id"] == object_id and a["name"] == "membres"]) == 1
    assert _read_values(client, object_id, "membres") == []


def test_history_write_attribute_value_creates_attribute_row_when_missing(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "100"})
    assert [a["name"] for a in db.attributes.values() if a["object_id"] == object_id] == ["matricule"]
    values_before = len(db.attribute_values)

    put = client.put(f"/api/write/attribute/immatriculation/{object_id}/age/5")
    assert put.status_code == 200, put.get_json()

    attrs = [a for a in db.attributes.values() if a["object_id"] == object_id]
    assert sorted(a["name"] for a in attrs) == ["age", "matricule"]
    age_attr = next(a for a in attrs if a["name"] == "age")
    assert age_attr["domain"] == "details"
    rows = _value_rows(db, object_id, "age")
    assert len(rows) == 1
    assert rows[0] == {
        "id": rows[0]["id"], "attribute_id": age_attr["id"],
        "value_integer": 5, "value_float": None, "value_string": None, "joint_id": None,
        "valid_to": None,
    }
    assert len(db.attribute_values) == values_before + 1
    assert _read_values(client, object_id, "age") == [5]


# ---------------------------------------------------------------------
# 11. Suppression logique (plan-mark2.md action 6.1) : delete_object.
#     Rapatrié depuis le fichier scratchpad du testeur (infra vraie DB),
#     adapté au harnais FakeDB/FakeCursor ci-dessus.
# ---------------------------------------------------------------------

def test_delete_object_closes_active_values_and_sets_deleted_at(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001", "age": 7})

    resp = client.delete(f"/api/delete/object/{object_id}")
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["deleted_at"] == "now"
    assert db.objects[object_id]["deleted_at"] is not None

    for attr_name in ("matricule", "age"):
        rows = _value_rows(db, object_id, attr_name)
        assert rows and all(r["valid_to"] is not None for r in rows)


def test_delete_object_twice_returns_404(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})

    first = client.delete(f"/api/delete/object/{object_id}")
    assert first.status_code == 200

    second = client.delete(f"/api/delete/object/{object_id}")
    assert second.status_code == 404


def test_delete_object_rejected_for_tenant_readonly(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})

    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_readonly=True, tenants=["tenant1"]))
    resp = client.delete(f"/api/delete/object/{object_id}")
    assert resp.status_code == 403
    assert db.objects[object_id]["deleted_at"] is None


def test_delete_object_rejected_for_tenant_admin_out_of_scope(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "001"}, "tenants": ["tenant1"],
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant2"]))
    resp = client.delete(f"/api/delete/object/{object_id}")
    assert resp.status_code == 403
    assert db.objects[object_id]["deleted_at"] is None


def test_delete_object_allowed_for_tenant_admin_in_scope(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "001"}, "tenants": ["tenant1"],
    })
    object_id = resp.get_json()["id"]

    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))
    resp = client.delete(f"/api/delete/object/{object_id}")
    assert resp.status_code == 200
    assert db.objects[object_id]["deleted_at"] is not None


def test_delete_object_allowed_for_global_admin_regardless_of_tenant(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "001"}, "tenants": ["tenant1"],
    })
    object_id = resp.get_json()["id"]

    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))
    resp = client.delete(f"/api/delete/object/{object_id}")
    assert resp.status_code == 200
    assert db.objects[object_id]["deleted_at"] is not None


def test_delete_object_cascade_closes_all_incoming_joins_for_global_admin(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    target = _create(client, {"matricule": "100"})
    source1 = _create(client, {"matricule": "001", "lien": {"joint_id": target}})
    source2 = _create(client, {"matricule": "002", "lien": {"joint_id": target}})

    resp = client.delete(f"/api/delete/object/{target}")
    assert resp.status_code == 200

    for source in (source1, source2):
        rows = _value_rows(db, source, "lien")
        assert rows and all(r["valid_to"] is not None for r in rows)
        assert _read_values(client, source, "lien") == []


def test_delete_object_cascade_scoped_to_tenant_for_tenant_admin(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    target = _create(client, {"matricule": "100"})
    # Le target doit être dans le périmètre tenant1 pour que le tenant-admin
    # puisse le supprimer (RBAC vérifié par ailleurs ci-dessus).
    db.objects[target]["tenants"] = "tenant1"

    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "001", "lien": {"joint_id": target}}, "tenants": ["tenant1"],
    })
    source_in_scope = resp.get_json()["id"]

    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "002", "lien": {"joint_id": target}}, "tenants": ["tenant2"],
    })
    source_out_of_scope = resp.get_json()["id"]

    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))
    resp = client.delete(f"/api/delete/object/{target}")
    assert resp.status_code == 200

    rows_in_scope = _value_rows(db, source_in_scope, "lien")
    assert rows_in_scope and all(r["valid_to"] is not None for r in rows_in_scope)

    rows_out_of_scope = _value_rows(db, source_out_of_scope, "lien")
    assert rows_out_of_scope and all(r["valid_to"] is None for r in rows_out_of_scope)


def test_delete_object_then_create_new_joint_toward_it_rejected(client, db_and_ctx):
    """Garde-fou anti-zombie (_apply_attribute_diff) : un objet supprimé ne
    doit jamais pouvoir recevoir une nouvelle jointure entrante - ici via
    write_object en création."""
    db = db_and_ctx
    _seed(db)
    target = _create(client, {"matricule": "100"})
    client.delete(f"/api/delete/object/{target}")

    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "001", "lien": {"joint_id": target}},
    })
    assert resp.status_code == 400


def test_delete_object_then_update_adding_new_joint_toward_it_rejected(client, db_and_ctx):
    """Même garde-fou, via write_object en mise à jour (remplacement d'un
    lien actif par un nouveau pointant vers un objet entre-temps supprimé)."""
    db = db_and_ctx
    _seed(db)
    alive = _create(client, {"matricule": "100"})
    target = _create(client, {"matricule": "200"})
    object_id = _create(client, {"matricule": "001", "lien": {"joint_id": alive}})

    client.delete(f"/api/delete/object/{target}")

    resp = client.post("/api/write/object", json={
        "id": object_id, "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "001", "lien": {"joint_id": target}},
    })
    assert resp.status_code == 400


def test_write_object_update_on_deleted_object_returns_404(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})
    client.delete(f"/api/delete/object/{object_id}")

    resp = client.post("/api/write/object", json={
        "id": object_id, "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "002"},
    })
    assert resp.status_code == 404


def test_write_attribute_value_on_deleted_object_returns_404(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})
    client.delete(f"/api/delete/object/{object_id}")

    resp = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/002")
    assert resp.status_code == 404


# ---------------------------------------------------------------------
# 12. Deadlock PostgreSQL (plan-mark2.md action 6.1, correction arbitrage
#     point 1) : cycle réel mais rare entre delete_object et write_object/
#     write_attribute_value (delete_object tient B puis attend R, un write
#     concurrent ferme R puis attend FOR SHARE sur B). PostgreSQL le
#     détecte et annule l'une des deux transactions : les 3 routes
#     attrapent désormais psycopg2.errors.DeadlockDetected avant le except
#     Exception générique et renvoient 409 plutôt que de laisser
#     l'exception remonter (500 non catché côté client).
# ---------------------------------------------------------------------

class _DeadlockCursor(FakeCursor):
    """FakeCursor qui lève DeadlockDetected dès qu'un execute() correspond
    au préfixe SQL donné, pour simuler le point précis de la transaction où
    PostgreSQL aurait détecté le cycle - le reste du comportement (SELECT/
    INSERT/UPDATE précédents) est inchangé, délégué à FakeCursor."""

    def __init__(self, db, trigger_prefix):
        super().__init__(db)
        self.trigger_prefix = trigger_prefix

    def execute(self, sql, params=None):
        if " ".join(sql.split()).startswith(self.trigger_prefix):
            raise psycopg2.errors.DeadlockDetected("deadlock detected")
        super().execute(sql, params)


class DeadlockConn(FakeConn):
    def __init__(self, db, trigger_prefix):
        super().__init__(db)
        self.trigger_prefix = trigger_prefix
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        if cursor_factory is not None:
            return FakeRealDictCursor(self.db)
        return _DeadlockCursor(self.db, self.trigger_prefix)

    def rollback(self):
        self.rolled_back = True
        super().rollback()


def test_delete_object_deadlock_returns_409(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})

    conn = DeadlockConn(db, "UPDATE object SET deleted_at = now()")
    monkeypatch.setattr(miami_app, "get_db", lambda: conn)

    resp = client.delete(f"/api/delete/object/{object_id}")
    assert resp.status_code == 409
    assert "Conflit" in resp.get_data(as_text=True)
    assert conn.rolled_back
    assert db.objects[object_id]["deleted_at"] is None


def test_write_object_deadlock_returns_409(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)

    conn = DeadlockConn(db, "INSERT INTO attribute_value (attribute_id, value_string)")
    monkeypatch.setattr(miami_app, "get_db", lambda: conn)

    resp = client.post("/api/write/object", json={
        "meta_class": "registre", "class": "immatriculation",
        "attributes": {"matricule": "001"},
    })
    assert resp.status_code == 409
    assert "Conflit" in resp.get_data(as_text=True)
    assert conn.rolled_back


def test_write_attribute_value_deadlock_returns_409(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})

    conn = DeadlockConn(db, "INSERT INTO attribute_value (attribute_id, value_string)")
    monkeypatch.setattr(miami_app, "get_db", lambda: conn)

    resp = client.put(f"/api/write/attribute/immatriculation/{object_id}/matricule/002")
    assert resp.status_code == 409
    assert "Conflit" in resp.get_data(as_text=True)
    assert conn.rolled_back


# ---------------------------------------------------------------------
# 13. Suppression physique du schéma (plan-mark2.md actions 6.3/6.4) :
#     delete_class et delete_metaclass. Aucune FK entre `object` et
#     `definition` (§3.4) : ces routes ne touchent jamais db.objects.
# ---------------------------------------------------------------------

def test_delete_class_removes_only_target_class(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    db.definitions["registre"]["data"]["classes"] = list(REGISTRE) + [
        {"class": "autre_classe", "attributes": [{"domain": "d", "name": "x", "type": "string"}]}
    ]

    resp = client.delete("/api/delete/class/registre/immatriculation")
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {"status": "ok", "class": "immatriculation"}

    classes = db.definitions["registre"]["data"]["classes"]
    assert [c["class"] for c in classes] == ["autre_classe"]


def test_delete_class_404_on_missing_metaclass(client, db_and_ctx):
    resp = client.delete("/api/delete/class/inconnue/x")
    assert resp.status_code == 404


def test_delete_class_404_on_missing_class(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    resp = client.delete("/api/delete/class/registre/classe_inexistante")
    assert resp.status_code == 404
    assert len(db.definitions["registre"]["data"]["classes"]) == 1


def test_delete_class_rejected_for_tenant_readonly(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_readonly=True, tenants=["tenant1"]))

    resp = client.delete("/api/delete/class/registre/immatriculation")
    assert resp.status_code == 403
    assert len(db.definitions["registre"]["data"]["classes"]) == 1


def test_delete_class_rejected_for_tenant_admin_out_of_scope(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    db.seed_definition("registre", [
        {"class": "immatriculation", "attributes": [{"domain": "d", "name": "matricule", "type": "string"}], "tenants": ["tenant2"]},
    ])
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))

    resp = client.delete("/api/delete/class/registre/immatriculation")
    assert resp.status_code == 403
    assert len(db.definitions["registre"]["data"]["classes"]) == 1


def test_delete_class_allowed_for_tenant_admin_in_scope(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    db.seed_definition("registre", [
        {"class": "immatriculation", "attributes": [{"domain": "d", "name": "matricule", "type": "string"}], "tenants": ["tenant1"]},
    ])
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))

    resp = client.delete("/api/delete/class/registre/immatriculation")
    assert resp.status_code == 200
    assert db.definitions["registre"]["data"]["classes"] == []


def test_delete_class_allowed_for_global_admin_regardless_of_tenant(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    db.seed_definition("registre", [
        {"class": "immatriculation", "attributes": [{"domain": "d", "name": "matricule", "type": "string"}], "tenants": ["tenant2"]},
    ])
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.delete("/api/delete/class/registre/immatriculation")
    assert resp.status_code == 200
    assert db.definitions["registre"]["data"]["classes"] == []


def test_delete_class_does_not_touch_existing_objects(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})

    resp = client.delete("/api/delete/class/registre/immatriculation")
    assert resp.status_code == 200
    assert object_id in db.objects
    assert db.objects[object_id]["deleted_at"] is None


def test_delete_metaclass_removes_definition_row(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)

    resp = client.delete("/api/delete/metaclass/registre")
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {"status": "ok", "meta_class": "registre"}
    assert "registre" not in db.definitions


def test_delete_metaclass_404_on_missing_metaclass(client, db_and_ctx):
    resp = client.delete("/api/delete/metaclass/inconnue")
    assert resp.status_code == 404


def test_delete_metaclass_rejected_for_tenant_readonly(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_readonly=True, tenants=["tenant1"]))

    resp = client.delete("/api/delete/metaclass/registre")
    assert resp.status_code == 403
    assert "registre" in db.definitions


def test_delete_metaclass_allowed_for_global_admin(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    _seed(db)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.delete("/api/delete/metaclass/registre")
    assert resp.status_code == 200
    assert "registre" not in db.definitions


def test_delete_metaclass_rejected_for_tenant_admin_out_of_scope(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    db.seed_definition("registre", [
        {"class": "immatriculation", "attributes": [{"domain": "d", "name": "matricule", "type": "string"}], "tenants": ["tenant2"]},
    ])
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))

    resp = client.delete("/api/delete/metaclass/registre")
    assert resp.status_code == 403
    assert "registre" in db.definitions


def test_delete_metaclass_allowed_for_tenant_admin_in_scope(client, db_and_ctx, monkeypatch):
    db = db_and_ctx
    db.seed_definition("registre", [
        {"class": "immatriculation", "attributes": [{"domain": "d", "name": "matricule", "type": "string"}], "tenants": ["tenant1"]},
    ])
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]))

    resp = client.delete("/api/delete/metaclass/registre")
    assert resp.status_code == 200
    assert "registre" not in db.definitions


def test_delete_metaclass_does_not_touch_existing_objects(client, db_and_ctx):
    db = db_and_ctx
    _seed(db)
    object_id = _create(client, {"matricule": "001"})

    resp = client.delete("/api/delete/metaclass/registre")
    assert resp.status_code == 200
    assert object_id in db.objects
    assert db.objects[object_id]["deleted_at"] is None

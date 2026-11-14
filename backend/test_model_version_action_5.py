"""Tests ciblés sur plan-mark3.md action 5 : champ "version" (optionnel,
entier >= 1, défaut 1) sur un document modèle (meta_class/classes),
propagé par /api/init (deux branches RBAC : fusion tenant-admin et
remplacement intégral global-admin) et /api/write/metaclass, et exposé
dans la réponse de /api/init sous "versions" (dict meta_class -> version)
sans changer la forme de "loaded" (liste de noms).

Même convention que backend/test_rbac_class_tenant_scope.py : pas de
vraie base Postgres ni de vrai Keycloak, get_db()/get_auth_context() sont
monkeypatchés, et SCHEMA_PATH doit pointer vers le vrai model/schema.json
du dépôt. Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/test_model_version_action_5.py -v
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import app as miami_app  # noqa: E402


def make_ctx(is_global_admin=False, is_tenant_admin=False, is_tenant_readonly=False, tenants=None):
    return miami_app.AuthContext(is_global_admin, is_tenant_admin, is_tenant_readonly, tenants or [])


class FakeCursor:
    """Simule juste assez de l'API psycopg2 pour write_metaclass /
    init_from_model_files sur la table `definition` (id, meta_class, data)."""

    def __init__(self, store):
        self.store = store
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT id, data FROM definition WHERE meta_class"):
            row = self.store.get(params[0])
            self._result = {"id": row["id"], "data": row["data"]} if row else None
        elif sql_norm.startswith("SELECT data FROM definition WHERE meta_class"):
            row = self.store.get(params[0])
            self._result = {"data": row["data"]} if row else None
        elif sql_norm.startswith("UPDATE definition SET data"):
            data_json, row_id = params
            for row in self.store.values():
                if row["id"] == row_id:
                    row["data"] = json.loads(data_json)
                    break
        elif sql_norm.startswith("INSERT INTO definition"):
            meta_class, data_json = params
            if meta_class in self.store:
                self.store[meta_class]["data"] = json.loads(data_json)
            else:
                new_id = max([r["id"] for r in self.store.values()], default=0) + 1
                self.store[meta_class] = {"id": new_id, "data": json.loads(data_json)}
        else:
            raise AssertionError(f"SQL non géré par FakeCursor : {sql_norm!r}")

    def fetchone(self):
        return self._result


class FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self, cursor_factory=None):
        return FakeCursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(miami_app.app.before_request_funcs, None, [])
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


def _write_model_file(tmp_path, filename, content):
    (tmp_path / filename).write_text(json.dumps(content))


# ---------------------------------------------------------------------
# 1. Non-régression : fichier model/*.json sans "version" reste chargeable
#    (défaut 1), global-admin.
# ---------------------------------------------------------------------

def test_init_loads_file_without_version_defaults_to_1(client, monkeypatch, tmp_path):
    _write_model_file(tmp_path, "personnes.json", {
        "meta_class": "personne",
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    store = {}
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == ["personne"]
    assert body["versions"] == {"personne": 1}
    assert store["personne"]["data"]["version"] == 1


def test_init_loads_all_existing_repo_model_files(client, monkeypatch):
    """Les fichiers model/*.json réels du dépôt (sans "version" pour la
    plupart) restent tous chargeables sans erreur, que le schéma aie ou non
    la propriété "version" ajoutée."""
    repo_model_dir = os.path.join(os.path.dirname(__file__), "..", "model")

    store = {}
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))
    monkeypatch.setenv("MODEL_DIR", repo_model_dir)

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body["loaded"], list)
    assert all(isinstance(name, str) for name in body["loaded"])
    assert body["skipped"] == []
    assert set(body["versions"].keys()) == set(body["loaded"])


# ---------------------------------------------------------------------
# 2. Version explicite conservée après chargement, /api/init (global-admin)
# ---------------------------------------------------------------------

def test_init_preserves_explicit_version_global_admin(client, monkeypatch, tmp_path):
    _write_model_file(tmp_path, "personnes.json", {
        "meta_class": "personne",
        "version": 3,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    store = {}
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["versions"] == {"personne": 3}
    assert store["personne"]["data"]["version"] == 3


# ---------------------------------------------------------------------
# 3. /api/init, tenant-admin, branche fusion classe par classe : un document
#    déjà existant en base n'a sa "version" écrasée par celle du fichier
#    rechargé que si une classe a réellement été skippée pour hors
#    périmètre tenant pendant cette fusion (pas juste "une ligne existait
#    déjà") - cf. correction croisée action 5.
# ---------------------------------------------------------------------

def test_init_preserves_explicit_version_tenant_admin_merge_branch(client, monkeypatch, tmp_path):
    store = {
        "personne": {
            "id": 1,
            "data": {
                "meta_class": "personne",
                "version": 5,
                "classes": [
                    {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}], "tenants": ["tenant1"]},
                    {"class": "personne_morale", "attributes": [{"domain": "d", "name": "raison_sociale", "type": "string"}], "tenants": ["tenant2"]},
                ],
            },
        }
    }

    _write_model_file(tmp_path, "personnes.json", {
        "meta_class": "personne",
        "version": 2,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}], "tenants": ["tenant1"]},
            {"class": "personne_morale", "attributes": [{"domain": "d", "name": "raison_sociale", "type": "string"}], "tenants": ["tenant2"]},
        ],
    })

    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == ["personne"]
    # personne_morale (tenant2) hors périmètre du tenant-admin (tenant1),
    # présente dans le fichier rechargé : réellement skippée pendant cette
    # fusion -> la version du fichier rechargé (2) n'écrase pas la version
    # stockée (5).
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["class"] == "personne_morale"
    assert body["versions"] == {"personne": 5}
    assert store["personne"]["data"]["version"] == 5
    by_name = {c["class"]: c for c in store["personne"]["data"]["classes"]}
    assert by_name["personne_morale"]["tenants"] == ["tenant2"]


# ---------------------------------------------------------------------
# 4. Version explicite conservée après chargement, /api/write/metaclass
# ---------------------------------------------------------------------

def test_write_metaclass_preserves_explicit_version(client, monkeypatch):
    store = {}
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.post("/api/write/metaclass", json={
        "meta_class": "personne",
        "version": 5,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    assert resp.status_code == 201
    assert store["personne"]["data"]["version"] == 5


def test_write_metaclass_defaults_version_to_1_when_absent(client, monkeypatch):
    store = {}
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.post("/api/write/metaclass", json={
        "meta_class": "personne",
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    assert resp.status_code == 201
    assert store["personne"]["data"]["version"] == 1


# ---------------------------------------------------------------------
# 5. Correction croisée : un float à valeur entière ("version": 2.0) est
#    rejeté, /api/write/metaclass et /api/init (jsonschema.validate accepte
#    un float sans partie fractionnaire comme "integer" au sens JSON Schema,
#    donc check explicite requis en plus du schéma).
# ---------------------------------------------------------------------

def test_write_metaclass_rejects_float_version(client, monkeypatch):
    store = {}
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.post("/api/write/metaclass", json={
        "meta_class": "personne",
        "version": 2.0,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    assert resp.status_code == 400
    assert "personne" not in store


def test_init_skips_file_with_float_version(client, monkeypatch, tmp_path):
    _write_model_file(tmp_path, "personnes.json", {
        "meta_class": "personne",
        "version": 2.0,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    store = {}
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == []
    assert "personne" not in body["versions"]
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["meta_class"] == "personne"
    assert "personne" not in store


# ---------------------------------------------------------------------
# 6. /api/init, tenant-admin, fusion partielle où la classe hors périmètre
#    (personne_morale, tenant2) est simplement absente du fichier rechargé
#    (jamais visitée par la boucle de fusion, donc jamais réellement
#    skippée pour hors-périmètre pendant CE chargement) : contenu préservé
#    tel quel comme toute classe absente du fichier, mais sans skip RBAC
#    réel la version suit normalement celle du fichier rechargé (1).
# ---------------------------------------------------------------------

def test_init_tenant_admin_partial_merge_with_out_of_scope_class_preserves_version(client, monkeypatch, tmp_path):
    store = {
        "personne": {
            "id": 1,
            "data": {
                "meta_class": "personne",
                "version": 5,
                "classes": [
                    {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}], "tenants": ["tenant1"]},
                    {"class": "personne_morale", "attributes": [{"domain": "d", "name": "raison_sociale", "type": "string"}], "tenants": ["tenant2"]},
                ],
            },
        }
    }

    _write_model_file(tmp_path, "personnes.json", {
        "meta_class": "personne",
        "version": 1,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}], "tenants": ["tenant1"]},
        ],
    })

    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == ["personne"]
    assert body["skipped"] == []
    assert body["versions"]["personne"] == 1
    assert store["personne"]["data"]["version"] == 1
    by_name = {c["class"]: c for c in store["personne"]["data"]["classes"]}
    assert by_name["personne_morale"]["tenants"] == ["tenant2"]


def test_init_tenant_admin_first_creation_keeps_file_version(client, monkeypatch, tmp_path):
    _write_model_file(tmp_path, "personnes.json", {
        "meta_class": "personne",
        "version": 2,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}], "tenants": ["tenant1"]},
        ],
    })

    store = {}
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["versions"]["personne"] == 2
    assert store["personne"]["data"]["version"] == 2


# ---------------------------------------------------------------------
# 7. /api/init, tenant-admin, ligne déjà existante en base MAIS aucune
#    classe réellement skippée pour hors périmètre pendant cette fusion
#    (le tenant-admin couvre 100% du contenu du document rechargé) : la
#    version du fichier s'applique normalement, comme pour global-admin -
#    pas de gel de version en l'absence de tout skip RBAC réel.
# ---------------------------------------------------------------------

def test_init_tenant_admin_full_coverage_no_skip_applies_file_version(client, monkeypatch, tmp_path):
    store = {
        "personne": {
            "id": 1,
            "data": {
                "meta_class": "personne",
                "version": 5,
                "classes": [
                    {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}], "tenants": ["tenant1"]},
                ],
            },
        }
    }

    _write_model_file(tmp_path, "personnes.json", {
        "meta_class": "personne",
        "version": 7,
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}], "tenants": ["tenant1"]},
        ],
    })

    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loaded"] == ["personne"]
    assert body["skipped"] == []
    assert body["versions"] == {"personne": 7}
    assert store["personne"]["data"]["version"] == 7

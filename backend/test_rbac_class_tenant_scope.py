"""Tests ciblés sur la correction 3 (action 11, 3e itération) : un
tenant-admin ne doit jamais pouvoir re-tagger silencieusement une classe
globale/hors-tenant existante vers son propre tenant en la remplaçant via
/api/write/class, /api/write/metaclass ou /api/init.

Symétrique à la correction bloquante 2 (re-tagging silencieux d'objets
globaux, plan.md §11.2) mais appliquée aux classes.

Pas de suite de tests automatisés préexistante dans ce dépôt : ce fichier
en pose les bases minimales pour ce scénario, sans dépendance à une vraie
base Postgres ni à un vrai Keycloak (get_db/get_auth_context sont
monkeypatchés). Lancer avec, depuis la racine du dépôt :

    .venv/bin/pip install pytest
    .venv/bin/pytest backend/test_rbac_class_tenant_scope.py -v
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
    """Simule juste assez de l'API psycopg2 pour les requêtes utilisées par
    write_class / write_metaclass / init_from_model_files sur la table
    `definition` (id, meta_class, data)."""

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
    # require_auth() (validation JWT Keycloak, before_request) est hors
    # périmètre de ce test, qui porte sur l'autorisation RBAC-tenant une
    # fois l'identité déjà établie : get_auth_context() est monkeypatché
    # directement par chaque test. Le hook before_request est enregistré
    # par référence directe à la fonction lors du décorateur @app.before_
    # request, donc monkeypatcher l'attribut module 'require_auth' seul ne
    # suffit pas : on neutralise la liste des before_request_funcs elle-même.
    monkeypatch.setitem(miami_app.app.before_request_funcs, None, [])
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


def _seed_personne_store(classes):
    return {
        "personne": {
            "id": 1,
            "data": {"meta_class": "personne", "classes": classes},
        }
    }


# ---------------------------------------------------------------------
# 1. Unit tests sur la fonction pure de décision (sans Flask/DB)
# ---------------------------------------------------------------------

def test_global_class_blocked_for_tenant_admin():
    ctx = make_ctx(is_tenant_admin=True, tenants=["tenant1"])
    existing_cls = {"class": "personne_physique", "attributes": []}  # pas de clé 'tenants' = globale
    assert miami_app._existing_class_out_of_tenant_scope(ctx, existing_cls) is True


def test_global_class_allowed_for_global_admin():
    ctx = make_ctx(is_global_admin=True)
    existing_cls = {"class": "personne_physique", "attributes": []}
    assert miami_app._existing_class_out_of_tenant_scope(ctx, existing_cls) is False


def test_own_tenant_class_allowed_for_tenant_admin():
    ctx = make_ctx(is_tenant_admin=True, tenants=["tenant1"])
    existing_cls = {"class": "personne_physique", "attributes": [], "tenants": ["tenant1"]}
    assert miami_app._existing_class_out_of_tenant_scope(ctx, existing_cls) is False


def test_other_tenant_class_blocked_for_tenant_admin():
    ctx = make_ctx(is_tenant_admin=True, tenants=["tenant1"])
    existing_cls = {"class": "personne_physique", "attributes": [], "tenants": ["tenant2"]}
    assert miami_app._existing_class_out_of_tenant_scope(ctx, existing_cls) is True


# ---------------------------------------------------------------------
# 2. /api/write/class : 403 + classe globale existante inchangée en base
# ---------------------------------------------------------------------

def test_write_class_403_on_existing_global_class_and_no_silent_retag(client, monkeypatch):
    store = _seed_personne_store([
        {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
    ])
    before = copy.deepcopy(store["personne"]["data"])

    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/write/class", json={
        "meta_class": "personne",
        "class": {
            "class": "personne_physique",
            "attributes": [
                {"domain": "d", "name": "nom", "type": "string"},
                {"domain": "d", "name": "intrus", "type": "string"},
            ],
        },
    })

    assert resp.status_code == 403
    # La classe globale existante doit rester strictement inchangée : pas de
    # re-tag silencieux vers tenant1, pas d'attribut "intrus" ajouté.
    assert store["personne"]["data"] == before
    assert "tenants" not in store["personne"]["data"]["classes"][0]


def test_write_class_ok_for_global_admin_on_global_class(client, monkeypatch):
    store = _seed_personne_store([
        {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
    ])

    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))

    resp = client.post("/api/write/class", json={
        "meta_class": "personne",
        "class": {
            "class": "personne_physique",
            "attributes": [{"domain": "d", "name": "nom", "type": "string"}, {"domain": "d", "name": "email", "type": "string"}],
        },
    })

    assert resp.status_code == 200
    assert len(store["personne"]["data"]["classes"][0]["attributes"]) == 2


# ---------------------------------------------------------------------
# 3. /api/write/metaclass : même règle sur un remplacement complet
# ---------------------------------------------------------------------

def test_write_metaclass_403_on_existing_global_class_and_no_silent_retag(client, monkeypatch):
    store = _seed_personne_store([
        {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
    ])
    before = copy.deepcopy(store["personne"]["data"])

    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/write/metaclass", json={
        "meta_class": "personne",
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
        ],
    })

    assert resp.status_code == 403
    assert store["personne"]["data"] == before


def test_write_metaclass_403_before_400_when_rbac_and_schema_both_invalid(client, monkeypatch):
    """Correction plan-mark2.md action 5, point 3 : les gardes RBAC fines
    s'exécutent désormais avant jsonschema.validate dans write_metaclass
    (même ordre que write_class) - un tenant-admin hors périmètre doit
    obtenir 403, pas 400, même si le schéma soumis est par ailleurs
    invalide au regard de model/schema.json."""
    store = _seed_personne_store([
        {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
    ])
    before = copy.deepcopy(store["personne"]["data"])

    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/write/metaclass", json={
        "meta_class": "personne",
        "classes": [
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "type_invalide"}]},
        ],
    })

    assert resp.status_code == 403
    assert store["personne"]["data"] == before


# ---------------------------------------------------------------------
# 4. /api/init : pas de 403 global sur tout le chargement, skip ciblé +
#    classe globale existante inchangée, autres classes traitées normalement
# ---------------------------------------------------------------------

def test_init_skips_only_blocked_class_and_loads_the_rest(client, monkeypatch, tmp_path):
    store = _seed_personne_store([
        {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
    ])
    before_physique = copy.deepcopy(store["personne"]["data"]["classes"][0])

    model_file = tmp_path / "personnes.json"
    model_file.write_text(json.dumps({
        "meta_class": "personne",
        "classes": [
            # Classe globale déjà en base -> doit être skippée, pas re-taguée.
            {"class": "personne_physique", "attributes": [{"domain": "d", "name": "nom", "type": "string"}]},
            # Nouvelle classe -> doit être chargée normalement et auto-taguée tenant1.
            {"class": "personne_morale", "attributes": [{"domain": "d", "name": "raison_sociale", "type": "string"}]},
        ],
    }))

    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(miami_app, "get_db", lambda: FakeConn(store))
    monkeypatch.setattr(
        miami_app, "get_auth_context",
        lambda: make_ctx(is_tenant_admin=True, tenants=["tenant1"]),
    )

    resp = client.post("/api/init")

    assert resp.status_code == 200
    body = resp.get_json()
    assert "personne" in body["loaded"]
    assert any(
        s["meta_class"] == "personne" and s["class"] == "personne_physique"
        for s in body["skipped"]
    )

    classes = store["personne"]["data"]["classes"]
    by_name = {c["class"]: c for c in classes}

    # La classe globale existante reste inchangée (pas de clé 'tenants' ajoutée).
    assert by_name["personne_physique"] == before_physique
    assert "tenants" not in by_name["personne_physique"]

    # La nouvelle classe a bien été chargée et auto-taguée pour tenant1.
    assert by_name["personne_morale"]["tenants"] == ["tenant1"]

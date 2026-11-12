"""Tests ciblés action 6.2 (purge physique différée), écrits par testeur
pour vérifier le diff non commité : RBAC global-admin strict sur les 3
nouvelles routes, validation de PUT /api/config/purge_grace_period_days,
et lecture dynamique de la période de grâce par POST /api/purge (doit
relire la config à chaque appel, jamais une constante figée).

Fichier de test autonome (ne modifie pas test_model_driven_typing.py) :
réutilise AuthContext/make_ctx/client depuis ce module, mais étend
FakeDB/FakeCursor localement pour app_config et les requêtes WITH
candidates (non gérées par le FakeCursor existant).

Lancer avec, depuis la racine du dépôt :
    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/test_purge_action_6_2.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import app as miami_app  # noqa: E402
from test_model_driven_typing import make_ctx  # noqa: E402


class OldDeletedAt:
    """Sentinel marquant un objet soft-deleted il y a `days_ago` jours
    (simulation, le FakeCursor ne modélise pas de vraies dates)."""
    def __init__(self, days_ago):
        self.days_ago = days_ago


class PurgeFakeDB:
    def __init__(self):
        self.app_config = {"purge_grace_period_days": "30"}
        self.objects = {}  # id -> {"deleted_at": None|OldDeletedAt}
        self.attribute_values = {}  # id -> {"joint_id":..}
        self._next_val_id = 1

    def add_object(self, obj_id, deleted_at=None):
        self.objects[obj_id] = {"id": obj_id, "deleted_at": deleted_at}

    def add_attribute_value(self, joint_id):
        vid = self._next_val_id
        self._next_val_id += 1
        self.attribute_values[vid] = {"id": vid, "joint_id": joint_id}
        return vid


class PurgeFakeCursor:
    def __init__(self, db):
        self.db = db
        self._result = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _candidates(self, grace_days):
        return {
            oid for oid, o in self.db.objects.items()
            if o["deleted_at"] is not None and o["deleted_at"].days_ago > grace_days
        }

    def execute(self, sql, params=None):
        self._result = None
        sql_norm = " ".join(sql.split())
        params = params or ()

        if sql_norm == "SELECT value FROM app_config WHERE key = 'purge_grace_period_days'":
            self._result = (self.db.app_config["purge_grace_period_days"],)

        elif sql_norm == "UPDATE app_config SET value = %s WHERE key = 'purge_grace_period_days'":
            (value,) = params
            self.db.app_config["purge_grace_period_days"] = value

        elif "DELETE FROM attribute_value WHERE joint_id IN (SELECT id FROM candidates)" in sql_norm:
            (grace_days,) = params
            cand = self._candidates(grace_days)
            to_delete = [vid for vid, v in self.db.attribute_values.items() if v["joint_id"] in cand]
            for vid in to_delete:
                del self.db.attribute_values[vid]
            self.rowcount = len(to_delete)

        elif "DELETE FROM object WHERE id IN (SELECT id FROM candidates)" in sql_norm:
            (grace_days,) = params
            cand = self._candidates(grace_days)
            for oid in cand:
                del self.db.objects[oid]
            self.rowcount = len(cand)

        else:
            raise AssertionError(f"SQL non géré par PurgeFakeCursor : {sql_norm!r}")

    def fetchone(self):
        return self._result


class PurgeFakeConn:
    def __init__(self, db):
        self.db = db

    def cursor(self, cursor_factory=None):
        return PurgeFakeCursor(self.db)

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
def purge_db_and_ctx(monkeypatch):
    db = PurgeFakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: PurgeFakeConn(db))
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(is_global_admin=True))
    return db


# --- RBAC strict global-admin sur les 3 routes ---

@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/config/purge_grace_period_days", None),
    ("put", "/api/config/purge_grace_period_days", {"value": 10}),
    ("post", "/api/purge", None),
])
@pytest.mark.parametrize("ctx_kwargs", [
    {"is_tenant_admin": True, "tenants": ["tenant1"]},
    {"is_tenant_readonly": True, "tenants": ["tenant1"]},
])
def test_rbac_rejected_for_non_global_admin(client, purge_db_and_ctx, monkeypatch, method, path, body, ctx_kwargs):
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(**ctx_kwargs))
    resp = getattr(client, method)(path, json=body)
    assert resp.status_code == 403, resp.get_data(as_text=True)


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/config/purge_grace_period_days", None),
    ("put", "/api/config/purge_grace_period_days", {"value": 10}),
    ("post", "/api/purge", None),
])
def test_rbac_allowed_for_global_admin(client, purge_db_and_ctx, method, path, body):
    resp = getattr(client, method)(path, json=body)
    assert resp.status_code == 200, resp.get_data(as_text=True)


# --- validation PUT ---

@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "abc", None])
def test_put_rejects_invalid_values(client, purge_db_and_ctx, value):
    body = {} if value is None else {"value": value}
    resp = client.put("/api/config/purge_grace_period_days", json=body)
    assert resp.status_code == 400, resp.get_data(as_text=True)


@pytest.mark.parametrize("value,expected", [(10, 10), (7.0, 7), (1, 1)])
def test_put_accepts_positive_integers_and_integer_floats(client, purge_db_and_ctx, value, expected):
    resp = client.put("/api/config/purge_grace_period_days", json={"value": value})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["value"] == expected
    get_resp = client.get("/api/config/purge_grace_period_days")
    assert get_resp.get_json()["value"] == expected


def test_put_missing_value_field_400(client, purge_db_and_ctx):
    resp = client.put("/api/config/purge_grace_period_days", json={})
    assert resp.status_code == 400


# --- lecture dynamique par POST /api/purge ---

def test_purge_uses_freshly_updated_grace_period_not_old_value(client, purge_db_and_ctx):
    db = purge_db_and_ctx
    # Objet supprimé il y a 20 jours : ne doit PAS être purgé avec grace=30
    # (valeur par défaut), mais DOIT l'être une fois grace=10 réglé via PUT.
    db.add_object(1, deleted_at=OldDeletedAt(days_ago=20))
    db.add_attribute_value(joint_id=1)

    resp = client.post("/api/purge")
    assert resp.status_code == 200
    assert resp.get_json()["purged"] == 0
    assert 1 in db.objects, "objet purgé trop tôt : grace_period par défaut (30) pas respectée"

    put_resp = client.put("/api/config/purge_grace_period_days", json={"value": 10})
    assert put_resp.status_code == 200

    resp2 = client.post("/api/purge")
    assert resp2.status_code == 200
    assert resp2.get_json()["purged"] == 1, "la nouvelle valeur (10) doit être relue en base, pas l'ancienne (30) figée"
    assert 1 not in db.objects
    assert len(db.attribute_values) == 0, "attribute_value référençant l'objet purgé doit aussi disparaître"


# --- 401 sans token (before_request réel, pas stripé) ---

@pytest.fixture
def real_client():
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


@pytest.mark.parametrize("method,path", [
    ("get", "/api/config/purge_grace_period_days"),
    ("put", "/api/config/purge_grace_period_days"),
    ("post", "/api/purge"),
])
def test_401_without_token_on_new_protected_routes(real_client, method, path):
    resp = getattr(real_client, method)(path, json={"value": 10} if method == "put" else None)
    assert resp.status_code == 401, resp.get_data(as_text=True)

"""Tests ciblés plan-mark3.md action 20 : autosuggest (suggestions de
valeurs apprises sur un attribut `string`), nouvelle route
GET /api/suggest/<meta_class>/<class>/<attribute> (routes_read.py) et
model/schema.json (nouvelle propriété "autosuggest").

Même convention que backend/test_attribute_type_datasource.py : pas de
vraie base Postgres, FakeDB/FakeConn/make_ctx réutilisés tels quels depuis
test_model_driven_typing.py, nouvelle branche SQL "SELECT DISTINCT
av.value_string" ajoutée localement à CE fichier (jamais à
test_model_driven_typing.py, hors périmètre) via une sous-classe de
FakeCursor dédiée - le socle commun ne connaît pas encore cette jointure.

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_attribute_autosuggest.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as miami_app  # noqa: E402
import auth.rbac as miami_rbac  # noqa: E402
from test_model_driven_typing import FakeDB, FakeConn, FakeCursor, FakeRealDictCursor, make_ctx  # noqa: E402


class _SuggestCursor(FakeCursor):
    """Ajoute la seule requête que le socle commun ne connaît pas encore :
    la jointure attribute_value/attribute/object sur (meta_class, class,
    attribute name), valeurs actives uniquement, utilisée par
    GET /api/suggest/<meta_class>/<class>/<attribute>."""

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT DISTINCT av.value_string"):
            self._result = None
            self._results = None
            self.rowcount = 0
            meta_class, cls, attr_name = params[0], params[1], params[2]
            actor_tenants = set(params[3]) if len(params) > 3 else None
            seen = []
            for attr in self.db.attributes.values():
                if attr["name"] != attr_name:
                    continue
                owner = self.db.objects.get(attr["object_id"])
                if owner is None or owner.get("deleted_at") is not None:
                    continue
                if owner["meta_class"] != meta_class or owner["class"] != cls:
                    continue
                if actor_tenants is not None:
                    owner_tenants = owner.get("tenants")
                    if owner_tenants and not (set(owner_tenants.split(",")) & actor_tenants):
                        continue
                for v in self.db.attribute_values.values():
                    if v["attribute_id"] != attr["id"] or v["valid_to"] is not None:
                        continue
                    if v.get("value_string") is None:
                        continue
                    if v["value_string"] not in seen:
                        seen.append(v["value_string"])
            self._results = [(s,) for s in seen]
        else:
            super().execute(sql, params)


class _SuggestConn(FakeConn):
    def cursor(self, cursor_factory=None):
        if cursor_factory is not None:
            return FakeRealDictCursor(self.db)
        return _SuggestCursor(self.db)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(miami_app.app.before_request_funcs, None, [])
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


CLASSES = [
    {
        "class": "site",
        "attributes": [
            {"domain": "details", "name": "ville", "type": "string", "autosuggest": True},
            {"domain": "details", "name": "description", "type": "string"},
        ],
    },
]


def _seed(db):
    db.seed_definition("cmdb_test", CLASSES)


def _set_ctx(monkeypatch, **kwargs):
    """Double monkeypatch nécessaire (même pattern que
    test_file_attribute_type.py) : les routes d'écriture appellent
    `app.get_auth_context()` (relu dynamiquement), mais `_tenant_read_filter`
    (rbac.py, utilisé par GET /api/suggest) appelle le nom `get_auth_context`
    de son PROPRE espace de noms module, jamais via `app.`."""
    ctx = make_ctx(**kwargs)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: ctx)
    monkeypatch.setattr(miami_rbac, "get_auth_context", lambda: ctx)


def _make_ctx_and_db(monkeypatch, **ctx_kwargs):
    db = FakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: _SuggestConn(db))
    _set_ctx(monkeypatch, **ctx_kwargs)
    return db


def _create_site(client, ville, tenants=None):
    body = {"meta_class": "cmdb_test", "class": "site", "attributes": {"ville": ville}}
    if tenants is not None:
        body["tenants"] = tenants
    resp = client.post("/api/write/object", json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


# ---------------------------------------------------------------------
# 1. Attribut non déclaré en autosuggest -> 400.
# ---------------------------------------------------------------------

def test_suggest_rejects_non_autosuggest_attribute_400(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)

    resp = client.get("/api/suggest/cmdb_test/site/description?q=x")
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# 2. Meta-classe/classe/attribut inconnu -> 404.
# ---------------------------------------------------------------------

def test_suggest_unknown_meta_class_404(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    resp = client.get("/api/suggest/inconnue/site/ville")
    assert resp.status_code == 404


def test_suggest_unknown_class_404(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    resp = client.get("/api/suggest/cmdb_test/inconnue/ville")
    assert resp.status_code == 404


def test_suggest_unknown_attribute_404(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    resp = client.get("/api/suggest/cmdb_test/site/inconnu")
    assert resp.status_code == 404


# ---------------------------------------------------------------------
# 3. Valeurs actives uniquement (valid_to IS NULL) - une valeur fermée par
#    réécriture ne doit plus être suggérée.
# ---------------------------------------------------------------------

def test_suggest_only_active_values_not_closed_history(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    object_id = _create_site(client, "Geneve")

    put = client.put(f"/api/write/attribute/site/{object_id}/ville/Lausanne")
    assert put.status_code == 200, put.get_json()

    resp = client.get("/api/suggest/cmdb_test/site/ville")
    assert resp.status_code == 200
    suggestions = resp.get_json()["suggestions"]
    assert "Lausanne" in suggestions
    assert "Geneve" not in suggestions


# ---------------------------------------------------------------------
# 4. Tri par distance d'édition (rapidfuzz) : la valeur la plus proche de
#    `q` arrive en premier.
# ---------------------------------------------------------------------

def test_suggest_sorted_by_edit_distance(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    _create_site(client, "Paris")
    _create_site(client, "Pariss")
    _create_site(client, "Lyon")

    resp = client.get("/api/suggest/cmdb_test/site/ville?q=Paris")
    assert resp.status_code == 200
    suggestions = resp.get_json()["suggestions"]
    assert suggestions[0] == "Paris"
    assert suggestions.index("Pariss") < suggestions.index("Lyon")


# ---------------------------------------------------------------------
# 5. q vide : pas de crash, renvoie des valeurs distinctes (défaut
#    raisonnable, pas de tri par distance).
# ---------------------------------------------------------------------

def test_suggest_empty_q_returns_values_without_crash(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    _create_site(client, "Geneve")
    _create_site(client, "Lausanne")

    resp = client.get("/api/suggest/cmdb_test/site/ville")
    assert resp.status_code == 200
    suggestions = resp.get_json()["suggestions"]
    assert set(suggestions) == {"Geneve", "Lausanne"}


# ---------------------------------------------------------------------
# 6. Top 10 : au-delà de 10 valeurs distinctes, seules 10 sont renvoyées.
# ---------------------------------------------------------------------

def test_suggest_limited_to_top_10(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    for i in range(15):
        _create_site(client, f"Ville{i}")

    resp = client.get("/api/suggest/cmdb_test/site/ville?q=Ville")
    assert resp.status_code == 200
    assert len(resp.get_json()["suggestions"]) == 10


# ---------------------------------------------------------------------
# 7. RBAC tenant : un tenant-admin ne voit que les valeurs des objets de
#    son périmètre, global-admin voit tout.
# ---------------------------------------------------------------------

def test_suggest_rbac_tenant_scope(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    _create_site(client, "ZoneA", tenants=["tenantA"])
    _create_site(client, "ZoneB", tenants=["tenantB"])

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenantA"])
    resp = client.get("/api/suggest/cmdb_test/site/ville")
    assert resp.status_code == 200
    suggestions = resp.get_json()["suggestions"]
    assert "ZoneA" in suggestions
    assert "ZoneB" not in suggestions

    _set_ctx(monkeypatch, is_global_admin=True)
    resp = client.get("/api/suggest/cmdb_test/site/ville")
    suggestions = resp.get_json()["suggestions"]
    assert "ZoneA" in suggestions and "ZoneB" in suggestions


# ---------------------------------------------------------------------
# 8. model/schema.json : validité Draft7 et acceptation de "autosuggest".
# ---------------------------------------------------------------------

def test_schema_is_valid_draft7():
    import jsonschema
    from data.db import load_schema

    jsonschema.Draft7Validator.check_schema(load_schema())


def test_schema_accepts_string_attribute_with_autosuggest():
    import jsonschema
    from data.db import load_schema

    jsonschema.validate(instance={
        "meta_class": "m",
        "classes": [{
            "class": "c",
            "attributes": [{"domain": "d", "name": "n", "type": "string", "autosuggest": True}],
        }],
    }, schema=load_schema())

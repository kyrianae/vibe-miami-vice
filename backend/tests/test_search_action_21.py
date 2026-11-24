"""Tests ciblés plan-mark3.md action 21 : recherche globale
(GET /api/search), nouveau module backend/routes/routes_search.py.
specifications/07-roadmap.md §10.18 pour le détail de conception.

Même convention que backend/tests/test_attribute_autosuggest.py : pas de
vraie base Postgres, FakeDB/FakeConn/make_ctx réutilisés depuis
test_model_driven_typing.py, requêtes SQL nouvelles (préchargement du
modèle, jointure de résultats, deux agrégations de facettes - action 21
point 3 de la revue -, pool fuzzy) ajoutées localement à CE fichier (jamais
à test_model_driven_typing.py) via une sous-classe dédiée de FakeCursor -
le socle commun ne connaît pas encore aucune d'entre elles.

Lancer avec, depuis la racine du dépôt :

    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_search_action_21.py -v
"""
import os
import re
import sys

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as miami_app  # noqa: E402
import auth.rbac as miami_rbac  # noqa: E402
from test_model_driven_typing import FakeDB, FakeConn, FakeCursor, FakeRealDictCursor, make_ctx  # noqa: E402


@pytest.fixture(autouse=True)
def secret_key_env(monkeypatch):
    """Requis par le test d'exclusion `secret` (test 3 ci-dessous) : écriture
    d'un attribut `secret` via /api/write/object échoue en 500 sans clé
    (secret_crypto.py, action 8) - même fixture que
    test_attribute_type_secret.py."""
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _ilike_match(value, pattern):
    """Émule ILIKE ... ESCAPE '\\' (insensible à la casse) à partir du motif
    SQL déjà échappé construit par _ilike_escape - reproduit fidèlement la
    sémantique réelle de Postgres (pas juste `q in value`), pour que le test
    d'échappement (caractères spéciaux ILIKE dans `q`) soit significatif."""
    if value is None:
        return False
    regex_parts = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            regex_parts.append(re.escape(pattern[i + 1]))
            i += 2
        elif c == "%":
            regex_parts.append(".*")
            i += 1
        elif c == "_":
            regex_parts.append(".")
            i += 1
        else:
            regex_parts.append(re.escape(c))
            i += 1
    return re.match("^" + "".join(regex_parts) + "$", value, re.IGNORECASE | re.DOTALL) is not None


class _SearchCursor(FakeCursor):
    """Ajoute les requêtes que le socle commun ne connaît pas encore : le
    préchargement global du modèle (safe-list/layers), la jointure
    attribute_value/attribute/object de /api/search (résultats + pool
    fuzzy), et les deux requêtes d'agrégation de facettes (action 21, point
    3 de la revue).

    Émule l'allow-list (action 21, point 1 de la revue) : un triplet
    (meta_class, class, attribute_name) n'est inclus QUE S'IL apparaît dans
    les tableaux `safe` passés en paramètres - l'inverse de la première
    implémentation (deny-list sur `secret_triples`)."""

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        params = params or ()

        if sql_norm == "SELECT meta_class, data FROM definition":
            self._results = [
                {"meta_class": mc, "data": row["data"]}
                for mc, row in self.db.definitions.items()
            ]
            self.rowcount = len(self._results)
            return

        if sql_norm.startswith("SELECT o.id AS object_id, o.meta_class, o.class, a.name AS attribute_name, av.value_string, av.valid_to IS NULL AS is_current FROM attribute_value av"):
            self._dispatch_search(sql_norm, params)
            return

        if sql_norm.startswith("SELECT o.meta_class, o.class, COUNT(DISTINCT o.id) AS cnt FROM attribute_value av"):
            self._dispatch_class_facets(sql_norm, params)
            return

        if sql_norm.startswith("SELECT a.name AS attribute_name, COUNT(DISTINCT o.id) AS cnt FROM attribute_value av"):
            self._dispatch_attribute_facets(sql_norm, params)
            return

        if sql_norm.startswith("SELECT DISTINCT av.value_string FROM attribute_value av"):
            self._dispatch_fuzzy_pool(sql_norm, params)
            return

        super().execute(sql, params)

    def _safe_triples(self, params, idx):
        safe_metas, safe_classes, safe_names = params[idx], params[idx + 1], params[idx + 2]
        return set(zip(safe_metas, safe_classes, safe_names)), idx + 3

    def _matching_rows(self, sql_norm, params, pattern_idx):
        """Lignes (owner, attr, v) matchant le même filtrage que la requête
        SQL réelle - WHERE ILIKE (si `pattern_idx` fourni), objets non
        supprimés, allow-list `secret`, historique, RBAC tenant. Partagé
        entre `_dispatch_search` et les deux dispatchers de facettes (même
        WHERE, sans LIMIT pour ces derniers - cf. _search_base_sql réel)."""
        idx = 0
        pattern = None
        if pattern_idx is not None:
            pattern = params[pattern_idx]
            idx = pattern_idx + 1
        safe_triples, idx = self._safe_triples(params, idx)
        require_active = "AND av.valid_to IS NULL" in sql_norm
        has_tenant_clause = "string_to_array(o.tenants" in sql_norm
        tenant_list = params[idx] if has_tenant_clause else None
        if has_tenant_clause:
            idx += 1

        rows = []
        for attr in self.db.attributes.values():
            owner = self.db.objects.get(attr["object_id"])
            if owner is None or owner.get("deleted_at") is not None:
                continue
            if (owner["meta_class"], owner["class"], attr["name"]) not in safe_triples:
                continue
            for v in self.db.attribute_values.values():
                if v["attribute_id"] != attr["id"]:
                    continue
                if require_active and v["valid_to"] is not None:
                    continue
                if v.get("value_string") is None:
                    continue
                if pattern is not None and not _ilike_match(v["value_string"], pattern):
                    continue
                if tenant_list is not None:
                    owner_tenants = owner.get("tenants")
                    if owner_tenants and not (set(owner_tenants.split(",")) & set(tenant_list)):
                        continue
                rows.append((owner, attr, v))
        return rows, idx

    def _dispatch_search(self, sql_norm, params):
        matched, idx = self._matching_rows(sql_norm, params, pattern_idx=0)
        limit = params[idx]
        rows = [
            {
                "object_id": owner["id"], "meta_class": owner["meta_class"], "class": owner["class"],
                "attribute_name": attr["name"], "value_string": v["value_string"],
                "is_current": v["valid_to"] is None,
                "_attr_id": attr["id"], "_val_id": v["id"],
            }
            for owner, attr, v in matched
        ]
        rows.sort(key=lambda r: (r["object_id"], r["_attr_id"], r["_val_id"]))
        self._results = rows[:limit]

    def _dispatch_class_facets(self, sql_norm, params):
        matched, _ = self._matching_rows(sql_norm, params, pattern_idx=0)
        object_ids_by_class = {}
        for owner, _attr, _v in matched:
            key = (owner["meta_class"], owner["class"])
            object_ids_by_class.setdefault(key, set()).add(owner["id"])
        self._results = [
            {"meta_class": mc, "class": cls, "cnt": len(ids)}
            for (mc, cls), ids in object_ids_by_class.items()
        ]

    def _dispatch_attribute_facets(self, sql_norm, params):
        matched, _ = self._matching_rows(sql_norm, params, pattern_idx=0)
        object_ids_by_attr = {}
        for owner, attr, _v in matched:
            object_ids_by_attr.setdefault(attr["name"], set()).add(owner["id"])
        self._results = [
            {"attribute_name": name, "cnt": len(ids)}
            for name, ids in object_ids_by_attr.items()
        ]

    def _dispatch_fuzzy_pool(self, sql_norm, params):
        matched, idx = self._matching_rows(sql_norm, params, pattern_idx=None)
        limit = params[idx]
        seen = sorted({v["value_string"] for _owner, _attr, v in matched})
        self._results = [(s,) for s in seen[:limit]]


class _SearchRealDictCursor(_SearchCursor, FakeRealDictCursor):
    pass


class _SearchConn(FakeConn):
    def cursor(self, cursor_factory=None):
        if cursor_factory is not None:
            return _SearchRealDictCursor(self.db)
        return _SearchCursor(self.db)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(miami_app.app.before_request_funcs, None, [])
    miami_app.app.config["TESTING"] = True
    return miami_app.app.test_client()


CLASSES = [
    {
        "class": "serveur",
        "layers": ["infra"],
        "attributes": [
            {"domain": "details", "name": "nom", "type": "string"},
            {"domain": "details", "name": "ville", "type": "string"},
        ],
    },
]

SECURITE_CLASSES = [
    {
        "class": "compte",
        "attributes": [
            {"domain": "details", "name": "mot_de_passe", "type": "secret"},
            {"domain": "details", "name": "login", "type": "string"},
        ],
    },
]


def _seed(db):
    db.seed_definition("cmdb_test", CLASSES)


def _set_ctx(monkeypatch, **kwargs):
    ctx = make_ctx(**kwargs)
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: ctx)
    monkeypatch.setattr(miami_rbac, "get_auth_context", lambda: ctx)


def _make_ctx_and_db(monkeypatch, **ctx_kwargs):
    db = FakeDB()
    monkeypatch.setattr(miami_app, "get_db", lambda: _SearchConn(db))
    _set_ctx(monkeypatch, **ctx_kwargs)
    return db


def _create_serveur(client, nom, ville="Geneve", tenants=None):
    body = {"meta_class": "cmdb_test", "class": "serveur", "attributes": {"nom": nom, "ville": ville}}
    if tenants is not None:
        body["tenants"] = tenants
    resp = client.post("/api/write/object", json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


# ---------------------------------------------------------------------
# 1. Recherche substring simple trouve un objet + facettes cohérentes.
# ---------------------------------------------------------------------

def test_search_substring_finds_object_and_facets(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    object_id = _create_serveur(client, "WebServer01")

    resp = client.get("/api/search?q=WebServer")
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert any(r["id"] == object_id and r["attribute"] == "nom" and r["value"] == "WebServer01" for r in data["results"])
    assert data["truncated"] is False
    assert data["fuzzy_suggestions"] == []

    layers = {f["value"]: f["count"] for f in data["facets"]["layers"]}
    assert layers.get("infra") == 1
    classes = {(f["meta_class"], f["class"]): f["count"] for f in data["facets"]["classes"]}
    assert classes.get(("cmdb_test", "serveur")) == 1
    attributes = {f["name"]: f["count"] for f in data["facets"]["attributes"]}
    assert attributes.get("nom") == 1


def test_search_missing_q_returns_400(client, monkeypatch):
    _make_ctx_and_db(monkeypatch, is_global_admin=True)
    resp = client.get("/api/search")
    assert resp.status_code == 400


# ---------------------------------------------------------------------
# 2. history=false exclut une valeur fermée, history=true la trouve.
# ---------------------------------------------------------------------

def test_search_history_flag_controls_closed_values(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    object_id = _create_serveur(client, "web01", ville="Geneve")

    put = client.put(f"/api/write/attribute/serveur/{object_id}/ville/Lausanne")
    assert put.status_code == 200, put.get_json()

    resp_default = client.get("/api/search?q=Geneve")
    assert resp_default.status_code == 200
    assert not any(r["id"] == object_id for r in resp_default.get_json()["results"])

    resp_history = client.get("/api/search?q=Geneve&history=true")
    assert resp_history.status_code == 200
    closed_row = next(r for r in resp_history.get_json()["results"] if r["id"] == object_id and r["value"] == "Geneve")
    assert closed_row["is_current"] is False

    resp_active = client.get("/api/search?q=Lausanne")
    active_row = next(r for r in resp_active.get_json()["results"] if r["id"] == object_id and r["value"] == "Lausanne")
    assert active_row["is_current"] is True

    # history=true doit retrouver les DEUX lignes (fermée + active) pour le
    # même objet/attribut, distinguables uniquement via `is_current` (fix
    # revue action 21, point 2 - avant le fix les deux lignes étaient
    # strictement identiques).
    resp_history_all = client.get("/api/search?q=e&history=true")
    ville_rows = [r for r in resp_history_all.get_json()["results"] if r["id"] == object_id and r["attribute"] == "ville"]
    by_value = {r["value"]: r["is_current"] for r in ville_rows}
    assert by_value == {"Geneve": False, "Lausanne": True}


# ---------------------------------------------------------------------
# 3. Exclusion stricte d'un attribut `secret`, même si sa valeur stockée
#    matcherait par hasard (simulé en manipulant directement la valeur
#    stockée en base, la vraie valeur chiffrée ne matchant jamais en
#    pratique).
# ---------------------------------------------------------------------

def test_search_excludes_secret_attribute_even_if_value_matches(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite", SECURITE_CLASSES)

    resp = client.post("/api/write/object", json={
        "meta_class": "securite", "class": "compte",
        "attributes": {"mot_de_passe": "hunter2", "login": "QUELCONQUE-matchmetext-login"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    secret_attr_id = next(
        a["id"] for a in db.attributes.values()
        if a["object_id"] == object_id and a["name"] == "mot_de_passe"
    )
    for v in db.attribute_values.values():
        if v["attribute_id"] == secret_attr_id:
            v["value_string"] = "zz-matchmetext-zz"

    resp = client.get("/api/search?q=matchmetext")
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(r["id"] == object_id and r["attribute"] == "login" for r in data["results"])
    assert not any(r["attribute"] == "mot_de_passe" for r in data["results"])
    assert "zz-matchmetext-zz" not in resp.get_data(as_text=True)
    assert "mot_de_passe" not in {f["name"] for f in data["facets"]["attributes"]}


# ---------------------------------------------------------------------
# 4. RBAC tenant : un tenant ne voit pas les résultats d'un objet hors de
#    son périmètre.
# ---------------------------------------------------------------------

def test_search_rbac_tenant_scope(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    object_a = _create_serveur(client, "ZoneAMatch", tenants=["tenantA"])
    object_b = _create_serveur(client, "ZoneBMatch", tenants=["tenantB"])

    _set_ctx(monkeypatch, is_tenant_admin=True, tenants=["tenantA"])
    resp = client.get("/api/search?q=Zone")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.get_json()["results"]}
    assert object_a in ids
    assert object_b not in ids

    _set_ctx(monkeypatch, is_global_admin=True)
    resp = client.get("/api/search?q=Zone")
    ids = {r["id"] for r in resp.get_json()["results"]}
    assert object_a in ids and object_b in ids


# ---------------------------------------------------------------------
# 5. LIMIT/truncated : au-delà de 500 lignes brutes, la réponse est
#    tronquée et le flag `truncated` est levé.
# ---------------------------------------------------------------------

def test_search_truncated_beyond_limit(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    for i in range(501):
        _create_serveur(client, f"TRUNCME-{i}")

    resp = client.get("/api/search?q=TRUNCME")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["truncated"] is True
    assert len(data["results"]) == 500


# ---------------------------------------------------------------------
# 6. fuzzy=true renvoie des suggestions proches sans faire planter la
#    requête standard.
# ---------------------------------------------------------------------

def test_search_fuzzy_mode_returns_suggestions_without_crash(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    _create_serveur(client, "paris-01", ville="Paris")
    _create_serveur(client, "pariss-02", ville="Pariss")
    _create_serveur(client, "lyon-03", ville="Lyon")

    resp = client.get("/api/search?q=Parix&fuzzy=true")
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["results"] == []
    assert "Paris" in data["fuzzy_suggestions"]
    assert "Pariss" in data["fuzzy_suggestions"]

    resp_no_fuzzy = client.get("/api/search?q=Parix")
    assert resp_no_fuzzy.status_code == 200
    assert resp_no_fuzzy.get_json()["fuzzy_suggestions"] == []


# ---------------------------------------------------------------------
# 7. Échappement ILIKE : un `q` contenant '%' ne doit matcher que
#    l'occurrence littérale, pas agir comme un joker élargissant le
#    résultat à toute valeur.
# ---------------------------------------------------------------------

def test_search_ilike_special_characters_are_escaped(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    object_id = _create_serveur(client, "charge-100%-ok")
    _create_serveur(client, "ne-doit-pas-matcher")

    resp = client.get("/api/search?q=100%25")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.get_json()["results"]}
    assert ids == {object_id}


# ---------------------------------------------------------------------
# 8. [Revue action 21, point 1 - fix sécurité allow-list] Une classe
#    supprimée du schéma depuis (routes_admin.py `delete_class` : « ne
#    supprime ni ne modifie les objets déjà créés sous cette classe ») ne
#    doit JAMAIS rendre ses valeurs visibles en recherche, même si elles ne
#    sont plus reconnues comme `secret` faute de déclaration dans le modèle
#    courant. Avant le fix (deny-list `NOT EXISTS` sur les triplets secrets
#    connus), ce scénario était "allow-by-default" - une ligne orpheline
#    passait le filtre faute d'être reconnue comme secrète.
# ---------------------------------------------------------------------

def test_search_excludes_values_of_class_removed_from_current_schema(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    object_id = _create_serveur(client, "OrphanClassZZZ")

    # Simule une suppression de classe côté schéma (delete_class) : l'objet
    # et ses attribute_value restent en base, la classe disparaît de
    # `definition.data.classes`.
    db.definitions["cmdb_test"]["data"]["classes"] = [
        c for c in db.definitions["cmdb_test"]["data"]["classes"] if c["class"] != "serveur"
    ]

    resp = client.get("/api/search?q=OrphanClassZZZ")
    assert resp.status_code == 200
    data = resp.get_json()
    assert not any(r["id"] == object_id for r in data["results"])
    assert "OrphanClassZZZ" not in resp.get_data(as_text=True)
    assert data["facets"]["classes"] == []


def test_search_excludes_values_of_attribute_removed_from_current_class(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    object_id = _create_serveur(client, "OrphanAttrZZZ")

    # Simule un attribut renommé/retiré de la classe (toujours déclarée) :
    # la classe existe encore dans le modèle courant, mais plus l'attribut
    # `nom` qui porte la valeur orpheline en base. Reconstruit un NOUVEAU
    # dict/liste (jamais de mutation en place) : `CLASSES` est un objet
    # partagé par référence depuis `seed_definition` (pas de deep copy), le
    # muter en place polluerait les autres tests du fichier qui réutilisent
    # `_seed`/`CLASSES`.
    db.definitions["cmdb_test"]["data"]["classes"] = [
        {**c, "attributes": [a for a in c["attributes"] if a["name"] != "nom"]} if c["class"] == "serveur" else c
        for c in db.definitions["cmdb_test"]["data"]["classes"]
    ]

    resp = client.get("/api/search?q=OrphanAttrZZZ")
    assert resp.status_code == 200
    data = resp.get_json()
    assert not any(r["id"] == object_id for r in data["results"])
    assert "OrphanAttrZZZ" not in resp.get_data(as_text=True)


# ---------------------------------------------------------------------
# 9. [Revue action 21, point 3] Les facettes portent sur l'ENSEMBLE des
#    lignes matchantes, pas seulement les 500 premières de `results` - une
#    classe dont l'unique objet matchant a un id trop élevé pour passer la
#    coupe `ORDER BY o.id LIMIT 500` doit quand même apparaître (et son
#    layer aussi) dans les facettes.
# ---------------------------------------------------------------------

FACET_CLASSES = [
    {
        "class": "serveur_f",
        "layers": ["infra"],
        "attributes": [{"domain": "details", "name": "nom", "type": "string"}],
    },
    {
        "class": "routeur_f",
        "layers": ["reseau"],
        "attributes": [{"domain": "details", "name": "nom", "type": "string"}],
    },
]


def test_search_facets_computed_on_full_matching_set_beyond_truncation(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    db.seed_definition("cmdb_facet_test", FACET_CLASSES)

    def _create(cls, nom):
        resp = client.post("/api/write/object", json={
            "meta_class": "cmdb_facet_test", "class": cls, "attributes": {"nom": nom},
        })
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()["id"]

    for i in range(500):
        _create("serveur_f", f"FACETME-{i}")
    routeur_id = _create("routeur_f", "FACETME-ROUTEUR")

    resp = client.get("/api/search?q=FACETME")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["truncated"] is True
    assert len(data["results"]) == 500
    assert not any(r["id"] == routeur_id for r in data["results"])

    classes = {(f["meta_class"], f["class"]): f["count"] for f in data["facets"]["classes"]}
    assert classes.get(("cmdb_facet_test", "routeur_f")) == 1
    assert classes.get(("cmdb_facet_test", "serveur_f")) == 500

    layers = {f["value"]: f["count"] for f in data["facets"]["layers"]}
    assert layers.get("reseau") == 1
    assert layers.get("infra") == 500


# ---------------------------------------------------------------------
# 10. [Revue action 21, point 4] `score_cutoff` : un `q` sans rapport avec
#     les données ne doit renvoyer AUCUNE suggestion fuzzy (pas les N
#     valeurs les "moins pires" du pool par défaut).
# ---------------------------------------------------------------------

def test_search_fuzzy_suggestions_empty_when_nothing_close(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    _seed(db)
    _create_serveur(client, "paris-01", ville="Paris")
    _create_serveur(client, "lyon-02", ville="Lyon")

    resp = client.get("/api/search?q=zzzzzzzzzzzzzzzzzzzz&fuzzy=true")
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["fuzzy_suggestions"] == []


# ---------------------------------------------------------------------
# 11. [Revue action 21, point 5] Une entrée `definition.data` malformée
#     (classe sans `class`, attribut sans `name`) est ignorée silencieusement
#     - ne fait jamais planter toute la requête de recherche en 500.
# ---------------------------------------------------------------------

MALFORMED_CLASSES = [
    {
        "class": "appareil",
        "attributes": [{"domain": "details", "name": "nom", "type": "string"}],
    },
]


def test_search_tolerates_malformed_definition_entries(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    db.seed_definition("cmdb_malformed", MALFORMED_CLASSES)
    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_malformed", "class": "appareil", "attributes": {"nom": "MalformedButFine"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    # Corruption APRÈS coup (jamais via /api/write/class, qui valide le
    # schéma) - simule une entrée déjà malformée en base (classe sans
    # `class`, attribut sans `name`), scénario que `write_object` ne peut
    # de toute façon pas produire lui-même (accès direct `cls["class"]`,
    # hors scope de cette action). Reconstruit un NOUVEAU dict/liste (jamais
    # de mutation en place de `MALFORMED_CLASSES`, objet partagé par
    # référence depuis `seed_definition`).
    db.definitions["cmdb_malformed"]["data"]["classes"] = [
        {**c, "attributes": c["attributes"] + [{"domain": "details", "type": "string"}]} if c["class"] == "appareil" else c
        for c in db.definitions["cmdb_malformed"]["data"]["classes"]
    ] + [{"layers": ["infra"], "attributes": [{"domain": "details", "name": "sansclasse", "type": "string"}]}]

    resp = client.get("/api/search?q=MalformedButFine")
    assert resp.status_code == 200, resp.get_json()
    assert any(r["id"] == object_id for r in resp.get_json()["results"])


def test_search_tolerates_null_attributes_and_non_dict_entries(client, monkeypatch):
    """[4e passage, bug réel en conditions réelles] `attributes` peut valoir
    `None` explicitement (clé présente, valeur null - pas seulement absente,
    déjà couvert par le test précédent) et une entrée de `classes` ou
    d'`attributes` peut être une chaîne au lieu d'un dict - les deux ont
    provoqué un vrai 500 (TypeError / AttributeError) observé en logs avant
    ce fix. Mêmes garanties que le test précédent : objet valide créé AVANT
    corruption (jamais via write_object sur une structure déjà malformée),
    corruption directe du pool FakeDB après coup."""
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    db.seed_definition("cmdb_malformed2", MALFORMED_CLASSES)
    resp = client.post("/api/write/object", json={
        "meta_class": "cmdb_malformed2", "class": "appareil", "attributes": {"nom": "StillFindable"},
    })
    assert resp.status_code == 201, resp.get_json()
    object_id = resp.get_json()["id"]

    db.definitions["cmdb_malformed2"]["data"]["classes"] = [
        {"class": "appareil", "attributes": MALFORMED_CLASSES[0]["attributes"]},
        {"class": "appareil_null_attrs", "attributes": None},
        {
            "class": "appareil_str_attr",
            "attributes": ["oops", {"domain": "details", "name": "autre", "type": "string"}],
        },
        "oops_class_entry_not_a_dict",
    ]

    resp = client.get("/api/search?q=StillFindable")
    assert resp.status_code == 200, resp.get_json()
    assert any(r["id"] == object_id for r in resp.get_json()["results"])


# ---------------------------------------------------------------------
# 12. [Revue 3 de l'action 21] Un même nom d'attribut déclaré DEUX FOIS dans
#     la même classe - une fois `secret`, une fois non-secret - ne doit
#     JAMAIS redevenir "safe" : la soustraction doit porter sur TOUS les
#     noms vus comme secrets dans la classe, pas seulement "en place" sur la
#     dernière entrée rencontrée du même nom. Insertion directe dans le pool
#     FakeDB (object/attribute/attribute_value), PAS via /api/write/object -
#     la résolution du type appliqué par le chemin d'écriture face à un nom
#     dupliqué est un bug préexistant différent, hors scope de ce fix
#     (routes_write.py, traité séparément).
# ---------------------------------------------------------------------

DUP_ATTR_NAME_CLASSES = [
    {
        "class": "compte_dup",
        "attributes": [
            {"domain": "details", "name": "pw", "type": "secret"},
            {"domain": "details", "name": "pw", "type": "string"},
        ],
    },
]


def _insert_raw(db, meta_class, class_name, attribute_name, value_string):
    """Insère directement un (objet, attribut, valeur) dans le pool FakeDB,
    en contournant /api/write/object - voir commentaire du test 12."""
    obj_id = db._next_obj_id
    db._next_obj_id += 1
    db.objects[obj_id] = {
        "id": obj_id, "meta_class": meta_class, "class": class_name,
        "tenants": None, "deleted_at": None,
    }
    attr_id = db._next_attr_id
    db._next_attr_id += 1
    db.attributes[attr_id] = {
        "id": attr_id, "object_id": obj_id, "domain": "details", "name": attribute_name,
    }
    val_id = db._next_val_id
    db._next_val_id += 1
    db.attribute_values[val_id] = {
        "id": val_id, "attribute_id": attr_id,
        "value_integer": None, "value_float": None,
        "value_string": value_string, "joint_id": None, "valid_to": None,
    }
    return obj_id


def test_search_excludes_attribute_declared_twice_secret_and_non_secret(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite_dup", DUP_ATTR_NAME_CLASSES)
    object_id = _insert_raw(db, "securite_dup", "compte_dup", "pw", "PWDUPMATCH-zz")

    resp = client.get("/api/search?q=PWDUPMATCH&fuzzy=true")
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert not any(r["id"] == object_id for r in data["results"])
    assert "PWDUPMATCH-zz" not in resp.get_data(as_text=True)
    assert "pw" not in {f["name"] for f in data["facets"]["attributes"]}
    assert data["facets"]["classes"] == []
    assert "PWDUPMATCH-zz" not in data["fuzzy_suggestions"]


# ---------------------------------------------------------------------
# 13. [Revue 3 de l'action 21] Une classe déclarée DEUX FOIS dans la même
#     meta-classe - une première fois avec un attribut `secret`, une
#     seconde fois (même nom de classe) où ce même attribut est redéclaré
#     non-secret - ne doit pas non plus laisser gagner la seconde
#     déclaration par simple écrasement de `safe_names[key]`.
# ---------------------------------------------------------------------

DUP_CLASS_DECLARATION_CLASSES = [
    {
        "class": "compte_twice",
        "attributes": [{"domain": "details", "name": "secretfield", "type": "secret"}],
    },
    {
        "class": "compte_twice",
        "attributes": [
            {"domain": "details", "name": "secretfield", "type": "string"},
            {"domain": "details", "name": "other", "type": "string"},
        ],
    },
]


def test_search_excludes_attribute_secret_in_one_of_two_duplicate_class_declarations(client, monkeypatch):
    db = _make_ctx_and_db(monkeypatch, is_global_admin=True)
    db.seed_definition("securite_twice", DUP_CLASS_DECLARATION_CLASSES)
    object_id = _insert_raw(db, "securite_twice", "compte_twice", "secretfield", "TWICEMATCH-zz")
    other_id = _insert_raw(db, "securite_twice", "compte_twice", "other", "TWICEMATCH-other")

    resp = client.get("/api/search?q=TWICEMATCH&fuzzy=true")
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert not any(r["id"] == object_id and r["attribute"] == "secretfield" for r in data["results"])
    assert any(r["id"] == other_id and r["attribute"] == "other" for r in data["results"])
    assert "TWICEMATCH-zz" not in resp.get_data(as_text=True)
    assert "secretfield" not in {f["name"] for f in data["facets"]["attributes"]}
    assert "other" in {f["name"] for f in data["facets"]["attributes"]}
    assert "TWICEMATCH-zz" not in data["fuzzy_suggestions"]

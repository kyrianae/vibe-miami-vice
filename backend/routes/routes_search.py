import psycopg2.extras
from flask import Blueprint, jsonify, abort, request
from rapidfuzz import process, fuzz

import app
from auth.rbac import _tenant_read_filter

# Recherche globale (plan-mark3.md action 21 ; specifications/07-roadmap.md
# §10.18). Module dédié (plutôt qu'ajouté à routes_read.py) : requête
# cross-table avec facettes + mode fuzzy, assez autonome pour justifier son
# propre fichier, même pattern d'import que routes_write.py qui importe déjà
# depuis routes_read.

search_bp = Blueprint("search", __name__)

# LIMIT serveur sur les lignes brutes remontées pour `results` (avant dédup
# objets) - point ouvert tranché à l'implémentation (specifications/
# 07-roadmap.md §10.18) : 500, avec flag "truncated" si atteint. Une ligne =
# un (objet, attribut, valeur) matchant, pas un objet distinct - un objet
# avec plusieurs attributs matchant consomme plusieurs lignes du budget.
# N'affecte PLUS les facettes depuis la revue de l'action 21 (point 3) :
# `facets` est calculé par des requêtes d'agrégation séparées sur l'ENSEMBLE
# des lignes matchantes, voir _facet_class_counts/_facet_attribute_counts.
_SEARCH_RESULT_LIMIT = 500

# Taille du pool de valeurs candidates interrogé pour le mode fuzzy (valeurs
# proches suggérées, PAS un élargissement des résultats substring déjà
# affichés) - choix arbitraire pour borner le coût de la requête
# "SELECT DISTINCT" sous-jacente, indépendant de _SEARCH_RESULT_LIMIT.
_SEARCH_FUZZY_POOL_LIMIT = 2000

# Top N suggestions fuzzy renvoyées, même valeur que _SUGGEST_LIMIT de
# routes_read.py (action 20) - pas de raison de diverger.
_FUZZY_SUGGESTIONS_LIMIT = 10

# Score minimal (rapidfuzz, échelle 0-100) sous lequel une suggestion n'est
# pas considérée pertinente - revue de l'action 21 (point 4) : sans seuil,
# `process.extract` renvoie quand même les N valeurs "les moins pires" du
# pool même si rien n'est réellement proche de `q` (bruit constaté en test
# live sur un `q` sans rapport avec les données, ex. 'zzzzzzzz'). Valeur 60
# choisie arbitrairement (pas de spécification initiale sur ce seuil).
_FUZZY_SCORE_CUTOFF = 60


def _ilike_escape(value):
    """Échappe les caractères spéciaux ILIKE ('\\', '%', '_') d'une saisie
    utilisateur avant de l'insérer dans un motif '%...%' - sans ça, un `q`
    contenant '%' ou '_' matcherait n'importe quoi (wildcard involontaire)
    au lieu du caractère littéral recherché. ESCAPE '\\' déclaré côté SQL
    (voir search_objects) désigne explicitement '\\' comme caractère
    d'échappement pour ce ILIKE précis."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _load_secret_and_layers_index(conn):
    """Précharge, une fois par requête, deux index dérivés du modèle chargé
    (table definition, colonne data) sur TOUTES les meta-classes/classes :

    - safe_names[(meta_class, class)] -> set des noms d'attributs dont le
      type est connu et DIFFÉRENT de `secret` (allow-list, pas deny-list -
      voir ci-dessous pourquoi). C'est la liste des attributs AUTORISÉS à
      apparaître dans un résultat de recherche.
    - layers_index[(meta_class, class)] -> liste des layers STATIQUES de la
      classe (classDef.layers, action 14) - PAS le layer effectif par objet
      (action 18), volontairement, pour ne pas payer un calcul par objet sur
      un résultat de recherche potentiellement large (même décision
      qu'actée dans specifications/07-roadmap.md §10.18).

    Allow-list, pas deny-list (fix sécurité, revue de l'action 21 point 1) :
    la première implémentation construisait `secret_names` (noms
    d'attributs `secret`) et excluait une ligne via `NOT EXISTS` sur ce set -
    donc incluse PAR DÉFAUT dès que son triplet (meta_class, class,
    attribute_name) n'était pas reconnu comme secret. Or une classe peut
    être supprimée du schéma sans toucher aux objets déjà créés sous cette
    classe (`routes_admin.py`, `delete_class` - « ne supprime ni ne modifie
    les objets déjà créés sous cette classe »), et un attribut peut être
    renommé/retiré d'une classe existante : dans les deux cas le triplet
    disparaît de `secret_names` sans que la VALEUR chiffrée en base ne
    change - un attribut `secret` orphelin redevenait donc visible en clair
    (ciphertext Fernet) via la recherche. Avec `safe_names`, un triplet
    absent du modèle actuel (classe orpheline, attribut renommé/supprimé)
    est exclu PAR DÉFAUT - jamais inclus tant qu'il n'est pas positivement
    déclaré non-secret dans le modèle courant.

    Une seule requête sur toute la table `definition` plutôt qu'un lookup
    par (meta_class, class) rencontré - la recherche traverse par
    construction toutes les classes, mutualiser est donc plus simple ET plus
    performant que le pattern par-objet de _secret_attribute_names
    (routes_read.py), qui lui reste adapté à son cas d'usage (un seul objet
    affiché à la fois).

    Accès défensif (revue de l'action 21, point 5 ; durci au 4e passage) :
    une entrée `classes` qui n'est pas un dict, une entrée `classes` sans
    `class`, une clé `attributes` explicitement `null` (pas seulement
    absente), une entrée d'`attributes` qui n'est pas un dict, ou un
    attribut sans `name`, sont ignorées silencieusement plutôt que de lever
    une exception - une ligne `definition.data` malformée ne doit jamais
    faire échouer TOUTE requête de recherche avec un 500 global (même
    pattern de robustesse que `_check_class_name_unique`, action 22,
    `routes_write.py`)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT meta_class, data FROM definition")
        rows = cur.fetchall()

    # Accumulation cumulative (JAMAIS de réassignation en place) sur TOUTES
    # les occurrences rencontrées d'une même clé (meta_class, class) - fix
    # sécurité suite à la revue 3 de l'action 21 : un attribut déclaré deux
    # fois dans la même classe (une fois `secret`, une fois non-secret) ou
    # une classe déclarée deux fois dans la même meta-classe ne doit JAMAIS
    # faire gagner la déclaration non-secrète. `all_names` = tous les noms
    # vus (quel que soit le type) ; `secret_names_seen` = tous les noms vus
    # AU MOINS UNE FOIS avec type `secret`. `safe_names` est dérivé par
    # soustraction (`all_names - secret_names_seen`) une fois la boucle
    # terminée, jamais pendant.
    all_names = {}
    secret_names_seen = {}
    layers_index = {}
    for row in rows:
        meta_class = row["meta_class"]
        for cls in ((row["data"] or {}).get("classes") or []):
            if not isinstance(cls, dict):
                continue
            class_name = cls.get("class")
            if class_name is None:
                continue
            key = (meta_class, class_name)
            all_names.setdefault(key, set())
            secret_names_seen.setdefault(key, set())
            for a in (cls.get("attributes") or []):
                if not isinstance(a, dict):
                    continue
                name = a.get("name")
                if not name:
                    continue
                all_names[key].add(name)
                if a.get("type") == "secret":
                    secret_names_seen[key].add(name)
            layers_index.setdefault(key, set()).update(cls.get("layers") or [])

    safe_names = {
        key: names - secret_names_seen.get(key, set())
        for key, names in all_names.items()
    }
    layers_index = {key: sorted(layers) for key, layers in layers_index.items()}
    return safe_names, layers_index


def _safe_attribute_arrays(safe_names):
    """Aplatit safe_names ({(meta_class, class): {noms}}) en trois listes
    parallèles (meta_class, class, name), consommées par un
    `unnest(%s::text[], %s::text[], %s::text[])` SQL - permet d'autoriser
    tous les triplets (meta_class, class, attribut_non_secret) en une seule
    clause EXISTS, sans construire dynamiquement une suite de AND/OR selon
    le nombre d'attributs déclarés dans le modèle."""
    metas, classes, names = [], [], []
    for (meta_class, cls), attr_names in safe_names.items():
        for name in attr_names:
            metas.append(meta_class)
            classes.append(cls)
            names.append(name)
    return metas, classes, names


# Allow-list (voir docstring de _load_secret_and_layers_index) : une ligne
# n'est incluse QUE SI son triplet (meta_class, class, attribute_name) est
# positivement présent dans le modèle courant ET que l'attribut n'y est pas
# de type `secret`. Tout triplet absent (classe orpheline, attribut
# renommé/supprimé) est donc exclu par défaut, jamais inclus.
_SAFE_ATTRIBUTE_SQL = """
    EXISTS (
        SELECT 1 FROM unnest(%s::text[], %s::text[], %s::text[]) AS safe(meta_class, class, name)
        WHERE safe.meta_class = o.meta_class AND safe.class = o.class AND safe.name = a.name
    )
"""


@search_bp.route("/api/search", methods=["GET"])
def search_objects():
    """Recherche globale toutes classes/meta-classes confondues, par
    contenu d'attribut (plan-mark3.md action 21 ; specifications/
    07-roadmap.md §10.18).

    Query params :
    - q (str, requis) : texte recherché. 400 si absent/vide - une recherche
      vide matcherait indistinctement toute valeur de la base (ILIKE '%%'),
      ce n'est pas un cas d'usage utile et serait coûteux sans apporter de
      valeur (choix arbitraire tranché ici, pas spécifié dans la conception
      initiale).
    - fuzzy (bool, défaut false) : '1'/'true'/'True' comme le reste de l'API
      (cf. `deref` de get_object_by_id). Si actif, ajoute `fuzzy_suggestions`
      à la réponse (valeurs proches de `q`, PAS un élargissement des
      résultats substring déjà renvoyés - l'utilisateur relance une
      nouvelle recherche sur la suggestion choisie côté frontend).
    - history (bool, défaut false) : si false, seuls les attribute_value
      ACTIFS (valid_to IS NULL) sont cherchés ; si true, l'historique
      complet (valeurs fermées incluses) est aussi cherché.

    RBAC tenant identique à `_tenant_read_filter` (global-admin : aucun
    filtrage ; sinon overlap Postgres sur `object.tenants`, objets non
    supprimés uniquement - `object.deleted_at IS NULL`).

    Exclusion stricte et systématique du type `secret`, implémentée en
    ALLOW-LIST (voir docstring de `_load_secret_and_layers_index`) : un
    attribut secret ne peut JAMAIS apparaître dans `results` ni alimenter
    `fuzzy_suggestions` ni les facettes, quelle que soit sa valeur stockée -
    et un attribut dont le triplet (meta_class, class, name) n'est plus
    déclaré dans le modèle courant (classe supprimée, attribut renommé) est
    exclu par défaut lui aussi, jamais inclus par défaut.

    Réponse JSON :
    {
        "results": [
            {"id": int, "meta_class": str, "class": str,
             "attribute": str, "value": str, "is_current": bool}, ...
        ],
        "facets": {
            "layers": [{"value": str, "count": int}, ...],
            "classes": [{"meta_class": str, "class": str, "count": int}, ...],
            "attributes": [{"name": str, "count": int}, ...]
        },
        "truncated": bool,
        "fuzzy_suggestions": [str, ...]
    }

    `is_current` : true si cette ligne porte la valeur ACTIVE de l'attribut
    (`valid_to IS NULL`), false si c'est une valeur fermée (historique) -
    distinction utile uniquement quand `history=true` (sinon toutes les
    lignes sont actives par construction) ; ajouté suite à la revue de
    l'action 21 (point 2), deux lignes history=true matchant la même valeur
    successivement sur un même attribut étaient avant indiscernables.

    `count` dans chaque facette = nombre d'OBJETS distincts matchant (pas de
    lignes) ; `results` peut en revanche contenir plusieurs lignes pour un
    même objet (un par attribut/valeur matchant - toutes deux dans
    l'historique si history=true). Les facettes sont calculées sur
    l'ENSEMBLE des lignes matchantes (requêtes d'agrégation SQL séparées,
    sans LIMIT), PAS seulement sur les lignes de `results` déjà tronquées à
    500 - fix suite à la revue de l'action 21 (point 3) : calculer les
    facettes sur les seules lignes tronquées pouvait rendre une classe
    totalement invisible des facettes (et donc jamais sélectionnable) dès
    que `truncated=true` et que ses objets avaient des ids plus élevés que
    la coupe `ORDER BY o.id LIMIT 500`. `truncated` : true si plus de 500
    lignes brutes (objet, attribut, valeur) matchaient avant troncature des
    SEULS `results` - affiner la recherche est alors recommandé côté
    frontend. `fuzzy_suggestions` : toujours présent (liste vide si
    fuzzy=false ou aucune suggestion), pour simplifier le typage frontend
    (pas de clé optionnelle à vérifier).
    """
    q = request.args.get("q", "")
    if not q:
        abort(400, description="Paramètre 'q' requis")

    fuzzy = request.args.get("fuzzy") in ("1", "true", "True")
    history = request.args.get("history") in ("1", "true", "True")

    conn = app.get_db()
    safe_names, layers_index = _load_secret_and_layers_index(conn)
    safe_metas, safe_classes, safe_attr_names = _safe_attribute_arrays(safe_names)

    tenants = _tenant_read_filter()
    pattern = f"%{_ilike_escape(q)}%"

    sql = f"""
        SELECT o.id AS object_id, o.meta_class, o.class, a.name AS attribute_name, av.value_string,
               av.valid_to IS NULL AS is_current
        FROM attribute_value av
        JOIN attribute a ON a.id = av.attribute_id
        JOIN object o ON o.id = a.object_id
        WHERE av.value_string ILIKE %s ESCAPE '\\'
          AND o.deleted_at IS NULL
          AND {_SAFE_ATTRIBUTE_SQL}
    """
    params = [pattern, safe_metas, safe_classes, safe_attr_names]

    if not history:
        sql += " AND av.valid_to IS NULL"

    if tenants is not None:
        sql += " AND (o.tenants IS NULL OR o.tenants = '' OR string_to_array(o.tenants, ',') && %s::text[])"
        params.append(tenants)

    sql += " ORDER BY o.id LIMIT %s"
    params.append(_SEARCH_RESULT_LIMIT + 1)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    truncated = len(rows) > _SEARCH_RESULT_LIMIT
    rows = rows[:_SEARCH_RESULT_LIMIT]

    results = [
        {
            "id": row["object_id"],
            "meta_class": row["meta_class"],
            "class": row["class"],
            "attribute": row["attribute_name"],
            "value": row["value_string"],
            "is_current": bool(row["is_current"]),
        }
        for row in rows
    ]

    class_counts = _facet_class_counts(conn, pattern, history, tenants, safe_metas, safe_classes, safe_attr_names)
    attribute_counts = _facet_attribute_counts(conn, pattern, history, tenants, safe_metas, safe_classes, safe_attr_names)

    layers_counts = {}
    classes_facet = []
    for row in class_counts:
        key = (row["meta_class"], row["class"])
        classes_facet.append({"meta_class": row["meta_class"], "class": row["class"], "count": row["cnt"]})
        for layer in layers_index.get(key, []):
            layers_counts[layer] = layers_counts.get(layer, 0) + row["cnt"]

    attributes_facet = [{"name": row["attribute_name"], "count": row["cnt"]} for row in attribute_counts]

    facets = {
        "layers": sorted(
            ({"value": value, "count": count} for value, count in layers_counts.items()),
            key=lambda f: (-f["count"], f["value"]),
        ),
        "classes": sorted(
            classes_facet,
            key=lambda f: (-f["count"], f["meta_class"], f["class"]),
        ),
        "attributes": sorted(
            attributes_facet,
            key=lambda f: (-f["count"], f["name"]),
        ),
    }

    fuzzy_suggestions = []
    if fuzzy:
        fuzzy_suggestions = _fuzzy_candidate_suggestions(
            conn, q, history, tenants, safe_metas, safe_classes, safe_attr_names
        )

    return jsonify({
        "results": results,
        "facets": facets,
        "truncated": truncated,
        "fuzzy_suggestions": fuzzy_suggestions,
    })


def _search_base_sql(select_clause, pattern, history, tenants, safe_metas, safe_classes, safe_attr_names):
    """Construit la base commune (FROM/JOIN/WHERE, sans LIMIT) des requêtes
    d'agrégation de facettes (_facet_class_counts/_facet_attribute_counts) -
    même filtrage (ILIKE échappé, objets non supprimés, allow-list
    `secret`, historique, RBAC tenant) que la requête principale de
    `search_objects`, SANS troncature (fix suite à la revue de l'action 21,
    point 3 : les facettes doivent porter sur l'ENSEMBLE des lignes
    matchantes, pas seulement les 500 premières de `results`)."""
    sql = f"""
        {select_clause}
        FROM attribute_value av
        JOIN attribute a ON a.id = av.attribute_id
        JOIN object o ON o.id = a.object_id
        WHERE av.value_string ILIKE %s ESCAPE '\\'
          AND o.deleted_at IS NULL
          AND {_SAFE_ATTRIBUTE_SQL}
    """
    params = [pattern, safe_metas, safe_classes, safe_attr_names]

    if not history:
        sql += " AND av.valid_to IS NULL"

    if tenants is not None:
        sql += " AND (o.tenants IS NULL OR o.tenants = '' OR string_to_array(o.tenants, ',') && %s::text[])"
        params.append(tenants)

    return sql, params


def _facet_class_counts(conn, pattern, history, tenants, safe_metas, safe_classes, safe_attr_names):
    """Nombre d'objets DISTINCTS matchant, agrégé par (meta_class, class),
    sur l'ensemble des lignes matchantes (pas de LIMIT - voir
    _search_base_sql)."""
    sql, params = _search_base_sql(
        "SELECT o.meta_class, o.class, COUNT(DISTINCT o.id) AS cnt",
        pattern, history, tenants, safe_metas, safe_classes, safe_attr_names,
    )
    sql += " GROUP BY o.meta_class, o.class"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _facet_attribute_counts(conn, pattern, history, tenants, safe_metas, safe_classes, safe_attr_names):
    """Nombre d'objets DISTINCTS matchant, agrégé par nom d'attribut, sur
    l'ensemble des lignes matchantes (pas de LIMIT - voir
    _search_base_sql)."""
    sql, params = _search_base_sql(
        "SELECT a.name AS attribute_name, COUNT(DISTINCT o.id) AS cnt",
        pattern, history, tenants, safe_metas, safe_classes, safe_attr_names,
    )
    sql += " GROUP BY a.name"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _fuzzy_candidate_suggestions(conn, q, history, tenants, safe_metas, safe_classes, safe_attr_names):
    """Valeurs distinctes proches de `q` (rapidfuzz, même principe que
    `suggest_attribute_values` de routes_read.py, action 20), calculées sur
    un pool de valeurs candidates (toutes classes confondues, pas seulement
    celles déjà substring-matchées) - PAS un élargissement du filtrage des
    `results` déjà renvoyés par `search_objects`, seulement des propositions
    sélectionnables côté frontend pour relancer une nouvelle recherche.

    Même exclusion stricte (allow-list) du type `secret` et même RBAC
    tenant que la recherche principale. Pool borné par
    _SEARCH_FUZZY_POOL_LIMIT (choix arbitraire de coût, indépendant de
    _SEARCH_RESULT_LIMIT - voir docstring du module), avec un `ORDER BY`
    stable (`av.value_string`) ajouté suite à la revue de l'action 21
    (point 4) : sans tri, le sous-ensemble de 2000 lignes gardé par le
    LIMIT était arbitraire (dépendant de l'ordre de retour Postgres, non
    garanti), donc potentiellement différent d'une requête à l'autre pour
    un même `q`.

    `score_cutoff=_FUZZY_SCORE_CUTOFF` (revue de l'action 21, point 4) :
    sans seuil, `process.extract` renvoie quand même les N valeurs "les
    moins pires" du pool même si rien n'est réellement proche de `q` (bruit
    pur constaté en test live, ex. `q='zzzzzzzz'`) - avec le seuil, aucune
    suggestion n'est renvoyée si rien ne dépasse le score minimal."""
    sql = f"""
        SELECT DISTINCT av.value_string
        FROM attribute_value av
        JOIN attribute a ON a.id = av.attribute_id
        JOIN object o ON o.id = a.object_id
        WHERE o.deleted_at IS NULL
          AND av.value_string IS NOT NULL
          AND {_SAFE_ATTRIBUTE_SQL}
    """
    params = [safe_metas, safe_classes, safe_attr_names]

    if not history:
        sql += " AND av.valid_to IS NULL"

    if tenants is not None:
        sql += " AND (o.tenants IS NULL OR o.tenants = '' OR string_to_array(o.tenants, ',') && %s::text[])"
        params.append(tenants)

    sql += " ORDER BY av.value_string LIMIT %s"
    params.append(_SEARCH_FUZZY_POOL_LIMIT)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        candidates = [row[0] for row in cur.fetchall()]

    if not candidates:
        return []

    matches = process.extract(
        q, candidates, scorer=fuzz.ratio, limit=_FUZZY_SUGGESTIONS_LIMIT, score_cutoff=_FUZZY_SCORE_CUTOFF,
    )
    return [m[0] for m in matches]

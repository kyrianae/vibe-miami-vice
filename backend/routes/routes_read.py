import psycopg2.extras
from flask import Blueprint, Response, jsonify, abort, request
from rapidfuzz import process, fuzz

import app
from files.class_icon import generate_class_fallback_icon
from auth.rbac import _tenant_read_filter, _tenants_db_to_list
from secret_crypto import SecretEncryptionKeyError, decrypt_secret

# Nombre max de suggestions renvoyées par /api/suggest (plan-mark3.md
# action 20, specifications/07-roadmap.md §10.17) - décision utilisateur
# "top 10".
_SUGGEST_LIMIT = 10

MAX_DEPTH = 5

# Placeholder fixe (plan-mark3.md action 8, specifications/07-roadmap.md
# §10.10) : renvoyé par la lecture générique à la place d'un attribut
# `secret` défini - jamais le texte chiffré brut, jamais la valeur
# déchiffrée. Volontairement indépendant du nombre de caractères du texte
# en clair (pas d'indice de longueur).
_SECRET_PLACEHOLDER = "••••••••"

read_bp = Blueprint("read", __name__)

# ---------------------
# READ endpoints
# ---------------------

@read_bp.route("/api/read/class", methods=["GET"])
def list_classes():
    """Liste toutes les classes définies."""
    conn = app.get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, meta_class, data FROM definition ORDER BY meta_class")
        rows = cur.fetchall()

        classes = []
        for row in rows:
            data = row["data"]
            for cls in data.get("classes", []):
                classes.append({
                    "meta_class": row["meta_class"],
                    "class": cls["class"],
                    "displayname": cls.get("displayname"),
                    "tenants": cls.get("tenants"),
                    # Layers (plan-mark3.md action 14) : simple passthrough
                    # de lecture, même statut que "icon" ci-dessus - champ
                    # déjà stocké tel quel dans la colonne JSONB "data" par
                    # write_metaclass/write_class (aucune validation ni
                    # RBAC dessus), seul ce projecteur de lecture l'omettait
                    # avant ce correctif, le rendant invisible côté frontend
                    # malgré sa présence en base.
                    "layers": cls.get("layers"),
                    "icon": cls.get("icon"),
                    "attributes": cls["attributes"]
                })
        return jsonify(classes)


@read_bp.route("/api/read/meta_class", methods=["GET"])
def list_meta_classes():
    """Liste toutes les meta-classes."""
    conn = app.get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, meta_class FROM definition ORDER BY meta_class")
        rows = cur.fetchall()
    return jsonify([{"id": r["id"], "meta_class": r["meta_class"]} for r in rows])


@read_bp.route("/api/read/class/<int:class_id>", methods=["GET"])
def get_class_by_id(class_id):
    """Récupère une classe par son ID (index global parmi toutes les classes)."""
    with app.get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, meta_class, data FROM definition ORDER BY meta_class")
        rows = cur.fetchall()

        index = 0
        for row in rows:
            data = row["data"]
            for cls in data.get("classes", []):
                index += 1
                if index == class_id:
                    return jsonify({
                        "id": index,
                        "meta_class": row["meta_class"],
                        "class": cls["class"],
                        "displayname": cls.get("displayname"),
                        "tenants": cls.get("tenants"),
                        # Layers (plan-mark3.md action 14) : passthrough, cf.
                        # commentaire de list_classes ci-dessus.
                        "layers": cls.get("layers"),
                        "icon": cls.get("icon"),
                        "attributes": cls["attributes"]
                    })
        abort(404, description="Classe non trouvée")


@read_bp.route("/api/read/<string:meta_class>", methods=["GET"])
def get_classes_by_meta_class(meta_class):
    """Récupère toutes les classes d'une meta-classe."""
    with app.get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
                "SELECT id, meta_class, data FROM definition WHERE meta_class = %s",
                (meta_class,)
            )
        row = cur.fetchone()

        if not row:
            abort(404, description=f"Meta-classe '{meta_class}' non trouvée")

        data = row["data"]
        classes = []
        for cls in data.get("classes", []):
            classes.append({
                "class": cls["class"],
                "displayname": cls.get("displayname"),
                "tenants": cls.get("tenants"),
                # Layers (plan-mark3.md action 14) : passthrough, cf.
                # commentaire de list_classes ci-dessus. Lu/édité par
                # ConfigurationPage.tsx via apiReadMetaClass - sans cette
                # clé, les layers sauvegardés disparaissaient au rechargement
                # de la page malgré leur présence en base.
                "layers": cls.get("layers"),
                "icon": cls.get("icon"),
                "attributes": cls["attributes"]
            })
        return jsonify({"meta_class": row["meta_class"], "classes": classes})


@read_bp.route("/api/read/objects", methods=["GET"])
def list_objects():
    """Liste tous les objets sans leurs attributs.

    Filtrage RBAC multi-tenant (action 11) : global-admin voit tout ;
    tenant-admin/tenant-readonly (et le rôle fail-closed par défaut, tenants
    forcé à liste vide) ne voient que les objets non tenantés
    (tenants IS NULL/vide) ou tagués pour l'un de leurs tenants - filtrage
    fait au niveau SQL via l'opérateur overlap Postgres, pas en
    post-traitement Python.
    """
    tenants = _tenant_read_filter()
    with app.get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if tenants is None:
            cur.execute("SELECT id, meta_class, class, tenants FROM object WHERE deleted_at IS NULL ORDER BY id")
        else:
            cur.execute(
                """SELECT id, meta_class, class, tenants FROM object
                   WHERE deleted_at IS NULL
                     AND (tenants IS NULL OR tenants = '' OR string_to_array(tenants, ',') && %s::text[])
                   ORDER BY id""",
                (tenants,)
            )
        rows = cur.fetchall()
    for row in rows:
        row["tenants"] = _tenants_db_to_list(row["tenants"])
    return jsonify(rows)


# Historisation (plan-mark2.md action 6.0) : ne retourne que les valeurs
# actives (valid_to IS NULL) d'un objet, groupées par ligne attribute.
# Partagée entre la lecture (_build_object_payload) et le diff d'écriture
# (write_object, voir _load_active_attributes_by_name) pour n'avoir qu'une
# seule définition de "valeur active" dans tout le module.
_ACTIVE_ATTRIBUTE_VALUES_SQL = """
    SELECT a.id AS attribute_id, a.domain, a.name,
           av.id AS value_id, av.value_integer, av.value_float, av.value_string, av.joint_id
    FROM attribute a
    LEFT JOIN attribute_value av ON av.attribute_id = a.id AND av.valid_to IS NULL
    WHERE a.object_id = %s
    ORDER BY a.id, av.id
"""


def _decode_attribute_value_column(row):
    """Retourne (colonne_de_stockage, valeur_décodée) d'une ligne renvoyée
    par _ACTIVE_ATTRIBUTE_VALUES_SQL, ou (None, None) si la ligne ne porte
    aucune valeur (attribut sans aucune valeur active, LEFT JOIN vide)."""
    if row["value_integer"] is not None:
        return "value_integer", row["value_integer"]
    if row["value_float"] is not None:
        return "value_float", row["value_float"]
    if row["value_string"] is not None:
        return "value_string", row["value_string"]
    if row["joint_id"] is not None:
        return "joint_id", row["joint_id"]
    return None, None


def _load_active_attributes_by_name(conn, object_id):
    """Charge, pour write_object et write_attribute_value, l'état actif
    actuel des attributs d'un objet déjà existant, regroupé par nom
    d'attribut (domain/name) :

    {attr_name: {"attribute_id": int, "domain": str,
                 "values": [{"id": int, "column": str, "value": ...}, ...]}}

    Un attribut multi-valué (joint-1-n) a plusieurs entrées dans "values".
    Base du diff de 6.0 : comparer ces valeurs actives à celles reçues dans
    le corps de la requête, sans jamais fermer/recréer une valeur
    inchangée au sein d'un même groupe.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_ACTIVE_ATTRIBUTE_VALUES_SQL, (object_id,))
        rows = cur.fetchall()

    by_name = {}
    for row in rows:
        entry = by_name.setdefault(row["name"], {
            "attribute_id": row["attribute_id"],
            "domain": row["domain"],
            "values": [],
        })
        column, value = _decode_attribute_value_column(row)
        if column is not None:
            entry["values"].append({"id": row["value_id"], "column": column, "value": value})
    return by_name


def _resolve_attr_def(classes, cls, attr_name):
    """Résout l'attr_def utilisé pour une décision de sécurité (chiffrement à
    l'écriture ou masquage/typage à la lecture) sur un (classe, nom
    d'attribut), à partir de la liste brute `classes` d'une meta-classe
    (`definition.data["classes"]`) - jamais seulement de la PREMIÈRE
    occurrence rencontrée (plan-mark3.md action 21bis : fuite démontrée côté
    écriture - `routes_write.py`, `_coerce_typed_value` - et lecture -
    `GET /api/suggest/...` ci-dessous, `GET /api/read/object/<id>/secret/
    <attribute>` - quand un nom a plusieurs déclarations).

    Deux angles morts couverts à la fois, même principe deny-priority que
    `_load_secret_and_layers_index` (routes_search.py, action 21 revue 3) :
    - un nom d'attribut déclaré PLUSIEURS FOIS au sein d'une même classe
      (une fois `secret`, une fois non-secret) ;
    - la classe elle-même déclarée PLUSIEURS FOIS dans la même meta-classe
      (cas que `_check_class_name_unique`/`_check_attribute_names_unique`,
      `routes_write.py`, bloquent désormais à l'écriture - mais qui peut
      encore exister dans des données déjà stockées avant ce correctif).

    Toute déclaration de type `secret` est TOUJOURS prioritaire : dès qu'au
    moins une existe parmi les candidats, elle est retournée - jamais une
    déclaration non-secrète par défaut. Sinon, la première déclaration
    trouvée est retournée (comportement historique inchangé pour un nom non
    ambigu). None si le nom n'est déclaré nulle part pour cette classe."""
    candidates = []
    for c in classes or []:
        if not isinstance(c, dict) or c.get("class") != cls:
            continue
        for a in (c.get("attributes") or []):
            if isinstance(a, dict) and a.get("name") == attr_name:
                candidates.append(a)
    if not candidates:
        return None
    for a in candidates:
        if a.get("type") == "secret":
            return a
    return candidates[0]


def _secret_attribute_names(conn, meta_class, cls):
    """Noms des attributs de type `secret` déclarés sur (meta_class, cls)
    (plan-mark3.md action 8) - utilisé par `_build_object_payload` pour
    masquer leur valeur, jamais pour la déchiffrer. Une requête dédiée par
    objet affiché (même coût qu'un lookup similaire dans routes_files.py,
    `_lookup_attr_type`) : accepté, cohérent avec le reste du module qui ne
    mutualise pas ce genre de lookup entre deux appels.

    Accumulation sur TOUTES les occurrences de `cls` (plan-mark3.md action
    21bis) : une classe déclarée deux fois dans la même meta-classe ne doit
    jamais laisser une déclaration `secret` de la 2e occurrence invisible au
    masquage sous prétexte que la 1re occurrence rencontrée ne la déclare
    pas (l'ancien `return` au premier match s'arrêtait là)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT data FROM definition WHERE meta_class = %s", (meta_class,))
        defn = cur.fetchone()
    if not defn:
        return set()
    names = set()
    for c in defn["data"].get("classes", []):
        if isinstance(c, dict) and c.get("class") == cls:
            names.update(a["name"] for a in (c.get("attributes") or []) if isinstance(a, dict) and a.get("type") == "secret")
    return names


def _build_object_payload(object_id, conn, tenant_filter=None):
    """Construit le dict {id, meta_class, class, tenants, attributes} d'un objet.

    Retourne None si l'objet n'existe pas, ou s'il existe mais n'est pas
    visible pour le tenant_filter donné (None = pas de filtrage/global-admin,
    sinon liste des tenants de l'utilisateur) - pas d'abort ici : c'est à
    l'appelant de décider comment traiter une absence, notamment pour une
    jointure résolue en profondeur, où « non trouvé/non visible » ne doit
    pas être une erreur HTTP (même traitement que l'orphelin existant).
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if tenant_filter is None:
            cur.execute("SELECT id, meta_class, class, tenants FROM object WHERE id = %s AND deleted_at IS NULL", (object_id,))
        else:
            cur.execute(
                """SELECT id, meta_class, class, tenants FROM object
                   WHERE id = %s AND deleted_at IS NULL
                     AND (tenants IS NULL OR tenants = '' OR string_to_array(tenants, ',') && %s::text[])""",
                (object_id, tenant_filter)
            )
        obj = cur.fetchone()

    if not obj:
        return None

    obj["tenants"] = _tenants_db_to_list(obj["tenants"])

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_ACTIVE_ATTRIBUTE_VALUES_SQL, (object_id,))
        attr_rows = cur.fetchall()

    attributes = {}
    for row in attr_rows:
        attr_key = row["attribute_id"]
        if attr_key not in attributes:
            attributes[attr_key] = {
                "domain": row["domain"],
                "name": row["name"],
                "values": []
            }
        if row["value_id"] is not None:
            column, decoded = _decode_attribute_value_column(row)
            value = {"joint_id": decoded} if column == "joint_id" else decoded
            attributes[attr_key]["values"].append(value)

    # Masquage des attributs `secret` (plan-mark3.md action 8) : AUCUN
    # déchiffrement ici, jamais le texte chiffré brut non plus - placeholder
    # fixe si une valeur active existe, liste vide sinon (déjà le cas par
    # construction ci-dessus). Seule la route dédiée
    # GET /api/read/object/<id>/secret/<attribute> (réservée global-admin)
    # déchiffre une valeur.
    secret_names = _secret_attribute_names(conn, obj["meta_class"], obj["class"])
    if secret_names:
        for entry in attributes.values():
            if entry["name"] in secret_names:
                entry["values"] = [_SECRET_PLACEHOLDER for _ in entry["values"]]

    obj["attributes"] = list(attributes.values())
    return obj


@read_bp.route("/api/read/object/<int:object_id>", methods=["GET"])
def get_object_by_id(object_id):
    """Récupère un objet avec tous ses attributs et valeurs.

    Paramètres de requête optionnels :
    - deref=1|true|True : active la résolution récursive des jointures
      (clé "resolved" ajoutée à côté de "joint_id" dans les attributs).
    - depth : profondeur de résolution (entier entre 0 et MAX_DEPTH),
      ignoré si deref n'est pas actif. Défaut 1 si deref actif sans depth.
    """
    conn = app.get_db()
    tenant_filter = _tenant_read_filter()
    obj = _build_object_payload(object_id, conn, tenant_filter)

    if not obj:
        abort(404, description="Objet non trouvé")

    deref = request.args.get('deref') in ('1', 'true', 'True')
    if not deref:
        return jsonify(obj)

    depth_param = request.args.get('depth')
    if depth_param is None:
        depth = 1
    else:
        try:
            depth = int(depth_param)
        except ValueError:
            abort(400, description=f"depth doit être un entier entre 0 et {MAX_DEPTH}")
        if depth < 0 or depth > MAX_DEPTH:
            abort(400, description=f"depth doit être un entier entre 0 et {MAX_DEPTH}")

    cache = {object_id: obj}
    in_progress = {object_id}

    def resolve_attributes(payload, remaining_depth):
        for attr in payload["attributes"]:
            attr["values"] = [
                _resolve_joint_value(v, remaining_depth) if isinstance(v, dict) and "joint_id" in v else v
                for v in attr["values"]
            ]

    def _resolve_joint_value(v, remaining_depth):
        # Compromis assumé : le cache {object_id: payload} est partagé entre
        # toutes les branches de résolution, sans tenir compte de la
        # remaining_depth utilisée au moment où l'objet a été mis en cache.
        # Un objet caché via une branche à faible profondeur restante sera
        # réutilisé tel quel (résolution potentiellement partielle) pour une
        # autre branche qui aurait eu droit à une profondeur plus grande,
        # sans aucun flag "truncated" pour signaler cette troncature
        # silencieuse. Ce choix évite de recalculer la résolution et garantit
        # l'absence de boucle infinie ; ce n'est pas un bug.
        joint_id = v["joint_id"]

        if joint_id in in_progress:
            return {"joint_id": joint_id, "cycle": True}

        if remaining_depth <= 0:
            return {"joint_id": joint_id}

        if joint_id in cache:
            return {"joint_id": joint_id, "resolved": cache[joint_id]}

        in_progress.add(joint_id)
        try:
            target = _build_object_payload(joint_id, conn, tenant_filter)
            if target is None:
                return {"joint_id": joint_id}
            resolve_attributes(target, remaining_depth - 1)
            cache[joint_id] = target
        finally:
            in_progress.discard(joint_id)

        return {"joint_id": joint_id, "resolved": target}

    resolve_attributes(obj, depth)
    return jsonify(obj)


@read_bp.route("/api/read/object/<int:object_id>/secret/<string:attribute>", methods=["GET"])
def reveal_object_secret(object_id, attribute):
    """Révèle en clair la valeur ACTIVE d'un attribut de type `secret`
    (plan-mark3.md action 8 ; specifications/07-roadmap.md §10.10).

    Placée dans routes_read.py plutôt que dans un module routes_secrets.py
    dédié : pas de complexité multipart/FileStorage à isoler (contrairement
    à routes_files.py), et la route réutilise directement
    `_load_active_attributes_by_name`, déjà défini dans ce module -
    cohérent avec le choix déjà fait d'y placer `get_object_by_id` et
    `_build_object_payload`.

    RBAC strict volontairement DIFFÉRENT de toutes les autres routes de
    lecture : réservée EXCLUSIVEMENT à `ctx.is_global_admin`, jamais le
    RBAC tenant générique (`_tenant_read_filter`) - un tenant-admin ne doit
    JAMAIS pouvoir révéler un secret, même dans son propre périmètre
    tenant (décision utilisateur 2026-11-22). Cette route est en plus
    explicitement listée dans `auth.py` (`_PROTECTED_REGEXES`) pour exiger
    un Bearer token valide même si elle est un GET (contrairement aux
    autres /api/read/*, ouvertes sans authentification obligatoire) :
    401 sans token/token invalide, 403 si authentifié mais pas
    global-admin.

    404 : objet inexistant/supprimé, OU attribut non déclaré/pas de type
    `secret` sur la classe de l'objet, OU aucune valeur active - même
    sémantique « ne pas distinguer les cas » que les routes de lecture
    ciblées existantes (cf. read_object_file, routes_files.py).

    500 (jamais un succès trompeur) : SECRET_ENCRYPTION_KEY absente/
    invalide, ou jeton chiffré corrompu/chiffré avec une autre clé - voir
    secret_crypto.py pour le choix fail-fast vs runtime documenté.
    """
    ctx = app.get_auth_context()
    if not ctx.is_global_admin:
        abort(403, description="Réservé à global-admin : révélation d'un attribut secret")

    conn = app.get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, class, meta_class, tenants, deleted_at FROM object WHERE id = %s", (object_id,))
        obj = cur.fetchone()
    if not obj or obj[4] is not None:
        abort(404, description="Objet non trouvé")
    _, obj_class, obj_meta_class, _, _ = obj

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT data FROM definition WHERE meta_class = %s", (obj_meta_class,))
        defn = cur.fetchone()

    # Résolution deny-priority (plan-mark3.md action 21bis, voir
    # _resolve_attr_def) : si une quelconque déclaration de ce nom (classe
    # dupliquée ou attribut dupliqué dans la même classe) est `secret`, elle
    # est celle utilisée ici - jamais une déclaration non-secrète trouvée en
    # premier qui masquerait à tort une déclaration `secret` plus loin.
    attr_def = _resolve_attr_def(defn["data"].get("classes", []) if defn else [], obj_class, attribute)
    if attr_def is None or attr_def.get("type") != "secret":
        abort(404, description=f"Attribut '{attribute}' non déclaré ou pas de type 'secret' sur la classe '{obj_class}'")

    existing_attr = _load_active_attributes_by_name(conn, object_id).get(attribute)
    ciphertext = None
    if existing_attr:
        ciphertext = next((ev["value"] for ev in existing_attr["values"] if ev["column"] == "value_string"), None)
    if ciphertext is None:
        abort(404, description=f"Attribut '{attribute}' sans valeur active")

    try:
        plaintext = decrypt_secret(ciphertext)
    except SecretEncryptionKeyError as e:
        abort(500, description=str(e))
    except ValueError as e:
        abort(500, description=str(e))

    return jsonify({"object_id": object_id, "attribute": attribute, "value": plaintext})


@read_bp.route("/api/suggest/<string:meta_class>/<string:cls>/<string:attribute>", methods=["GET"])
def suggest_attribute_values(meta_class, cls, attribute):
    """Suggestions de valeurs apprises sur un attribut `string` marqué
    `autosuggest: true` (plan-mark3.md action 20 ; specifications/
    07-roadmap.md §10.17).

    Source des valeurs candidates : value_string ACTIF (valid_to IS NULL)
    de tout attribute_value du triplet (meta_class, class, attribute),
    toutes instances confondues - pas tout l'historique (décision
    utilisateur : une faute de frappe corrigée depuis ne doit plus être
    suggérée). RBAC tenant identique aux autres routes de lecture
    d'objets (_tenant_read_filter + objets non supprimés) : un
    tenant-admin ne voit que les valeurs portées par des objets visibles
    dans son périmètre.

    Tri par distance d'édition (rapidfuzz.process.extract, scorer
    fuzz.ratio) entre `q` (query param, défaut chaîne vide) et chaque
    valeur candidate distincte, top _SUGGEST_LIMIT renvoyé. `q` vide :
    pas de calcul de distance (comparer à une chaîne vide n'a pas de sens
    de tri), les _SUGGEST_LIMIT premières valeurs distinctes sont
    renvoyées telles quelles.

    404 : meta-classe/classe/attribut non déclaré dans le modèle - même
    sémantique "ne pas distinguer les cas" que les autres routes de
    lecture ciblées de ce module (reveal_object_secret, get_class_by_id).
    400 : attribut existant mais pas de type 'string' ou sans
    autosuggest actif sur sa définition.
    """
    with app.get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT data FROM definition WHERE meta_class = %s", (meta_class,))
        defn = cur.fetchone()
    if not defn:
        abort(404, description=f"Meta-classe '{meta_class}' non trouvée")

    all_classes = defn["data"].get("classes", [])
    class_exists = any(isinstance(c, dict) and c.get("class") == cls for c in all_classes)
    if not class_exists:
        abort(404, description=f"Classe '{cls}' non trouvée dans la meta-classe '{meta_class}'")

    # Résolution deny-priority (plan-mark3.md action 21bis, voir
    # _resolve_attr_def) : un nom d'attribut dupliqué (dans la classe, ou via
    # une classe elle-même dupliquée) dont AU MOINS une déclaration est
    # `secret` doit toujours être traité comme `secret` ici - la vérification
    # de type juste en dessous ("!= 'string'") le refuse alors
    # automatiquement (400), jamais un contournement via la déclaration
    # non-secrète trouvée en premier dans l'ancienne résolution.
    attr_def = _resolve_attr_def(all_classes, cls, attribute)
    if attr_def is None:
        abort(404, description=f"Attribut '{attribute}' non déclaré sur la classe '{cls}'")

    if attr_def.get("type") != "string" or not attr_def.get("autosuggest"):
        abort(400, description=f"Attribut '{attribute}' n'est pas configuré en autosuggest (type 'string' + autosuggest: true requis)")

    tenants = _tenant_read_filter()
    with app.get_db().cursor() as cur:
        if tenants is None:
            cur.execute(
                """SELECT DISTINCT av.value_string
                   FROM attribute_value av
                   JOIN attribute a ON a.id = av.attribute_id
                   JOIN object o ON o.id = a.object_id
                   WHERE o.meta_class = %s AND o.class = %s AND a.name = %s
                     AND av.valid_to IS NULL AND av.value_string IS NOT NULL
                     AND o.deleted_at IS NULL""",
                (meta_class, cls, attribute)
            )
        else:
            cur.execute(
                """SELECT DISTINCT av.value_string
                   FROM attribute_value av
                   JOIN attribute a ON a.id = av.attribute_id
                   JOIN object o ON o.id = a.object_id
                   WHERE o.meta_class = %s AND o.class = %s AND a.name = %s
                     AND av.valid_to IS NULL AND av.value_string IS NOT NULL
                     AND o.deleted_at IS NULL
                     AND (o.tenants IS NULL OR o.tenants = '' OR string_to_array(o.tenants, ',') && %s::text[])""",
                (meta_class, cls, attribute, tenants)
            )
        candidates = [row[0] for row in cur.fetchall()]

    q = request.args.get("q", "")
    if not q:
        suggestions = candidates[:_SUGGEST_LIMIT]
    else:
        matches = process.extract(q, candidates, scorer=fuzz.ratio, limit=_SUGGEST_LIMIT)
        suggestions = [m[0] for m in matches]

    return jsonify({"suggestions": suggestions})


@read_bp.route("/api/class_icon/<string:meta_class>/<string:cls>", methods=["GET"])
def get_class_fallback_icon(meta_class, cls):
    """Sert le SVG de secours généré localement pour une classe sans logo NI
    icône choisie manuellement (plan-mark3.md action 4, point 1bis ; détail
    de conception specifications/07-roadmap.md §10.8 ; génération :
    class_icon.py).

    Répartition frontend/backend assumée, à ne pas confondre : le jeu fixe
    d'icônes choisies manuellement (champ "icon" du schéma, point 1) est
    entièrement embarqué côté frontend (frontend/src/classIcons.tsx) -
    cette route ne sert JAMAIS une icône de ce jeu fixe, uniquement le
    fallback auto-généré (rond + initiales), dernier recours avant la
    couleur de palette (§6.4). Le frontend décide lui-même, sans requête
    réseau, s'il doit rendre le SVG embarqué du jeu fixe (icône choisie
    manuellement présente) ; il n'appelle cette route que si ni logo ni
    icône manuelle ne sont disponibles pour l'objet/la classe concernée.

    Pas de filtrage tenant ici (contrairement aux routes de lecture
    d'objet) : cohérent avec les autres routes de lecture de schéma déjà
    non filtrées par tenant (list_classes, get_class_by_id,
    get_classes_by_meta_class ci-dessus) - le SVG généré ne dépend que du
    NOM de la classe, jamais d'une donnée d'objet, donc aucune fuite
    possible. 404 si la classe n'existe pas dans le modèle, pour éviter de
    générer/cacher un SVG pour un nom de classe arbitraire non défini."""
    with app.get_db().cursor() as cur:
        cur.execute("SELECT data FROM definition WHERE meta_class = %s", (meta_class,))
        row = cur.fetchone()
    if not row:
        abort(404, description=f"Meta-classe '{meta_class}' non trouvée")
    class_def = next((c for c in row[0].get("classes", []) if c["class"] == cls), None)
    if class_def is None:
        abort(404, description=f"Classe '{cls}' non trouvée dans la meta-classe '{meta_class}'")

    svg = generate_class_fallback_icon(cls)
    response = Response(svg, content_type="image/svg+xml")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response

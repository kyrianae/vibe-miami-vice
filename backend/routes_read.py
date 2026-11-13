import psycopg2.extras
from flask import Blueprint, jsonify, abort, request

import app
from rbac import _tenant_read_filter, _tenants_db_to_list

MAX_DEPTH = 5

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

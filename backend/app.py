import os
import json
import psycopg2
import psycopg2.extras
import jwt
from jwt import PyJWKClient
from flask import Flask, jsonify, request, abort, g

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://miami:vice@localhost:5432/miami_vice")
SCHEMA_PATH = os.environ.get("SCHEMA_PATH", "/model/schema.json")
MAX_DEPTH = 5

# ---------------------
# Authentification (Keycloak) — voir plan.md action 7, doc/choix-authent.md
# ---------------------
#
# ATTENTION, point de vigilance explicite : les rôles/groupes Keycloak
# vérifiés ici ne servent qu'à l'authentification/autorisation d'accès à
# l'API (qui a le droit d'écrire). Ils ne doivent JAMAIS être confondus
# avec les classes métier "role"/"groupe" du modèle applicatif
# (model/personnes.json), qui sont des objets métier ordinaires, éditables
# librement via l'UI générique (POST /api/write/object) et n'ont aucun
# rapport avec les droits d'accès à cette API.

KEYCLOAK_ISSUER = os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8080/realms/miami-vice")
KEYCLOAK_JWKS_URL = os.environ.get(
    "KEYCLOAK_JWKS_URL",
    "http://keycloak:8080/realms/miami-vice/protocol/openid-connect/certs",
)

# PyJWKClient gère nativement le cache + TTL (5 minutes par défaut) du jeu
# de clés JWKS, et ne refait un appel réseau que si le cache a expiré ou si
# le "kid" du token n'est pas (encore) dans le cache courant — jamais un
# appel réseau systématique à chaque requête protégée. Important ici : le
# backend tourne avec un seul worker Gunicorn synchrone (voir
# backend/Dockerfile), donc ce cache réduit très fortement (sans
# l'éliminer) le risque de blocage du worker sur un appel JWKS : un
# rafraîchissement du cache expiré (TTL dépassé) ou un "kid" inconnu peut
# encore déclencher, à ce moment précis, un appel réseau bloquant vers
# Keycloak si celui-ci est lent ou indisponible — rare en pratique, mais
# pas impossible.
_jwk_client = None


def get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(KEYCLOAK_JWKS_URL, cache_jwk_set=True, lifespan=300)
    return _jwk_client


# Routes mutantes à protéger, listées explicitement (pas un simple
# startswith('/api/write') qui oublierait /api/init et la future
# /api/purge de l'action 6.2, cf. plan.md action 7).
_PROTECTED_PREFIXES = ("/api/write/", "/api/delete/")
_PROTECTED_EXACT_PATHS = ("/api/init", "/api/purge")


def _requires_auth(path):
    return path.startswith(_PROTECTED_PREFIXES) or path in _PROTECTED_EXACT_PATHS


@app.before_request
def require_auth():
    """Protège les routes d'écriture/suppression avec un Bearer JWT Keycloak.

    Les routes /api/read/* restent entièrement ouvertes (pas de contrôle).
    """
    if not _requires_auth(request.path):
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        abort(401, description="Authentification requise (en-tête 'Authorization: Bearer <token>' manquant)")

    token = auth_header[len("Bearer "):].strip()
    try:
        signing_key = get_jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            # Pas de vérification stricte de "aud" : par défaut, Keycloak
            # n'ajoute pas automatiquement l'audience du client appelant
            # dans les tokens émis (il faudrait un protocol mapper dédié,
            # non configuré dans ce premier passage, cf. rapport du worker
            # pour ce choix). On vérifie à la place "azp" (authorized
            # party, toujours présent) contre les clients applicatifs
            # connus, ce qui donne une garantie équivalente ici.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as e:
        abort(401, description=f"Token invalide ou expiré : {e}")
    except jwt.PyJWKClientError as e:
        abort(401, description=f"Impossible de vérifier le token (JWKS Keycloak injoignable ou kid inconnu) : {e}")

    if claims.get("azp") not in ("miami-vice-direct", "miami-vice-service"):
        abort(401, description="Token émis pour un client inattendu")

    g.auth_claims = claims


def get_db():
    """Ouvre une nouvelle connexion à la base de données si aucune n'existe pour le contexte actuel."""
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = False
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """Ferme la connexion à la base de données à la fin de la requête."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


# ---------------------
# READ endpoints
# ---------------------

@app.route("/api/read/class", methods=["GET"])
def list_classes():
    """Liste toutes les classes définies."""
    conn = get_db()
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
                    "attributes": cls["attributes"]
                })
        return jsonify(classes)


@app.route("/api/read/meta_class", methods=["GET"])
def list_meta_classes():
    """Liste toutes les meta-classes."""
    conn = get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, meta_class FROM definition ORDER BY meta_class")
        rows = cur.fetchall()
    return jsonify([{"id": r["id"], "meta_class": r["meta_class"]} for r in rows])


@app.route("/api/read/class/<int:class_id>", methods=["GET"])
def get_class_by_id(class_id):
    """Récupère une classe par son ID (index global parmi toutes les classes)."""
    with get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
                        "attributes": cls["attributes"]
                    })
        abort(404, description="Classe non trouvée")


@app.route("/api/read/<string:meta_class>", methods=["GET"])
def get_classes_by_meta_class(meta_class):
    """Récupère toutes les classes d'une meta-classe."""
    with get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
                "attributes": cls["attributes"]
            })
        return jsonify({"meta_class": row["meta_class"], "classes": classes})


@app.route("/api/read/objects", methods=["GET"])
def list_objects():
    """Liste tous les objets sans leurs attributs."""
    with get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, meta_class, class FROM object ORDER BY id")
        rows = cur.fetchall()
    return jsonify(rows)


def _build_object_payload(object_id, conn):
    """Construit le dict {id, meta_class, class, attributes} d'un objet.

    Retourne None si l'objet n'existe pas (pas d'abort ici : c'est à
    l'appelant de décider comment traiter une absence, notamment pour une
    jointure résolue en profondeur, où « non trouvé » ne doit pas être une
    erreur HTTP).
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, meta_class, class FROM object WHERE id = %s", (object_id,))
        obj = cur.fetchone()

    if not obj:
        return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT a.id AS attribute_id, a.domain, a.name,
                   av.id AS value_id, av.value_integer, av.value_float, av.value_string, av.joint_id
            FROM attribute a
            LEFT JOIN attribute_value av ON av.attribute_id = a.id
            WHERE a.object_id = %s
            ORDER BY a.id, av.id
        """, (object_id,))
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
            value = None
            if row["value_integer"] is not None:
                value = row["value_integer"]
            elif row["value_float"] is not None:
                value = row["value_float"]
            elif row["value_string"] is not None:
                value = row["value_string"]
            elif row["joint_id"] is not None:
                value = {"joint_id": row["joint_id"]}
            attributes[attr_key]["values"].append(value)

    obj["attributes"] = list(attributes.values())
    return obj


@app.route("/api/read/object/<int:object_id>", methods=["GET"])
def get_object_by_id(object_id):
    """Récupère un objet avec tous ses attributs et valeurs.

    Paramètres de requête optionnels :
    - deref=1|true|True : active la résolution récursive des jointures
      (clé "resolved" ajoutée à côté de "joint_id" dans les attributs).
    - depth : profondeur de résolution (entier entre 0 et MAX_DEPTH),
      ignoré si deref n'est pas actif. Défaut 1 si deref actif sans depth.
    """
    conn = get_db()
    obj = _build_object_payload(object_id, conn)

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
            target = _build_object_payload(joint_id, conn)
            if target is None:
                return {"joint_id": joint_id}
            resolve_attributes(target, remaining_depth - 1)
            cache[joint_id] = target
        finally:
            in_progress.discard(joint_id)

        return {"joint_id": joint_id, "resolved": target}

    resolve_attributes(obj, depth)
    return jsonify(obj)


# ---------------------
# WRITE endpoints
# ---------------------

@app.route("/api/write/object", methods=["POST"])
def write_object():
    """Crée ou met à jour un objet avec ses attributs et valeurs.

    Body JSON attendu :
    {
        "meta_class": "personne",
        "class": "personne_physique",
        "attributes": {
            "nom": "Doe",
            "prenom": "John"
        }
    }

    Si un champ "id" est présent, l'objet existant est mis à jour.
    """
    body = request.get_json()
    if not body or "meta_class" not in body or "class" not in body:
        abort(400, description="Champs 'meta_class' et 'class' requis")

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: # RealDictCursor pour la lecture
            # Chercher la définition de la classe
            cur.execute("SELECT data FROM definition WHERE meta_class = %s", (body["meta_class"],))
            defn = cur.fetchone()

            class_def = None
            if defn:
                for cls in defn["data"].get("classes", []):
                    if cls["class"] == body["class"]:
                        class_def = cls
                        break

        object_id = body.get("id")

        with conn.cursor() as cur:
            if object_id:
                # UPDATE : vérifier que l'objet existe
                cur.execute("SELECT id FROM object WHERE id = %s", (object_id,))
                if not cur.fetchone():
                    abort(404, description=f"Objet {object_id} non trouvé")

                # Mettre à jour meta_class et class
                cur.execute(
                    "UPDATE object SET meta_class = %s, class = %s WHERE id = %s",
                    (body["meta_class"], body["class"], object_id)
                )

                # Supprimer les anciennes valeurs et attributs
                cur.execute("""
                    DELETE FROM attribute_value WHERE attribute_id IN (
                        SELECT id FROM attribute WHERE object_id = %s
                    )
                """, (object_id,))
                cur.execute("DELETE FROM attribute WHERE object_id = %s", (object_id,))
            else:
                # CREATE
                cur.execute(
                    "INSERT INTO object (meta_class, class) VALUES (%s, %s) RETURNING id",
                    (body["meta_class"], body["class"])
                )
                object_id = cur.fetchone()[0]

            attrs = body.get("attributes", {})
            for attr_name, attr_value in attrs.items():
                # Trouver le domain depuis la définition
                domain = "default"
                if class_def:
                    for attr_def in class_def.get("attributes", []):
                        if attr_def["name"] == attr_name:
                            domain = attr_def["domain"]
                            break

                cur.execute(
                    "INSERT INTO attribute (object_id, domain, name) VALUES (%s, %s, %s) RETURNING id",
                    (object_id, domain, attr_name)
                )
                attribute_id = cur.fetchone()[0]

                # Déterminer le type de valeur
                if isinstance(attr_value, list):
                    for v in attr_value:
                        _insert_value(cur, attribute_id, v)
                else:
                    _insert_value(cur, attribute_id, attr_value)

        conn.commit()
        action = "updated" if body.get("id") else "created"
        return jsonify({"status": "ok", "id": object_id, "action": action}), 200 if action == "updated" else 201
    except Exception as e:
        conn.rollback()
        raise e


def _insert_value(cur, attribute_id, value):
    """Insère une valeur dans attribute_value selon son type."""
    if isinstance(value, dict) and "joint_id" in value:
        cur.execute(
            "INSERT INTO attribute_value (attribute_id, joint_id) VALUES (%s, %s)",
            (attribute_id, value["joint_id"])
        )
    elif isinstance(value, int):
        cur.execute(
            "INSERT INTO attribute_value (attribute_id, value_integer) VALUES (%s, %s)",
            (attribute_id, value)
        )
    elif isinstance(value, float):
        cur.execute(
            "INSERT INTO attribute_value (attribute_id, value_float) VALUES (%s, %s)",
            (attribute_id, value)
        )
    else:
        cur.execute(
            "INSERT INTO attribute_value (attribute_id, value_string) VALUES (%s, %s)",
            (attribute_id, str(value))
        )


@app.route("/api/write/attribute/<string:cls>/<int:object_id>/<string:attribute>/<string:value>", methods=["PUT"])
def write_attribute_value(cls, object_id, attribute, value):
    """Écrit ou met à jour la valeur d'un attribut d'un objet.

    URL: /api/write/attribute/<class>/<id>/<attribute>/<value>
    """
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Vérifier que l'objet existe et correspond à la classe
            cur.execute("SELECT id, class FROM object WHERE id = %s", (object_id,))
            obj = cur.fetchone()

            if not obj:
                abort(404, description="Objet non trouvé")
            if obj["class"] != cls:
                abort(400, description=f"L'objet {object_id} n'est pas de classe '{cls}'")

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Chercher l'attribut existant
            cur.execute(
                "SELECT id FROM attribute WHERE object_id = %s AND name = %s",
                (object_id, attribute)
            )
            attr_row = cur.fetchone()

            if attr_row:
                attribute_id = attr_row["id"]
                # Supprimer les anciennes valeurs
                cur.execute("DELETE FROM attribute_value WHERE attribute_id = %s", (attribute_id,))
            else:
                # Créer l'attribut (chercher le domain dans la définition)
                domain = "default"
                cur.execute("SELECT meta_class FROM object WHERE id = %s", (object_id,))
                obj_meta = cur.fetchone()
                if obj_meta:
                    cur.execute("SELECT data FROM definition WHERE meta_class = %s", (obj_meta["meta_class"],))
                    defn = cur.fetchone()
                    if defn:
                        for c in defn["data"].get("classes", []):
                            if c["class"] == cls:
                                for a in c.get("attributes", []):
                                    if a["name"] == attribute:
                                        domain = a["domain"]
                                        break

                cur.execute(
                    "INSERT INTO attribute (object_id, domain, name) VALUES (%s, %s, %s) RETURNING id",
                    (object_id, domain, attribute)
                )
                attribute_id = cur.fetchone()["id"]

            # Insérer la nouvelle valeur (tenter int, puis float, sinon string)
            try:
                int_val = int(value)
                cur.execute(
                    "INSERT INTO attribute_value (attribute_id, value_integer) VALUES (%s, %s)",
                    (attribute_id, int_val)
                )
            except ValueError:
                try:
                    float_val = float(value)
                    cur.execute(
                        "INSERT INTO attribute_value (attribute_id, value_float) VALUES (%s, %s)",
                        (attribute_id, float_val)
                    )
                except ValueError:
                    cur.execute(
                        "INSERT INTO attribute_value (attribute_id, value_string) VALUES (%s, %s)",
                        (attribute_id, value)
                    )

        conn.commit()
        return jsonify({"status": "ok", "object_id": object_id, "attribute": attribute, "value": value})
    except Exception as e:
        conn.rollback()
        raise e

@app.route("/api/write/class", methods=["POST"])
def write_class():
    """Ajoute ou met à jour une classe dans une meta-classe existante.

    Body JSON attendu :
    {
        "meta_class": "personne",
        "class": {
            "class": "personne_morale",
            "attributes": [...]
        }
    }
    """
    body = request.get_json()
    if not body or "meta_class" not in body or "class" not in body:
        abort(400, description="Champs 'meta_class' et 'class' requis")

    meta_class_name = body["meta_class"]
    new_class = body["class"]

    if "class" not in new_class or "attributes" not in new_class:
        abort(400, description="La classe doit contenir 'class' et 'attributes'")

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: # RealDictCursor pour la lecture
            cur.execute(
                "SELECT id, data FROM definition WHERE meta_class = %s",
                (meta_class_name,)
            )
            row = cur.fetchone()

            if not row:
                abort(404, description=f"Meta-classe '{meta_class_name}' non trouvée. Créez-la d'abord avec /api/write/metaclass")

        data = row["data"]
        # Remplacer si la classe existe déjà, sinon ajouter
        classes = data.get("classes", [])
        replaced = False
        for i, cls in enumerate(classes):
            if cls["class"] == new_class["class"]:
                classes[i] = new_class
                replaced = True
                break
        if not replaced:
            classes.append(new_class)

        data["classes"] = classes

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE definition SET data = %s WHERE id = %s",
                (json.dumps(data), row["id"])
            )
        conn.commit()

        return jsonify({"status": "ok", "action": "updated" if replaced else "created", "class": new_class["class"]}), 200 if replaced else 201
    except Exception as e:
        conn.rollback()
        raise e


@app.route("/api/write/metaclass", methods=["POST"])
def write_metaclass():
    """Crée ou remplace une meta-classe entière.

    Body JSON attendu (même format que les fichiers model/*.json) :
    {
        "meta_class": "personne",
        "classes": [...]
    }
    """
    body = request.get_json()
    if not body or "meta_class" not in body or "classes" not in body:
        abort(400, description="Champs 'meta_class' et 'classes' requis")

    meta_class_name = body["meta_class"]
    data = {"meta_class": meta_class_name, "classes": body["classes"]}

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: # RealDictCursor pour la lecture
            cur.execute(
                "SELECT id FROM definition WHERE meta_class = %s",
                (meta_class_name,)
            )
            existing = cur.fetchone()

        with conn.cursor() as cur:
            if existing:
                cur.execute(
                    "UPDATE definition SET data = %s WHERE id = %s",
                    (json.dumps(data), existing["id"])
                )
                action = "updated"
            else:
                cur.execute(
                    "INSERT INTO definition (meta_class, data) VALUES (%s, %s)",
                    (meta_class_name, json.dumps(data))
                )
                action = "created"
        conn.commit()

        return jsonify({"status": "ok", "action": action, "meta_class": meta_class_name}), 200 if action == "updated" else 201
    except Exception as e:
        conn.rollback()
        raise e


# ---------------------
# Chargement initial des fichiers model/*.json
# ---------------------

@app.route("/api/init", methods=["POST"])
def init_from_model_files():
    """Charge tous les fichiers JSON du dossier /model dans la table definition."""
    model_dir = os.environ.get("MODEL_DIR", "/model")
    loaded = []

    conn = get_db()
    try:
        with conn.cursor() as cur:
            for filename in os.listdir(model_dir):
                if filename.endswith(".json") and filename != "schema.json":
                    filepath = os.path.join(model_dir, filename)
                    with open(filepath) as f:
                        data = json.load(f)

                    if "meta_class" not in data or "classes" not in data:
                        continue

                    meta_class_name = data["meta_class"]
                    store_data = {"meta_class": meta_class_name, "classes": data["classes"]}

                    cur.execute(
                            """INSERT INTO definition (meta_class, data) VALUES (%s, %s)
                               ON CONFLICT (meta_class) DO UPDATE SET data = EXCLUDED.data""",
                            (meta_class_name, json.dumps(store_data))
                        )
                    loaded.append(meta_class_name)

        conn.commit()
        return jsonify({"status": "ok", "loaded": loaded})
    except Exception as e:
        conn.rollback()
        raise e


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

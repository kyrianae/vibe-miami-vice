import os
import json
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, abort, g

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://miami:vice@localhost:5432/miami_vice")
SCHEMA_PATH = os.environ.get("SCHEMA_PATH", "/model/schema.json")


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


@app.route("/api/read/object/<int:object_id>", methods=["GET"])
def get_object_by_id(object_id):
    """Récupère un objet avec tous ses attributs et valeurs."""
    conn = get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, meta_class, class FROM object WHERE id = %s", (object_id,))
        obj = cur.fetchone()

    if not obj:
        abort(404, description="Objet non trouvé")

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

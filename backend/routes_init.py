import json
import os

import psycopg2.extras
import jsonschema
from flask import Blueprint, jsonify, abort

import app
from db import load_schema
from rbac import _check_class_tenant_write_permission, _existing_class_out_of_tenant_scope

init_bp = Blueprint("init", __name__)

# ---------------------
# Chargement initial des fichiers model/*.json
# ---------------------

@init_bp.route("/api/init", methods=["POST"])
def init_from_model_files():
    """Charge tous les fichiers JSON du dossier /model dans la table definition.

    RBAC multi-tenant (action 11) : tenant-readonly -> 403 systématique.
    tenant-admin -> chaque classe chargée est soumise à la même règle que
    write_class/write_metaclass (classe non taguée -> auto-tag avec son
    tenant ; classe déjà existante hors de son périmètre, i.e. taguée pour
    un autre tenant OU globale/non taguée -> jamais de 403 global qui
    avorterait tout le chargement multi-fichiers : la ou les classes
    concernées sont simplement "skippées" (laissées inchangées en base,
    jamais re-taguées silencieusement) et listées dans la réponse JSON sous
    `skipped`, le reste du fichier (classes nouvelles ou déjà dans son
    périmètre) continue d'être chargé normalement. Comportement identique à
    write_class/write_metaclass (403 dur) uniquement pour global-admin, qui
    n'a de toute façon aucune restriction donc le cas ne se présente pas.
    """
    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : chargement du modèle interdit")

    model_dir = os.environ.get("MODEL_DIR", "/model")
    loaded = []
    skipped = []

    conn = app.get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for filename in os.listdir(model_dir):
                if filename.endswith(".json") and filename != "schema.json":
                    filepath = os.path.join(model_dir, filename)
                    with open(filepath) as f:
                        data = json.load(f)

                    if "meta_class" not in data or "classes" not in data:
                        continue

                    meta_class_name = data["meta_class"]

                    try:
                        jsonschema.validate(instance=data, schema=load_schema())
                    except jsonschema.ValidationError as e:
                        skipped.append({
                            "meta_class": meta_class_name,
                            "file": filename,
                            "reason": f"fichier invalide au regard du schéma JSON : {e}",
                        })
                        continue

                    if ctx.is_tenant_admin:
                        cur.execute("SELECT data FROM definition WHERE meta_class = %s", (meta_class_name,))
                        existing_defn = cur.fetchone()
                        existing_by_name = {}
                        if existing_defn:
                            existing_by_name = {
                                c["class"]: c for c in existing_defn["data"].get("classes", [])
                            }

                        merged_classes = []
                        seen_names = set()
                        for cls in data["classes"]:
                            cls_name = cls.get("class")
                            seen_names.add(cls_name)
                            existing_cls = existing_by_name.get(cls_name)
                            if existing_cls is not None and _existing_class_out_of_tenant_scope(ctx, existing_cls):
                                skipped.append({
                                    "meta_class": meta_class_name,
                                    "class": cls_name,
                                    "reason": "classe existante hors de votre périmètre tenant (globale ou autre tenant) : non modifiée",
                                })
                                merged_classes.append(existing_cls)
                                continue
                            _check_class_tenant_write_permission(ctx, cls)
                            merged_classes.append(cls)

                        # Classes déjà en base mais absentes du fichier rechargé :
                        # jamais supprimées silencieusement par un rechargement partiel.
                        for name, existing_cls in existing_by_name.items():
                            if name not in seen_names:
                                merged_classes.append(existing_cls)

                        store_data = {"meta_class": meta_class_name, "classes": merged_classes}
                    else:
                        store_data = {"meta_class": meta_class_name, "classes": data["classes"]}

                    cur.execute(
                            """INSERT INTO definition (meta_class, data) VALUES (%s, %s)
                               ON CONFLICT (meta_class) DO UPDATE SET data = EXCLUDED.data""",
                            (meta_class_name, json.dumps(store_data))
                        )
                    loaded.append(meta_class_name)

        conn.commit()
        return jsonify({"status": "ok", "loaded": loaded, "skipped": skipped})
    except Exception as e:
        conn.rollback()
        raise e

"""Routes pour les types d'attribut « fichier », « image » et « csv »
(plan-mark3.md action 3 ; détail de conception : specifications/07-roadmap.md
§10.8). Dépend de `file_storage.py` (action 2) et de la logique
d'historisation `_apply_attribute_diff` (routes_write.py, plan-mark2.md
action 6.0).

Aucune nouvelle colonne en base : la valeur stockée dans
`attribute_value.value_string` est un pointeur "<version>:<nom_fichier>" vers
le contenu réel géré par `FileStorage`. `_coerce_typed_value` (routes_write.py)
n'a pas besoin d'être modifié pour ces trois types : la branche par défaut
("value_string", str(raw_value)) s'applique déjà correctement à un pointeur
construit ici. En revanche, write_object/write_attribute_value (JSON)
rejettent explicitement toute tentative d'écrire une valeur sur un attribut
de type file/image/csv (voir routes_write.py) : ces types ne s'écrivent que
via les routes multipart de ce module, jamais via le endpoint JSON générique
(pas d'encodage JSON raisonnable d'un pointeur fiable côté client - éviter
qu'un appelant injecte un pointeur arbitraire ne correspondant à aucun
fichier réellement stocké).

Nom de fichier stocké dans le pointeur : `os.path.basename(nom_reçu)`, pas le
nom brut du multipart tel quel - élimine tout composant de répertoire qu'un
client pourrait inclure (ex. anciens navigateurs envoyant un chemin complet),
avant même d'atteindre `file_storage._sanitize_segment` (qui, lui, rejette
plutôt que ne transforme). Le même nom (post-basename) est utilisé pour
l'appel à `FileStorage.save` ET pour le pointeur stocké : par construction,
jamais de divergence entre le nom annoncé dans le pointeur et le nom réel sur
disque.

Pointeur parsé avec `split(":", 1)` : seul le premier ':' sépare la version
du nom de fichier, le nom lui-même peut légitimement contenir ':'.

Décision de sécurité SVG (cf. plan-mark3.md action 3, point 6 /
specifications/07-roadmap.md §10.8) : pas de sanitization du SVG à l'upload
(trop fragile sans lib externe dédiée). Accepté tel quel après validation
structurelle (XML bien formé, racine <svg>, via `defusedxml` - voir
file_validation.py), mais toujours servi en lecture avec
Content-Disposition: attachment (jamais inline) - cohérent avec l'absence
d'aperçu <img> côté frontend pour ce cas.

Validation de contenu (image/csv) et nom de fichier limite -> 400 propre :
factorisées dans file_validation.py (partagé avec routes_write.py, point A
de la revue croisée - éviter un import circulaire entre ce module et
routes_write.py).
"""
import os

import psycopg2
import psycopg2.errors
import psycopg2.extras
from flask import Blueprint, Response, abort, jsonify, request

import app
from file_storage import LocalFileStorage
from file_validation import extension_of, save_file_or_400, validate_csv_content, validate_image_content
from rbac import _tenant_read_filter, _tenants_db_to_list
from routes_read import _build_object_payload, _load_active_attributes_by_name
from routes_write import _apply_attribute_diff

files_bp = Blueprint("files", __name__)

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "svg": "image/svg+xml",
    "csv": "text/csv",
}


@files_bp.route("/api/write/object/<int:object_id>/file/<string:attribute>", methods=["POST"])
def write_object_file(object_id, attribute):
    """Upload (multipart/form-data, champ `file`) d'une nouvelle version pour
    un attribut de type `file`/`image`/`csv` d'un objet existant.
    Historisation identique aux autres routes d'écriture
    (_apply_attribute_diff) : ferme la valeur active précédente, en ouvre une
    nouvelle pointant la version FileStorage nouvellement créée.

    Verrouillage réduit (correction post-revue, point D3) : résolution du
    modèle, RBAC, validation du contenu et écriture disque (jusqu'à 20 Mo,
    cf. MAX_CONTENT_LENGTH) se font SANS verrou `FOR NO KEY UPDATE` - ce
    verrou n'est repris que pour l'insert final d'attribute_value, fenêtre
    réduite au strict SQL. Limite connue assumée : l'objet est relu une
    seconde fois sous verrou pour reconfirmer qu'il n'a pas été supprimé
    entre-temps (race rare, fichier déjà écrit alors nettoyé best-effort),
    mais les autres conditions RBAC (tenant de l'objet/de la classe) ne sont
    pas revérifiées après l'acquisition du verrou - fenêtre de race
    théorique mais non ré-exploitée ici (pas de complexité supplémentaire
    pour ce cas marginal).
    """
    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture de fichier interdite")

    if "file" not in request.files:
        abort(400, description="Champ multipart 'file' requis")
    upload = request.files["file"]
    filename = os.path.basename(upload.filename or "")
    if not filename:
        abort(400, description="Nom de fichier vide ou invalide")

    conn = app.get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, class, meta_class, tenants, deleted_at FROM object WHERE id = %s", (object_id,))
            obj = cur.fetchone()
        if not obj:
            abort(404, description="Objet non trouvé")
        _, obj_class, obj_meta_class, obj_tenants_raw, obj_deleted_at = obj
        if obj_deleted_at is not None:
            abort(404, description="Objet non trouvé")

        with conn.cursor() as cur:
            cur.execute("SELECT data FROM definition WHERE meta_class = %s", (obj_meta_class,))
            defn = cur.fetchone()
        class_def = None
        if defn:
            for c in defn[0].get("classes", []):
                if c["class"] == obj_class:
                    class_def = c
                    break

        if ctx.is_tenant_admin:
            obj_tenants = _tenants_db_to_list(obj_tenants_raw)
            if obj_tenants and not (set(obj_tenants) & set(ctx.tenants)):
                abort(403, description="Objet hors de votre périmètre tenant")
            class_tenants = (class_def or {}).get("tenants") or []
            if class_tenants and not (set(class_tenants) & set(ctx.tenants)):
                abort(403, description=f"Classe '{obj_class}' non autorisée pour votre tenant")

        attr_def = None
        if class_def:
            for a in class_def.get("attributes", []):
                if a["name"] == attribute:
                    attr_def = a
                    break

        if attr_def is None:
            abort(400, description=f"Attribut '{attribute}' non déclaré dans le modèle de la classe '{obj_class}'")
        # "csv" inclus ici bien que plan-mark3.md action 3 ne mentionne
        # explicitement que "file"/"image" dans le texte de ce garde-fou :
        # le JSON générique (write_object/write_attribute_value) rejette
        # désormais aussi "csv" (cf. routes_write.py), donc cette route
        # multipart est le SEUL chemin d'écriture possible pour csv -
        # l'exclure ici rendrait le type inutilisable en pratique.
        if attr_def.get("type") not in ("file", "image", "csv"):
            abort(400, description=f"Attribut '{attribute}' n'est pas de type 'file'/'image'/'csv' (type déclaré : {attr_def.get('type')!r})")

        content = upload.read()
        if attr_def["type"] == "image":
            validate_image_content(filename, content)
        elif attr_def["type"] == "csv":
            validate_csv_content(filename, content)

        storage = LocalFileStorage()
        version = save_file_or_400(storage, obj_class, object_id, attribute, filename, content)
        pointer = f"{version}:{filename}"

        with conn.cursor() as cur:
            # Verrou repris ici seulement, juste avant l'écriture SQL finale
            # (même raison que write_attribute_value : FOR NO KEY UPDATE,
            # compatible avec le KEY SHARE pris par une FK joint_id
            # concurrente).
            cur.execute("SELECT deleted_at FROM object WHERE id = %s FOR NO KEY UPDATE", (object_id,))
            locked = cur.fetchone()
            if locked is None or locked[0] is not None:
                # Objet supprimé entre la lecture initiale et ce verrou (race
                # rare) : le fichier déjà écrit ci-dessus ne doit pas rester
                # orphelin, purge best-effort avant de répondre 404.
                storage.delete(obj_class, object_id, attribute, version=version)
                abort(404, description="Objet non trouvé")

            existing_attr = _load_active_attributes_by_name(conn, object_id).get(attribute)
            _apply_attribute_diff(cur, object_id, attribute, attr_def, existing_attr, [pointer])

        conn.commit()
        return jsonify({
            "status": "ok",
            "object_id": object_id,
            "attribute": attribute,
            "version": version,
            "filename": filename,
            "value": pointer,
        }), 200
    except psycopg2.errors.DeadlockDetected:
        conn.rollback()
        abort(409, description="Conflit d'écriture concurrente, réessayez")
    except Exception as e:
        conn.rollback()
        raise e


def _lookup_attr_type(conn, meta_class, cls, attribute):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT data FROM definition WHERE meta_class = %s", (meta_class,))
        defn = cur.fetchone()
    if not defn:
        return None
    for c in defn["data"].get("classes", []):
        if c["class"] == cls:
            for a in c.get("attributes", []):
                if a["name"] == attribute:
                    return a.get("type")
            return None
    return None


def _find_pointer_for_version(conn, object_id, attribute, version):
    """Retrouve le pointeur "<version>:<nom>" d'une version précise d'un
    attribut fichier, qu'elle soit active ou déjà fermée (historique
    toujours conservé, plan-mark2.md action 6.0) - nécessaire car
    `FileStorage.read` a besoin du nom de fichier exact, qui peut différer
    d'une version à l'autre."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT av.value_string FROM attribute a
               JOIN attribute_value av ON av.attribute_id = a.id
               WHERE a.object_id = %s AND a.name = %s AND av.value_string IS NOT NULL""",
            (object_id, attribute),
        )
        rows = cur.fetchall()
    for (value_string,) in rows:
        if ":" not in value_string:
            continue
        version_part, _ = value_string.split(":", 1)
        try:
            if int(version_part) == version:
                return value_string
        except ValueError:
            continue
    return None


@files_bp.route("/api/read/object/<int:object_id>/file/<string:attribute>", methods=["GET"])
def read_object_file(object_id, attribute):
    """Télécharge le contenu d'un attribut `file`/`image`/`csv`. `?version=N`
    optionnel cible une version précise (active ou historique) ; sinon la
    version active est servie. Content-Type déduit de l'extension du nom de
    fichier ; Content-Disposition inline uniquement pour une image
    jpg/jpeg/png (type déclaré `image`), attachment dans tous les autres cas
    - y compris systématiquement pour le svg (décision de sécurité, voir
    docstring de module)."""
    conn = app.get_db()
    tenant_filter = _tenant_read_filter()
    obj = _build_object_payload(object_id, conn, tenant_filter)
    if not obj:
        abort(404, description="Objet non trouvé")

    version_param = request.args.get("version")
    if version_param is None:
        attr_entry = next((a for a in obj["attributes"] if a["name"] == attribute), None)
        if attr_entry is None or not attr_entry["values"]:
            abort(404, description=f"Attribut '{attribute}' introuvable ou sans valeur active")
        pointer = attr_entry["values"][0]
    else:
        try:
            requested_version = int(version_param)
        except ValueError:
            abort(400, description="'version' doit être un entier")
        pointer = _find_pointer_for_version(conn, object_id, attribute, requested_version)
        if pointer is None:
            abort(404, description=f"Version {requested_version} introuvable pour l'attribut '{attribute}'")

    if not isinstance(pointer, str) or ":" not in pointer:
        abort(404, description=f"Attribut '{attribute}' ne porte pas un pointeur fichier valide")

    version_str, filename = pointer.split(":", 1)
    try:
        version = int(version_str)
    except ValueError:
        abort(404, description=f"Pointeur fichier invalide pour l'attribut '{attribute}'")

    storage = LocalFileStorage()
    try:
        content = storage.read(obj["class"], object_id, attribute, version, filename)
    except FileNotFoundError:
        abort(404, description="Fichier introuvable sur le stockage")

    attr_type = _lookup_attr_type(conn, obj["meta_class"], obj["class"], attribute)
    ext = extension_of(filename)
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
    inline = attr_type == "image" and ext in ("jpg", "jpeg", "png")

    # content_type= (pas mimetype=) : évite l'ajout automatique d'un
    # "; charset=utf-8" par Werkzeug pour les mimetypes texte/XML (text/csv,
    # image/svg+xml) - Content-Type attendu exactement tel que déduit de
    # l'extension, sans suffixe.
    response = Response(content, content_type=content_type)
    safe_filename = filename.replace('"', "'")
    response.headers["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{safe_filename}"'
    return response

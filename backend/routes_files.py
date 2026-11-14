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

Extension du format de pointeur (plan-mark3.md action 4, point 3 ;
specifications/07-roadmap.md §10.8) : un logo d'objet peut être une
RÉFÉRENCE vers le fichier déjà stocké d'un AUTRE objet plutôt qu'une
duplication d'octets. Le pointeur stocké dans `value_string` est donc
désormais de l'une de ces deux formes :
- direct (inchangé) : "<version>:<nom_fichier>", résolu dans le dossier de
  l'objet/attribut courant ;
- référence : "ref:<classe>:<object_id>:<attribut>:<version>:<nom_fichier>",
  résolu dans le dossier de l'objet SOURCE désigné. Construit exclusivement
  par POST .../file/<attribute>/reference ci-dessous, toujours APLATI sur
  l'emplacement physique final (jamais une référence vers une autre
  référence - _resolve_physical_location n'a besoin de suivre qu'un seul
  niveau en pratique, la boucle anti-chaîne n'y est qu'une garde
  défensive). `_resolve_physical_location` distingue les deux formes par un
  préfixe "ref:" explicite AVANT de faire le split(":", 1) existant - jamais
  une ambiguïté possible : un nom de fichier direct ne commence jamais par
  "ref:" (préfixe réservé, cf. `_find_pointer_for_version`/
  `read_object_file`, qui doivent reconnaître les deux formes dans
  l'historique).

Garde-fou d'auto-réparation (plan-mark3.md action 4, point 3) : si le
fichier résolu (direct ou via référence) est introuvable sur le storage au
moment de la lecture DE LA VALEUR ACTIVE (pas d'une version historique
explicite via ?version=N, qui peut légitimement avoir été purgée), l'objet
AFFICHÉ voit son attribut fermé côté serveur (`_self_heal_broken_pointer`)
avant de renvoyer 404 - jamais l'objet SOURCE référencé, qui n'est pas en
cause. Évite qu'un pointeur mort reste indéfiniment actif après une
suppression de fichier anormale (hors du chemin de purge sécurisé de
routes_admin.py, qui lui est désormais conscient des références - voir sa
docstring).
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
    """Retrouve le pointeur (direct "<version>:<nom>" OU référence
    "ref:<classe>:<object_id>:<attribut>:<version>:<nom>") d'une version
    précise d'un attribut fichier, qu'elle soit active ou déjà fermée
    (historique toujours conservé, plan-mark2.md action 6.0) - nécessaire car
    `FileStorage.read` a besoin du nom de fichier exact, qui peut différer
    d'une version à l'autre.

    Pour un pointeur "ref:", la "version" comparée est celle encodée dans la
    référence (version de la SOURCE au moment où la référence a été créée),
    pas un compteur local à cet objet/attribut - limite assumée si plusieurs
    valeurs historiques "ref:" de sources différentes partagent par
    coïncidence le même numéro de version source (cas marginal, non
    bloquant : le comportement par défaut sans `?version=N`, qui cible
    toujours la valeur active, n'est jamais affecté)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT av.value_string FROM attribute a
               JOIN attribute_value av ON av.attribute_id = a.id
               WHERE a.object_id = %s AND a.name = %s AND av.value_string IS NOT NULL""",
            (object_id, attribute),
        )
        rows = cur.fetchall()
    for (value_string,) in rows:
        if value_string.startswith("ref:"):
            parts = value_string.split(":", 5)
            if len(parts) != 6:
                continue
            try:
                if int(parts[4]) == version:
                    return value_string
            except ValueError:
                continue
            continue
        if ":" not in value_string:
            continue
        version_part, _ = value_string.split(":", 1)
        try:
            if int(version_part) == version:
                return value_string
        except ValueError:
            continue
    return None


def _resolve_physical_location(class_name, object_id, attribute, pointer):
    """Résout un pointeur (direct ou "ref:", voir docstring de module) vers
    son emplacement physique final sur FileStorage : (class_name, object_id,
    attribute, version, filename). Retourne None si le pointeur est
    syntaxiquement invalide.

    Les références sont toujours aplaties à l'écriture
    (write_object_file_reference ne construit jamais une référence vers une
    autre référence) : une seule résolution suffit en pratique, mais une
    garde anti-boucle est conservée par prudence (ex. donnée historique
    produite par une version future du code qui chaînerait les références)."""
    seen = set()
    cur_class, cur_object_id, cur_attribute, cur_pointer = class_name, object_id, attribute, pointer

    while True:
        if not isinstance(cur_pointer, str):
            return None

        if cur_pointer.startswith("ref:"):
            parts = cur_pointer.split(":", 5)
            if len(parts) != 6:
                return None
            _, ref_class, ref_object_id, ref_attribute, ref_version, ref_filename = parts
            key = (ref_class, ref_object_id, ref_attribute, ref_version)
            if key in seen:
                return None
            seen.add(key)
            try:
                ref_object_id_int = int(ref_object_id)
                ref_version_int = int(ref_version)
            except ValueError:
                return None
            cur_class, cur_object_id, cur_attribute = ref_class, ref_object_id_int, ref_attribute
            cur_pointer = f"{ref_version_int}:{ref_filename}"
            continue

        if ":" not in cur_pointer:
            return None
        version_str, filename = cur_pointer.split(":", 1)
        try:
            version = int(version_str)
        except ValueError:
            return None
        return cur_class, cur_object_id, cur_attribute, version, filename


def _self_heal_broken_pointer(conn, object_id, attribute, failed_pointer):
    """Garde-fou d'auto-réparation (plan-mark3.md action 4, point 3) : ferme
    (valid_to = now()) la valeur active de cet attribut sur l'objet AFFICHÉ
    quand le fichier qu'elle pointe (direct ou via référence) s'avère
    introuvable sur le storage - retour à vide plutôt qu'un pointeur mort
    laissé indéfiniment actif, pour que l'affichage suivant retombe sur le
    fallback normal (icône de classe, puis couleur, §6.4). Commit immédiat :
    appelée juste avant un abort(404), transaction courte et dédiée.

    Filtre sur `value_string = failed_pointer` (correction post-revue, bug 3)
    en plus de `valid_to IS NULL` : sans ce filtre, fermer aveuglément "la"
    valeur active au moment de l'appel fermerait par erreur un nouveau
    pointeur valide si un autre appelant a réécrit cet attribut entre
    l'échec de lecture (FileNotFoundError) et cet appel - fenêtre de course
    étroite mais réelle. Un numéro de version n'est jamais réutilisé
    (monotone par FileStorage), donc matcher le pointeur exact qui a échoué
    élimine la course sans verrou supplémentaire."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE attribute_value av SET valid_to = now()
               FROM attribute a
               WHERE av.attribute_id = a.id AND a.object_id = %s AND a.name = %s
                 AND av.valid_to IS NULL AND av.value_string = %s""",
            (object_id, attribute, failed_pointer),
        )
    conn.commit()


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
    # Garde-fou d'auto-réparation (voir docstring de module) appliqué
    # uniquement à la valeur ACTIVE (pas de version explicite) : un
    # ?version=N historique introuvable est un cas normal (purge légitime
    # passée), pas une raison de fermer la valeur active courante, qui peut
    # être parfaitement saine par ailleurs.
    self_heal_on_missing = version_param is None
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

    resolved = _resolve_physical_location(obj["class"], object_id, attribute, pointer)
    if resolved is None:
        abort(404, description=f"Pointeur fichier invalide pour l'attribut '{attribute}'")
    physical_class, physical_object_id, physical_attribute, version, filename = resolved

    storage = LocalFileStorage()
    try:
        content = storage.read(physical_class, physical_object_id, physical_attribute, version, filename)
    except FileNotFoundError:
        if self_heal_on_missing:
            _self_heal_broken_pointer(conn, object_id, attribute, pointer)
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


@files_bp.route("/api/write/object/<int:object_id>/file/<string:attribute>/reference", methods=["POST"])
def write_object_file_reference(object_id, attribute):
    """Réutilisation d'un fichier déjà stocké pour un AUTRE objet - typiquement
    un logo (plan-mark3.md action 4, point 2/3 ; specifications/07-roadmap.md
    §10.8, décision utilisateur 2026-11-14) : pointe `attribute_value` vers
    le (classe, object_id, attribut, version) de la SOURCE plutôt que de
    dupliquer les octets. Construit un pointeur "ref:..." (voir docstring de
    module), toujours APLATI sur l'emplacement physique final avant d'être
    stocké : si la source désignée est elle-même une référence, elle est
    résolue ICI (_resolve_physical_location), jamais en lecture - une
    référence ne pointe donc jamais vers une autre référence.

    Body JSON attendu : {"class": "...", "object_id": N, "attribute": "...",
    "version": N} - décrit l'objet/attribut/version SOURCE qui porte déjà le
    fichier physique.

    RBAC : mêmes gardes que write_object_file sur l'objet/la classe
    DESTINATION (object_id de l'URL). L'objet SOURCE doit en plus être
    visible par l'appelant (_build_object_payload avec le même filtre
    tenant que les routes de lecture) - sinon un tenant pourrait référencer,
    et donc exposer indirectement via son propre objet, le fichier d'un
    objet qu'il n'a pas le droit de lire.
    """
    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture de fichier interdite")

    body = request.get_json(silent=True) or {}
    required = ("class", "object_id", "attribute", "version")
    if not all(k in body for k in required):
        abort(400, description=f"Champs requis dans le corps JSON : {required}")
    source_class = body["class"]
    source_attribute = body["attribute"]
    if isinstance(body["object_id"], bool) or isinstance(body["version"], bool):
        abort(400, description="'object_id' et 'version' doivent être des entiers")
    try:
        source_object_id = int(body["object_id"])
        source_version = int(body["version"])
    except (TypeError, ValueError):
        abort(400, description="'object_id' et 'version' doivent être des entiers")

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
        if attr_def.get("type") not in ("file", "image", "csv"):
            abort(400, description=f"Attribut '{attribute}' n'est pas de type 'file'/'image'/'csv' (type déclaré : {attr_def.get('type')!r})")

        tenant_filter = _tenant_read_filter()
        source_obj = _build_object_payload(source_object_id, conn, tenant_filter)
        if not source_obj or source_obj["class"] != source_class:
            abort(404, description="Objet source introuvable ou non visible")

        source_pointer = _find_pointer_for_version(conn, source_object_id, source_attribute, source_version)
        if source_pointer is None:
            abort(400, description=f"Version {source_version} introuvable pour l'attribut '{source_attribute}' de l'objet source {source_object_id}")

        resolved = _resolve_physical_location(source_class, source_object_id, source_attribute, source_pointer)
        if resolved is None:
            abort(400, description="Pointeur source invalide")
        physical_class, physical_object_id, physical_attribute, physical_version, filename = resolved

        storage = LocalFileStorage()
        try:
            storage.read(physical_class, physical_object_id, physical_attribute, physical_version, filename)
        except FileNotFoundError:
            abort(400, description="Fichier source introuvable sur le stockage, référence refusée")

        ref_pointer = f"ref:{physical_class}:{physical_object_id}:{physical_attribute}:{physical_version}:{filename}"

        with conn.cursor() as cur:
            # Verrou repris ici seulement, juste avant l'écriture SQL finale
            # (même pattern que write_object_file).
            cur.execute("SELECT deleted_at FROM object WHERE id = %s FOR NO KEY UPDATE", (object_id,))
            locked = cur.fetchone()
            if locked is None or locked[0] is not None:
                abort(404, description="Objet non trouvé")

            existing_attr = _load_active_attributes_by_name(conn, object_id).get(attribute)
            _apply_attribute_diff(cur, object_id, attribute, attr_def, existing_attr, [ref_pointer])

        conn.commit()
        return jsonify({
            "status": "ok",
            "object_id": object_id,
            "attribute": attribute,
            "value": ref_pointer,
        }), 200
    except psycopg2.errors.DeadlockDetected:
        conn.rollback()
        abort(409, description="Conflit d'écriture concurrente, réessayez")
    except Exception as e:
        conn.rollback()
        raise e


@files_bp.route("/api/logos", methods=["GET"])
def list_logos():
    """Liste les logos actuellement actifs, toutes classes « à logo »
    confondues (attribut réservé `logo`, domaine `display`, type `image` -
    convention plan-mark3.md action 4, point 2) - alimente le sélecteur
    frontend de réutilisation d'un logo existant (NavigationPage.tsx), qui
    construit ensuite une référence via write_object_file_reference
    ci-dessus.

    Chaque entrée expose l'emplacement PHYSIQUE déjà aplati (classe/
    object_id/attribut/version du fichier réel sur FileStorage, jamais un
    pointeur "ref:" intermédiaire) : si l'objet qui porte ce logo le fait
    déjà lui-même via une référence croisée, cette liste expose directement
    sa source physique - une nouvelle référence construite à partir d'une
    entrée de cette liste pointe donc toujours sur l'original, jamais sur
    une chaîne de références. `display_name` reste néanmoins celui de
    l'objet PORTEUR (classe/#id), pour que l'utilisateur reconnaisse le
    logo qu'il a vu affiché ailleurs dans l'IHM.

    RBAC : filtré par le même tenant_filter que les routes de lecture
    d'objet (_tenant_read_filter, overlap Postgres) - un objet hors
    périmètre de l'appelant (qu'il soit la source physique ou simplement un
    porteur de référence) ne doit jamais apparaître ici.
    """
    conn = app.get_db()
    tenant_filter = _tenant_read_filter()
    with conn.cursor() as cur:
        if tenant_filter is None:
            cur.execute(
                """SELECT o.id, o.class, av.value_string
                   FROM object o
                   JOIN attribute a ON a.object_id = o.id AND a.name = 'logo'
                   JOIN attribute_value av ON av.attribute_id = a.id AND av.valid_to IS NULL
                   WHERE o.deleted_at IS NULL AND av.value_string IS NOT NULL
                   ORDER BY o.id"""
            )
        else:
            cur.execute(
                """SELECT o.id, o.class, av.value_string
                   FROM object o
                   JOIN attribute a ON a.object_id = o.id AND a.name = 'logo'
                   JOIN attribute_value av ON av.attribute_id = a.id AND av.valid_to IS NULL
                   WHERE o.deleted_at IS NULL AND av.value_string IS NOT NULL
                     AND (o.tenants IS NULL OR o.tenants = '' OR string_to_array(o.tenants, ',') && %s::text[])
                   ORDER BY o.id""",
                (tenant_filter,),
            )
        rows = cur.fetchall()

    storage = LocalFileStorage()
    entries = []
    for carrier_object_id, carrier_class, pointer in rows:
        resolved = _resolve_physical_location(carrier_class, carrier_object_id, "logo", pointer)
        if resolved is None:
            continue
        physical_class, physical_object_id, physical_attribute, version, filename = resolved
        # list_versions (listing de répertoire) plutôt que storage.read
        # (lecture complète du contenu) : vérification d'existence
        # beaucoup moins coûteuse pour un endpoint qui énumère
        # potentiellement de nombreuses entrées.
        if version not in storage.list_versions(physical_class, physical_object_id, physical_attribute):
            continue
        entries.append({
            "class": physical_class,
            "object_id": physical_object_id,
            "attribute": physical_attribute,
            "version": version,
            "filename": filename,
            "display_name": f"{carrier_class} #{carrier_object_id}",
        })
    return jsonify(entries), 200

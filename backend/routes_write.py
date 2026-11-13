import json
import re

import psycopg2
import psycopg2.errors
import psycopg2.extras
import jsonschema
from flask import Blueprint, jsonify, request, abort

import app
from db import load_schema
from rbac import (
    _tenants_list_to_db,
    _tenants_db_to_list,
    _determine_object_tenants,
    _check_class_tenant_write_permission,
    _check_existing_class_tenant_scope,
)
from routes_read import _load_active_attributes_by_name

write_bp = Blueprint("write", __name__)

# ---------------------
# WRITE endpoints
# ---------------------

@write_bp.route("/api/write/object", methods=["POST"])
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

    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture d'objet interdite")

    conn = app.get_db()
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

        if defn is None or class_def is None:
            abort(400, description=f"meta_class {body['meta_class']!r} / class {body['class']!r} non définie")

        # RBAC multi-tenant : un tenant-admin ne peut écrire que dans les
        # classes non taguées (globales) ou taguées pour l'un de ses tenants.
        if ctx.is_tenant_admin:
            class_tenants = (class_def or {}).get("tenants") or []
            if class_tenants and not (set(class_tenants) & set(ctx.tenants)):
                abort(403, description=f"Classe '{body['class']}' non autorisée pour votre tenant")

        object_id = body.get("id")
        existing_by_name = {}

        with conn.cursor() as cur:
            if object_id:
                # UPDATE : vérifier que l'objet existe, sous verrou de ligne.
                # FOR NO KEY UPDATE et non FOR UPDATE : la vérification FK de
                # tout INSERT attribute_value(joint_id) prend un KEY SHARE sur
                # la ligne object cible ; FOR UPDATE le bloque (deadlock si deux
                # objets se référencent en croisé), NO KEY UPDATE le laisse passer
                # tout en sérialisant deux écritures sur le même objet.
                cur.execute("SELECT id, tenants, deleted_at FROM object WHERE id = %s FOR NO KEY UPDATE", (object_id,))
                existing = cur.fetchone()
                if not existing:
                    abort(404, description=f"Objet {object_id} non trouvé")
                if existing[2] is not None:
                    abort(404, description=f"Objet {object_id} non trouvé")
                existing_tenants = _tenants_db_to_list(existing[1])

                if ctx.is_tenant_admin and existing_tenants and not (set(existing_tenants) & set(ctx.tenants)):
                    abort(403, description="Objet hors de votre périmètre tenant")

                object_tenants = _determine_object_tenants(ctx, body, existing_tenants)

                # Mettre à jour meta_class, class et tenants
                cur.execute(
                    "UPDATE object SET meta_class = %s, class = %s, tenants = %s WHERE id = %s",
                    (body["meta_class"], body["class"], _tenants_list_to_db(object_tenants), object_id)
                )

                # Historisation (plan-mark2.md action 6.0) : plus de
                # delete-then-recreate. L'état actif actuel est chargé pour
                # être diffé, attribut par attribut, contre le corps de la
                # requête (voir _apply_attribute_diff) - une valeur active
                # retrouvée telle quelle dans la requête n'est jamais
                # touchée (ni fermée ni réinsérée), seules les valeurs
                # effectivement différentes sont historisées.
                existing_by_name = _load_active_attributes_by_name(conn, object_id)
            else:
                # CREATE
                object_tenants = _determine_object_tenants(ctx, body, None)
                cur.execute(
                    "INSERT INTO object (meta_class, class, tenants) VALUES (%s, %s, %s) RETURNING id",
                    (body["meta_class"], body["class"], _tenants_list_to_db(object_tenants))
                )
                object_id = cur.fetchone()[0]

            attrs = body.get("attributes", {})
            seen_attr_names = set()
            for attr_name, attr_value in attrs.items():
                seen_attr_names.add(attr_name)

                # Trouver la définition de l'attribut dans le modèle de la classe
                attr_def = None
                for a in class_def.get("attributes", []):
                    if a["name"] == attr_name:
                        attr_def = a
                        break

                if attr_def is None:
                    abort(400, description=f"Attribut {attr_name!r} non déclaré dans le modèle de la classe {body['class']!r}")

                received_values = attr_value if isinstance(attr_value, list) else [attr_value]
                _apply_attribute_diff(
                    cur, object_id, attr_name, attr_def,
                    existing_by_name.get(attr_name), received_values
                )

            # Attribut actif entier non repassé dans le corps de la requête
            # (sémantique « remplacement complet », specifications.md §4.3) :
            # fermeture de toutes ses valeurs actives, sans nouvelle
            # insertion - l'attribut devient fermé, plus de version active.
            for attr_name, existing_attr in existing_by_name.items():
                if attr_name in seen_attr_names:
                    continue
                for ev in existing_attr["values"]:
                    cur.execute("UPDATE attribute_value SET valid_to = now() WHERE id = %s", (ev["id"],))

        conn.commit()
        action = "updated" if body.get("id") else "created"
        return jsonify({"status": "ok", "id": object_id, "action": action, "tenants": object_tenants}), 200 if action == "updated" else 201
    except psycopg2.errors.DeadlockDetected:
        conn.rollback()
        abort(409, description="Conflit d'écriture concurrente, réessayez")
    except Exception as e:
        conn.rollback()
        raise e


def _coerce_typed_value(attr_def, raw_value):
    """Valide et convertit une valeur brute selon le type déclaré de
    l'attribut dans le modèle (attr_def["type"]), jamais par une devinette
    sur la valeur reçue. Retourne (colonne_de_stockage, valeur_convertie),
    sans toucher à la base - seul point de typage du diff d'historisation
    (_apply_attribute_diff, action 6.0), qui compare une valeur reçue à une
    valeur active existante sur exactement les mêmes critères que ceux
    appliqués à l'écriture.
    """
    attr_type = attr_def.get("type")
    attr_name = attr_def.get("name")

    if attr_type in ("joint-1-1", "joint-1-n"):
        if not (isinstance(raw_value, dict) and "joint_id" in raw_value):
            abort(400, description=f"Attribut {attr_name!r} (type {attr_type}) : valeur attendue de la forme {{'joint_id': <id>}}")
        # int() obligatoire : la valeur active relue depuis joint_id (INTEGER)
        # est un int, un "5" reçu en JSON ne matcherait jamais 5 dans le diff
        # (fermeture + réinsertion à tort) et la FK recevrait une chaîne.
        joint_id = raw_value["joint_id"]
        if isinstance(joint_id, bool):
            abort(400, description=f"Attribut {attr_name!r} (type {attr_type}) : joint_id entier attendu : {joint_id!r}")
        if isinstance(joint_id, float) and not joint_id.is_integer():
            abort(400, description=f"Attribut {attr_name!r} (type {attr_type}) : joint_id entier attendu : {joint_id!r}")
        try:
            return "joint_id", int(joint_id)
        except (TypeError, ValueError):
            abort(400, description=f"Attribut {attr_name!r} (type {attr_type}) : joint_id entier attendu : {joint_id!r}")

    if attr_type == "integer":
        try:
            return "value_integer", int(raw_value)
        except (TypeError, ValueError):
            abort(400, description=f"Valeur invalide pour l'attribut {attr_name!r} (entier attendu) : {raw_value!r}")

    if attr_type in ("float", "number"):
        try:
            return "value_float", float(raw_value)
        except (TypeError, ValueError):
            abort(400, description=f"Valeur invalide pour l'attribut {attr_name!r} (nombre attendu) : {raw_value!r}")

    # "string" (et tout type non reconnu, par sécurité) : toujours
    # value_string, jamais de tentative int()/float() même si la valeur a
    # l'air numérique (ex. code postal "007" doit rester "007").
    #
    # Validation de la "constraint" (regex) factorisée ici plutôt que dans
    # write_object uniquement, pour qu'elle s'applique aussi à
    # write_attribute_value (édition inline) : _coerce_typed_value ne
    # traite jamais qu'une valeur scalaire à la fois (write_object itère
    # déjà par élément pour un attribut multi-valué), donc un simple
    # re.fullmatch par appel suffit à couvrir les deux cas d'usage.
    if attr_type == "string" and attr_def.get("constraint"):
        try:
            matches = re.fullmatch(attr_def["constraint"], str(raw_value))
        except re.error as e:
            abort(400, description=f"Regex 'constraint' invalide dans le modèle pour l'attribut {attr_name!r} : {e}")
        if not matches:
            abort(400, description=f"Valeur invalide pour l'attribut {attr_name!r}: {raw_value!r}")
    return "value_string", str(raw_value)


def _apply_attribute_diff(cur, object_id, attr_name, attr_def, existing_attr, received_values):
    """Historisation (plan-mark2.md action 6.0) : applique le diff entre
    l'état actif d'UN attribut (existing_attr, entrée de
    _load_active_attributes_by_name ou None si l'attribut n'existe pas
    encore sur l'objet) et la liste des valeurs brutes reçues pour cet
    attribut. Seul chemin d'écriture d'attribute_value du module, partagé
    par write_object et write_attribute_value :

    - la ligne `attribute` existante est réutilisée (jamais de doublon,
      garanti aussi par UNIQUE (object_id, name)), son domaine réaligné
      sur le modèle si celui-ci a évolué ; sinon elle est créée ;
    - valeur reçue identique (même colonne de stockage ET même contenu)
      à une valeur active : continuité historique, ni UPDATE ni INSERT ;
    - valeur active non retrouvée parmi les valeurs reçues : fermée
      (valid_to = now()), jamais supprimée ;
    - valeur reçue sans correspondance active : nouvelle version
      (valid_from = now(), valid_to NULL).

    Attend un curseur tuple (conn.cursor() sans factory) ; l'appelant doit
    détenir le verrou FOR NO KEY UPDATE sur la ligne `object`. Retourne
    attribute_id.
    """
    if existing_attr is not None:
        attribute_id = existing_attr["attribute_id"]
        remaining_existing = list(existing_attr["values"])
        if existing_attr["domain"] != attr_def["domain"]:
            cur.execute("UPDATE attribute SET domain = %s WHERE id = %s", (attr_def["domain"], attribute_id))
    else:
        cur.execute(
            "INSERT INTO attribute (object_id, domain, name) VALUES (%s, %s, %s) RETURNING id",
            (object_id, attr_def["domain"], attr_name)
        )
        attribute_id = cur.fetchone()[0]
        remaining_existing = []

    received_coerced = [_coerce_typed_value(attr_def, v) for v in received_values]

    to_insert = []
    for column, value in received_coerced:
        match_index = next(
            (i for i, ev in enumerate(remaining_existing)
             if ev["column"] == column and ev["value"] == value),
            None
        )
        if match_index is not None:
            remaining_existing.pop(match_index)
        else:
            to_insert.append((column, value))

    for ev in remaining_existing:
        cur.execute("UPDATE attribute_value SET valid_to = now() WHERE id = %s", (ev["id"],))

    for column, value in to_insert:
        if column == "joint_id":
            # Garde-fou (plan-mark2.md action 6.1) : interdit de créer une
            # nouvelle jointure vers un objet déjà soft-deleted (état
            # "zombie" sinon possible). FOR SHARE sur la même ligne object
            # que celle verrouillée en FOR UPDATE par la suppression logique
            # (DELETE /api/delete/object) : les deux s'excluent mutuellement
            # le temps de la transaction. Un deadlock PostgreSQL reste
            # possible ici (rare) : si cet appel ferme par ailleurs un lien
            # existant (UPDATE attribute_value sur une ligne R) pendant
            # qu'une suppression logique concurrente de l'objet cible tient
            # déjà B (FOR UPDATE) et tente à son tour de fermer cette même
            # ligne R en cascade, les deux transactions s'attendent
            # mutuellement (R puis B d'un côté, B puis R de l'autre).
            # PostgreSQL détecte ce cycle et annule automatiquement l'une
            # des deux transactions (DeadlockDetected) : pas de corruption
            # ni de hang, voir le except dédié de write_object/
            # write_attribute_value/delete_object qui renvoie 409.
            cur.execute("SELECT deleted_at FROM object WHERE id = %s FOR SHARE", (value,))
            target = cur.fetchone()
            if target is None or target[0] is not None:
                abort(400, description=f"Objet cible {value} inexistant ou déjà supprimé")
        cur.execute(
            f"INSERT INTO attribute_value (attribute_id, {column}) VALUES (%s, %s)",
            (attribute_id, value)
        )

    return attribute_id


@write_bp.route("/api/write/attribute/<string:cls>/<int:object_id>/<string:attribute>/<string:value>", methods=["PUT"])
def write_attribute_value(cls, object_id, attribute, value):
    """Écrit ou met à jour la valeur d'un attribut d'un objet.

    URL: /api/write/attribute/<class>/<id>/<attribute>/<value>

    Historisée exactement comme write_object (même _apply_attribute_diff),
    sur un seul attribut à la fois : jamais de DELETE sur attribute_value,
    les versions déjà fermées sont conservées. La valeur de l'URL est passée
    comme liste à un seul élément : sur un attribut multi-valué ayant
    plusieurs valeurs actives, toutes les valeurs sœurs différentes sont
    fermées (valid_to = now()) et il ne reste qu'une seule valeur active
    (comportement hérité de l'ancien DELETE ; l'édition inline du frontend
    n'envoie que values[0]). Une valeur identique à une valeur active est
    conservée sans nouvelle ligne.
    """
    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture d'attribut interdite")

    conn = app.get_db()
    try:
        with conn.cursor() as cur:
            # Verrou de ligne pris avant tout chargement d'état actif : deux
            # PUT concurrents sur le même attribut se sérialisent ici, sinon
            # chacun fermerait/insérerait à partir du même état et laisserait
            # deux valeurs actives. FOR NO KEY UPDATE (pas FOR UPDATE) : reste
            # compatible avec le KEY SHARE que la FK joint_id prend sur cet
            # objet quand une autre transaction y insère une jointure (sinon
            # attente, et deadlock si les écritures se croisent A->B / B->A).
            cur.execute("SELECT id, class, meta_class, tenants, deleted_at FROM object WHERE id = %s FOR NO KEY UPDATE", (object_id,))
            obj = cur.fetchone()

            if not obj:
                abort(404, description="Objet non trouvé")
            _, obj_class, obj_meta_class, obj_tenants_raw, obj_deleted_at = obj
            if obj_deleted_at is not None:
                abort(404, description="Objet non trouvé")
            if obj_class != cls:
                abort(400, description=f"L'objet {object_id} n'est pas de classe '{cls}'")

            # Résolution du modèle (classe -> attr_def), nécessaire dans tous
            # les cas (RBAC tenant-admin ET typage/Option B ci-dessous), donc
            # faite une seule fois ici plutôt que dupliquée comme auparavant.
            cur.execute("SELECT data FROM definition WHERE meta_class = %s", (obj_meta_class,))
            defn = cur.fetchone()
            class_def = None
            if defn:
                for c in defn[0].get("classes", []):
                    if c["class"] == cls:
                        class_def = c
                        break

            if ctx.is_tenant_admin:
                obj_tenants = _tenants_db_to_list(obj_tenants_raw)
                if obj_tenants and not (set(obj_tenants) & set(ctx.tenants)):
                    abort(403, description="Objet hors de votre périmètre tenant")
                class_tenants = (class_def or {}).get("tenants") or []
                if class_tenants and not (set(class_tenants) & set(ctx.tenants)):
                    abort(403, description=f"Classe '{cls}' non autorisée pour votre tenant")

            attr_def = None
            if class_def:
                for a in class_def.get("attributes", []):
                    if a["name"] == attribute:
                        attr_def = a
                        break

            if attr_def is None:
                abort(400, description=f"Attribut '{attribute}' non déclaré dans le modèle de la classe '{cls}'")

            existing_attr = _load_active_attributes_by_name(conn, object_id).get(attribute)
            _apply_attribute_diff(cur, object_id, attribute, attr_def, existing_attr, [value])

        conn.commit()
        return jsonify({"status": "ok", "object_id": object_id, "attribute": attribute, "value": value})
    except psycopg2.errors.DeadlockDetected:
        conn.rollback()
        abort(409, description="Conflit d'écriture concurrente, réessayez")
    except Exception as e:
        conn.rollback()
        raise e


@write_bp.route("/api/delete/object/<int:object_id>", methods=["DELETE"])
def delete_object(object_id):
    """Suppression logique d'un objet (plan-mark2.md action 6.1).

    RBAC (hérité de Mark 1 §11.2, même logique que write_object) :
    tenant-readonly -> 403 systématique ; tenant-admin -> 403 si l'objet est
    hors de son périmètre tenant ; global-admin -> toujours autorisé.

    FOR UPDATE (et non FOR NO KEY UPDATE comme ailleurs dans ce module) :
    verrou exclusif volontaire sur la ligne `object`, pour bloquer toute
    insertion concurrente d'une jointure vers cet objet (qui prend un FOR
    SHARE, voir le garde-fou de _apply_attribute_diff) pendant la
    suppression. Un deadlock PostgreSQL reste possible (rare, cf. le
    commentaire du garde-fou dans _apply_attribute_diff) : ce même appel
    ferme en cascade des attribute_value (joint_id = cet objet) pendant
    qu'un write_object/write_attribute_value concurrent peut tenir l'une de
    ces lignes (fermeture d'un autre lien) en attendant FOR SHARE sur cette
    même ligne `object`. PostgreSQL détecte le cycle et annule
    automatiquement l'une des deux transactions - pas de corruption, pas de
    hang - rattrapé ci-dessous par un except dédié (409).

    Cascade sur les jointures entrantes, scopée au périmètre tenant de
    l'acteur (voir plan-mark2.md action 6.1 pour la brèche RBAC évitée par
    ce scoping) : fermeture (valid_to = now()) des attribute_value dont le
    joint_id pointe vers cet objet, restreinte aux objets sources du
    périmètre tenant de l'acteur pour un tenant-admin, sans restriction pour
    un global-admin.
    """
    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : suppression d'objet interdite")

    conn = app.get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, deleted_at, tenants FROM object WHERE id = %s FOR UPDATE", (object_id,))
            existing = cur.fetchone()
            if not existing:
                abort(404, description=f"Objet {object_id} non trouvé")
            _, deleted_at, tenants_raw = existing
            if deleted_at is not None:
                abort(404, description=f"Objet {object_id} non trouvé")

            existing_tenants = _tenants_db_to_list(tenants_raw)
            if ctx.is_tenant_admin and existing_tenants and not (set(existing_tenants) & set(ctx.tenants)):
                abort(403, description="Objet hors de votre périmètre tenant")

            cur.execute("UPDATE object SET deleted_at = now() WHERE id = %s RETURNING deleted_at", (object_id,))
            (deleted_at,) = cur.fetchone()

            cur.execute(
                """UPDATE attribute_value SET valid_to = now()
                   WHERE valid_to IS NULL AND attribute_id IN
                       (SELECT id FROM attribute WHERE object_id = %s)""",
                (object_id,)
            )

            if ctx.is_global_admin:
                cur.execute(
                    "UPDATE attribute_value SET valid_to = now() WHERE joint_id = %s AND valid_to IS NULL",
                    (object_id,)
                )
            else:
                cur.execute(
                    """UPDATE attribute_value av
                       SET valid_to = now()
                       FROM attribute a, object o
                       WHERE av.attribute_id = a.id AND a.object_id = o.id
                         AND av.joint_id = %s AND av.valid_to IS NULL
                         AND (o.tenants IS NULL OR o.tenants = '' OR string_to_array(o.tenants, ',') && %s::text[])""",
                    (object_id, ctx.tenants)
                )

        conn.commit()
        return jsonify({"status": "ok", "id": object_id, "deleted_at": deleted_at.isoformat()}), 200
    except psycopg2.errors.DeadlockDetected:
        conn.rollback()
        abort(409, description="Conflit d'écriture concurrente, réessayez")
    except Exception as e:
        conn.rollback()
        raise e


@write_bp.route("/api/write/class", methods=["POST"])
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

    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture de schéma interdite")

    conn = app.get_db()
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
                # Un tenant-admin ne peut remplacer que des classes déjà
                # dans son périmètre (évite d'écraser une classe globale ou
                # d'un autre tenant via un simple remplacement par nom).
                _check_existing_class_tenant_scope(ctx, cls)
                classes[i] = new_class
                replaced = True
                break
        _check_class_tenant_write_permission(ctx, new_class)
        if not replaced:
            classes.append(new_class)

        data["classes"] = classes

        try:
            jsonschema.validate(instance=data, schema=load_schema())
        except jsonschema.ValidationError as e:
            abort(400, description=str(e))

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


@write_bp.route("/api/write/metaclass", methods=["POST"])
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

    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture de schéma interdite")

    meta_class_name = body["meta_class"]
    data = {"meta_class": meta_class_name, "classes": body["classes"]}

    conn = app.get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: # RealDictCursor pour la lecture
            cur.execute(
                "SELECT id, data FROM definition WHERE meta_class = %s",
                (meta_class_name,)
            )
            existing = cur.fetchone()

        # Un tenant-admin ne peut remplacer une meta-classe entière que si
        # toutes les classes déjà existantes y restent dans son périmètre
        # (sinon un remplacement complet pourrait effacer les classes d'un
        # autre tenant ou globales) ; chaque classe du nouveau contenu est
        # vérifiée/tagué par défaut selon la même règle que write_class.
        # Gardes RBAC fines exécutées avant la validation de schéma JSON
        # ci-dessous, même ordre que write_class (403 avant 400 pour un
        # appelant hors de son périmètre tenant, même si le schéma soumis
        # est par ailleurs invalide).
        if existing:
            for existing_cls in existing["data"].get("classes", []):
                _check_existing_class_tenant_scope(ctx, existing_cls)
        for cls in data["classes"]:
            _check_class_tenant_write_permission(ctx, cls)

        try:
            jsonschema.validate(instance=data, schema=load_schema())
        except jsonschema.ValidationError as e:
            abort(400, description=str(e))

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

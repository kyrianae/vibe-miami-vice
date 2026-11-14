import json

import psycopg2.errors
import psycopg2.extras
from flask import Blueprint, jsonify, request, abort

import app
from file_storage import LocalFileStorage
from rbac import _check_existing_class_tenant_scope

admin_bp = Blueprint("admin", __name__)

# ---------------------
# Purge physique différée (plan-mark2.md action 6.2)
# ---------------------

@admin_bp.route("/api/config/purge_grace_period_days", methods=["GET"])
def get_purge_grace_period_days():
    """Lit la période de grâce (en jours) avant purge physique. Réservé
    strictement à global-admin (même pas tenant-admin) : paramètre qui
    affecte tous les tenants, cf. plan-mark2.md action 6.2."""
    ctx = app.get_auth_context()
    if not ctx.is_global_admin:
        abort(403, description="Réservé à global-admin")

    with app.get_db().cursor() as cur:
        cur.execute("SELECT value FROM app_config WHERE key = 'purge_grace_period_days'")
        row = cur.fetchone()
    if row is None:
        abort(500, description="Paramètre 'purge_grace_period_days' absent de app_config")
    return jsonify({"value": int(row[0])})


@admin_bp.route("/api/config/purge_grace_period_days", methods=["PUT"])
def set_purge_grace_period_days():
    """Modifie la période de grâce avant purge physique. Réservé strictement
    à global-admin. Body {"value": N}, N entier strictement positif (400
    sinon - en particulier 0 et les négatifs, qui purgeraient immédiatement
    ou jamais). bool explicitement rejeté avant le cast int() (même piège
    que joint_id, cf. _coerce_typed_value) : un bool Python est une
    sous-classe de int, int(True) == 1 serait accepté silencieusement."""
    ctx = app.get_auth_context()
    if not ctx.is_global_admin:
        abort(403, description="Réservé à global-admin")

    body = request.get_json()
    if not body or "value" not in body:
        abort(400, description="Champ 'value' requis")

    raw_value = body["value"]
    if isinstance(raw_value, bool):
        abort(400, description=f"'value' doit être un entier strictement positif : {raw_value!r}")
    if isinstance(raw_value, float) and not raw_value.is_integer():
        abort(400, description=f"'value' doit être un entier strictement positif : {raw_value!r}")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        abort(400, description=f"'value' doit être un entier strictement positif : {raw_value!r}")
    if value <= 0:
        abort(400, description=f"'value' doit être un entier strictement positif : {raw_value!r}")

    conn = app.get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE app_config SET value = %s WHERE key = 'purge_grace_period_days'",
                (str(value),)
            )
        conn.commit()
        return jsonify({"status": "ok", "value": value})
    except Exception as e:
        conn.rollback()
        raise e


@admin_bp.route("/api/purge", methods=["POST"])
def purge_objects():
    """Purge physique différée (plan-mark2.md action 6.2).

    Supprime définitivement les objets soft-deleted (object.deleted_at non
    NULL) depuis plus longtemps que la période de grâce configurable
    (app_config.purge_grace_period_days), relue en base à CHAQUE appel -
    jamais une constante Python chargée une fois au démarrage, pour qu'un
    changement administrateur soit pris en compte sans redémarrage.

    Réservé strictement à global-admin (opération qui traverse tous les
    tenants, pas de scoping tenant-admin possible ici).

    Ordre impératif, même transaction (plan-mark2.md action 6.2, conception
    actée) : purge inconditionnelle de TOUTES les attribute_value.joint_id
    référençant un objet candidat (actives ou déjà fermées) AVANT le DELETE
    FROM object. Exécuté en deux requêtes séparées (pas un seul WITH
    multi-CTE) : PostgreSQL ne garantit pas d'ordre d'exécution entre
    plusieurs sous-requêtes de modification d'un même WITH sans dépendance
    de données explicite entre elles - seule une séquence de deux
    instructions dans la même transaction garantit cet ordre strict. Sans
    cette garde, une ligne attribute_value déjà historiquement fermée mais
    oubliée verrait son joint_id mis à NULL par le FK ON DELETE SET NULL au
    moment du DELETE FROM object, violant la contrainte CHECK (piège déjà
    rencontré et corrigé en Mark 1 action 6)."""
    ctx = app.get_auth_context()
    if not ctx.is_global_admin:
        abort(403, description="Réservé à global-admin")

    conn = app.get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM app_config WHERE key = 'purge_grace_period_days'")
            row = cur.fetchone()
            if row is None:
                abort(500, description="Paramètre 'purge_grace_period_days' absent de app_config")
            grace_days = int(row[0])

            cur.execute(
                """
                WITH candidates AS (
                    SELECT id FROM object
                    WHERE deleted_at IS NOT NULL
                      AND deleted_at < now() - make_interval(days => %s::integer)
                )
                DELETE FROM attribute_value WHERE joint_id IN (SELECT id FROM candidates)
                """,
                (grace_days,)
            )

            cur.execute(
                """
                WITH candidates AS (
                    SELECT id FROM object
                    WHERE deleted_at IS NOT NULL
                      AND deleted_at < now() - make_interval(days => %s::integer)
                )
                DELETE FROM object WHERE id IN (SELECT id FROM candidates)
                """,
                (grace_days,)
            )
            purged = cur.rowcount

        conn.commit()
        return jsonify({"status": "ok", "purged": purged}), 200
    except psycopg2.errors.DeadlockDetected:
        conn.rollback()
        abort(409, description="Conflit d'écriture concurrente, réessayez")
    except Exception as e:
        conn.rollback()
        raise e


# ---------------------
# Sweep des fichiers orphelins du stockage (plan-mark3.md action 3, point B
# de la revue croisée).
# ---------------------

@admin_bp.route("/api/admin/sweep_orphan_files", methods=["POST"])
def sweep_orphan_files():
    """Purge les fichiers présents sur FileStorage mais jamais indexés par
    une ligne `attribute_value` (plan-mark3.md action 3, point B).

    Scénario visé : un fichier écrit sur disque (`FileStorage.save`) sans
    que la transaction Postgres qui devait l'indexer n'ait jamais commité -
    ex. crash du process entre l'écriture et le commit dans
    `_write_object_multipart`/`write_object_file`, cas que le nettoyage
    best-effort de ces routes (`_cleanup_saved_files`, except déjà exécuté)
    ne couvre pas s'il n'a pas eu l'occasion de s'exécuter. Complète ce
    nettoyage au niveau requête, ne le remplace pas.

    Un fichier est conservé dès qu'il existe AU MOINS UNE ligne
    attribute_value dont le pointeur correspond, qu'elle soit active ou
    déjà fermée (historisée) - cohérent avec la purge physique différée
    (plan-mark2.md action 6.2, fenêtre de grâce) : tant qu'une version
    historique n'a pas été physiquement supprimée de la base, le fichier
    qu'elle référence doit rester disponible en lecture (`?version=N`).

    Énumération du contenu du stockage via `FileStorage.list_all()` (ajouté
    pour ce sweep, coûteux - parcours complet de l'arborescence disque,
    jamais utilisé par le chemin d'écriture/lecture normal). Correspondance
    vérifiée par triplet exact (object_id, nom d'attribut, pointeur
    "<version>:<nom_fichier>"), indépendamment de la classe actuelle de
    l'objet en base - un objet dont la classe a été changée après l'upload
    (via write_object) garde ses fichiers historiques valides même si leur
    chemin disque porte l'ancienne classe.

    RBAC : réservé à global-admin, même garde que /api/purge (opération de
    maintenance traversant tous les tenants, sans scoping tenant-admin
    possible)."""
    ctx = app.get_auth_context()
    if not ctx.is_global_admin:
        abort(403, description="Réservé à global-admin")

    conn = app.get_db()
    storage = LocalFileStorage()
    on_disk = storage.list_all()

    purged = []
    with conn.cursor() as cur:
        # Dette assumée (revue croisée action 3, point 2) : une requête SQL par
        # fichier scanné, sans commit intermédiaire - sur un volume important
        # (dizaines de milliers de fichiers) peut créer une transaction
        # idle-in-transaction longue côté Postgres. Acceptable au volume actuel
        # (Mark 3) ; à traiter (requête groupée, ou commits par lot/chunking)
        # avant d'exposer cet endpoint sur un volume important.
        for class_name, object_id, attribute_name, version, filename in on_disk:
            pointer = f"{version}:{filename}"
            cur.execute(
                """SELECT 1 FROM attribute a
                   JOIN attribute_value av ON av.attribute_id = a.id
                   WHERE a.object_id = %s AND a.name = %s AND av.value_string = %s
                   LIMIT 1""",
                (object_id, attribute_name, pointer),
            )
            if cur.fetchone() is not None:
                continue
            storage.delete(class_name, object_id, attribute_name, version=version)
            purged.append({
                "class": class_name, "object_id": object_id,
                "attribute": attribute_name, "version": version, "filename": filename,
            })

    return jsonify({"status": "ok", "purged_count": len(purged), "purged": purged}), 200


@admin_bp.route("/api/delete/class/<string:meta_class>/<string:cls>", methods=["DELETE"])
def delete_class(meta_class, cls):
    """Suppression physique d'une classe dans le schéma (plan-mark2.md
    action 6.3).

    Ne supprime ni ne modifie les objets déjà créés sous cette classe :
    aucune FK entre `object` et `definition` (§3.4 du plan), c'est une
    pure purge du schéma, pas une opération dangereuse pour les données
    `object` existantes.

    RBAC (hérité de Mark 1 action 11, même garde que write_class) :
    tenant-readonly -> 403 systématique ; réservé sinon à global-admin/
    tenant-admin, avec un tenant-admin restreint à ses propres classes
    (_check_existing_class_tenant_scope, même pattern que le remplacement
    d'une classe existante dans write_class).
    """
    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : suppression de schéma interdite")

    conn = app.get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # FOR UPDATE (même pattern que delete_object) : verrouille la ligne
            # `definition` dès la lecture, avant la vérification RBAC et jusqu'au
            # commit, pour empêcher un write_metaclass concurrent d'ajouter une
            # classe hors périmètre tenant qui échapperait à la garde ci-dessous.
            cur.execute(
                "SELECT id, data FROM definition WHERE meta_class = %s FOR UPDATE",
                (meta_class,)
            )
            row = cur.fetchone()

        if not row:
            abort(404, description=f"Meta-classe '{meta_class}' non trouvée")

        data = row["data"]
        classes = data.get("classes", [])
        target = None
        remaining = []
        for existing_cls in classes:
            if existing_cls["class"] == cls and target is None:
                target = existing_cls
            else:
                remaining.append(existing_cls)

        if target is None:
            abort(404, description=f"Classe '{cls}' non trouvée dans la meta-classe '{meta_class}'")

        _check_existing_class_tenant_scope(ctx, target)

        data["classes"] = remaining

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE definition SET data = %s WHERE id = %s",
                (json.dumps(data), row["id"])
            )
        conn.commit()

        return jsonify({"status": "ok", "class": cls}), 200
    except Exception as e:
        conn.rollback()
        raise e


@admin_bp.route("/api/delete/metaclass/<string:meta_class>", methods=["DELETE"])
def delete_metaclass(meta_class):
    """Suppression physique d'une meta-classe entière du schéma
    (plan-mark2.md action 6.4).

    Ne supprime pas les objets déjà créés sous cette meta-classe : aucune
    FK entre `object` et `definition` (§3.4 du plan), c'est une pure purge
    du schéma.

    RBAC : suppression physique d'une meta-classe entière est au moins
    aussi sensible qu'un remplacement complet (write_metaclass, 6.3) - un
    tenant-admin ne doit pas pouvoir supprimer une meta-classe contenant
    une classe hors de son périmètre tenant (autre tenant ou globale),
    alors qu'il ne pourrait même pas la remplacer. Même garde que
    write_metaclass/delete_class (_check_existing_class_tenant_scope),
    appliquée à chaque classe existante de la meta-classe ciblée. Ne fait
    rien pour global-admin (aucune restriction, comme partout ailleurs).
    """
    ctx = app.get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : suppression de schéma interdite")

    conn = app.get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # FOR UPDATE (même pattern que delete_object) : verrouille la ligne
            # `definition` dès la lecture, avant la vérification RBAC et jusqu'au
            # commit, pour empêcher un write_metaclass concurrent d'ajouter une
            # classe hors périmètre tenant qui échapperait à la garde ci-dessous.
            cur.execute(
                "SELECT id, data FROM definition WHERE meta_class = %s FOR UPDATE",
                (meta_class,)
            )
            row = cur.fetchone()

        if not row:
            abort(404, description=f"Meta-classe '{meta_class}' non trouvée")

        for existing_cls in row["data"].get("classes", []):
            _check_existing_class_tenant_scope(ctx, existing_cls)

        with conn.cursor() as cur:
            cur.execute("DELETE FROM definition WHERE meta_class = %s", (meta_class,))
        conn.commit()

        return jsonify({"status": "ok", "meta_class": meta_class}), 200
    except Exception as e:
        conn.rollback()
        raise e

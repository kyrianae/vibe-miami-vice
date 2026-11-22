from flask import abort, g

# ---------------------
# RBAC multi-tenant (action 11) — à partir des rôles realm_access.roles et de
# la claim "tenants" (liste de noms de groupes Keycloak sans le '/' préfixe,
# cf. mapper "oidc-group-membership-mapper" avec full.path=false sur le
# client miami-vice-direct, voir keycloak/miami-vice-realm.json) extraits du
# JWT déjà validé ci-dessus par before_request.
#
# ATTENTION, point de vigilance (rappel, déjà noté plus haut au sujet de
# l'authentification) : ces rôles/groupes Keycloak (global-admin,
# tenant-admin, tenant-readonly, tenants) ne servent qu'à l'autorisation
# d'accès à cette API. Ils n'ont AUCUN rapport avec les classes métier
# "role"/"groupe" du modèle applicatif (model/personnes.json), qui sont des
# objets métier ordinaires éditables via /api/write/object.
# ---------------------

ROLE_GLOBAL_ADMIN = "global-admin"
ROLE_TENANT_ADMIN = "tenant-admin"
ROLE_TENANT_READONLY = "tenant-readonly"
_RBAC_ROLES = {ROLE_GLOBAL_ADMIN, ROLE_TENANT_ADMIN, ROLE_TENANT_READONLY}

# Sentinelle distincte de None, pour distinguer "clé 'tenants' absente du
# corps de la requête" (-> ne pas toucher au tag existant, cf. correction
# bloquante 2 de plan.md action 11.2) de "clé 'tenants' présente avec la
# valeur null/liste vide" (-> vouloir explicitement l'absence de tag).
_UNSET = object()


class AuthContext:
    """Contexte d'autorisation RBAC multi-tenant pour la requête courante."""

    __slots__ = ("is_global_admin", "is_tenant_admin", "is_tenant_readonly", "tenants")

    def __init__(self, is_global_admin, is_tenant_admin, is_tenant_readonly, tenants):
        self.is_global_admin = is_global_admin
        self.is_tenant_admin = is_tenant_admin
        self.is_tenant_readonly = is_tenant_readonly
        self.tenants = tenants


def get_auth_context():
    """Construit l'AuthContext de la requête courante à partir de g.auth_claims
    (absent si lecture anonyme ou token non protégé non fourni/invalide).

    Correctif bloquant (plan.md action 11.2, correction 1, 2026-11-09,
    remplace le choix "fail-open" du premier passage) : un appelant sans
    aucun des 3 rôles RBAC reconnus (anonyme, token absent/invalide, ou JWT
    sans role RBAC connu) n'obtient plus aucun droit étendu. Il est traité
    comme le rôle le plus restrictif possible : aucune écriture
    (is_tenant_readonly=True) et lecture strictement limitée aux objets/
    classes hors-tenant (tenants forcé à liste vide ici, sans tenir compte
    d'une éventuelle claim "tenants" du token - un appelant sans rôle RBAC
    reconnu n'est pas un principal de confiance pour du scoping tenant).
    `testuser` et le compte de service `miami-vice-service`, dont l'usage
    était déjà validé avant l'introduction du RBAC, reçoivent désormais
    explicitement le rôle `global-admin` (realm Keycloak + role mapping),
    pour préserver leur comportement sans rouvrir cette brèche pour
    quiconque d'autre. Précédence en cas de rôles multiples sur un même
    utilisateur (cas non prévu par les comptes de test fournis) :
    global-admin > tenant-admin > tenant-readonly.
    """
    claims = getattr(g, "auth_claims", None)
    realm_access = (claims or {}).get("realm_access", {}) or {}
    roles = set(realm_access.get("roles", []) or [])
    tenants = list((claims or {}).get("tenants", []) or [])
    rbac_roles = roles & _RBAC_ROLES

    if not rbac_roles:
        return AuthContext(False, False, True, [])

    return AuthContext(
        ROLE_GLOBAL_ADMIN in rbac_roles,
        ROLE_TENANT_ADMIN in rbac_roles and ROLE_GLOBAL_ADMIN not in rbac_roles,
        ROLE_TENANT_READONLY in rbac_roles and ROLE_GLOBAL_ADMIN not in rbac_roles and ROLE_TENANT_ADMIN not in rbac_roles,
        tenants,
    )


def _tenant_read_filter():
    """None : pas de filtrage (global-admin). Sinon : liste des tenants de
    l'utilisateur (éventuellement vide - cas fail-closed d'un appelant sans
    rôle RBAC reconnu, voir get_auth_context()), à utiliser dans un
    "tenants IS NULL OR tenants = '' OR string_to_array(tenants, ',') &&
    %s::text[]" (overlap Postgres) : une liste vide ne « overlap » jamais
    avec rien, donc seuls les objets hors-tenant restent visibles."""
    ctx = get_auth_context()
    if ctx.is_global_admin:
        return None
    return ctx.tenants


def _normalize_tenants_input(value):
    """Normalise une valeur 'tenants' reçue dans un corps de requête en
    liste de chaînes non vides. Accepte soit une liste JSON
    (["tenant1", "tenant2"]), soit une chaîne déjà jointe par des virgules
    ("tenant1,tenant2"), pour rester tolérant côté client. None -> liste
    vide (démande explicite de dé-tagger l'objet vers "hors tenant")."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    abort(400, description="Le champ 'tenants' doit être une liste ou une chaîne")


def _tenants_list_to_db(tenants_list):
    """Convertit une liste de tenants en valeur stockée en base (chaîne
    jointe par virgules, ou None si vide - NULL = hors tenant, visible par
    tous, cf. plan.md action 11.1)."""
    if not tenants_list:
        return None
    return ",".join(tenants_list)


def _tenants_db_to_list(db_value):
    """Convertit la valeur brute stockée en base (chaîne jointe par
    virgules, ou NULL/vide) en liste Python, pour l'API JSON et les
    comparaisons de périmètre tenant."""
    if not db_value:
        return []
    return [t for t in db_value.split(",") if t]


def _check_class_tenant_write_permission(ctx, cls_dict):
    """Vérifie (et complète au besoin) le champ "tenants" d'une classe en
    cours de création/modification de schéma, pour un tenant-admin.

    Lève 403 si la classe est explicitement taguée pour un ou plusieurs
    tenants dont aucun ne correspond à l'utilisateur. Si le champ est
    absent/vide, le complète en mutant cls_dict en place avec les tenants de
    l'utilisateur (choix assumé "sûr par défaut" : un tenant-admin ne doit
    pas pouvoir rendre une classe visible/éditable par tous les tenants sans
    le vouloir explicitement - voir rapport worker action 11). Ne fait rien
    si l'appelant n'est pas tenant-admin (global-admin : aucune contrainte).
    """
    if not ctx.is_tenant_admin:
        return
    tenants = cls_dict.get("tenants") or []
    if tenants:
        if not (set(tenants) & set(ctx.tenants)):
            abort(403, description=f"Classe '{cls_dict.get('class')}' non autorisée pour votre tenant")
    else:
        cls_dict["tenants"] = list(ctx.tenants)


def _existing_class_out_of_tenant_scope(ctx, existing_cls):
    """Retourne True si un tenant-admin n'a pas le droit d'écraser cette
    classe existante par un remplacement complet (write_class/write_metaclass
    /api/init), sans lever d'exception - utilisé là où l'appelant doit
    pouvoir décider lui-même de la suite (ex. /api/init qui doit pouvoir
    "skip" une classe bloquée plutôt qu'avorter toute la requête).

    Bloqué si la classe existante est explicitement taguée pour un ou
    plusieurs tenants dont aucun ne correspond à l'appelant, OU si elle n'a
    aucun tenant du tout (globale/hors-tenant) : un tenant-admin ne doit
    jamais pouvoir la re-tagger silencieusement vers son propre tenant en la
    "remplaçant" (même bug/correction que le re-tagging silencieux d'objets
    globaux, §11.2 correction bloquante 2, ici étendu aux classes). Toujours
    False pour global-admin (aucune contrainte).
    """
    if not ctx.is_tenant_admin:
        return False
    tenants = existing_cls.get("tenants") or []
    if not tenants:
        return True
    return not (set(tenants) & set(ctx.tenants))


def _check_existing_class_tenant_scope(ctx, existing_cls):
    """Empêche un tenant-admin d'écraser (via un remplacement complet de
    classe/meta-classe) une classe existante taguée pour un autre tenant, ou
    non taguée du tout (globale/hors-tenant) - jamais de re-tag silencieux
    d'une classe globale existante, cf. _existing_class_out_of_tenant_scope.
    Ne fait rien pour global-admin.
    """
    if _existing_class_out_of_tenant_scope(ctx, existing_cls):
        abort(403, description=f"Classe '{existing_cls.get('class')}' hors de votre périmètre tenant")


def _determine_object_tenants(ctx, body, existing_tenants):
    """Détermine la liste de tenants à poser sur un objet en écriture
    (création ou mise à jour). Appelant déjà vérifié non tenant-readonly.
    `existing_tenants` : None si création, sinon la liste déjà en base
    (éventuellement vide) de l'objet existant.

    Règles (plan.md action 11.2, correction bloquante 2 - ne jamais
    re-tagger silencieusement un objet existant) :
    - Mise à jour sans clé 'tenants' fournie explicitement dans le corps :
      la valeur existante est préservée telle quelle, y compris si elle est
      vide/hors-tenant - jamais de bascule automatique vers le(s) tenant(s)
      de l'éditeur.
    - Clé 'tenants' fournie explicitement (création ou mise à jour) :
      validée pour cohérence avec les tenants de l'appelant (sauf
      global-admin, qui n'a aucune restriction) ; une valeur vide/None
      explicitement fournie reste autorisée sans validation d'overlap -
      c'est une action explicite et volontaire de l'éditeur (dé-tagger vers
      "hors tenant"), pas un re-tag silencieux.
    - Création sans clé 'tenants' fournie : global-admin -> objet créé sans
      tag (hors-tenant) ; tenant-admin à un seul tenant -> auto-tag avec ce
      tenant (cas simple visé par la conception) ; tenant-admin multi-tenant
      -> 400 "tenant ambigu", doit préciser 'tenants' explicitement.
    """
    explicit = body.get("tenants", _UNSET)

    if explicit is _UNSET:
        if existing_tenants is not None:
            return existing_tenants
        if ctx.is_global_admin:
            return []
        if len(ctx.tenants) == 1:
            return [ctx.tenants[0]]
        abort(400, description="Tenant ambigu : utilisateur multi-tenant, préciser 'tenants' explicitement dans la requête")

    requested = _normalize_tenants_input(explicit)
    if not ctx.is_global_admin and requested and not (set(requested) <= set(ctx.tenants)):
        abort(400, description=f"Tenants {requested!r} non autorisés pour cet utilisateur")
    return requested

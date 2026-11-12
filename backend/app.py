import os
import json
import re
import psycopg2
import psycopg2.errors
import psycopg2.extras
import jsonschema
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
    """Valide le Bearer JWT Keycloak s'il est présent, et protège les routes
    d'écriture/suppression explicitement listées (401 si absent/invalide).

    Évolution action 11 (RBAC multi-tenant) : les routes /api/read/* restent
    ouvertes sans authentification obligatoire (pas de 401 si le token est
    absent ou invalide), MAIS si un Bearer valide est fourni, il est quand
    même décodé et stocké dans g.auth_claims, pour permettre aux endpoints
    de lecture d'appliquer un filtrage par tenant quand l'identité de
    l'appelant est connue (voir get_auth_context()/_tenant_read_filter()
    plus bas). Un visiteur anonyme (aucun token), ou un token sans rôle RBAC
    reconnu, est alors traité par get_auth_context() comme le rôle le plus
    restrictif possible (fail-closed, voir le choix documenté là-bas) - pas
    de 401 ici (la route de lecture reste accessible), mais aucun droit
    étendu n'est accordé.
    """
    protected = _requires_auth(request.path)

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[len("Bearer "):].strip() if auth_header.startswith("Bearer ") else None

    if token is None:
        if protected:
            abort(401, description="Authentification requise (en-tête 'Authorization: Bearer <token>' manquant)")
        return

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
        if protected:
            abort(401, description=f"Token invalide ou expiré : {e}")
        return
    except jwt.PyJWKClientError as e:
        if protected:
            abort(401, description=f"Impossible de vérifier le token (JWKS Keycloak injoignable ou kid inconnu) : {e}")
        return

    if claims.get("azp") not in ("miami-vice-direct", "miami-vice-service"):
        if protected:
            abort(401, description="Token émis pour un client inattendu")
        return

    g.auth_claims = claims


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
                    "tenants": cls.get("tenants"),
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
                        "tenants": cls.get("tenants"),
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
                "tenants": cls.get("tenants"),
                "attributes": cls["attributes"]
            })
        return jsonify({"meta_class": row["meta_class"], "classes": classes})


@app.route("/api/read/objects", methods=["GET"])
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
    with get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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

    ctx = get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture d'objet interdite")

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


@app.route("/api/write/attribute/<string:cls>/<int:object_id>/<string:attribute>/<string:value>", methods=["PUT"])
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
    ctx = get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture d'attribut interdite")

    conn = get_db()
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


@app.route("/api/delete/object/<int:object_id>", methods=["DELETE"])
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
    ctx = get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : suppression d'objet interdite")

    conn = get_db()
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

    ctx = get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture de schéma interdite")

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

    ctx = get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : écriture de schéma interdite")

    meta_class_name = body["meta_class"]
    data = {"meta_class": meta_class_name, "classes": body["classes"]}

    conn = get_db()
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


# ---------------------
# Chargement initial des fichiers model/*.json
# ---------------------

@app.route("/api/init", methods=["POST"])
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
    ctx = get_auth_context()
    if ctx.is_tenant_readonly:
        abort(403, description="Rôle tenant-readonly : chargement du modèle interdit")

    model_dir = os.environ.get("MODEL_DIR", "/model")
    loaded = []
    skipped = []

    conn = get_db()
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

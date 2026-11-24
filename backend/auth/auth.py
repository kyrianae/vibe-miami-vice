import os
import re

import jwt
from jwt import PyJWKClient
from flask import request, abort, g

# ---------------------
# Authentification (Keycloak) — voir plan.md action 7, doc/choix-authent.md
# ---------------------
#
# ATTENTION, point de vigilance explicite : les rôles/groupes Keycloak
# vérifiés ici ne servent qu'à l'authentification/autorisation d'accès à
# l'API (qui a le droit d'écrire). Ils ne doivent JAMAIS être confondus
# avec les classes métier "role"/"groupe" du modèle applicatif
# (model/organisation.json), qui sont des objets métier ordinaires, éditables
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
#
# /api/config/purge_grace_period_days (action 6.2) : ajoutée ici bien que
# GET/PUT (pas write/delete), car réservée global-admin strict (jamais
# appelable anonymement) - cohérent avec le choix 401 (pas seulement 403)
# déjà appliqué aux autres routes listées ici quand le token est absent.
#
# /api/config/default_layers (action 18) : volontairement ABSENTE de cette
# liste, contrairement à purge_grace_period_days ci-dessus - ne pas
# "corriger" par souci de cohérence (suggestion déjà rejetée). Cette liste
# protège par CHEMIN SEUL, pas par méthode HTTP (cf. _requires_auth
# juste en dessous) : l'y ajouter forcerait un 401 systématique même sur le
# GET sans token, ce qui casserait la lecture anonyme requise par
# Sidebar.tsx (layers affichés à tout utilisateur, pas seulement aux
# admins - même principe que les layers de classe, action 14). Le PUT reste
# protégé, mais uniquement par le check is_global_admin dans le handler
# (routes_admin.py set_default_layers) : donc 403 sans token/droit, pas
# 401. Différence assumée vis-à-vis de purge_grace_period_days, pas un
# oubli.
_PROTECTED_PREFIXES = ("/api/write/", "/api/delete/")
_PROTECTED_EXACT_PATHS = ("/api/init", "/api/purge", "/api/config/purge_grace_period_days")

# Route de lecture ciblée réservée global-admin strict (plan-mark3.md
# action 8, révélation d'un attribut `secret` en clair) : seule route
# GET /api/read/* protégée par un 401 systématique si le token est
# absent/invalide - toutes les autres restent ouvertes en lecture
# anonyme (filtrage RBAC/tenant appliqué séparément, voir rbac.py). Un
# pattern dédié (pas _PROTECTED_EXACT_PATHS, chemin dynamique avec
# object_id/attribute) plutôt qu'un simple startswith générique sur
# "/api/read/" qui romprait l'ouverture anonyme de toutes les autres
# routes de lecture.
_PROTECTED_REGEXES = (re.compile(r"^/api/read/object/\d+/secret/[^/]+$"),)


def _requires_auth(path):
    if path.startswith(_PROTECTED_PREFIXES) or path in _PROTECTED_EXACT_PATHS:
        return True
    return any(rx.match(path) for rx in _PROTECTED_REGEXES)


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

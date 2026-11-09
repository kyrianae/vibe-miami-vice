#!/bin/sh
# Fallback de provisioning du realm miami-vice via l'API Admin REST de
# Keycloak, à utiliser seulement si l'import automatique du realm au
# démarrage (--import-realm + miami-vice-realm.json) échoue ou doit être
# rejoué manuellement (ex. après un `docker compose down -v` suivi d'un
# changement du JSON). Idempotent : réexécutable sans tout casser (les
# POST échouent silencieusement avec un message si la ressource existe déjà).
#
# Usage : KEYCLOAK_URL=http://localhost:8080 ./provision-realm.sh
set -eu

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"

TOKEN=$(curl -sf -X POST "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "client_id=admin-cli" \
  -d "username=${ADMIN_USER}" \
  -d "password=${ADMIN_PASSWORD}" \
  -d "grant_type=password" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')

if [ -z "$TOKEN" ]; then
  echo "Impossible d'obtenir un token admin sur ${KEYCLOAK_URL}" >&2
  exit 1
fi

echo "Import du realm miami-vice..."
curl -sf -X POST "${KEYCLOAK_URL}/admin/realms" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d @"$(dirname "$0")/miami-vice-realm.json" \
  && echo "Realm créé." \
  || echo "Le realm existe peut-être déjà (ou autre erreur, voir ci-dessus) - non bloquant."

echo "Terminé. Vérifier dans la console admin : ${KEYCLOAK_URL}/admin/master/console/#/miami-vice"

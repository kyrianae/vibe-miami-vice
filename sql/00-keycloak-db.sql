-- Base dédiée à Keycloak, dans la même instance Postgres que miami_vice
-- (évite d'ajouter un second service stateful, cf. doc/choix-authent.md).
-- Numéroté 00- pour s'exécuter avant 01-init.sql (ordre alphabétique des
-- scripts docker-entrypoint-initdb.d).
-- Exécuté avec le rôle POSTGRES_USER (miami), superutilisateur de
-- l'instance au moment de l'initialisation : la base créée lui appartient,
-- ce qui permet de réutiliser les identifiants miami/vice comme
-- KC_DB_USERNAME/KC_DB_PASSWORD du service keycloak (voir docker-compose.yml).
CREATE DATABASE keycloak;

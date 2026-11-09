# Choix d'authentification — options possibles

> Document créé le 2026-11-09, suite à la discussion de `tocheck.md`
> (voir `specifications.md` §10.3 et `plan.md` action 7b). Liste les
> solutions d'authentification envisageables pour ce projet, avant
> décision finale. Contexte à garder en tête : API Flask stateless
> (une connexion psycopg2 par requête), aujourd'hui entièrement ouverte
> (`specifications.md` §2), un seul worker Gunicorn synchrone
> (`backend/Dockerfile`), frontend SPA sans routeur (`App.tsx`, juste une
> variable d'état `page`), services `ldap`/`lam` déjà déclarés mais
> entièrement commentés dans `docker-compose.yml`.

## Tableau comparatif

> Points forts/faibles issus d'une analyse croisée de l'équipe (optimiste/
> pessimiste), ancrée dans le code réel du dépôt (`backend/app.py`,
> `backend/Dockerfile`, `docker-compose.yml`, `frontend/src/App.tsx`,
> `model/personnes.json`), pas des généralités de documentation.

| # | Solution | Principe | Points forts | Points faibles |
|---|---|---|---|---|
| 1 | **Clé API statique** | Un secret partagé envoyé en en-tête `Authorization`, vérifié dans un `before_request` | • Aucune friction : `app.py` n'a aujourd'hui aucun `before_request`, un seul bloc suffit<br>• Protège immédiatement `POST /api/purge` (6.2) et le toggle `readOnly` sans toucher au frontend<br>• Zéro impact `docker-compose.yml` (aucun nouveau service) | • Aucune granularité : tout ou rien, impossible de distinguer lecture/écriture par utilisateur — `readOnly` resterait un artifice client<br>• `POST /api/init` et la future `POST /api/purge` ne matchent pas les préfixes `/api/write\|delete/*` : risque d'oubli du garde si non étendu explicitement<br>• SPA statique sans backend-for-frontend : la clé finit visible en clair dans le bundle/devtools |
| 2 | **Compte local (DB + session/JWT)** | Table `user` dans Postgres, login/mot de passe, `Flask-Login` ou JWT maison | • Réutilise le pattern `g.db` existant (une connexion psycopg2 par requête) : pas de nouvelle techno de persistance<br>• Reste dans le même paradigme stateless déjà en place<br>• Aucune dépendance réseau externe (adapté à un backend mono-worker) | • Pas de `SECRET_KEY` Flask configurée aujourd'hui (`Flask(__name__)` sans secret) : à ajouter, risque d'oubli/clé en dur<br>• Hash bcrypt/scrypt au login bloque le seul worker Gunicorn synchrone → `/api/login` devient un vecteur de ralentissement trivial de toute l'API<br>• Aucune brique SMTP dans `docker-compose.yml` : un reset de mot de passe exige un nouveau service mail non prévu |
| 3 | **LDAP direct** | Lib type `flask-ldap3-login`/`python-ldap`, bind contre le serveur LDAP | • Service `ldap`/`lam` déjà déclaré et configuré (`ldap/init.ldif` existe), juste commenté — investissement non perdu<br>• `lam` donne une UI d'admin des comptes sans rien développer côté `app.py`<br>• S'intègre comme un simple bind dans `before_request` | • Bind LDAP lent ou serveur indisponible bloque le worker unique pendant le timeout → gèle toute l'API, pas seulement l'utilisateur concerné<br>• Nécessite quand même une session/`SECRET_KEY` pour porter l'identité après le bind (même lacune que l'option 2)<br>• Investissement à sens unique : migrer vers Keycloak ensuite oblige à réécrire toute la couche d'auth de `app.py` |
| 4 | **OIDC Google direct** | Lib type `Authlib`/`google-auth`, flux OAuth2 avec Google comme IdP | • Lib mature : peu de code maison à sécuriser comparé à l'option 2<br>• Aucun nouveau service dans `docker-compose.yml` (Google = IdP externe, zéro charge opérationnelle)<br>• Le callback est l'occasion d'introduire un routeur frontend utile au-delà de l'auth | • Aucun routeur React existant (`App.tsx` = simple `useState`) : rien où accrocher une route de callback proprement<br>• Stack en mode dev sans TLS/reverse-proxy, or Google OAuth exige HTTPS en prod (sauf `localhost`) — brique manquante<br>• Google ne fournit qu'une identité, pas des rôles : il faut quand même une table `user`/`role` → retrouve la complexité de l'option 2 |
| 5 | **SSO générique (SAML/OIDC)** | Lib type `python3-saml` ou `Authlib` contre un IdP d'entreprise | • Capitalise sur un IdP d'entreprise déjà existant (zéro compte à gérer côté projet)<br>• Authlib mutualisable avec l'option 4 si Google fait aussi partie des IdP visés<br>• Hérite gratuitement des politiques de sécurité internes (MFA, rotation de mot de passe) | • `python3-saml` dépend de libs C natives (`xmlsec1`) : alourdit/complexifie le `Dockerfile` actuellement minimal (`python:3.12-slim`)<br>• SAML impose certificats/clés privées — aucun pattern de gestion de secrets dans `docker-compose.yml` aujourd'hui (tout en variables d'env en clair)<br>• Binding SAML POST nécessite une page ACS intermédiaire, plus lourd que le callback GET de l'option 4, et toujours sans routeur frontend |
| 6 | **Keycloak (fédérateur)** | IdP central auto-hébergé, fédère LDAP + Google + SSO derrière un seul protocole OIDC ; le backend ne valide qu'un JWT | • **Recommandé à l'unanimité par l'équipe.** Réutilise le LDAP déjà déclaré comme backend fédéré, aucune duplication<br>• Une seule intégration JWT côté `app.py` au lieu de 3 libs distinctes (LDAP+Google+SSO séparément)<br>• Groupes/rôles Keycloak peuvent porter nativement la notion de tenant (§10.2) | • Service stateful supplémentaire (sa propre DB) — rupture avec l'archi stateless actuelle<br>• Risque réel de confusion : `model/personnes.json` définit déjà des classes métier `role`/`groupe` éditables librement par l'UI générique — si mal distingué des groupes d'autorisation Keycloak, risque d'élévation de privilèges<br>• Validation JWT nécessite de récupérer les clés JWKS (appel réseau) : sans cache, un seul worker synchrone peut geler sur une lenteur/indisponibilité de Keycloak |
| 7 | **IAM managé (Auth0, Okta, Authentik...)** | Équivalent SaaS ou self-hosted léger de Keycloak | • Même bénéfice d'intégration JWT unique que Keycloak, sans opérer soi-même l'IdP (offres cloud)<br>• Authentik (self-hosted) compatible avec le LDAP déjà déclaré, présenté comme plus léger que Keycloak<br>• Offres SaaS : aucun service/DB supplémentaire à opérer, adapté à un backend mono-worker | • Auth0/Okta = dépendance réseau externe obligatoire pour se connecter — rupture de la posture actuelle « tout auto-hébergé, circuit fermé »<br>• Authentik nécessite en réalité Postgres **et** Redis : potentiellement 2 services stateful de plus (vs 1 pour Keycloak) — l'argument de légèreté est à vérifier<br>• Coût/vendor lock-in (Auth0/Okta) + même manque de routeur frontend pour le callback OAuth que l'option 4 |

### Risques transversaux (indépendants de l'option choisie)

Relevés par l'équipe en creusant `docker-compose.yml` : le port Postgres
`5432:5432` est publié directement sur l'hôte avec des identifiants en
clair (`miami`/`vice`, versionnés dans git) — n'importe qui ayant accès
réseau à l'hôte peut se connecter directement à la base et contourner
**entièrement** toute authentification ajoutée côté Flask (options 2 à 7
qui stockent des utilisateurs/jetons en base). À restreindre/fermer avant
d'implémenter n'importe laquelle de ces options, indépendamment du choix
final.

## Décision (2026-11-09)

**Keycloak retenu.** Critère décisif de l'utilisateur : besoin de comptes
de service (token) **et** de login/mot de passe direct pour obtenir un
Bearer — les deux flux sont nativement couverts par Keycloak :

- **Compte de service** : client confidentiel avec *Service Accounts
  Enabled*, flux `client_credentials` (`POST
  /realms/miami-vice/protocol/openid-connect/token`) → Bearer JWT sans
  interaction utilisateur. Adapté à l'automatisation (scripts, future
  tâche de purge périodique de l'action 6.2, intégrations externes).
- **Login/mot de passe direct** : client avec *Direct Access Grants*
  activé (Resource Owner Password Credentials) → un utilisateur humain
  envoie username/password directement à Keycloak et récupère un Bearer,
  sans redirection navigateur — pertinent ici puisque le frontend n'a
  aujourd'hui aucun routeur pour un flux OIDC Authorization Code complet
  avec redirection (limite déjà documentée dans le tableau ci-dessus).

Le flux « redirection + page de login hébergée par Keycloak » (le plus
standard/sécurisé) reste possible plus tard si un routeur est ajouté au
frontend — non bloquant pour démarrer avec le flux direct.

Transition avec l'étape intermédiaire déjà prévue (option 1, clé API
statique, action 7b du plan) : elle reste le point de départ immédiat et
sans risque pour débloquer `readOnly`/`POST /api/purge` ; Keycloak la
remplace ensuite comme solution structurante.

## Dépendances avec le reste du plan

- **Tenant** (`specifications.md` §10.2) : dépend de ce choix — les
  groupes/rôles Keycloak pourraient porter directement la notion de
  tenant plutôt que de la dupliquer dans une table applicative.
- **Action 7b** (`plan.md`) : l'étape « clé API statique » est le point
  de départ (option 1) ; la solution finale retenue ici la remplace ou
  la complète selon l'option choisie.
- **Action 6.2** (purge physique différée) : la route `POST /api/purge`
  doit être protégée par la solution d'authentification retenue.

## Statut

**Tranché : Keycloak.** Conception technique détaillée pour
l'implémentation : voir `plan.md` action 7b.

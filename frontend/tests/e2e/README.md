# Tests IHM (Playwright) — smoke tests

Plan-mark4.md action 2. Un test par page principale (Navigation,
Configuration, Diagramme, Dashboard, Recherche) : charge via le menu
`Navbar.tsx`, vérifie l'absence d'erreur console et la présence d'un
élément clé.

## Pré-requis

- Stack docker-compose déjà up (`docker compose up -d`), en particulier
  `frontend` (port 3000) et `keycloak` (port 8080) exposés sur l'hôte.
- Utilisateur de test `testuser`/`testuser123` (déjà utilisé par
  `tools/screenshot_demo.py`).

## Pourquoi pas `docker compose exec frontend npx playwright test`

Le conteneur `frontend` est basé sur `node:20-alpine` (musl) : Playwright ne
supporte pas d'installer/lancer ses navigateurs embarqués sur Alpine (pas de
glibc), confirmé en pratique (`spawn ... ENOENT` au lancement de Chromium).
`@playwright/test` reste néanmoins déclaré en devDependency dans
`package.json` (cohérence du manifeste, `npm install`/`npm ci` fonctionnent
dans ce conteneur), mais l'exécution réelle des tests se fait via un
conteneur Playwright officiel séparé (Debian/glibc), ponctuel, qui monte le
dossier `frontend/` et rejoint le réseau de l'hôte pour atteindre
`127.0.0.1:3000`/`127.0.0.1:8080` (ports déjà publiés par docker-compose) :

```bash
cd frontend
docker run --rm --network host \
  -v "$(pwd):/app" -w /app \
  mcr.microsoft.com/playwright:v1.65.1-noble \
  bash -c "npm install && npx playwright test"
```

La version du conteneur Playwright officiel doit matcher la version de
`@playwright/test` installée (`npx playwright --version`) — sinon le
conteneur refuse de lancer les navigateurs (message explicite indiquant la
version attendue).

## Pourquoi `127.0.0.1` et pas `localhost`

Documenté en commentaire dans `playwright.config.ts` : la résolution
dual-stack de `localhost` (`::1` + `127.0.0.1`) combinée à la rafale de
requêtes parallèles de la page Diagramme (`DiagramPage.tsx`,
`Promise.all` sur des dizaines de `GET /api/read/object/<id>`) déclenche de
façon systématique `ERR_NETWORK_CHANGED` dans Chromium sous ce conteneur
(réseau host) — éliminé à 100 % en forçant `127.0.0.1`. Rien côté
application n'a été modifié pour ce correctif.

## Pourquoi 1 seul worker (`workers: 1`)

Le serveur de dev Vite ciblé (single-process) devient contentieux sous 2
Chromium headless en parallèle — un dépassement de timeout a été observé
sur `dashboard.spec.ts` (> 5 s) en 2 workers, absent en 1 worker ou en
isolé. Suite volontairement 100 % séquentielle pour ce premier passage
(5 tests, overhead de parallélisation non nécessaire).

## Authentification

`global-setup.ts` reproduit le pattern déjà utilisé par
`tools/screenshot_demo.py` : password grant Keycloak direct (client public
`miami-vice-direct`, `testuser`/`testuser123`), token injecté en
`localStorage` (clé `miami-vice-auth-token`, cf. `frontend/src/api.ts`) sur
l'origine du frontend, capturé une fois comme `storageState` Playwright
réutilisable par tous les tests (`tests/e2e/.auth/storageState.json`,
ignoré par git).

## Limite connue de couverture — `diagramme.spec.ts`

Ce test vérifie l'absence d'erreur console et la présence du conteneur
canvas (`.diagram-chart canvas`), mais `DiagramPage.tsx` avale
silencieusement les erreurs réseau du chargement des objets
(`.catch(() => {})` ligne ~132 sur `Promise.all([apiReadObjects(),
apiReadClasses()])`, `.catch(() => null)` ligne ~141 sur le `Promise.all`
de détail par objet). Un vrai échec réseau en production (pas seulement
l'artefact dual-stack déjà corrigé par `127.0.0.1` ci-dessus) ne ferait
donc pas échouer ce test : le canvas reste visible même avec un graphe
vide ou partiel. Non corrigé ici — changer ce comportement de
`DiagramPage.tsx` est hors périmètre de cette suite de smoke tests.

## Point de suivi connu

Un test a révélé une pollution pré-existante de la base de dev partagée :
classe orpheline `testeur_dup_rt/compte_rt_dup` (attribut `pw` déclaré deux
fois), hors de tout `model/*.json` versionné, qui déclenche un vrai
avertissement React ("two children with the same key") dès le chargement.
Filtré explicitement dans `helpers.ts` (`isKnownPreexistingDuplicateKeyWarning`)
le temps d'un nettoyage manuel :

```
DELETE /api/delete/object/187
DELETE /api/delete/class/testeur_dup_rt/compte_rt_dup
DELETE /api/delete/metaclass/testeur_dup_rt
```

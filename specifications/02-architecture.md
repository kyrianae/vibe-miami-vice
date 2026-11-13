# 2. Architecture générale

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

```
┌────────────┐      HTTP (proxy /api)      ┌──────────────┐      SQL      ┌────────────┐
│  Frontend  │ ───────────────────────────▶ │   Backend    │ ────────────▶ │ PostgreSQL │
│ React+Vite │ ◀─────────────────────────── │ Flask+psycopg2│ ◀──────────── │    16      │
│  :3000     │                              │    :8000      │               │   :5432    │
└────────────┘                              └──────────────┘               └────────────┘

(services optionnels, définis mais commentés dans docker-compose.yml :
 ldap (OpenLDAP) + lam (LDAP Account Manager) — non utilisés par le code actuel,
 aucune route backend ni composant frontend ne fait référence au LDAP)
```

- **`db`** : PostgreSQL 16, source de vérité unique. Schéma créé une seule
  fois par `sql/init.sql` au premier démarrage du volume.
- **`backend`** : API Flask stateless côté HTTP (une connexion psycopg2 par
  requête, via `flask.g`), sans ORM, sans authentification, sans CORS
  explicite (fonctionne car le frontend passe par le proxy Vite, donc
  même origine du point de vue du navigateur).
- **`frontend`** : SPA React 18 + TypeScript, servie par le serveur de dev
  Vite (`npm run dev`, pas de build de production en conteneur), 3 pages
  pilotées par état React local (pas de routeur), thèmes CSS, et un graphe
  ECharts.
- Aucune authentification, autorisation ou session n'existe nulle part dans
  le code (ni backend ni frontend) : l'API est entièrement ouverte.

## 5. Flux de démarrage

1. `docker-compose up -d` :
   - **`db`** démarre en premier ; l'image officielle `postgres:16` exécute
     automatiquement, **uniquement si le volume `pgdata` est vide** (premier
     démarrage), tout script trouvé directement dans
     `/docker-entrypoint-initdb.d/` — ici `01-init.sql` (= `sql/init.sql`),
     qui crée les 4 tables (`object`, `attribute`, `attribute_value`,
     `definition`), toutes vides. Le sous-dossier `./model` est aussi monté
     dans `/docker-entrypoint-initdb.d/model`, mais **cela n'a aucun effet
     automatique** : Postgres n'exécute que des scripts `.sql`/`.sql.gz`/`.sh`
     placés directement à la racine de ce dossier, pas des fichiers `.json`
     dans un sous-dossier — ce montage est inerte pour l'initialisation DB.
   - Un `healthcheck` (`pg_isready`) conditionne le démarrage de `backend`
     (`depends_on: db: condition: service_healthy`).
   - **`backend`** se construit depuis `backend/Dockerfile` (Python 3.12
     slim + `pip install -r requirements.txt`), monte `./backend` et
     `./model` en volumes, et lance `gunicorn --bind 0.0.0.0:8000 --reload
     app:app`. ⚠️ Dans l'état actuel du code, cet import échoue (voir §0) —
     le serveur ne démarre pas réellement.
   - **`frontend`** se construit depuis `frontend/Dockerfile` (Node 20
     alpine + `npm install`), démarre après `backend` (ordre de démarrage
     seulement, pas de healthcheck), lance `npm run dev` (serveur Vite,
     port 3000), avec un volume anonyme sur `/app/node_modules` pour ne
     pas écraser les dépendances installées en conteneur par le montage
     du code source hôte.
2. À ce stade, la base est vide : aucune meta-classe/classe/objet n'existe.
   Les endpoints de lecture renverraient des listes vides.
3. Il faut **explicitement** déclencher le chargement des définitions :
   soit `curl -X POST http://localhost:8000/api/init`, soit le bouton
   « Charger depuis model/ » de la page Configuration (`apiInit()`). Ce
   n'est jamais fait automatiquement par docker-compose ou par le backend
   au démarrage.
4. Une fois les meta-classes chargées, les objets peuvent être créés via
   la page Navigation (ou directement en `POST /api/write/object`).
5. Le proxy Vite (`frontend/vite.config.ts`) redirige toute requête
   `/api/*` faite par le navigateur (sur le port 3000) vers
   `http://backend:8000` côté serveur de dev — le frontend n'appelle
   jamais directement le port 8000 depuis le navigateur.

Réinitialisation complète : `docker-compose down -v` (supprime aussi le
volume `pgdata`, donc force le script `sql/init.sql` à se rejouer au
prochain démarrage) puis `docker-compose up -d`.

## 7. LDAP (désactivé)

`docker-compose.yml` définit deux services **entièrement commentés** :
- `ldap` (image `osixia/openldap:1.5.0`), amorcé avec `ldap/init.ldif`
  (deux OU `users`/`groups`, deux comptes `admin`/`user`, deux groupes
  `miami-admins`/`miami-users`, domaine `dc=miami-vice,dc=local`).
- `lam` (LDAP Account Manager), pointant vers ce serveur LDAP.

Les volumes nommés `ldapdata`/`ldapconfig` sont déclarés en bas du fichier
mais ne sont utilisés par aucun service actif tant que ces blocs restent
commentés. **Aucun code backend ou frontend ne référence LDAP** — ni
authentification, ni lecture d'annuaire : ce sont des services prêts à
être activés mais non intégrés fonctionnellement au reste de l'application.

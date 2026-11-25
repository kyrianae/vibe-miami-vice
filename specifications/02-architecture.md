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

*(État réel actuel, hors scope de cet instantané figé — voir
[07-roadmap.md](07-roadmap.md) §10.2/§10.3 : authentification Keycloak
(`backend/auth/auth.py`) et RBAC multi-tenant (`backend/auth/rbac.py`)
actifs depuis `plan-mark1.md` actions 7b et 11 (chemins packagés depuis
`plan-mark3.md` action 12). Voir « Découpage en Blueprints » ci-dessous
pour la structure à jour de ces modules.)*

## 2bis. Découpage de `backend/app.py` en Blueprints et packages (ajout 2026-11-21 `plan-mark3.md` actions 1-4, réorganisé en packages 2026-11-22 action 12, mis à jour 2026-11-23 action 16)

`backend/app.py` n'est plus un fichier plat (c'était le cas à l'audit
initial, §0) : depuis `plan-mark3.md` action 1, c'est un point d'entrée
mince qui construit `app = Flask(__name__)`, fixe `app.config
["MAX_CONTENT_LENGTH"]` (limite d'upload, 20 Mo par défaut, configurable via
`MAX_UPLOAD_SIZE_BYTES` — action 3, voir §10.1/§10.8), enregistre
`app.before_request(require_auth)` et `app.teardown_appcontext(close_db)`
par appel explicite, puis enregistre 5 Blueprints dans cet ordre (sans
dépendance d'ordre vis-à-vis de `before_request`, qui s'applique à toutes
les routes quel que soit l'ordre d'enregistrement) :
`routes_read.read_bp`, `routes_write.write_bp`, `routes_init.init_bp`,
`routes_admin.admin_bp`, `routes_files.files_bp` (24 routes applicatives au
total, action 12).

Depuis `plan-mark3.md` action 12 (2026-11-22), `backend/` **n'est plus
plat** : les modules ci-dessus (hors `app.py`) sont répartis en 5 packages
Python (déplacement mécanique, aucun changement de comportement) :
- `backend/auth/` : `auth.py` (hook d'authentification Keycloak,
  `require_auth`, `get_jwk_client`, et depuis l'action 8 la liste
  `_PROTECTED_REGEXES` qui force un Bearer token même sur certaines routes
  `GET /api/read/...` normalement ouvertes — voir §4.7 de
  [04-api-backend.md](04-api-backend.md)), `rbac.py` (`AuthContext`,
  `get_auth_context`, filtrage/validation tenant —
  `_tenant_read_filter`, `_check_class_tenant_write_permission`, etc.).
- `backend/data/` : `db.py` (`get_db`, `close_db`, `load_schema`).
- `backend/files/` : `file_storage.py` (action 2, interface `FileStorage`
  ABC + `LocalFileStorage`), `file_validation.py` (action 3, validation de
  contenu `image`/`csv` et écriture sûre `save_file_or_400`), `class_icon.py`
  (action 4, génération de l'icône de secours SVG par classe).
- `backend/routes/` : `routes_read.py` (Blueprint `read_bp`, tous les
  `GET /api/read/...`, dont `GET /api/class_icon/<meta_class>/<class>`
  action 4, et depuis l'action 8 `GET /api/read/object/<id>/secret/
  <attribute>`), `routes_write.py` (Blueprint `write_bp`, `POST/PUT
  /api/write/...`, `DELETE /api/delete/object/<id>`, dont la détection
  multipart de `POST /api/write/object` — création atomique objet +
  fichiers, action 3 itération 2, `_write_object_multipart` — et depuis
  les actions 7/8/9 la coercition typée `select`/`secret`/`datasource`,
  voir §4.3/§4.7 de [04-api-backend.md](04-api-backend.md)),
  `routes_init.py` (Blueprint `init_bp`, `POST /api/init`), `routes_admin.py`
  (Blueprint `admin_bp`, purge/suppression de schéma — action Mark 2 — et
  depuis l'action 3 `POST /api/admin/sweep_orphan_files`, voir §4.6 de
  [04-api-backend.md](04-api-backend.md)), `routes_files.py` (Blueprint
  `files_bp`, actions 3-4, routes de lecture/écriture des attributs
  `file`/`image`/`csv` et des références de logo, détail complet : §4.6 de
  [04-api-backend.md](04-api-backend.md)), `routes_search.py` (Blueprint
  `search_bp`, ajouté `plan-mark3.md` action 21, `GET /api/search` —
  recherche globale toutes classes/meta-classes confondues, détail
  complet : §4.10 de [04-api-backend.md](04-api-backend.md)) — 6
  Blueprints enregistrés dans `app.py` depuis cette action (5 avant,
  action 12).
- `backend/tests/` : les 11 fichiers `test_*.py` (invocation :
  `SCHEMA_PATH=<chemin absolu>/model/schema.json pytest backend/tests/ -v`
  depuis la racine du dépôt — le chemin a changé par rapport à l'ancienne
  commande `pytest backend/test_X.py`, corrigé aussi dans les docstrings
  des fichiers de test eux-mêmes).

Restent à la racine de `backend/` (pas de package dédié) :
- `app.py` : point d'entrée Flask décrit ci-dessus.
- `secret_crypto.py` (action 8) : chiffrement/déchiffrement Fernet des
  attributs `secret` (`encrypt_secret`/`decrypt_secret`, clé lue
  dynamiquement depuis `SECRET_ENCRYPTION_KEY`) — jugé module générique de
  chiffrement sans lien direct avec un seul des 4 domaines de packages
  (`auth`/`data`/`files`/`routes`), donc non déplacé. Détail complet :
  §4.7 de [04-api-backend.md](04-api-backend.md).

Chaque `routes/routes_*.py` fait `import app` en tête de module (le
`WORKDIR` du conteneur et la racine `backend/` du dépôt placent `app.py`
sur le path d'import, même depuis un sous-package) et appelle
`app.get_db()`/`app.get_auth_context()` à l'intérieur des corps de
fonctions (jamais au niveau module) : permet aux tests de monkeypatcher
directement `miami_app.get_db`/`miami_app.get_auth_context`, sans import
circulaire constaté — préservé tel quel par la réorganisation en packages
(aucun changement requis au `Dockerfile`, `COPY backend/ .` copie tout le
dossier et `CMD gunicorn app:app` reste valide). Détail complet
(vérifications, tests, dettes assumées) : `plan-mark3.md` actions 1 et 12.

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

     *(État réel actuel, hors scope de cet instantané figé — voir
     [07-roadmap.md](07-roadmap.md) §10.2/§10.3 : `backend/app.py` démarre
     normalement sous `gunicorn ... app:app` depuis `plan-mark1.md`, voir
     « Découpage en Blueprints » ci-dessous.)*
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

# Miami Vice

Un modélisateur de données générique : un schéma de meta-classes/classes/attributs défini en JSON, stocké dans PostgreSQL, exposé par une API Flask et manipulé via une interface React (vue tableau, formulaire de configuration, et diagramme interactif ECharts).

## 📋 Table des matières

- [Caractéristiques](#caractéristiques)
- [Architecture](#architecture)
- [Modèle de données](#modèle-de-données)
- [Installation & démarrage](#installation--démarrage)
- [Authentification (Keycloak)](#-authentification-keycloak)
- [API Endpoints](#api-endpoints)
- [Frontend](#frontend)
- [Développement](#développement)

## ✨ Caractéristiques

### Backend (Flask)
- **API REST minimaliste** (`flask` + `psycopg2`, sans ORM) pour lire/écrire des meta-classes, classes, objets et attributs
- **Schéma piloté par JSON** - les classes et leurs attributs sont définis dans des fichiers `model/*.json` (validés par `model/schema.json`) puis chargés en base via `/api/init`
- **Modèle objet générique** - table `object` (instances), `attribute` (attributs posés sur un objet) et `attribute_value` (valeurs typées : entier, flottant, chaîne, ou jointure vers un autre objet)
- **Jointures 1-1 / 1-N** entre objets, portées par le type d'attribut (`joint-1-1`, `joint-1-n`)
- **Gunicorn** en conteneur, rechargement à chaud (`--reload`) en dev

### Frontend (React + Vite)
- **React 18 + TypeScript**, bundlé avec **Vite**
- **3 vues** pilotées par une barre de navigation et une sidebar commune :
  - **Navigation** - tableau des objets, édition inline des attributs (y compris jointures), bascule lecture seule / lecture-écriture
  - **Configuration** - éditeur de meta-classes/classes/attributs (CRUD du schéma)
  - **Diagramme** - graphe interactif des objets et de leurs jointures avec **ECharts** (layouts force / circulaire / organigramme)
- **Thèmes** dark / midnight / light
- Pas de framework de routage : navigation par état React (`App.tsx`)

### Autres composants (prévus / optionnels)
- **PostgreSQL 16** comme unique source de vérité
- **OpenLDAP + LDAP Account Manager** - services définis mais **désactivés** (commentés) dans `docker-compose.yml`, avec un `ldap/init.ldif` prêt à l'emploi

## 🏗️ Architecture

### Structure du projet

```
miami-vice/
├── backend/                    # API Flask
│   ├── app.py                  # Toutes les routes (read/write/init)
│   ├── requirements.txt        # flask, psycopg2-binary, gunicorn, jsonschema
│   └── Dockerfile
│
├── frontend/                   # React + TypeScript (Vite)
│   ├── src/
│   │   ├── api.ts              # Client API (fetch) vers /api/*
│   │   ├── types.ts            # Types du modèle (meta-classe, classe, attribut, objet)
│   │   ├── App.tsx             # Layout + état global (page, thème, sélection)
│   │   ├── components/
│   │   │   ├── Navbar.tsx      # Navigation entre pages + switch thème/RO-RW
│   │   │   └── Sidebar.tsx     # Arborescence meta-classe → classe
│   │   ├── pages/
│   │   │   ├── NavigationPage.tsx     # Tableau des objets, édition inline
│   │   │   ├── ConfigurationPage.tsx  # Éditeur du schéma (meta-classes/classes)
│   │   │   └── DiagramPage.tsx        # Graphe ECharts des objets/jointures
│   │   ├── styles.css
│   │   └── main.tsx
│   ├── vite.config.ts          # Proxy /api → backend:8000
│   └── Dockerfile
│
├── model/                      # Définitions de schéma chargées en base
│   ├── schema.json             # JSON Schema validant les fichiers de définition
│   ├── personnes.json          # Exemple de meta-classe "personne"
│   └── reseau.json             # Exemple de meta-classe "réseau"
│
├── sql/
│   └── init.sql                # Tables : object, attribute, attribute_value, definition
│
├── ldap/
│   └── init.ldif                # Données d'amorçage LDAP (service désactivé)
│
├── docker-compose.yml          # Services : db (Postgres), backend, frontend, (ldap/lam commentés)
├── specifications.md           # Pointeur vers specifications/ (contenu déplacé le 2026-11-13)
└── specifications/             # Spécifications splittées par thème (fonctionnel, architecture, technique, anomalies, roadmap)
```

### Pattern URL de l'API

```
GET  /api/read/meta_class                 # Liste des meta-classes
GET  /api/read/class                      # Liste de toutes les classes (toutes meta-classes)
GET  /api/read/class/<id>                 # Une classe par id global
GET  /api/read/<meta_class>                # Classes d'une meta-classe donnée
GET  /api/read/objects                    # Liste des objets (sans attributs)
GET  /api/read/object/<id>                 # Un objet avec attributs/valeurs

POST /api/write/metaclass                 # Crée/remplace une meta-classe entière
POST /api/write/class                     # Ajoute/remplace une classe dans une meta-classe
POST /api/write/object                    # Crée/met à jour un objet et ses attributs
PUT  /api/write/attribute/<cls>/<id>/<attribute>/<value>  # Écrit la valeur d'un attribut

POST /api/init                            # Charge les fichiers model/*.json en base
```

## 🧬 Modèle de données

### Schéma de définition (`model/*.json`)

Chaque fichier décrit une **meta-classe** regroupant plusieurs **classes**, chacune avec ses **attributs** :

```json
{
  "meta_class": "personne",
  "classes": [
    {
      "class": "personne_physique",
      "displayname": "{{nom}} {{prenom}}",
      "attributes": [
        { "domain": "details", "name": "nom", "type": "string" },
        { "domain": "details", "name": "prenom", "type": "string" },
        { "domain": "liens", "name": "employeur", "type": "joint-1-1", "classes": ["organisation"] }
      ]
    }
  ]
}
```

- `type` : `string`, `integer`, `float`, `joint-1-1` ou `joint-1-n` (jointure vers une autre instance)
- `constraint` : regex de validation (pour `string`)
- `displayname` : gabarit d'affichage `{{attribut}}` (sinon concaténation du domaine `details`)

### Tables PostgreSQL (`sql/init.sql`)

- `definition(id, meta_class, data JSONB)` - stocke le JSON de définition tel quel
- `object(id, meta_class, class)` - une instance
- `attribute(id, object_id, domain, name)` - un attribut posé sur un objet
- `attribute_value(id, attribute_id, value_integer | value_float | value_string | joint_id)` - valeur typée (une seule colonne renseignée, contrainte CHECK), `joint_id` référence un autre `object`

## 🚀 Installation & démarrage

### Prérequis
- Docker & Docker Compose

### Démarrer

```bash
docker-compose up -d
```

- **Frontend** - http://localhost:3000
- **Backend (API Flask)** - http://localhost:8000
- **PostgreSQL** - localhost:5432 (user `miami`, password `vice`, db `miami_vice`)

Le proxy Vite redirige automatiquement `/api/*` du frontend vers le backend.

### Charger les définitions de modèle en base

Au premier démarrage (ou après modification des fichiers `model/*.json`) :

```bash
curl -X POST http://localhost:8000/api/init
```

Cela lit tous les `model/*.json` (hors `schema.json`) et les insère/remplace dans la table `definition`.

### Réinitialiser complètement

```bash
docker-compose down -v   # supprime aussi le volume pgdata
docker-compose up -d
```

### LDAP (optionnel, désactivé par défaut)

Les services `ldap` (OpenLDAP) et `lam` (LDAP Account Manager) sont définis dans `docker-compose.yml` mais commentés. Pour les activer, décommenter les deux blocs puis relancer `docker-compose up -d`.

### 🔐 Authentification (Keycloak)

L'API protège les routes mutantes (`/api/write/*`, `/api/delete/*`, `/api/init`, `/api/purge`) par un token JWT vérifié auprès d'un realm Keycloak (service `keycloak` dans `docker-compose.yml`, exposé sur http://localhost:8080).

**Rebuild obligatoire du backend après mise à jour** - `backend/requirements.txt` embarque désormais `PyJWT` et `cryptography` (vérification des tokens JWT/JWKS). Une image `backend` déjà construite avant ce changement ne les contient pas : il faut reconstruire l'image, sinon le backend plante au démarrage avec un `ModuleNotFoundError` :

```bash
docker-compose build backend
# ou, plus simple :
docker-compose up -d --build
```

**Volume `pgdata` déjà initialisé : la base `keycloak` n'est pas créée automatiquement** - le script `sql/00-keycloak-db.sql` est déposé dans `docker-entrypoint-initdb.d/`, mais l'image officielle Postgres n'exécute ces scripts **qu'au tout premier démarrage d'un volume vierge**. Sur un environnement de dev existant où le volume `pgdata` a déjà été initialisé avant l'ajout de ce script, la base `keycloak` ne sera **jamais** créée automatiquement, et le service `keycloak` échouera à se connecter à sa base. Deux remédiations possibles :

- Créer la base manuellement, sans perte de données :
  ```bash
  docker-compose exec db psql -U miami -d miami_vice -c "CREATE DATABASE keycloak;"
  ```
- Ou repartir d'un volume vierge (perte de **toutes** les données existantes, à n'utiliser que si acceptable) :
  ```bash
  docker-compose down -v
  docker-compose up -d
  ```

**Volume `pgdata` déjà initialisé : la table `app_config` n'est pas créée automatiquement** - de la même façon, le script `sql/init.sql` ajoute la table `app_config` (clé/valeur, utilisée pour le paramètre `purge_grace_period_days` de la purge physique différée, action 6.2) et son seed. Sur un volume `pgdata` déjà initialisé avant ce changement, cette table ne sera **jamais** créée automatiquement, et les routes `GET`/`PUT /api/config/purge_grace_period_days` ainsi que `POST /api/purge` échoueront avec une erreur 500. Deux remédiations possibles :

- Créer la table manuellement, sans perte de données :
  ```bash
  docker-compose exec db psql -U miami -d miami_vice -c "CREATE TABLE IF NOT EXISTS app_config (key TEXT PRIMARY KEY, value TEXT NOT NULL); INSERT INTO app_config (key, value) VALUES ('purge_grace_period_days', '30') ON CONFLICT (key) DO NOTHING;"
  ```
- Ou repartir d'un volume vierge (perte de **toutes** les données existantes, à n'utiliser que si acceptable) :
  ```bash
  docker-compose down -v
  docker-compose up -d
  ```

## 🎨 Frontend

### Développement local (hors Docker)

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 par défaut (ou via Docker : 3000)
```

### Build production

```bash
npm run build
```

### Pages

| Page | Rôle |
|------|------|
| **Navigation** | Tableau des objets filtrable par meta-classe/classe, édition inline des valeurs (y compris jointures via modale), bascule lecture seule |
| **Configuration** | CRUD du schéma : création/édition de meta-classes, classes et attributs |
| **Diagramme** | Visualisation graphe (ECharts) des objets et de leurs jointures, avec 3 layouts (force, circulaire, organigramme) |

### Client API

Tous les appels passent par `src/api.ts` (fetch natif, pas d'Axios) :

```typescript
import { apiReadObjects, apiReadObject, apiWriteObject, apiWriteAttribute } from './api';

const objects = await apiReadObjects();
const detail = await apiReadObject(42);
await apiWriteAttribute('personne_physique', 42, 'nom', 'Dupont');
```

## 👨‍💻 Développement

### Ajouter une nouvelle meta-classe

1. Créer un fichier `model/<nom>.json` respectant `model/schema.json`
2. Recharger via `POST /api/init` (ou passer par la page Configuration)

### Ajouter un attribut à une classe existante

Soit via la page **Configuration**, soit directement :

```bash
curl -X POST http://localhost:8000/api/write/class \
  -H "Content-Type: application/json" \
  -d '{
    "meta_class": "personne",
    "class": {
      "class": "personne_physique",
      "attributes": [
        { "domain": "details", "name": "nom", "type": "string" },
        { "domain": "details", "name": "email", "type": "string", "constraint": "^.+@.+$" }
      ]
    }
  }'
```

> ⚠️ `/api/write/class` **remplace** la liste complète des attributs de la classe : il faut renvoyer l'ensemble des attributs existants plus les nouveaux.

### Créer un objet avec des attributs

```bash
curl -X POST http://localhost:8000/api/write/object \
  -H "Content-Type: application/json" \
  -d '{
    "meta_class": "personne",
    "class": "personne_physique",
    "attributes": { "nom": "Doe", "prenom": "John" }
  }'
```

### Tests backend (RBAC multi-tenant)

Pas de suite de tests automatisés formelle sur l'ensemble du projet, mais le scénario de non-régression du bug de re-tagging silencieux des classes (action 11, §11.2) est couvert par `backend/test_rbac_class_tenant_scope.py` (monkeypatch de `get_db`/`get_auth_context`, aucune dépendance à une vraie base ou à un vrai Keycloak) :

```bash
cd backend
pip install -r requirements-dev.txt
pytest test_rbac_class_tenant_scope.py -v
```

## 📚 Dépendances principales

### Backend
- **Flask** - framework web
- **psycopg2-binary** - driver PostgreSQL (accès SQL direct, pas d'ORM)
- **gunicorn** - serveur WSGI
- **jsonschema** - validation des fichiers `model/*.json`

### Frontend
- **React 18** / **TypeScript**
- **Vite** - dev server & build
- **echarts** - rendu du graphe sur la page Diagramme

## 🚀 Prochaines étapes

- [x] Remplir `specifications.md` (désormais scindé dans `specifications/`)
- [ ] Activer et documenter l'intégration LDAP (si besoin)
- [ ] Ajouter des tests (aucun actuellement)
- [ ] Authentification / autorisation sur l'API

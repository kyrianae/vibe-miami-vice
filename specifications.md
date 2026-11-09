# Spécifications — Miami Vice

> Document généré par reverse engineering du code source présent dans le dépôt
> au 2026-11-07. Il décrit le fonctionnement **réel** du projet tel qu'implémenté
> (backend `backend/app.py`, frontend `frontend/src/`, modèle `model/*.json`,
> schéma SQL `sql/init.sql`, orchestration `docker-compose.yml`), y compris les
> écarts entre le comportement voulu (docstrings, README) et le comportement
> effectif du code. Les anomalies constatées sont signalées explicitement
> (⚠️) à l'endroit où elles s'appliquent, et résumées en fin de document.

## 0. Avertissement — état réel du code au moment de l'audit

Le fichier `backend/app.py` contient actuellement une **erreur de syntaxe
Python** (`IndentationError`) dans la fonction `get_classes_by_meta_class`
(route `GET /api/read/<meta_class>`, ligne 97) :

```python
cur.execute(
        "SELECT id, meta_class, data FROM definition WHERE meta_class = %s",
        (meta_class,)
    )
    row = cur.fetchone()      # <-- indentation invalide (12 espaces au lieu de 8)
```

`python3 -c "import ast; ast.parse(open('backend/app.py').read())"` échoue avec
`IndentationError: unexpected indent` à cette ligne. Conséquence concrète :
**le module `app.py` ne peut pas être importé**, donc ni `flask run`, ni le
`gunicorn ... app:app` lancé par `backend/Dockerfile` ne peuvent démarrer
l'application. Dans l'état actuel du dépôt, le conteneur `backend` ne sert
aucune requête — toutes les routes documentées ci-dessous sont donc décrites
d'après la lecture du code (comportement *voulu*), avec mention explicite des
bugs logiques supplémentaires qui subsisteraient même une fois cette erreur de
syntaxe corrigée.

## 1. Objectif du projet

Miami Vice est un **modélisateur de données générique** : il permet de définir
un schéma de données (meta-classes → classes → attributs typés, avec
jointures 1-1 et 1-N entre objets) sous forme de JSON, de le charger dans
PostgreSQL, puis de créer/lire/modifier des instances (« objets ») conformes
à ce schéma via une API REST Flask et une interface React.

Le modèle n'est pas figé dans des tables SQL métier : il est entièrement
dynamique — toute entité (« classe ») et ses attributs sont décrits dans des
documents JSON stockés en base, interprétés à la volée par le backend et le
frontend. Deux exemples de domaines sont fournis (`model/personnes.json` :
personnes, rôles, groupes ; `model/reseau.json` : adresses IP, VLAN).

## 2. Architecture générale

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

## 3. Modèle de données

### 3.1 Concepts

| Concept | Rôle | Porté par |
|---|---|---|
| **Meta-classe** | Regroupement logique de classes (ex. `personne`, `element_avec_ip`) | table `definition` (une ligne par meta-classe) |
| **Classe** | Type d'objet concret (ex. `personne_physique`, `vlan`) avec sa liste d'attributs | élément du tableau `classes` dans `definition.data` (JSONB) |
| **Attribut (définition)** | Nom + domaine + type (+ contraintes) déclaré sur une classe | élément du tableau `attributes` d'une classe, dans `definition.data` |
| **Objet** | Instance d'une classe | ligne de la table `object` |
| **Attribut (instance)** | Attribut effectivement posé sur un objet donné | ligne de la table `attribute` |
| **Valeur** | Valeur(s) typée(s) d'un attribut d'instance ; une liste de valeurs permet de modéliser des jointures 1-N | ligne(s) de la table `attribute_value` |
| **Jointure** | Référence d'un objet vers un autre objet, typée `joint-1-1` (une seule valeur) ou `joint-1-n` (plusieurs valeurs) | colonne `attribute_value.joint_id` → `object.id` |

### 3.2 `model/schema.json` — contrat JSON Schema des définitions

Validé en théorie par le package `jsonschema` (présent dans
`backend/requirements.txt`), mais ⚠️ **jamais réellement invoqué** : `app.py`
définit bien une fonction `load_schema()` lisant `SCHEMA_PATH`
(`/model/schema.json` par défaut) mais ne l'appelle jamais, et n'importe pas
`jsonschema`. Aucune validation contre ce schéma n'a lieu au runtime, ni à
l'écriture (`/api/write/*`), ni au chargement (`/api/init`).

Structure attendue (draft-07) :

```jsonc
{
  "meta_class": "string",       // requis
  "classes": [                  // requis
    {
      "class": "string",        // requis
      "displayname": "string",  // optionnel — gabarit {{attribut}}
      "attributes": [
        {
          "domain": "string",   // requis
          "name": "string",     // requis
          "type": "string|integer|float|joint-1-1|joint-1-n",  // requis
          "classes": ["string"],      // requis si type est joint-1-1/joint-1-n — classes cibles autorisées
          "constraint": "regexp",     // optionnel, pour type=string
          "sql_constraint": "string"  // optionnel, contrainte SQL libre (jamais appliquée par le code — voir §8)
        }
      ]
    }
  ]
}
```

`additionalProperties: false` à tous les niveaux. ⚠️ Note : les fichiers
`model/personnes.json` et `model/reseau.json` fournis contiennent une clé
`"$schema": "schema.json"` au niveau racine, qui n'est pas déclarée dans
`model/schema.json` — si la validation était un jour activée, ces fichiers
d'exemple échoueraient eux-mêmes à cause de `additionalProperties: false`.

### 3.3 Fichiers de modèle fournis

**`model/personnes.json`** — meta-classe `personne` :
- `personne_physique` : attributs `nom`, `prenom` (domaine `details`, string). `displayname`: `"{{prenom}} {{nom}}"`.
- `role` : `nom` (string) + `membres` (`joint-1-1` → `personne_physique`).
- `groupe` : `nom` (string) + `membres` (`joint-1-n` → `personne_physique` ou `groupe`, donc récursif).

**`model/reseau.json`** — meta-classe `element_avec_ip` :
- `addresse_ip` : `adresse_ip` (string, `constraint` = regex IPv4, `sql_constraint: "UNIQUE VALUE"` — non appliquée par le code, voir §8).
- `vlan` : `nom` (string), `definition` (string, regex CIDR), `membres` (`joint-1-n` → `addresse_ip`).

### 3.4 Tables PostgreSQL (`sql/init.sql`)

```sql
object(id SERIAL PK, meta_class TEXT NOT NULL, class TEXT NOT NULL)

attribute(id SERIAL PK, object_id INT NOT NULL REFERENCES object(id) ON DELETE CASCADE,
          domain TEXT NOT NULL, name TEXT NOT NULL)

attribute_value(id SERIAL PK, attribute_id INT NOT NULL REFERENCES attribute(id) ON DELETE CASCADE,
                 value_integer INT, value_float DOUBLE PRECISION, value_string TEXT,
                 joint_id INT REFERENCES object(id) ON DELETE SET NULL,
                 CHECK (exactement une des 4 colonnes de valeur est non-NULL))

definition(id SERIAL PK, meta_class TEXT NOT NULL UNIQUE, data JSONB NOT NULL)
```

Points clés :
- Une **jointure 1-N** se modélise simplement par **plusieurs lignes**
  `attribute_value` pour le même `attribute_id` (une jointure 1-1 n'en a
  qu'une seule) — il n'y a pas de distinction structurelle en base entre
  1-1 et 1-N, seule la définition JSON (`type`) encode cette contrainte ;
  rien en SQL n'empêche d'insérer plusieurs valeurs sous un attribut
  déclaré `joint-1-1`.
- `attribute_value.joint_id` a `ON DELETE SET NULL` : supprimer l'objet
  cible d'une jointure ne supprime pas l'attribut source, mais met son
  `joint_id` à `NULL` (valeur « orpheline », distincte d'une valeur
  scalaire — elle resterait alors invisible côté lecture, voir §4).
- `object`/`attribute` sont en `ON DELETE CASCADE` : supprimer un objet
  supprime tous ses attributs et leurs valeurs. ⚠️ Mais **aucune route de
  suppression d'objet n'existe** dans `app.py` — il n'y a pas de
  `DELETE /api/...` pour les objets, les classes ou les meta-classes.
- `definition.data` stocke **le JSON de définition tel quel**
  (`{"meta_class": ..., "classes": [...]}`), c'est la seule table qui
  porte le schéma ; `object`/`attribute`/`attribute_value` ne référencent
  jamais `definition` par clé étrangère — la cohérence entre schéma déclaré
  et objets stockés n'est pas imposée par la base.

## 4. API Backend — contrat des endpoints

Base URL : `/api`. Toutes les réponses sont en JSON (`jsonify`). Il n'y a
aucune authentification. Les erreurs de validation (`abort(400/404)`)
renvoient le format d'erreur HTML/JSON par défaut de Flask (`{"description":
...}` n'est pas garanti — Flask `abort()` produit par défaut une page
d'erreur standard contenant le message dans son corps ; aucun gestionnaire
d'erreur JSON personnalisé n'est défini). Toute exception non prévue dans un
endpoint d'écriture est « rattrapée » (`except Exception as e: conn.rollback();
raise e`) puis **re-levée telle quelle** — donc une `HTTPException`
(`abort`) ressort bien avec son code HTTP d'origine, mais une erreur
inattendue (ex. contrainte SQL violée) ressort en 500 avec la trace Flask
par défaut.

### 4.1 Lecture des définitions

**`GET /api/read/meta_class`**
Liste toutes les meta-classes.
Réponse `200` : `[{"id": int, "meta_class": str}, ...]` (triées par nom).

**`GET /api/read/class`**
Liste toutes les classes de toutes les meta-classes (à plat).
Réponse `200` : `[{"meta_class": str, "class": str, "attributes": [...]}, ...]`.
⚠️ Le champ `displayname` défini dans `definition.data` **n'est jamais
renvoyé** par cet endpoint (le code ne le recopie pas dans l'objet JSON de
sortie), alors que le frontend (`ClassInfo`, `types.ts`) s'attend à pouvoir
le lire ici pour résoudre l'affichage des objets (voir §6.7).

**`GET /api/read/class/<int:class_id>`**
Récupère une classe par un **index global** 1-based calculé en parcourant
toutes les classes de toutes les meta-classes (ordre : meta-classes triées
par nom, puis ordre d'apparition dans le tableau `classes` de chaque
définition) — ce n'est pas un identifiant stable en base, il change si une
classe est ajoutée/supprimée avant elle dans cet ordre.
Réponse `200` : `{"id": int, "meta_class": str, "class": str, "attributes": [...]}` (sans `displayname`, même limitation que ci-dessus).
Réponse `404` si l'index dépasse le nombre total de classes (`"Classe non trouvée"`).

**`GET /api/read/<string:meta_class>`**
Récupère toutes les classes d'une meta-classe donnée (correspondance exacte
et sensible à la casse sur la colonne `meta_class`).
Réponse `200` : `{"meta_class": str, "classes": [{"class": str, "attributes": [...]}, ...]}` (sans `displayname`).
Réponse `404` si la meta-classe n'existe pas (`"Meta-classe '<x>' non trouvée"`).
⚠️ **C'est dans le corps de cette fonction que se trouve l'erreur de syntaxe
décrite en §0** — dans l'état actuel du dépôt, non seulement cette route est
inatteignable, mais **aucune route du backend ne l'est**, le fichier entier
étant syntaxiquement invalide.
Note de routage (comportement normal de Flask/Werkzeug, indépendant du bug
ci-dessus) : une meta-classe nommée littéralement `class`, `meta_class`,
`objects` ou `object` ne pourrait jamais être atteinte via cette route
générique, car Werkzeug priorise les règles statiques (`/api/read/class`,
`/api/read/meta_class`, `/api/read/objects`) sur la règle à segment
variable `/api/read/<meta_class>`.

### 4.2 Lecture des objets

**`GET /api/read/objects`**
Liste tous les objets **sans leurs attributs**.
Réponse `200` : `[{"id": int, "meta_class": str, "class": str}, ...]` (triés par `id`).

**`GET /api/read/object/<int:object_id>`**
Censé récupérer un objet avec tous ses attributs et valeurs, sous la forme :
```json
{
  "id": 1, "meta_class": "personne", "class": "personne_physique",
  "attributes": [
    {"domain": "details", "name": "nom", "values": ["Doe"]},
    {"domain": "liens", "name": "employeur", "values": [{"joint_id": 4}]}
  ]
}
```
⚠️ **Bug logique indépendant du §0** : dans le code tel qu'écrit, le bloc qui
construit et retourne cette réponse est placé **à l'intérieur** du
`if not obj:` (sous l'appel à `abort(404, ...)`), donc :
- objet **inexistant** → `abort(404)` s'exécute normalement (le code mort
  qui suit n'est jamais atteint, pas d'erreur visible) → réponse `404`
  correcte « Objet non trouvé ».
- objet **existant** → la condition `if not obj` est fausse, tout le bloc
  (y compris `return jsonify(obj)`) est sauté, la fonction se termine sans
  `return` → Flask lève `TypeError: The view function did not return a
  valid response` → réponse `500`.
Autrement dit, **cet endpoint ne renvoie jamais les attributs d'un objet
existant** dans l'état actuel du code ; il échoue systématiquement en 500
pour tout objet réellement présent en base.

### 4.3 Écriture des objets

**`POST /api/write/object`**
Corps attendu :
```json
{
  "id": 12,                         // optionnel : présent = mise à jour, absent = création
  "meta_class": "personne",
  "class": "personne_physique",
  "attributes": {
    "nom": "Doe",
    "prenom": "John",
    "employeur": {"joint_id": 4},          // joint-1-1 : objet unique
    "collegues": [{"joint_id": 5}, {"joint_id": 6}]  // joint-1-n : liste
  }
}
```
Comportement :
- `400` si `meta_class` ou `class` absents du corps.
- Si `id` fourni : vérifie que l'objet existe (`404` sinon), **remplace**
  `meta_class`/`class`, puis **supprime tous les attributs et valeurs
  existants de l'objet** et les recrée intégralement à partir du corps
  (ce n'est pas un *merge* — tout attribut non repassé dans `attributes`
  disparaît).
- Si `id` absent : crée une nouvelle ligne `object`.
- Pour chaque attribut du corps, le `domain` est recherché dans la
  définition JSON de la classe (si trouvée) ; sinon `domain = "default"`.
  ⚠️ **Aucune validation** n'est faite contre le schéma déclaré : on peut
  écrire un attribut dont le nom n'existe pas dans la classe, ou créer un
  objet avec une `meta_class`/`class` qui n'a jamais été définie dans
  `definition` — l'objet est créé quand même (typage/contraintes
  `constraint`/`sql_constraint` jamais vérifiés).
- Typage de la valeur stockée (fonction `_insert_value`) : dict avec clé
  `joint_id` → colonne `joint_id` ; `int` Python → `value_integer` ;
  `float` Python → `value_float` ; tout le reste → `str(valeur)` dans
  `value_string`. Comme le corps est du JSON, un nombre écrit sans guillemets
  (`"age": 30`) est un entier, un nombre avec guillemets (`"age": "30"`)
  finit en `value_string`.
  Exemples concrets (`backend/app.py`, lignes ~267-285) : un booléen JSON
  (`true`/`false`) est stocké comme entier `1`/`0` dans `value_integer`, car
  `bool` est une sous-classe de `int` en Python et le test `isinstance(value,
  int)` est vrai avant même d'atteindre le cas générique ; un dict sans clé
  `joint_id` (ex. `{"x": 1}`) ne correspond à aucun des cas typés et tombe
  dans la branche générique, finissant stocké tel quel comme repr Python
  dans `value_string` (ex. `"{'x': 1}"`).
- Réponse `201 Created` + `{"status":"ok","id":int,"action":"created"}` à la
  création ; `200 OK` + `{"status":"ok","id":int,"action":"updated"}` à la
  mise à jour.

**`PUT /api/write/attribute/<string:cls>/<int:object_id>/<string:attribute>/<string:value>`**
Écrit (crée ou remplace) **une seule valeur scalaire** d'un attribut
d'objet, directement via l'URL (pas de corps JSON).
- `404` si l'objet `object_id` n'existe pas (`"Objet non trouvé"`).
- `400` si la classe réelle de l'objet ≠ `cls` (`"L'objet <id> n'est pas de classe '<cls>'"`).
- Si l'attribut `attribute` n'existe pas encore sur l'objet, il est créé
  (domain recherché dans la définition de la meta-classe de l'objet, sinon
  `"default"`) ; s'il existe déjà, **toutes ses valeurs existantes sont
  supprimées** puis remplacées par la nouvelle valeur unique.
- `value` est toujours une chaîne (segment d'URL) : le code tente
  `int(value)`, puis `float(value)`, sinon la stocke comme `value_string`.
  ⚠️ Il est donc **impossible d'écrire une jointure (`joint_id`)** via cet
  endpoint — seules des valeurs scalaires peuvent être posées. Rien n'empêche
  non plus d'appeler cet endpoint sur un attribut déclaré `joint-1-1`/`joint-1-n`
  dans le schéma : la valeur serait alors stockée comme scalaire, en
  contradiction avec le type déclaré, et deviendrait invisible/mal interprétée
  par `GET /api/read/object/<id>` qui attend un `joint_id`.
- Réponse `200` (implicite) : `{"status":"ok","object_id":int,"attribute":str,"value":str}`.
- ⚠️ **Non utilisé par le frontend** : `apiWriteAttribute` existe bien dans
  `frontend/src/api.ts` mais n'est importé/appelé nulle part — voir §6.7.

### 4.4 Écriture des définitions de schéma

**`POST /api/write/class`**
Corps : `{"meta_class": str, "class": {"class": str, "attributes": [...]}}`.
- `400` si `meta_class` ou `class` absents, ou si `class` n'a pas lui-même
  les clés `class`/`attributes`.
- `404` si la meta-classe `meta_class` n'existe pas encore dans `definition`
  (message : « ...Créez-la d'abord avec /api/write/metaclass »).
- Si une classe du même nom existe déjà dans cette meta-classe, elle est
  **intégralement remplacée** (pas de fusion d'attributs — il faut renvoyer
  la liste complète des attributs désirés, y compris ceux déjà existants) ;
  sinon la classe est ajoutée au tableau.
- Réponse `201` (créée) ou `200` (remplacée) : `{"status":"ok","action":"created"|"updated","class":str}`.

**`POST /api/write/metaclass`**
Corps : `{"meta_class": str, "classes": [...]}` (même format que les
fichiers `model/*.json`, sans la clé `$schema`).
- `400` si `meta_class` ou `classes` absents.
- Si la meta-classe existe déjà, son `data` est **entièrement remplacé**
  (toutes les classes précédemment définies pour cette meta-classe sont
  perdues si elles ne sont pas réincluses dans `classes`) ; sinon une
  nouvelle ligne `definition` est créée.
- Réponse `201` (créée) ou `200` (remplacée) : `{"status":"ok","action":"created"|"updated","meta_class":str}`.

### 4.5 Initialisation depuis les fichiers modèles

**`POST /api/init`**
Pas de corps attendu. Parcourt le dossier `MODEL_DIR` (env var, défaut
`/model`, monté dans le conteneur backend depuis `./model` du host),
pour chaque fichier `*.json` **sauf `schema.json`** :
- charge le JSON ; si les clés `meta_class`/`classes` sont absentes, le
  fichier est **silencieusement ignoré** (pas d'erreur retournée) ;
- sinon, upsert dans `definition` : `INSERT ... ON CONFLICT (meta_class) DO
  UPDATE SET data = EXCLUDED.data` — remplace entièrement les classes de
  cette meta-classe si elle existait déjà.
- Réponse `200` : `{"status":"ok","loaded": ["personne", "element_avec_ip", ...]}`
  (noms des meta-classes effectivement chargées ; ordre dépendant de
  l'ordre renvoyé par `os.listdir`, non garanti alphabétique).
- Aucune validation JSON Schema n'est appliquée (voir §3.2).

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

## 6. Frontend

### 6.1 Structure générale

- `main.tsx` : point d'entrée, monte `<App />` dans `#root` (mode
  `StrictMode`).
- `App.tsx` : état global applicatif tenu en `useState` local (pas de
  state manager externe, pas de routeur — la « page » active est une
  simple variable d'état `'navigation' | 'configuration' | 'diagramme'`) :
  page courante, repli de la sidebar, bascule lecture seule (`readOnly`),
  thème (`'dark' | 'midnight' | 'light'`), meta-classe/classe sélectionnées
  (partagées entre Sidebar et la page affichée). Le thème est appliqué en
  posant l'attribut `data-theme` sur `<html>`. **Rien n'est persisté**
  (ni `localStorage` ni cookie) : un rechargement de page réinitialise
  toujours au thème `dark`, lecture-écriture, et sidebar ouverte.
- `components/Navbar.tsx` : titre, 3 boutons de changement de page,
  sélecteur de thème, interrupteur RO/RW.
- `components/Sidebar.tsx` : charge `apiReadClasses()` au montage et à
  chaque changement de page, affiche un arbre meta-classe → classes
  (regroupement calculé côté client), piloté par clic (toggle
  sélection/désélection). Le choix ici alimente les 3 pages via les props
  `selectedMetaClass`/`selectedClass` de `App.tsx`.

### 6.2 Page Navigation (`pages/NavigationPage.tsx`)

Vue tableau des objets, groupés par (meta-classe, classe), avec panneaux
dépliables par groupe.
- Au montage : charge `apiReadObjects()` (liste légère) et
  `apiReadClasses()` (définitions, pour connaître colonnes/types/`displayname`).
- Quand un groupe est déplié (ou que le filtre sidebar change), charge en
  parallèle le détail (`apiReadObject(id)`) de chaque objet du groupe pour
  peupler un cache (`detailCache`), nécessaire pour afficher les valeurs
  réelles des attributs et résoudre les jointures en libellé lisible.
  ⚠️ Avec le bug §4.2 (`GET /api/read/object/<id>` en échec pour tout
  objet existant), ces appels échoueraient systématiquement et les cellules
  resteraient affichées en `…` (indicateur de chargement) indéfiniment.
  Ce même bug produit aussi, ailleurs dans cette page, des messages
  contradictoires ou trompeurs plutôt qu'un simple blocage silencieux :
  - `handleSave` (modale de création/édition, lignes ~356-366) : après un
    `apiWriteObject` réussi, un toast de succès (« Objet créé/mis à jour »)
    est affiché, puis le code tente de rafraîchir le cache de détail via
    `apiReadObject(editingObjectId)` en cas d'édition ; cet appel échouant à
    cause du bug, un toast d'erreur contradictoire apparaît juste après le
    toast de succès, alors que l'écriture a bien réussi.
  - `handleQuickCreateSave` (ligne ~554) : même mécanisme sur le chemin de
    création rapide (« quick-create ») d'un objet cible depuis un champ
    joint — `apiWriteObject` réussit et crée l'objet en base, mais le
    `apiReadObject(res.id)` qui suit pour peupler le cache de détail échoue,
    déclenchant un toast « Erreur création » qui est un **faux négatif** :
    l'objet existe bel et bien en base malgré le message d'erreur affiché.
- Filtres par classe (boutons à bascule) quand une meta-classe est
  sélectionnée dans la sidebar.
- Résolution du nom affiché (`resolveDisplayName`) : si `classDef.displayname`
  est défini, remplace chaque `{{attribut}}` par la première valeur de cet
  attribut (ou `#id` si c'est une jointure) ; sinon concatène les valeurs
  des attributs de domaine `details`. ⚠️ Comme `GET /api/read/class`
  ne renvoie jamais `displayname` (§4.1), **cette branche n'est en pratique
  jamais empruntée** : c'est toujours le fallback (concaténation du domaine
  `details`) qui s'applique, même pour des classes ayant un `displayname`
  configuré (ex. `"{{prenom}} {{nom}}"` de `personne_physique`).
- Création/édition d'objet via une modale : sélection meta-classe/classe
  (ou préremplie depuis la sidebar), un champ par attribut scalaire, un
  `<select>` pour les jointures `joint-1-1`, une interface « disponibles /
  sélectionnés » à deux colonnes pour les jointures `joint-1-n`, avec
  possibilité de créer à la volée (« + Créer un X ») un objet cible
  directement depuis le champ joint (quick-create). Sauvegarde via
  `apiWriteObject` (avec `id` si édition).
- Édition inline au clic sur une cellule :
  - cellule `joint-1-n` → ouvre une modale dédiée (même UI deux colonnes)
    sauvegardée via `apiWriteObject` (reconstruit tout le corps `attributes`
    de l'objet, y compris les autres attributs, pour ne rien perdre lors
    du remplacement complet côté backend).
  - cellule `joint-1-1` → `<select>` inline.
  - cellule scalaire → `<input>` inline.
  - ⚠️ **Bug** : la fonction `saveInlineEdit` (appelée au blur/Enter des
    éditions scalaires et `joint-1-1` inline) ne fait **aucun appel réseau
    d'écriture** — le code contient des commentaires indiquant qu'un appel à
    `apiWriteAttribute` (`PUT /api/write/attribute/...`) « devrait » être
    fait, mais cet appel est resté commenté/non implémenté : la fonction se
    contente de re-télécharger l'objet (`apiReadObject`) et d'afficher un
    toast de succès. **L'édition inline de valeurs scalaires et de jointures
    1-1 ne persiste donc jamais rien en base**, bien que l'UI affiche un
    message de succès. Seules la création/édition via la modale complète et
    l'édition des jointures `joint-1-n` (via `jointEdit`, qui appelle
    `apiWriteObject`) écrivent réellement.
- Bascule lecture seule (`readOnly`, héritée de `Navbar`) : désactive
  côté UI uniquement (pas de contrôle serveur) les boutons de création, le
  double-clic d'édition et le clic sur cellule.
  ⚠️ Ce prop `readOnly` n'est transmis qu'à `NavigationPage` : dans
  `frontend/src/App.tsx` (lignes 41-52), seul l'appel à `<NavigationPage>`
  reçoit `readOnly={readOnly}` ; les appels à `<ConfigurationPage>` et
  `<DiagramPage>` ne reçoivent pas ce prop du tout. Conséquence : basculer
  en lecture seule ne restreint jamais rien sur la page Configuration — un
  utilisateur en mode RO peut y créer/modifier/supprimer librement
  meta-classes, classes et attributs, sans aucun signal visuel ni
  restriction côté UI, contrairement à la page Navigation où le toggle
  désactive au moins les contrôles correspondants.
- Notifications « toast » (succès/erreur) en haut à droite, auto-disparition
  après 5 s avec animation de fondu.

### 6.3 Page Configuration (`pages/ConfigurationPage.tsx`)

Éditeur du schéma (CRUD des meta-classes/classes/attributs) :
- Si une meta-classe est sélectionnée dans la sidebar : charge sa
  définition via `apiReadMetaClass(nom)` (`GET /api/read/<meta_class>`) et
  préremplit le formulaire ; sinon formulaire vierge (création d'une
  nouvelle meta-classe).
  ⚠️ Comme `GET /api/read/<meta_class>` ne renvoie pas `displayname`
  (§4.1), le champ « Displayname » apparaît toujours vide au rechargement
  d'une classe existante, même si un `displayname` a été précédemment
  enregistré — perte d'affichage (pas de perte en base : l'écriture, elle,
  conserve bien `displayname` tel quel dans `definition.data`).
- Édition multi-classes : chaque classe est une carte dépliable, avec nom,
  `displayname`, et un tableau d'attributs (domaine, nom, type, options).
  Pour un attribut de type `joint-1-1`/`joint-1-n`, les « classes cibles »
  se choisissent par boutons à bascule parmi toutes les classes déjà
  connues (`apiReadClasses()`) + celles en cours de saisie localement ;
  sinon deux champs libres `constraint` (regex) et `sql_constraint`.
  Attributs réordonnables (▲/▼), ajout/suppression de classes et
  d'attributs (toujours au moins 1 classe et 1 attribut par classe).
- Bouton « Charger depuis model/ » → `apiInit()` (`POST /api/init`).
- Bouton « Sauvegarder » → nettoie les classes/attributs vides puis envoie
  `apiWriteMetaClass` (`POST /api/write/metaclass`) avec **la totalité**
  des classes actuellement affichées dans le formulaire (remplacement
  complet de la meta-classe côté backend, cf. §4.4).

### 6.4 Page Diagramme (`pages/DiagramPage.tsx`)

Graphe interactif (bibliothèque **ECharts**, composant `series: graph` ou
`tree`) :
- Charge tous les objets (`apiReadObjects`), toutes les classes
  (`apiReadClasses`), puis le détail de chaque objet (`apiReadObject`,
  avec tolérance aux échecs individuels via `.catch(() => null)`) pour
  extraire les relations de jointure (`joint_id`) comme arêtes du graphe.
- 3 layouts sélectionnables : **Force** (disposition physique, répulsion/
  gravité), **Circulaire**, **Organigramme** (reconstruction d'un arbre à
  partir des nœuds sans arête entrante comme racines ; les nœuds orphelins
  non atteints sont ajoutés séparément).
- Chaque classe a une couleur assignée depuis une palette fixe de 10
  couleurs (cyclique si plus de 10 classes).
- Filtres : chips par classe (regroupées par meta-classe) pour
  masquer/afficher, boutons « Tout »/« Rien ».
- Infobulle au survol d'un nœud (nom résolu + classe + id) ; redimensionnement
  automatique du graphe via `ResizeObserver` et l'événement `resize` de la
  fenêtre ; nettoyage (`dispose()`) de l'instance ECharts au démontage.
- Même logique `resolveDisplayName` que la page Navigation, avec la même
  limitation (§6.2) : `displayname` n'étant jamais renvoyé par l'API, les
  étiquettes des nœuds utilisent toujours le fallback (concaténation du
  domaine `details`).

### 6.5 Thèmes

3 thèmes CSS définis dans `styles.css` via l'attribut `data-theme` sur la
racine du document : `dark` (défaut), `midnight`, `light`. Changement
instantané sans rechargement, non persisté entre sessions.

### 6.6 Client API (`src/api.ts`)

Wrapper `fetch` minimal (`fetchJson`), pas d'Axios, erreurs levées comme
`Error("<status>: <corps texte de la réponse>")` en cas de réponse non-`ok`.

| Fonction | Méthode + URL |
|---|---|
| `apiReadMetaClasses()` | `GET /api/read/meta_class` |
| `apiReadClasses()` | `GET /api/read/class` |
| `apiReadClassById(id)` | `GET /api/read/class/:id` |
| `apiReadMetaClass(metaClass)` | `GET /api/read/:metaClass` |
| `apiReadObjects()` | `GET /api/read/objects` |
| `apiReadObject(id)` | `GET /api/read/object/:id` |
| `apiWriteMetaClass(data)` | `POST /api/write/metaclass` |
| `apiWriteClass(metaClass, cls)` | `POST /api/write/class` |
| `apiWriteObject(data)` | `POST /api/write/object` |
| `apiWriteAttribute(cls, id, attribute, value)` | `PUT /api/write/attribute/:cls/:id/:attribute/:value` — ⚠️ définie mais jamais appelée dans le code frontend actuel |
| `apiInit()` | `POST /api/init` |

### 6.7 Récapitulatif des anomalies frontend

- `displayname` configuré dans le modèle n'a aucun effet visible, car
  aucun endpoint de lecture ne le renvoie (cause backend, §4.1) — impacte
  `NavigationPage` et `DiagramPage`.
- Le bug §4.2 (`GET /api/read/object/<id>`) ne se limite pas à un blocage
  silencieux (cellules bloquées sur `…`) : il produit aussi, via le
  re-fetch post-écriture, de **faux messages d'erreur** dans
  `NavigationPage.tsx` alors que l'écriture a réussi — toast d'erreur
  contradictoire juste après un toast de succès dans `handleSave` (édition,
  lignes ~356-366), et faux négatif « Erreur création » dans
  `handleQuickCreateSave` (ligne ~554) alors que l'objet est bien créé en
  base.
- L'édition inline de cellules scalaires et de jointures `joint-1-1` dans
  la page Navigation ne sauvegarde rien côté serveur (`saveInlineEdit` ne
  fait pas d'appel réseau d'écriture) tout en affichant un toast de succès
  trompeur.
- Le toggle lecture seule (RO/RW) et les thèmes sont des états purement
  côté client, non persistés et sans portée sur l'API (aucune autorisation
  réelle n'est appliquée côté serveur).

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

## 8. Dépendances déclarées mais non exploitées par le code

- `jsonschema` (backend) : dépendance présente, jamais utilisée (§3.2, §4.5).
- `sql_constraint` (modèle JSON) : champ documenté dans `model/schema.json`
  et renseigné dans `model/reseau.json` (`"UNIQUE VALUE"` sur `adresse_ip`),
  mais **jamais lu ni appliqué** par `app.py` — aucune contrainte SQL n'est
  générée dynamiquement à partir de cette valeur ; la table `attribute_value`
  ne porte aucune contrainte d'unicité par attribut.
- `constraint` (regex de validation d'un attribut `string`) : également
  jamais vérifié côté backend à l'écriture (`POST /api/write/object`,
  `PUT /api/write/attribute/...`) — seul le frontend l'affiche comme
  placeholder indicatif dans les formulaires, sans bloquer la saisie.

## 9. Récapitulatif des anomalies constatées (par gravité)

1. **Bloquant** — `backend/app.py` ne compile pas (`IndentationError` ligne
   97, dans `get_classes_by_meta_class`) : l'application Flask ne démarre
   pas du tout dans l'état actuel du dépôt.
2. **Bloquant fonctionnel** (une fois le point 1 corrigé) —
   `GET /api/read/object/<id>` ne retourne jamais les attributs d'un objet
   existant (code de construction de la réponse placé par erreur sous
   `if not obj:`) ; il renvoie une erreur 500 pour tout objet présent en
   base et 404 pour tout objet absent.
3. **Fonctionnel** — `displayname` n'est jamais renvoyé par les 3 endpoints
   de lecture de classes (`/api/read/class`, `/api/read/class/<id>`,
   `/api/read/<meta_class>`), rendant inopérant le gabarit d'affichage
   pourtant bien stocké en base et bien restitué à l'écriture.
4. **Fonctionnel** — l'édition inline (cellule scalaire ou jointure 1-1)
   de la page Navigation n'effectue aucune écriture réelle
   (`saveInlineEdit` dans `NavigationPage.tsx`), malgré un message de
   succès affiché à l'utilisateur ; `apiWriteAttribute`/`PUT
   /api/write/attribute/...` existe côté client et serveur mais n'est
   jamais relié.
5. **Absence de contrôle** — aucune validation du schéma JSON
   (`model/schema.json`) n'est appliquée nulle part (ni à l'écriture des
   définitions, ni au chargement `/api/init`) ; aucune validation de
   `constraint`/`sql_constraint` n'est appliquée à l'écriture des objets ;
   aucune vérification que la `meta_class`/`class` d'un objet écrit via
   `POST /api/write/object` corresponde à une définition existante.
6. **Absence de fonctionnalité** — aucune route de suppression (objet,
   classe ou meta-classe) n'existe, bien que le schéma SQL soit prévu pour
   (`ON DELETE CASCADE`).
7. **Absence de sécurité** — aucune authentification/autorisation sur
   l'API ; le toggle lecture seule du frontend est un simple artifice
   d'interface, sans portée serveur.
8. **Cohérence modèle** — les fichiers `model/personnes.json` et
   `model/reseau.json` contiennent une clé `$schema` non déclarée dans
   `model/schema.json` (`additionalProperties: false`), ce qui les rendrait
   eux-mêmes invalides si la validation décrite au point 5 était un jour
   activée telle quelle.

## 10. Pistes d'évolution et décisions en cours (roadmap)

> Section ajoutée le 2026-11-09, suite à une discussion des notes brutes
> de `tocheck.md` avec l'équipe de revue (optimiste/pessimiste/candide).
> Distincte de §9 : il ne s'agit pas d'anomalies du code actuel, mais
> d'évolutions futures, certaines actées et planifiées (voir `plan.md`),
> d'autres encore ouvertes.

### 10.1 Décisions tranchées (pour mémoire)

- **Déréférencement illimité (`depth=-1`) sur `GET /api/read/object/<id>?deref=true`
  — refusé.** Proposé pour accepter une profondeur illimitée en plus de
  l'intervalle `[0, MAX_DEPTH=5]` actuellement imposé (voir `plan.md`
  action 2bis). Refusé après analyse de l'équipe : le backend tourne avec
  un unique worker Gunicorn synchrone (`backend/Dockerfile`, pas de
  `--workers`/`--threads`), sans aucune authentification sur l'API — une
  requête à profondeur illimitée sur un graphe large (même acyclique,
  donc sans déclencher la détection de cycle déjà en place) peut
  bloquer tout le backend pour tous les utilisateurs, un vecteur de déni
  de service trivial à exploiter. `MAX_DEPTH` reste figé à 5.

### 10.2 Multi-tenant (ouvert — dépend de l'authentification §10.3)

Idée : ajouter une notion de tenant dans la configuration — des classes
accessibles seulement dans certains tenants, des objets rattachés à un ou
plusieurs tenants à la création, et une option « hors tenant » rendant un
objet/une classe accessible depuis n'importe quel tenant.

Analysé comme un changement transversal profond (schéma `object` et
`definition.data`, toutes les routes de lecture/écriture existantes,
UI de sélection de tenant) plutôt qu'un simple filtre. Point bloquant
identifié par l'équipe : **sans authentification réelle, un filtre
tenant n'est qu'un filtre cosmétique** — rien n'empêche un client de
prétendre appartenir à n'importe quel tenant via un simple paramètre/
en-tête, l'API étant entièrement ouverte (§2). L'authentification étant
désormais tranchée (§10.3 : Keycloak), ce point peut être conçu en
détail : les groupes/rôles Keycloak sont un candidat naturel pour porter
la notion de tenant plutôt que de la dupliquer dans une table
applicative — reste à concevoir, pas encore une action du plan.
concevoir en détail qu'une fois l'authentification tranchée.

### 10.3 Authentification (tranché — Keycloak)

Décision utilisateur (2026-11-09) : **Keycloak**, pour couvrir à la fois
des comptes de service (flux `client_credentials`, Bearer JWT sans
interaction utilisateur — automatisation/intégrations) et une connexion
humaine directe par login/mot de passe (*Direct Access Grants*, pertinent
tant que le frontend n'a pas de routeur pour un flux OIDC avec
redirection complet). Comparatif détaillé des 7 options envisagées et
justification : voir `doc/choix-authent.md`. Conception technique
d'implémentation : voir `plan.md` action 7b.

Éléments déjà réunis par l'équipe, à discuter avant de trancher :
- `docker-compose.yml` contient déjà deux services `ldap`/`lam`
  **entièrement commentés et inertes** (§7) — un investissement de départ
  jamais câblé au code.
- Keycloak fédérerait LDAP (service déjà présent), Google (OIDC) et SSO
  (SAML/OIDC) derrière un seul protocole côté backend (validation JWT),
  réduisant la surface de code d'authentification custom dans `app.py` —
  mais ajoute un service stateful supplémentaire à l'infrastructure
  (actuellement « stateless côté HTTP », §2).
- `plan.md` action 7b prévoit déjà une étape intermédiaire volontairement
  minimale (clé API statique via en-tête `Authorization`) avant toute
  authentification structurante — à clarifier si LDAP/Google/SSO/Keycloak
  remplace ou prolonge cette étape.
- Dépendance avec §10.2 (tenant) : les groupes/rôles Keycloak pourraient
  directement porter la notion de tenant plutôt que de la dupliquer dans
  une table applicative séparée — à trancher conjointement.

### 10.4 Historisation des objets et attributs (acté — voir `plan.md` action 6 révisée)

Décision utilisateur (2026-11-09) : implémenter une historisation
temporelle des attributs (`valid_from`/`valid_to` sur `attribute_value`)
et une suppression **logique** des objets (`deleted_at` sur `object`,
fermeture de tous les attributs actifs), suivie d'une **purge physique
différée** après une période de grâce (valeur encore à confirmer — 30
jours proposé à titre provisoire). Conception détaillée et prérequis
technique (réécriture de `POST /api/write/object`, aujourd'hui un
delete-then-recreate incompatible avec un diff versionné) : voir `plan.md`
action 6 (révisée). L'affichage d'un historique de versions dans l'UI est
explicitement reporté — seul le stockage historisé est prévu pour
l'instant ; un TODO d'implémentation future de cette UI est noté ici pour
mémoire.

### 10.5 Partitionnement PostgreSQL par type d'objet (acté comme piste à évaluer — voir `plan.md` action 9)

Idée : partitionner la table `object` (et éventuellement
`attribute`/`attribute_value`) par `class`/`meta_class` pour la
performance. Réserve de l'équipe, documentée dans `plan.md` action 9 :
le modèle est entièrement dynamique (classes définies en JSON dans
`definition.data`, créées/renommées à chaud sans aucun DDL), alors que le
partitionnement déclaratif PostgreSQL exige de connaître les valeurs de
partition à l'avance et un DDL (`ATTACH PARTITION`) par nouvelle classe —
tension de fond avec le principe même du projet (§1). Aucune volumétrie
réelle ne justifie aujourd'hui ce chantier ; à n'engager qu'après mesure
d'un besoin de performance concret.

### 10.6 Liens transitifs du graphe au filtrage (acté — voir `plan.md` action 10)

Idée : dans la page Diagramme (`DiagramPage.tsx`), quand un filtre de
classe masque un nœud intermédiaire d'une chaîne de jointures (A→B→C, B
masqué), préserver la connexion logique en reliant A→C directement plutôt
que de perdre les deux arêtes. Conception détaillée (fermeture
transitive, gestion des cycles, distinction visuelle des arêtes
reconstituées) : voir `plan.md` action 10.

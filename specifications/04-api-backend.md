# 4. API Backend — contrat des endpoints

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

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

## 4.1 Lecture des définitions

**`GET /api/read/meta_class`**
Liste toutes les meta-classes.
Réponse `200` : `[{"id": int, "meta_class": str}, ...]` (triées par nom).

**`GET /api/read/class`**
Liste toutes les classes de toutes les meta-classes (à plat).
Réponse `200` : `[{"meta_class": str, "class": str, "displayname": str|None,
"tenants": ..., "layers": ..., "icon": ..., "attributes": [...]}, ...]`.
Le champ `displayname` défini dans `definition.data` **est bien renvoyé**
par cet endpoint (`cls.get("displayname")` recopié dans l'objet JSON de
sortie, `backend/routes/routes_read.py:39`), et le frontend (`ClassInfo`,
`types.ts`) le lit effectivement ici pour résoudre l'affichage des objets
(voir §6.7).

**`GET /api/read/class/<int:class_id>`**
Récupère une classe par un **index global** 1-based calculé en parcourant
toutes les classes de toutes les meta-classes (ordre : meta-classes triées
par nom, puis ordre d'apparition dans le tableau `classes` de chaque
définition) — ce n'est pas un identifiant stable en base, il change si une
classe est ajoutée/supprimée avant elle dans cet ordre.
Réponse `200` : `{"id": int, "meta_class": str, "class": str, "displayname":
str|None, "tenants": ..., "layers": ..., "icon": ..., "attributes": [...]}`
(`displayname` inclus, même comportement que ci-dessus,
`backend/routes/routes_read.py:82`).
Réponse `404` si l'index dépasse le nombre total de classes (`"Classe non trouvée"`).

**`GET /api/read/<string:meta_class>`**
Récupère toutes les classes d'une meta-classe donnée (correspondance exacte
et sensible à la casse sur la colonne `meta_class`).
Réponse `200` : `{"meta_class": str, "classes": [{"class": str, "displayname":
str|None, "tenants": ..., "layers": ..., "icon": ..., "attributes": [...]},
...]}` (`displayname` inclus, `backend/routes/routes_read.py:111`).
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

## 4.2 Lecture des objets

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

## 4.3 Écriture des objets

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

## 4.4 Écriture des définitions de schéma

**`POST /api/write/class`**
Corps : `{"meta_class": str, "class": {"class": str, "attributes": [...]}}`.
- `400` si `meta_class` ou `class` absents, ou si `class` n'a pas lui-même
  les clés `class`/`attributes`.
- `404` si la meta-classe `meta_class` n'existe pas encore dans `definition`
  (message : « ...Créez-la d'abord avec /api/write/metaclass »).
- `409` si `class.attributes` contient deux déclarations du même nom
  (`_check_attribute_names_unique`, plan-mark3.md action 21bis — cause
  racine d'une incohérence de chiffrement/masquage si l'une des deux
  déclarations est de type `secret`, voir §4.7).
- Si une classe du même nom existe déjà dans cette meta-classe, elle est
  **intégralement remplacée** (pas de fusion d'attributs — il faut renvoyer
  la liste complète des attributs désirés, y compris ceux déjà existants) ;
  sinon la classe est ajoutée au tableau.
- Réponse `201` (créée) ou `200` (remplacée) : `{"status":"ok","action":"created"|"updated","class":str}`.

**`POST /api/write/metaclass`**
Corps : `{"meta_class": str, "classes": [...]}` (même format que les
fichiers `model/*.json`, sans la clé `$schema`).
- `400` si `meta_class` ou `classes` absents.
- Corps accepte un champ optionnel `"version"` (entier >= 1, défaut `1` si
  absent), propagé tel quel dans `data` ; `400` si ce n'est pas un entier
  valide, notamment un float à valeur entière (ex. `2.0`) est rejeté.
- `409` si `classes` contient deux entrées du même nom de classe DANS CE
  MÊME payload (`_check_no_duplicate_class_names_in_payload`, plan-mark3.md
  action 21bis — distinct de la vérification `_check_class_name_unique`
  ci-dessous, qui ne compare qu'aux AUTRES meta-classes déjà en base) ; puis
  `409` si l'une des classes du payload contient deux attributs du même nom
  (`_check_attribute_names_unique`, même action, même contrôle que
  `POST /api/write/class` ci-dessus).
- Si la meta-classe existe déjà, son `data` est **entièrement remplacé**
  (toutes les classes précédemment définies pour cette meta-classe sont
  perdues si elles ne sont pas réincluses dans `classes`) ; sinon une
  nouvelle ligne `definition` est créée.
- Réponse `201` (créée) ou `200` (remplacée) : `{"status":"ok","action":"created"|"updated","meta_class":str}`.

## 4.5 Initialisation depuis les fichiers modèles

**`POST /api/init`**
Pas de corps attendu. Parcourt **tous** les fichiers du dossier
`MODEL_DIR` (env var, défaut `/model`) — c'est le dossier `./model` du
host, monté dans le conteneur `backend` via `docker-compose.yml`
(`volumes: - ./model:/model`) ; tout fichier `*.json` qu'on dépose dans
`./model/` sur le host est donc automatiquement vu par `/api/init`, sans
modifier le code ni la config. Pour chaque fichier `*.json` **sauf
`schema.json`** :
- charge le JSON ; si les clés `meta_class`/`classes` sont absentes, le
  fichier est **silencieusement ignoré** (pas d'erreur retournée) ;
- validation JSON Schema appliquée (`jsonschema.validate` contre
  `model/schema.json`, voir §3.2) : fichier invalide au regard du schéma
  → **pas d'erreur HTTP**, l'entrée est ajoutée à `skipped` avec la
  raison, le chargement des autres fichiers continue ;
- unicité des noms (action 21bis, `plan-mark3.md`, trou identifié après le
  correctif initial sur `write_class`/`write_metaclass`) : une classe
  déclarée deux fois dans le **même fichier** (même `class`), ou un
  attribut déclaré deux fois au sein d'une classe du fichier (`attributes[].name`
  dupliqué, ex. une déclaration `secret` et une non-secrète) → **pas
  d'erreur HTTP**, le fichier entier est ajouté à `skipped` avec la raison
  (`class` renseigné pour le cas attribut dupliqué), **rien n'est persisté**
  pour la meta-classe de ce fichier lors de ce passage, le chargement des
  autres fichiers continue. Détection faite sur le contenu du fichier
  rechargé, **avant** toute fusion avec l'existant en base (branche
  tenant-admin ci-dessous) ;
- RBAC multi-tenant (action 11, `plan-mark2.md`) :
  - `tenant-readonly` → `403` systématique, rien n'est chargé.
  - `tenant-admin` → fusion **classe par classe**, pas un remplacement
    intégral du fichier : une classe déjà existante mais hors du
    périmètre de l'appelant (globale ou taguée pour un autre tenant)
    est laissée inchangée et listée dans `skipped` (jamais re-taguée
    silencieusement) ; une classe déjà en base mais absente du fichier
    rechargé n'est **jamais supprimée** par ce rechargement partiel ;
    le reste (classes nouvelles ou dans son périmètre) est chargé
    normalement.
  - `global-admin` → pas de restriction, les classes du fichier
    remplacent entièrement celles de la meta-classe en base (upsert
    `INSERT ... ON CONFLICT (meta_class) DO UPDATE SET data =
    EXCLUDED.data`).
- Champ `"version"` (optionnel, entier, absent = `1`, action 5
  `plan-mark3.md` — préparation migrations futures, aucune logique de
  migration appliquée pour l'instant) : propagé tel quel dans `data`
  lors du chargement, visible dans la réponse via `versions` ci-dessous.
- Réponse `200` : `{"status":"ok", "loaded": ["personne", "element_avec_ip", ...],
  "skipped": [{"meta_class":str, "file"?:str, "class"?:str, "reason":str}, ...],
  "versions": {"personne": 1, ...}}` — `loaded` reste une liste de noms
  de meta-classes (ordre dépendant de `os.listdir`, non garanti
  alphabétique) pour ne pas casser le frontend existant
  (`ConfigurationPage.tsx` fait `res.loaded.join(', ')`) ; `versions` est
  additif, une entrée par meta-classe effectivement chargée.

## 4.6 Fichiers (`file`/`image`/`csv`), logos et icônes de classe (ajout 2026-11-21, `plan-mark3.md` actions 3-4)

Routes du Blueprint `backend/routes/routes_files.py` (sauf mention
contraire ; chemins packagés depuis `plan-mark3.md` action 12, voir §2bis
de [02-architecture.md](02-architecture.md)), consommant
`backend/files/file_storage.py` (action 2) et
`backend/files/file_validation.py`. Le contenu des attributs `file`/`image`/`csv`
ne transite jamais par le JSON générique de `POST /api/write/object`/
`PUT /api/write/attribute/...` : ces deux routes rejettent explicitement
(`400`) toute tentative d'écrire une valeur sur un attribut de ce type
(`routes/routes_write.py`), afin qu'un appelant ne puisse jamais injecter un
pointeur arbitraire ne correspondant à aucun fichier réellement stocké.
`POST /api/write/object` accepte en plus, depuis l'action 3 itération 2, un
corps `multipart/form-data` (détection sur `request.content_type`) pour
créer **atomiquement** un objet et un ou plusieurs de ses attributs
fichier en une seule transaction (`_write_object_multipart`,
`routes/routes_write.py`) — réservé à la création (`id` interdit dans ce mode).

**Format de pointeur** stocké dans `attribute_value.value_string` (aucune
nouvelle colonne) :
- direct : `"<version>:<nom_fichier>"`, résolu dans le dossier
  `<class>/<object_id>/<attribute>/<version>/` de l'objet/attribut courant.
- référence (action 4, réutilisation d'un logo existant) :
  `"ref:<classe>:<object_id>:<attribut>:<version>:<nom_fichier>"`, résolu
  dans le dossier de l'objet **source** désigné — construit exclusivement
  par `POST .../file/<attribute>/reference` ci-dessous, toujours aplati sur
  l'emplacement physique final (jamais une référence vers une autre
  référence). Le nom de fichier peut lui-même contenir `:` ; seul le
  premier (format direct) ou les 5 premiers (format `ref:`) `:` sont
  significatifs pour le split.

**`POST /api/write/object/<int:object_id>/file/<string:attribute>`**
(`multipart/form-data`, champ `file`) — upload d'une nouvelle version pour
un attribut `file`/`image`/`csv` d'un objet existant et non supprimé
logiquement. Vérifie que l'attribut est bien déclaré `file`/`image`/`csv`
sur la classe de l'objet, applique le même RBAC tenant en écriture que les
autres routes d'écriture (`403` tenant-readonly, `403` hors périmètre
tenant), valide le contenu (`validate_image_content`/`validate_csv_content`,
`file_validation.py` — signature binaire jpg/png, XML bien formé racine
`<svg>` via `defusedxml` pour svg, extension + décodabilité texte pour
csv), écrit via `FileStorage.save(...)` (nom de fichier = `os.path.basename`
du nom reçu), puis ferme/ouvre la ligne `attribute_value` via
`_apply_attribute_diff` (historisation inchangée, `plan-mark2.md` action
6.0). Réponse `200` : `{"status":"ok","object_id":int,"attribute":str,
"version":int,"filename":str,"value":"<pointeur>"}`. Limite de taille :
`app.config["MAX_CONTENT_LENGTH"]` (20 Mo par défaut, configurable via
`MAX_UPLOAD_SIZE_BYTES`), appliquée par Flask/Werkzeug à toute requête.

**`GET /api/read/object/<int:object_id>/file/<string:attribute>`**
(`?version=N` optionnel, sinon version active) — même filtre de lecture
tenant que `_build_object_payload`, résout le pointeur (direct ou `ref:`)
vers son emplacement physique, sert les octets via `FileStorage.read(...)`.
`Content-Type` déduit de l'extension du nom de fichier ;
`Content-Disposition: inline` **uniquement** pour une image jpg/jpeg/png
(attribut déclaré `image`), `attachment` dans tous les autres cas — **y
compris systématiquement pour le SVG**, décision de sécurité actée
(pas de sanitization du contenu SVG à l'upload, trop fragile sans lib
dédiée ; le neutraliser en lecture en ne le servant jamais inline supprime
le vecteur XSS stocké sans prétendre nettoyer le contenu).

**Auto-réparation (self-heal)** : si le fichier résolu (direct ou via
référence) est introuvable sur le storage au moment de la lecture **de la
valeur active** (pas d'une version historique explicite via `?version=N`,
qui peut légitimement avoir été purgée), `_self_heal_broken_pointer` ferme
côté serveur la valeur active de cet attribut sur l'objet affiché
(`valid_to = now()`, filtré sur le `value_string` exact qui a échoué pour
éviter une course avec une réécriture concurrente) avant de répondre `404`
— jamais l'objet source référencé, qui n'est pas en cause. Retombe ainsi
sur le fallback normal (icône de classe puis couleur) dès l'affichage
suivant, plutôt que de laisser un pointeur mort actif indéfiniment.

**`POST /api/write/object/<int:object_id>/file/<string:attribute>/reference`**
(corps JSON `{"class":str,"object_id":int,"attribute":str,"version":int}`)
— réutilise le fichier déjà stocké d'un **autre** objet (typiquement un
logo) sans dupliquer les octets : construit un pointeur `ref:...` toujours
aplati sur l'emplacement physique final. RBAC : mêmes gardes que l'upload
sur l'objet/la classe **destination** ; l'objet **source** doit en plus
être visible par l'appelant (même filtre tenant que les routes de lecture)
et le fichier source doit exister sur le storage (`400` sinon), pour
qu'un tenant ne puisse pas référencer — et donc exposer indirectement — le
fichier d'un objet hors de son périmètre.

**`GET /api/logos`** — liste les logos actifs (attribut réservé `logo`,
domaine `display`, type `image`), filtrée par le même `_tenant_read_filter`
que les routes de lecture d'objet. Chaque entrée expose l'emplacement
physique déjà aplati (classe/object_id/attribut/version réels, jamais un
pointeur `ref:` intermédiaire), avec un `display_name` identifiant l'objet
porteur (`"<classe> #<id>"`) — alimente le sélecteur frontend de
réutilisation d'un logo existant (`NavigationPage.tsx`).

**`GET /api/class_icon/<string:meta_class>/<string:cls>`** (Blueprint
`routes/routes_read.py`, génération dans `backend/files/class_icon.py`) — sert le SVG de
secours généré localement (rond coloré + initiales, hash déterministe du
nom de classe, mis en cache disque sous
`<FILE_STORAGE_ROOT>/_class_icon_cache/`) pour une classe sans logo ni
icône choisie manuellement (jeu fixe `frontend/src/classIcons.tsx`, voir
§6.8 de [05-frontend.md](05-frontend.md)). `404` si la classe n'existe pas
dans le modèle. **Volontairement non filtrée tenant** — à la différence des
routes de lecture d'objet — car le SVG généré ne dépend que du **nom** de
la classe, jamais d'une donnée d'objet : aucune fuite possible, cohérent
avec les autres routes de lecture de schéma déjà non filtrées tenant
(`GET /api/read/class`, `GET /api/read/class/<id>`,
`GET /api/read/<meta_class>`).

**`POST /api/admin/sweep_orphan_files`** (`backend/routes/routes_admin.py`) —
purge les fichiers présents sur `FileStorage` mais jamais indexés par une
ligne `attribute_value` (crash process entre écriture disque et commit).
Réservé strictement à `global-admin` : contrôle fait dans le handler via
`ctx.is_global_admin` (`403` si non admin, y compris anonyme) — à la
différence de `/api/purge` qui est pré-filtré par `require_auth` (`401` si
aucun token). **Référence-consciente** : un fichier n'est supprimé que
s'il n'existe NI un pointeur direct propriétaire NI un pointeur `ref:...`
porté par n'importe quel autre objet/attribut — sans cette seconde
recherche, purger l'objet qui a initialement reçu l'upload casserait le
logo de tout objet qui le référence encore. Réponse `200` :
`{"status":"ok","purged_count":int,"purged":[{"class":str,"object_id":int,
"attribute":str,"version":int,"filename":str}, ...]}`. Dette assumée
documentée dans le code : une requête SQL par fichier scanné, sans commit
intermédiaire — acceptable au volume actuel, à traiter avant un volume
important (voir aussi §10.8 de [07-roadmap.md](07-roadmap.md)).

## 4.7 Types `select`/`secret`/`datasource` (ajout 2026-11-23, `plan-mark3.md` actions 7-9)

Les trois types ci-dessous transitent par le JSON classique de `POST
/api/write/object` (coercition dans `_coerce_typed_value`,
`backend/routes/routes_write.py`) — contrairement à `file`/`image`/`csv`
(§4.6), aucune route binaire dédiée.

**`select`** (action 7) — la valeur soumise doit appartenir au tableau
`values` déclaré sur l'attribut (`model/schema.json`) : `_coerce_typed_value`
vérifie l'appartenance, `abort(400)` avec message explicite sinon ; stockage
scalaire ordinaire dans `value_string`, aucune route dédiée. Même garde
rejouée côté `PUT /api/write/attribute/<cls>/<id>/<attribute>/<value>`
(édition inline par URL) — ce type n'est **pas** bloqué sur cette route
(contrairement à `file`/`image`/`csv`/`secret` ci-dessous), car la valeur
reste une chaîne scalaire ordinaire sans risque d'injecter un pointeur
arbitraire.

**`secret`** (action 8, conception détaillée : §10.10 de
[07-roadmap.md](07-roadmap.md)) :
- **Écriture** — `_coerce_typed_value` chiffre la valeur reçue (Fernet,
  `backend/secret_crypto.py`, clé lue dynamiquement depuis
  `SECRET_ENCRYPTION_KEY`) avant stockage dans `value_string` ; `abort(500)`
  si la clé est absente/invalide au moment de l'appel (jamais de repli en
  clair). Le token Fernet n'étant pas déterministe, **resoumettre la même
  valeur en clair n'est jamais dédupliqué** par l'historisation — une
  nouvelle ligne `attribute_value` est systématiquement créée.
- **Garde-fou d'écriture par URL** — `PUT /api/write/attribute/<cls>/<id>/
  <attribute>/<value>` rejette explicitement (`abort(400)`) toute tentative
  d'écrire un attribut `secret` via ce chemin (même garde que `file`/
  `image`/`csv`, §4.6) : la valeur en clair transiterait sinon dans l'URL,
  donc potentiellement dans des logs d'accès proxy/APM — pas un défaut de
  chiffrement en base, un risque de fuite ailleurs.
- **Masquage en lecture générique** — `GET /api/read/object/<id>` (et donc
  tout code qui le consomme) ne renvoie **jamais** le texte chiffré ni le
  texte en clair pour un attribut `secret` : chaque valeur active est
  remplacée par un placeholder fixe (`"••••••••"`), une par valeur
  présente (`_build_object_payload`, `backend/routes/routes_read.py`).
  Aucun flag `?reveal=true` sur cette route.
- **`GET /api/read/object/<int:object_id>/secret/<string:attribute>`**
  (`backend/routes/routes_read.py`) — seule route qui déchiffre et renvoie
  la valeur en clair d'un attribut `secret`. RBAC strict et **différent**
  de toutes les autres routes de lecture : réservée exclusivement à
  `ctx.is_global_admin` (`403` même pour un tenant-admin dans son propre
  périmètre) ; en plus, cette route est explicitement listée dans
  `_PROTECTED_REGEXES` (`backend/auth/auth.py`) pour exiger un Bearer token
  valide même si c'est un `GET` — à la différence des autres `GET
  /api/read/*`, ouvertes sans authentification obligatoire (`401` sans
  token/token invalide, `403` si authentifié non global-admin). `404` si
  objet inexistant/supprimé, attribut non déclaré ou pas de type `secret`
  sur la classe, ou aucune valeur active — même sémantique « ne pas
  distinguer les cas » que les routes de fichiers. `500` (jamais un succès
  trompeur) si `SECRET_ENCRYPTION_KEY` absente/invalide ou si le jeton
  chiffré est corrompu/chiffré avec une autre clé.
- **Historisation** (§10.4) : une valeur `secret` historisée reste chiffrée
  dans les versions passées aussi, aucun traitement différent du reste du
  modèle.
- Limite connue acceptée : aucune voie API pour fermer explicitement un
  attribut `secret` existant sans le remplacer — l'omettre dans
  `POST /api/write/object` ne le ferme jamais par garde-fou volontaire
  (contrairement aux autres types scalaires, où un attribut omis ferme la
  valeur active).
- **Résolution deny-priority** (plan-mark3.md action 21bis, durcissement
  sécurité) : `POST /api/write/class`/`POST /api/write/metaclass` rejettent
  désormais (`409`) un nom d'attribut déclaré deux fois dans la même classe,
  et une classe déclarée deux fois dans le même payload `write_metaclass`
  (voir §4.4) — cause racine bloquée pour toute NOUVELLE écriture de schéma.
  Pour des données déjà stockées avant ce correctif (aucune migration
  rétroactive requise), tout point de code qui résout un attr_def par nom
  (chiffrement à l'écriture, masquage en lecture générique, route reveal,
  route suggest §4.9, `routes_files.py`) traite désormais un nom ambigu
  comme `secret` dès qu'**au moins une** de ses déclarations l'est —
  jamais une déclaration non-secrète trouvée en premier qui laisserait
  passer un stockage en clair ou une valeur non masquée.

**`datasource`** (action 9, conception détaillée : §10.11 de
[07-roadmap.md](07-roadmap.md)) :
- **Écriture** — `_coerce_typed_value` attend un identifiant d'objet entier
  (ou une chaîne numérique), `abort(400)` sinon (y compris un flottant non
  entier, ex. `3.5`). Stocké dans `value_string` (jamais la colonne
  `joint_id`) — en lecture, la valeur ressort donc comme une chaîne brute
  (l'identifiant), pas comme `{"joint_id": ...}`.
- **Validation de cible** — `_apply_attribute_diff` (`backend/routes/
  routes_write.py`) vérifie, pour chaque valeur insérée : l'objet cible
  existe et n'est pas supprimé logiquement (`abort(400)` sinon), sa classe
  appartient à `attr_def["classes"]` (`abort(400)` sinon), et — pour un
  acteur tenant-admin — l'objet cible est dans son périmètre tenant
  (`abort(403)` sinon). Rejoué à l'identique sur `PUT /api/write/attribute/
  .../` (édition inline par URL), qui n'est **pas** bloqué pour ce type
  (contrairement à `secret`/`file`/`image`/`csv`) : la valeur reste un
  entier scalaire ordinaire, pas un pointeur fichier ni un secret en clair.
  ⚠️ Ce niveau de validation (classe + tenant de la cible) est **plus
  strict** que celui appliqué aujourd'hui à une jointure `joint-1-1`/
  `joint-1-n` ordinaire, qui ne vérifie que l'existence/non-suppression de
  la cible — incohérence assumée entre les deux mécanismes, non corrigée
  côté jointures par cette action.
- **Suppression en cascade** — `delete_object` (`DELETE /api/delete/
  object/<id>`) ferme désormais aussi toute valeur `attribute_value` de
  type `datasource` qui pointait (`value_string = str(id)`) vers l'objet
  supprimé, filtrée tenant et revalidée contre la définition réelle de
  l'attribut source (ne ferme que si le type est bien `datasource` et que
  la classe source figure dans `attr_def["classes"]`) — même esprit que
  `joint_id` → `ON DELETE SET NULL`, mais géré applicativement puisque
  `value_string` n'est pas une clé étrangère SQL.
- Pas de câblage d'exécution de requête (aucune route n'interroge
  Prometheus ou une autre source réelle) : uniquement le type, la
  référence, et la meta-classe de démo `model/datasource.json` (§3.2ter de
  [03-modele-donnees.md](03-modele-donnees.md)).

## 4.8 Type `boolean` (ajout 2026-11-23, `plan-mark3.md` action 19)

**`boolean`** (action 19, conception détaillée : §10.16 de
[07-roadmap.md](07-roadmap.md)) — type scalaire le plus simple du jeu
actuel, transite lui aussi par le JSON classique de `POST
/api/write/object` (coercition dans `_coerce_typed_value`,
`backend/routes/routes_write.py`), comme `select`/`secret`/`datasource`
ci-dessus : aucune route binaire dédiée.

- **Écriture** — `_coerce_typed_value` accepte **deux** formes de
  `raw_value`, strictement, rien d'autre :
  - un bool Python natif (`True`/`False`) — cas nominal, reçu via `POST
    /api/write/object` après parsing JSON du corps de la requête (un
    `true`/`false` JSON devient un bool Python) ;
  - la chaîne **exactement** `"true"` ou `"false"` — reçue via `PUT
    /api/write/attribute/<cls>/<id>/<attribute>/<value>` (édition
    inline de cellule), où la valeur transite par le chemin d'URL Flask
    (`<string:value>`) : un bool JSON ne peut physiquement pas être
    porté par un segment d'URL, cette route ne voit donc jamais rien
    d'autre qu'une chaîne. Ce type n'est **pas** bloqué sur cette route
    (contrairement à `file`/`image`/`csv`/`secret`, §4.6/ci-dessus) —
    contrairement à `joint-1-1`, qui contourne cette même contrainte en
    routant son édition inline par l'objet complet plutôt que par cette
    route URL (`NavigationPage.tsx`, `saveInlineEdit`), `boolean` reste
    ici sur la route URL : la valeur transite déjà en texte canonique
    identique au stockage (`value_string`), donc l'accepter directement
    sous cette forme n'introduit aucune ambiguïté et évite de
    complexifier `saveInlineEdit` pour un seul type.
  - Toute autre valeur (chaînes `"1"`/`"yes"`/`"0"`/`"True"`, entiers
    `0`/`1`, flottants, `null`, listes, objets...) est rejetée
    `abort(400)` avec message explicite — pas de parsing permissif.
  Dans les deux cas, stockage normalisé dans `value_string` en texte
  **exactement** `"true"`/`"false"` (jamais `"True"`/`"1"`/autre) :
  une valeur reçue sous l'une ou l'autre forme produit donc le même
  texte stocké, garantissant que l'historisation (`_apply_attribute_diff`)
  déduplique correctement une valeur inchangée quel que soit le chemin
  d'écriture emprunté.
- **Lecture générique** — aucun traitement spécial dans
  `_build_object_payload` (`backend/routes/routes_read.py`) : le texte
  `"true"`/`"false"` ressort tel quel dans `values`, comme n'importe quel
  autre attribut `value_string` ordinaire (`string`/`select`/`datasource`)
  — contrairement à `secret` (masqué par un placeholder) ou
  `file`/`image`/`csv` (pointeur `<version>:<nom>` à résoudre). Aucune
  route dédiée.
- **IHM** (`frontend/src/pages/NavigationPage.tsx`) — case à cocher aux
  **deux** endroits attendus pour toute édition d'attribut de ce module
  (rappel de la conception, déjà manqué une fois à l'action 7 pour
  `select`) : le formulaire modal de création/édition (`newAttrs`, state
  local `Record<string, string>`, porte `"true"`/`"false"` comme tout
  autre type scalaire et n'est reconverti en bool JSON natif qu'à
  l'envoi, `handleSave`) et l'édition inline de cellule du tableau
  (branche `isInlineEditing && isBoolean`, même route `PUT
  /api/write/attribute/...` que `select`/`string`). Rendu en lecture
  (cellule non éditée) : case à cocher désactivée plutôt que le texte
  brut, pour la cohérence visuelle avec le rendu édition.
- `frontend/src/pages/ConfigurationPage.tsx` : `ATTR_TYPES` étendu à 12
  types ; colonne « Options » affiche « Aucune option » (même branche que
  `file`/`image`/`secret`, aucun champ requis supplémentaire pour ce
  type).

## 4.9 Autosuggest : suggestions de valeurs apprises (ajout 2026-11-24, plan-mark3.md action 20)

Conception détaillée : §10.17 de [07-roadmap.md](07-roadmap.md).

**`GET /api/suggest/<meta_class>/<class>/<attribute>?q=<saisie>`**
(`suggest_attribute_values`, `backend/routes/routes_read.py`) — seule
route dédiée à ce mécanisme, aucune écriture associée (l'attribut
`autosuggest` transite par le JSON classique de `POST
/api/write/object`/`PUT /api/write/attribute/...` comme n'importe quel
autre attribut `string`, sans coercition particulière).

- **Résolution de l'attribut** — la route relit `definition.data` pour le
  triplet (meta_class, class, attribute) : `abort(404)` si la meta-classe,
  la classe ou l'attribut n'est pas déclaré dans le modèle (même sémantique
  « ne pas distinguer les cas » que les autres routes de lecture ciblées du
  module, ex. `reveal_object_secret`, §4.7). `abort(400)` si l'attribut
  existe mais n'est pas `type: "string"` ou n'a pas `autosuggest: true` sur
  sa définition — seule route de ce module qui vérifie à l'usage la
  cohérence du champ `autosuggest` (voir aussi §3.2quinquies de
  [03-modele-donnees.md](03-modele-donnees.md) : aucune garde n'existe au
  chargement du modèle). Résolution deny-priority (plan-mark3.md action
  21bis, `_resolve_attr_def`) : si le nom a plusieurs déclarations (attribut
  ou classe dupliqué dans le modèle), celle de type `secret` prévaut
  systématiquement — la vérification de type ci-dessus la rejette alors en
  `400`, jamais un contournement via une déclaration non-secrète trouvée en
  premier.
- **Valeurs candidates** — `SELECT DISTINCT av.value_string` jointe
  `attribute_value`/`attribute`/`object` sur (meta_class, class,
  attribute), `av.valid_to IS NULL` (valeurs **actives seulement** —
  décision utilisateur, une faute de frappe corrigée depuis l'historique
  n'est plus suggérée) et `o.deleted_at IS NULL`. RBAC tenant via
  `_tenant_read_filter`, même mécanisme que `list_objects`/
  `_build_object_payload` (pas de réimplémentation) : un tenant-admin ne
  voit que les valeurs portées par des objets visibles dans son périmètre.
- **Tri** — `rapidfuzz.process.extract` (scorer `fuzz.ratio`) entre `q`
  (query param, défaut chaîne vide) et chaque valeur candidate distincte,
  top `_SUGGEST_LIMIT` (constante en tête de fichier, valeur `10`) renvoyé.
  `q` vide : pas de calcul de distance (comparer à une chaîne vide n'a pas
  de sens de tri), les `_SUGGEST_LIMIT` premières valeurs distinctes sont
  renvoyées telles quelles. Réponse `200` : `{"suggestions": [...]}`.
- **IHM** (`frontend/src/pages/NavigationPage.tsx`, composant
  `AutosuggestInput`) : détail complet §6.9 de
  [05-frontend.md](05-frontend.md).
- Limite connue acceptée (notée en revue, pas bloquante au volume actuel) :
  aucun index SQL dédié sur `attribute_value.value_string`/`attribute.name`
  pour cette requête, et aucun garde-fou de cardinalité sur le nombre de
  valeurs distinctes passées à `rapidfuzz.process.extract` — même esprit
  que la dette déjà assumée sur `datasource`/les jointures en fin de §4.7
  (acceptable au volume actuel, à traiter avant un volume important).

## 4.10 Recherche globale (ajout 2026-11-23/24, `plan-mark3.md` action 21)

Conception détaillée : §10.18 de [07-roadmap.md](07-roadmap.md).

**`GET /api/search?q=<texte>&fuzzy=<bool>&history=<bool>`**
(`search_objects`, nouveau module `backend/routes/routes_search.py`,
blueprint `search_bp` dédié) — recherche toutes classes/meta-classes
confondues par contenu d'attribut (`attribute_value.value_string`).

- **Query params** — `q` (requis, 400 si absent/vide) : texte cherché,
  substring insensible casse (`ILIKE '%...%' ESCAPE '\'`, `q` échappé
  contre les caractères spéciaux ILIKE avant insertion dans le motif).
  `fuzzy` (défaut false, `'1'/'true'/'True'`) : si actif, ajoute
  `fuzzy_suggestions` à la réponse (valeurs proches de `q`, calculées sur
  un pool de 2000 valeurs candidates distinctes max, `rapidfuzz.
  process.extract` + `fuzz.ratio`, `score_cutoff=60` et `ORDER BY
  av.value_string` sur le pool — sans seuil ni tri, les suggestions
  pouvaient être du bruit pur sans rapport avec `q`, et le sous-ensemble de
  2000 lignes gardé par le `LIMIT` était arbitraire d'une requête à
  l'autre) — n'élargit JAMAIS le filtrage des `results` déjà renvoyés,
  sert seulement à relancer une nouvelle recherche côté frontend. `history`
  (défaut false) : si false, seuls les `attribute_value` ACTIFS
  (`valid_to IS NULL`) sont cherchés ; si true, l'historique fermé est
  aussi cherché.
- **RBAC tenant** identique à `_tenant_read_filter` (même overlap Postgres
  que le reste de l'API lecture), objets non supprimés uniquement
  (`object.deleted_at IS NULL`).
- **Exclusion stricte du type `secret` — ALLOW-LIST, pas deny-list** :
  implémentée en SQL (clause `EXISTS (SELECT 1 FROM unnest(%s::text[],
  %s::text[], %s::text[]) AS safe(meta_class, class, name) WHERE ...)`),
  construite à partir d'un préchargement unique de tout le modèle chargé
  (`SELECT meta_class, data FROM definition`) qui aplatit, pour CHAQUE
  classe du modèle courant, l'ensemble des attributs dont le type n'est
  PAS `secret` (`safe_names`). Une ligne n'est incluse QUE SI son triplet
  (meta_class, class, attribute_name) est positivement présent dans
  `safe_names` — tout triplet absent du modèle courant (classe supprimée
  du schéma depuis — `routes_admin.py`, `delete_class`, qui ne touche pas
  aux objets déjà créés —, ou attribut renommé/retiré d'une classe
  existante) est donc exclu PAR DÉFAUT, jamais inclus par défaut. Fix
  sécurité (revue action 21) : la première implémentation faisait l'inverse
  (deny-list `NOT EXISTS` sur les triplets reconnus `secret` dans le modèle
  courant) — un triplet orphelin y était alors inclus par défaut
  (allow-by-default), pouvant exposer en clair le ciphertext Fernet d'un
  attribut `secret` dont la classe ou l'attribut avait disparu du schéma
  depuis. Accès défensif (`.get(...)`) sur chaque entrée du modèle lu
  (classe sans `class`, attribut sans `name` ignorés silencieusement) —
  une ligne `definition.data` malformée ne doit jamais faire échouer toute
  la requête de recherche en 500.
- **Limite de résultats** : `LIMIT` serveur à 500 lignes brutes
  (`_SEARCH_RESULT_LIMIT`, avant dédup objets) — une ligne = un (objet,
  attribut, valeur) matchant, pas un objet distinct. `truncated=true` si
  plus de 500 lignes matchaient.
- **Facettes** (`facets.layers`/`facets.classes`/`facets.attributes`,
  compte d'OBJETS DISTINCTS par valeur de facette, pas de lignes) —
  calculées sur l'ENSEMBLE des lignes matchantes via deux requêtes
  d'agrégation SQL séparées (`GROUP BY o.meta_class, o.class`/`GROUP BY
  a.name`, `COUNT(DISTINCT o.id)`), **sans LIMIT** : `classes`/`attributes`
  directement depuis ces agrégations, `layers` dérivé en Python (somme des
  comptes de `classes` par layer statique de la classe, `classDef.layers`
  — pas le layer effectif dynamique de l'action 18, pour ne pas payer un
  calcul par objet). Fix (revue action 21) : la première implémentation
  calculait les facettes sur les seules lignes de `results` déjà tronquées
  à 500 — une classe dont tous les objets avaient des ids triés après la
  coupe `ORDER BY o.id LIMIT 500` pouvait devenir invisible des facettes
  dès que `truncated=true`, sans qu'aucun clic ne puisse la faire
  réapparaître. `results` reste plafonné à 500 + `truncated` inchangé —
  seule l'assiette de calcul des facettes a changé.
- **Réponse JSON** :
  ```json
  {
    "results": [
      {"id": 12, "meta_class": "cmdb", "class": "serveur",
       "attribute": "nom", "value": "web-01", "is_current": true}
    ],
    "facets": {
      "layers": [{"value": "infra", "count": 3}],
      "classes": [{"meta_class": "cmdb", "class": "serveur", "count": 5}],
      "attributes": [{"name": "nom", "count": 5}]
    },
    "truncated": false,
    "fuzzy_suggestions": []
  }
  ```
  `is_current` : true si la ligne porte la valeur ACTIVE de l'attribut
  (`valid_to IS NULL`), false si fermée (historique) — ajout a posteriori
  (revue action 21) : sans ce champ, deux valeurs successives d'un même
  attribut matchant toutes les deux en `history=true` étaient
  indiscernables. `fuzzy_suggestions` toujours présent (liste vide si
  `fuzzy=false` ou aucune suggestion au-dessus du seuil).
- **IHM** (`frontend/src/pages/RecherchePage.tsx`) : détail complet §6.14
  de [05-frontend.md](05-frontend.md).

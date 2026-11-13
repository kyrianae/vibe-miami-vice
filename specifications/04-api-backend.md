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

## 4.5 Initialisation depuis les fichiers modèles

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

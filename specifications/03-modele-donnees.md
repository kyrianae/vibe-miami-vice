# 3. Modèle de données

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

## 3.1 Concepts

| Concept | Rôle | Porté par |
|---|---|---|
| **Meta-classe** | Regroupement logique de classes (ex. `personne`, `element_avec_ip`) | table `definition` (une ligne par meta-classe) |
| **Classe** | Type d'objet concret (ex. `personne_physique`, `vlan`) avec sa liste d'attributs | élément du tableau `classes` dans `definition.data` (JSONB) |
| **Attribut (définition)** | Nom + domaine + type (+ contraintes) déclaré sur une classe | élément du tableau `attributes` d'une classe, dans `definition.data` |
| **Objet** | Instance d'une classe | ligne de la table `object` |
| **Attribut (instance)** | Attribut effectivement posé sur un objet donné | ligne de la table `attribute` |
| **Valeur** | Valeur(s) typée(s) d'un attribut d'instance ; une liste de valeurs permet de modéliser des jointures 1-N | ligne(s) de la table `attribute_value` |
| **Jointure** | Référence d'un objet vers un autre objet, typée `joint-1-1` (une seule valeur) ou `joint-1-n` (plusieurs valeurs) | colonne `attribute_value.joint_id` → `object.id` |

## 3.2 `model/schema.json` — contrat JSON Schema des définitions

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

`additionalProperties: false` à tous les niveaux.

## 3.2bis Extensions Mark 3 : types `file`/`image`/`csv`, `icon`, `version` (ajout 2026-11-21)

Trois ajouts à `model/schema.json`, livrés par `plan-mark3.md` actions 3-5
(absents de la structure §3.2 ci-dessus, qui documente l'état pré-Mark 3) :

- **Champ top-level `"version"`** (entier, `minimum: 1`, optionnel) sur un
  document modèle, à côté de `meta_class`/`depends_on`/`classes`. Absent =
  version 1 par défaut. Purement informatif pour l'instant — aucune
  logique de migration ne le consomme encore (action 5, préparation
  future) ; propagé tel quel par `backend/routes/routes_init.py` (`/api/init`) et
  `backend/routes/routes_write.py` (`write_metaclass`), voir §4.4/§4.5 de
  [04-api-backend.md](04-api-backend.md).
- **`attributes[].type`** étendu à `"file"`, `"image"`, `"csv"` (aux côtés
  de `string|integer|float|joint-1-1|joint-1-n`) — ces trois types
  n'utilisent ni `constraint`/`sql_constraint` ni `classes`. Le type `csv`
  porte en plus un champ optionnel `"separator"` sur la définition
  d'attribut (défaut `,` si absent, appliqué côté code, pas une valeur par
  défaut du schéma JSON lui-même). Représentation en base inchangée :
  aucune nouvelle colonne, la valeur stockée dans
  `attribute_value.value_string` est un pointeur vers le contenu réel géré
  par `FileStorage`, pas le contenu lui-même — détail complet des deux
  formats de pointeur (direct et référence `ref:`) en §4.6 de
  [04-api-backend.md](04-api-backend.md).
- **Champ `"icon"`** (chaîne, optionnel) sur une classe — identifiant
  choisi dans le jeu fixe d'icônes embarquées côté frontend
  (`frontend/src/classIcons.tsx`, 18 icônes), pas un upload libre, pas de
  validation de valeur côté backend. Utilisé par `DiagramPage`/
  `NavigationPage` comme représentation par défaut d'un objet de cette
  classe, après un éventuel logo d'objet (voir ci-dessous) et avant le
  repli couleur de palette (§6.4). Détail frontend : §6.8 de
  [05-frontend.md](05-frontend.md).
- **Convention « logo d'objet »** (pas un champ de schéma dédié, une
  convention de nommage) : une classe qui « a un logo » porte un attribut
  réservé nommé `logo`, type `image`, domaine `display` (ex. classe
  `serveur` de `model/itil_cmdb.json`) ; la plomberie est celle d'un
  attribut `image` ordinaire (section ci-dessus), avec en plus la
  possibilité de *référencer* le fichier déjà stocké d'un autre objet
  plutôt que d'uploader de nouveaux octets (voir §4.6 de
  [04-api-backend.md](04-api-backend.md)).

## 3.2ter Extensions Mark 3 (suite) : types `select`/`secret`/`datasource`, champ `layers`, meta-classes `datasource`/`dashboard` (ajout 2026-11-23, actions 7-9/14)

Quatre ajouts supplémentaires à `model/schema.json` (`attributes[].type` et
une classe), livrés par `plan-mark3.md` actions 7-9 et 14, postérieurs à
§3.2bis :

- **`attributes[].type` étendu à `"select"`** (action 7) — liste fermée de
  valeurs, portée par un nouveau champ `"values"` (tableau de chaînes) sur
  la définition d'attribut, `required` si `type: select`. La valeur
  stockée dans `attribute_value.value_string` doit appartenir à `values` —
  vérifié côté serveur (`_coerce_typed_value`, `backend/routes/
  routes_write.py`), `abort(400)` sinon. Restructuration du bloc `allOf`
  du schéma en **2 branches** (pas une 3e couple `if`/`then` séparée) :
  branche 1 — `type` dans `["joint-1-1", "joint-1-n", "datasource"]` →
  `classes` requis ; branche 2 — `type` = `"select"` → `values` requis.
  ⚠️ Pas de migration automatique si `values` est réduit après coup sur un
  attribut déjà utilisé (valeurs orphelines possibles dans l'historique).
- **`attributes[].type` étendu à `"secret"`** (action 8) — valeur
  chiffrée Fernet (`cryptography.fernet`) dans `value_string`, jamais en
  clair. Clé unique globale lue dynamiquement depuis la variable
  d'environnement `SECRET_ENCRYPTION_KEY` (`backend/secret_crypto.py`,
  jamais mise en cache au démarrage). Aucune nouvelle colonne, aucun champ
  de schéma supplémentaire sur la définition d'attribut (contrairement à
  `select`/`csv`/`joint-*`/`datasource`) — le typage seul suffit, le
  masquage et le chiffrement sont entièrement portés par le code. Détail
  complet (masquage en lecture, route reveal, garde-fou d'écriture par
  URL) : §4.7 de [04-api-backend.md](04-api-backend.md).
- **`attributes[].type` étendu à `"datasource"`** (action 9) — pointeur
  vers un objet d'une meta-classe `datasource_*` dédiée (ex.
  `datasource_prometheus`), réutilisant le modèle objet dynamique
  existant plutôt qu'un blob JSON opaque. Le champ `"classes"` — déjà
  requis pour `joint-1-1`/`joint-1-n` — est **réutilisé tel quel** pour
  lister les classes cibles autorisées (même branche `allOf` que les
  jointures, voir ci-dessus). ⚠️ Différence de représentation importante
  avec une jointure : la valeur est stockée dans `value_string` (un
  identifiant d'objet entier en chaîne), **jamais** dans la colonne
  `joint_id` — en lecture, la valeur ressort donc comme une chaîne brute,
  pas comme `{"joint_id": ...}`. Validation serveur plus stricte qu'une
  jointure ordinaire (`_apply_attribute_diff`, `backend/routes/
  routes_write.py`) : `abort(400)` si l'objet cible n'existe pas/est
  supprimé ou si sa classe n'est pas dans `attr_def["classes"]`,
  `abort(403)` si l'objet cible est hors du périmètre tenant de l'acteur
  (tenant-admin) — plus strict que `joint-1-1`/`joint-1-n`, qui ne
  vérifient aujourd'hui ni classe ni tenant de la cible (incohérence
  documentée, non corrigée pour les jointures ordinaires). Suppression de
  l'objet cible : `delete_object` ferme en cascade toute valeur
  `datasource` qui pointait dessus (même esprit que `joint_id` → `ON
  DELETE SET NULL`, mais géré applicativement puisque `value_string`
  n'est pas une clé étrangère). Détail complet : §4.7 de
  [04-api-backend.md](04-api-backend.md).
- **Champ `"layers"`** (array de string, optionnel) sur une classe (action
  14) — même emplacement/pattern que `"tenants"` : tag texte libre,
  **pas** une nouvelle meta-classe dédiée. Absent/vide = classe toujours
  visible quel que soit le filtre actif. Purement un filtre d'affichage
  100% frontend (localStorage, §6.9 de [05-frontend.md](05-frontend.md)),
  **pas** un mécanisme RBAC comme `tenants`.

Deux nouveaux fichiers de modèle (meta-classes applicatives, pas des
extensions de `schema.json`) :
- **`model/datasource.json`** (action 9) — meta-classe `datasource`, deux
  classes : `datasource_prometheus` (`url` string) et `query` (`name`,
  `expression` string + `datasource` en `joint-1-1` vers
  `datasource_prometheus`) — une datasource (connexion) et une requête
  sont deux concepts distincts, la requête référence sa datasource.
  Aucun champ credential/secret sur `datasource_prometheus` à ce jour (le
  jour où ce besoin apparaît, il devra utiliser le type `secret`
  ci-dessus, jamais un champ texte en clair).
- **`model/dashboard.json`** (action 10a/10d) — meta-classe `dashboard`,
  deux classes : `dashboard` (`name` string) et `tab` (`name` string,
  `dashboard` en `joint-1-1` vers `dashboard`, `target_meta_class`/
  `target_class` string libres désignant la meta-classe/classe précise à
  afficher dans l'onglet — deux champs séparés, pas un seul, car une
  meta-classe peut porter plusieurs classes — et `filter_attribute`/
  `filter_value` string optionnels, action 10d, filtre d'égalité stricte
  sur les objets candidats). Aucune table applicative dédiée : stockage
  entièrement porté par le modèle dynamique existant (`object`/
  `attribute`/`attribute_value`), comme toute autre meta-classe. Détail
  complet (rendu, CRUD, filtre) : §6.10 de
  [05-frontend.md](05-frontend.md).

⚠️ Note : les fichiers
`model/personnes.json` et `model/reseau.json` fournis contiennent une clé
`"$schema": "schema.json"` au niveau racine, qui n'est pas déclarée dans
`model/schema.json` — si la validation était un jour activée, ces fichiers
d'exemple échoueraient eux-mêmes à cause de `additionalProperties: false`.

## 3.2quater Extensions Mark 3 (suite) : type `boolean` (ajout 2026-11-23, action 19)

**`attributes[].type` étendu à `"boolean"`** (action 19, conception
détaillée : §10.16 de [07-roadmap.md](07-roadmap.md)) — case à cocher
simple, type le plus simple du jeu actuel aux côtés de
`string`/`integer`/`float` : aucun champ requis supplémentaire sur la
définition d'attribut (contrairement à `select`/`joint-*`/`datasource`),
donc aucune nouvelle branche `allOf` dans le schéma. Stockage inchangé :
`value_string` existant, valeur stockée en texte **exactement**
`"true"`/`"false"` — aucune nouvelle colonne SQL.

`_coerce_typed_value` (`backend/routes/routes_write.py`) accepte deux
formes en entrée (pas une seule) : un bool Python natif — cas nominal,
reçu via `POST /api/write/object` (corps JSON, après parsing) — **et** la
chaîne exacte `"true"`/`"false"` — reçue via `PUT /api/write/attribute/
<cls>/<id>/<attribute>/<value>` (édition inline de cellule), dont la
valeur transite par le chemin d'URL Flask (`<string:value>`) et ne peut
donc physiquement jamais porter un bool JSON. Tout le reste (chaînes
`"1"`/`"yes"`/`"0"`, entiers, `null`, etc.) est rejeté `abort(400)` — pas
de parsing permissif. Détail complet (les deux routes d'écriture, IHM) :
§4.8 de [04-api-backend.md](04-api-backend.md).

Aucun traitement spécial en lecture (`_build_object_payload`,
`backend/routes/routes_read.py`) : le texte `"true"`/`"false"` ressort tel
quel, comme n'importe quel autre attribut `value_string` — contrairement à
`secret` (masqué) ou `file`/`image`/`csv` (pointeur).

## 3.3 Fichiers de modèle fournis

**`model/personnes.json`** — meta-classe `personne` :
- `personne_physique` : attributs `nom`, `prenom` (domaine `details`, string). `displayname`: `"{{prenom}} {{nom}}"`.
- `role` : `nom` (string) + `membres` (`joint-1-1` → `personne_physique`).
- `groupe` : `nom` (string) + `membres` (`joint-1-n` → `personne_physique` ou `groupe`, donc récursif).

**`model/reseau.json`** — meta-classe `element_avec_ip` :
- `addresse_ip` : `adresse_ip` (string, `constraint` = regex IPv4, `sql_constraint: "UNIQUE VALUE"` — non appliquée par le code, voir §8).
- `vlan` : `nom` (string), `definition` (string, regex CIDR), `membres` (`joint-1-n` → `addresse_ip`).

## 3.4 Tables PostgreSQL (`sql/init.sql`)

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
- `object`/`attribute` sont en `ON DELETE CASCADE` : une suppression SQL
  réelle d'un objet supprimerait tous ses attributs et leurs valeurs. En
  pratique, `DELETE /api/delete/object/<int:object_id>`
  (`backend/routes/routes_write.py:683`, détail §3.2ter ci-dessus) existe bien
  et ne fait jamais de `DELETE` SQL sur `object` : elle pose `deleted_at =
  now()` (suppression logique) et ferme (`valid_to = now()`) les
  `attribute_value` associées, donc le `ON DELETE CASCADE` ci-dessus n'est
  jamais déclenché par ce chemin applicatif. Pas de route de suppression
  pour les classes/meta-classes (`definition`) à ce jour.
- `definition.data` stocke **le JSON de définition tel quel**
  (`{"meta_class": ..., "classes": [...]}`), c'est la seule table qui
  porte le schéma ; `object`/`attribute`/`attribute_value` ne référencent
  jamais `definition` par clé étrangère — la cohérence entre schéma déclaré
  et objets stockés n'est pas imposée par la base.

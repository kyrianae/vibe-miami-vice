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
  future) ; propagé tel quel par `backend/routes_init.py` (`/api/init`) et
  `backend/routes_write.py` (`write_metaclass`), voir §4.4/§4.5 de
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

⚠️ Note : les fichiers
`model/personnes.json` et `model/reseau.json` fournis contiennent une clé
`"$schema": "schema.json"` au niveau racine, qui n'est pas déclarée dans
`model/schema.json` — si la validation était un jour activée, ces fichiers
d'exemple échoueraient eux-mêmes à cause de `additionalProperties: false`.

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
- `object`/`attribute` sont en `ON DELETE CASCADE` : supprimer un objet
  supprime tous ses attributs et leurs valeurs. ⚠️ Mais **aucune route de
  suppression d'objet n'existe** dans `app.py` — il n'y a pas de
  `DELETE /api/...` pour les objets, les classes ou les meta-classes.
- `definition.data` stocke **le JSON de définition tel quel**
  (`{"meta_class": ..., "classes": [...]}`), c'est la seule table qui
  porte le schéma ; `object`/`attribute`/`attribute_value` ne référencent
  jamais `definition` par clé étrangère — la cohérence entre schéma déclaré
  et objets stockés n'est pas imposée par la base.

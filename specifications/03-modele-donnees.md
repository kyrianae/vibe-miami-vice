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
`model/organisation.json` et `model/reseau.json` fournis contiennent une clé
`"$schema": "schema.json"` au niveau racine, qui n'est pas déclarée dans
`model/schema.json` — si la validation était un jour activée, ces fichiers
d'exemple échoueraient eux-mêmes à cause de `additionalProperties: false`.
En pratique cette clé est ignorée au runtime (voir `$schema` dans
`model/schema.json`, purement informatif) et la validation Draft7 de
l'action 17 (`backend/tests/test_model_files_schema_validation_action_17.py`)
confirme que tous les `model/*.json` du dépôt, celui-ci inclus, passent.

## 3.2quater Extensions Mark 3 (suite) : type `boolean` (ajout 2026-11-23, action 19)

**`attributes[].type` étendu à `"boolean"`** (action 19) — case à cocher
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

## 3.2quinquies Extensions Mark 3 (suite) : champ `autosuggest` (ajout 2026-11-24, action 20)

**Nouveau champ optionnel `"autosuggest": true`** (booléen) sur une
définition d'attribut (`model/schema.json`). Réservé en intention au type
`type: "string"` uniquement — **mais aucune contrainte JSON Schema**
(`allOf`/`if-then`) n'empêche de le poser sur un attribut d'un autre type :
pure convention documentaire, même esprit que `separator`/`values` déjà
notés ainsi dans ce fichier (§3.2quater ci-dessus pour `values`/`classes`).
Aucune garde serveur ne vérifie cette cohérence au chargement du modèle
(`/api/init`) — seule la route `GET /api/suggest/...` la vérifie à l'usage,
`abort(400)` si l'attribut existe mais n'est pas `string`+`autosuggest`
(détail complet : §4.9 de [04-api-backend.md](04-api-backend.md)).

Aucune nouvelle colonne SQL ni nouveau mécanisme de stockage : un attribut
`autosuggest` reste un `string` ordinaire, stocké dans `value_string`
comme n'importe quel autre attribut de ce type — seule la route de
lecture `/api/suggest` ci-dessus interprète ce champ, l'écriture
(`POST /api/write/object`/`PUT /api/write/attribute/...`) ne le consulte
jamais.

Démonstration manuelle réelle : `autosuggest: true` activé sur deux
attributs existants, `datacenter.localisation` (`model/itil_cmdb.json`) et
`version_logicielle.environnement` (`model/ansible_inventory.json`).

## 3.2sexies Extensions Mark 3 (suite) : champ `layer_map` — layer dynamique piloté par un attribut `select` (ajout 2026-11-23, action 18)

**Nouveau champ optionnel `"layer_map"`** (objet `{valeur: [layers]}`) sur
une définition d'attribut de type `"select"` (`model/schema.json`).
Motivation (besoin `serveur.type`, §3.3 ci-dessous) : le champ `layers`
d'une classe (§3.2ter) est **statique**, posé une fois pour toutes sur la
classe — il ne peut pas représenter un objet dont le layer effectif dépend
de la valeur courante d'un de ses attributs (ex. un `serveur` de
`type: "vm"` ne doit pas porter le layer `physique`, contrairement à un
`serveur` de `type: "physique"`).

- Clés censées être un sous-ensemble des `values` déclarées sur le même
  attribut `select` — **non vérifié strictement** par le schéma JSON
  (`additionalProperties` ouvert sur l'objet `layer_map`, aucune
  contrainte croisée avec `values`). Chaque clé associe une valeur
  possible à une liste de layers (même taxonomie texte libre que
  `ClassDefinition.layers`, action 14).
- La seule **présence** du champ marque l'attribut comme pilotant le layer
  effectif de l'objet — pas de flag booléen séparé redondant (même
  convention que `values` requis sur `select` sans flag « a des valeurs »
  à côté).
- Sans objet pour tout autre type que `select` ; aucune contrainte `allOf`
  dédiée dans `model/schema.json` ne l'impose (pure convention
  documentaire, même statut que `autosuggest` ci-dessus) — rien n'empêche
  de le poser sur un attribut d'un autre type, mais lui seul (via
  `getObjectEffectiveLayers` côté frontend, voir ci-dessous) le lit.
- **Calcul du layer effectif d'un objet** = union du `layers` statique de
  sa classe et, pour chaque attribut `select` de la classe portant un
  `layer_map`, des layers mappés à la valeur courante de l'objet sur cet
  attribut (repli sur `layers` statique seul si aucune valeur ne mappe,
  ou si l'attribut n'a pas encore de valeur posée). Calcul **100%
  frontend** (`getObjectEffectiveLayers`, dupliquée dans
  `NavigationPage.tsx`/`DiagramPage.tsx`, détail complet : §6.12 de
  [05-frontend.md](05-frontend.md)) — aucun changement backend, cohérent
  avec le principe déjà posé à l'action 14 (le filtre `layers` est un
  filtre d'affichage, jamais un mécanisme RBAC/sécurité).
- Exemple réel du dépôt (`model/itil_cmdb.json`, classe `serveur`) :
  attribut `type` (`select`, `values: ["physique", "vm"]`) porte
  `layer_map: {"physique": ["physique"]}` ; le `layers` statique de
  `serveur` ne porte plus que `["reseau"]` — le tag `physique` est
  entièrement piloté par la valeur de `type`, pour qu'un serveur `vm` ne
  soit jamais compté comme `physique` par le filtre.
- Aucune nouvelle colonne SQL ni nouveau mécanisme de stockage : la valeur
  de l'attribut `select` lui-même reste stockée normalement dans
  `attribute_value.value_string` (§3.2ter) ; `layer_map` ne vit que dans
  `definition.data` (le schéma), jamais dans une ligne d'instance.

## 3.2septies Extensions Mark 4 : champ `cascade` — sélection en cascade générique (ajout 2026-11-26, action 6)

**Nouveau champ optionnel `"cascade"`** (tableau ordonné de strings) sur une
définition d'attribut de type `"joint-1-1"` (`model/schema.json`). Motivation
(besoin `materiel.salle` → `salle.etage` → `etage.batiment`, §3.3
ci-dessous) : chaque jointure de la chaîne se sélectionnait jusqu'ici
indépendamment dans `NavigationPage.tsx` (pas de narrowing successif) —
choisir un `materiel` imposait de connaître directement l'id de la `salle`
exacte parmi TOUTES les salles du système, sans pouvoir d'abord filtrer par
bâtiment puis par étage.

- **Mécanisme générique, configuré au niveau du modèle** — pas spécifique à
  la chaîne salle/bâtiment/étage : n'importe quel attribut `joint-1-1`
  déclarant `cascade` bénéficie du même sélecteur en cascade (ex.
  réutilisable pour `baie_serveur`/`datacenter` si une chaîne équivalente
  existait).
- Le tableau liste, dans l'ordre, les noms d'attributs `joint-1-1` à
  **remonter** depuis la classe cible de CET attribut (`attr.classes[0]`).
  Exemple réel du dépôt (`model/itil_cmdb.json`, classe `materiel`,
  attribut `salle` — joint-1-1 → classe `salle`) :
  `"cascade": ["etage", "batiment"]` — la classe `salle` porte elle-même un
  attribut joint-1-1 `etage` (→ classe `etage`), qui porte lui-même un
  attribut joint-1-1 `batiment` (→ classe `batiment`). Chaîne complète
  reconstruite côté frontend : `salle` (niveau 0, classe cible) → `etage`
  (niveau 1) → `batiment` (niveau 2, sommet).
- **Non vérifié strictement** par le schéma JSON : pas de contrainte `allOf`
  croisée validant que chaque nom existe réellement comme attribut
  `joint-1-1` de la classe précédente de la chaîne — même niveau de
  validation documentaire que `layer_map`/`autosuggest` (§3.2sexies/
  §3.2quinquies). Une chaîne mal formée (nom d'attribut inexistant, pas
  `joint-1-1`, ou classe cible sans attribut correspondant) est simplement
  ignorée côté frontend : repli silencieux sur le sélecteur `<select>` plat
  déjà existant (`computeCascadeChain` retourne `null`,
  `NavigationPage.tsx`).
- **Pure aide de sélection IHM** : la valeur réellement stockée reste un
  simple pointeur `joint-1-1` vers l'objet final choisi (ex. l'id de la
  `salle`) — **aucun changement de format de stockage**
  (`attribute_value.joint_id`, §3.2), aucune nouvelle colonne SQL, aucune
  logique backend. `cascade` ne vit que dans `definition.data` (le schéma),
  jamais dans une ligne d'instance — même statut que `layer_map`.
- **Rendu IHM** (`NavigationPage.tsx`, détail complet : §6.10bis de
  [05-frontend.md](05-frontend.md)) : sélecteur du SOMMET de la chaîne en
  premier (dernier élément de `cascade`, ex. `batiment`, liste tous les
  objets de la classe), puis un sélecteur par niveau en redescendant,
  chacun filtré aux candidats dont l'attribut de liaison pointe vers le
  choix du niveau parent — jusqu'à la classe cible finale (ex. `salle`).
  Branché dans le formulaire de création/édition ET dans l'édition inline de
  cellule (rappel explicite du plan : point oublié 2 fois par le passé aux
  actions 7/19 de Mark 3). En édition d'un objet existant, toute la chaîne
  est pré-remplie en remontant depuis la valeur déjà stockée.
- **Vigilance suppression** (point explicitement signalé par l'utilisateur) :
  vérifié réellement via l'API (pas seulement en lisant le code) — supprimer
  un élément intermédiaire de la chaîne (ex. un `batiment`) ne fait que
  fermer (`valid_to = now()`) l'unique `attribute_value` qui pointe
  DIRECTEMENT vers lui (ici `etage.batiment`, qui devient vide) ; les objets
  `etage`/`salle`/`materiel` eux-mêmes ne sont jamais supprimés ni
  corrompus, car leurs propres jointures (`salle.etage`, `materiel.salle`)
  ne référencent pas l'objet supprimé mais l'objet intermédiaire toujours
  existant. Le mécanisme de suppression en cascade déjà en place
  (`backend/routes/routes_write.py`, `delete_object`, §3.2 — scopé tenant)
  convient donc **tel quel** à ce nouveau cas d'usage, aucune modification
  backend nécessaire.
- Validation `model/schema.json` : propriété `"cascade"` documentée
  (`type: array`, `items: string`), sans contrainte stricte — même esprit
  que `layer_map`/`separator` déjà acceptés à ce niveau.

## 3.3 Fichiers de modèle fournis

**`model/organisation.json`** — meta-classe `organisation` (action 17,
remplace les anciens `model/organigramme.json`/`model/personnes.json`,
supprimés) :
- `personne_physique` : attributs `nom`, `prenom` (domaine `details`, string). `displayname`: `"{{prenom}} {{nom}}"`.
- `role` : `nom` (string) + `membres` (`joint-1-1` → `personne_physique`).
- `groupe` : `nom` (string) + `membres` (`joint-1-n` → `personne_physique` ou `groupe`, donc récursif).
- `service_organisation`, `poste` : organigramme (hiérarchie service/poste, repris à l'identique de l'ancien `organigramme.json`).
- `societe` (+`holding` auto-référence), `departement`, `contact` (`type` tel/mail, `cible` multi-classe) : nouvelles classes action 17.

**`model/reseau.json`** — meta-classe `element_avec_ip` :
- `addresse_ip` : `adresse_ip` (string, `constraint` = regex IPv4, `sql_constraint: "UNIQUE VALUE"` — non appliquée par le code, voir §8), `vlan` (`joint-1-1` → `vlan`, action 17).
- `vlan` : `nom` (string), `definition` (string, regex CIDR), `membres` (`joint-1-n` → `addresse_ip`).
- `zone_reseau` (`nom`, `niveau_securite`, layers `infra`/`reseau`/`securite`),
  `equipement_reseau` (`nom`, `type` select `routeur`/`switch`/`firewall`,
  `zone` joint-1-1 → `zone_reseau`, layers `infra`/`reseau`),
  `entree_dns` (`nom`, `type` select `A`/`CNAME`/`MX`/`TXT`/`NS`, `cible`,
  `zone_dns`, layers `infra`/`reseau`) : nouvelles classes réseau action 17.
  Pas de classe `subnet` séparée : `vlan.definition` porte déjà le CIDR, un
  `vlan` **est** le subnet dans ce modèle (point vérifié explicitement en
  conception, pour éviter un doublon).

**`model/itil_cmdb.json`** — meta-classe `cmdb` (extension action 17 des
classes `datacenter`/`serveur`/`application`/`service_metier`/
`fournisseur`/`contrat_support` déjà fournies avant cette action) :
- `datacenter` : `nom`, `localisation` (string, `autosuggest`). Layers
  `physique`.
- `baie_serveur` 🆕 : `nom`, `datacenter` (joint-1-1 → `datacenter`),
  `position_rack`. Layers `infra`/`physique`. Reste rattachée à
  `datacenter` (pas à `salle` de `model/localisation.json` ci-dessous —
  changement envisagé en conception puis non retenu à l'implémentation).
- `serveur` : `nom`, `type` 🆕 (`select`, `physique`/`vm`, porte
  `layer_map: {"physique": ["physique"]}` — §3.2sexies, layer dynamique),
  `ip` (string, regex IPv4), `environnement` (string), `datacenter`
  (joint-1-1), `logo` 🆕 (`image`, domaine `display`, convention logo
  d'objet §3.2bis), `monitoring` 🆕 (`datasource`, classes autorisées
  `["query"]`), `actif` 🆕 (`boolean`), `hyperviseur` 🆕 (joint-1-1 →
  `hyperviseur` de `model/cluster.json` ci-dessous, pertinent si
  `type=vm`), `os` 🆕 (joint-1-1 → `os` ci-dessous). Layers `reseau` —
  **le layer statique `physique` a été retiré** de cette classe au profit
  du `layer_map` sur `type` (sinon l'union statique+dynamique aurait
  rendu tout serveur, y compris les VM, visible sous le filtre
  `physique`).
- `os` 🆕 : `nom` (string, `autosuggest`), `type` (`select`,
  `linux`/`windows`), `architecture` (`select`, `32`/`64`/`arm`),
  `version`, `code_version` (string), `active` (`boolean`). Layers
  `infra`.
- `application` : `nom`, `version`, `serveurs` (joint-1-n → `serveur`),
  `base_de_donnees` (joint-1-1), `modules` 🆕 (joint-1-n → `module`). 🆕
  (plan-mark4.md action 3b, révision post-revue 2026-11-26) : 6 attributs
  de démo ajoutés dans un domaine dédié `demo` (distinct de `details`/
  `logique`/`lien` ci-dessus, regroupement visuel à part dans
  `ConfigurationPage.tsx`), préfixés `demo_` pour rester visuellement non
  ambigus avec les attributs CMDB métier réels — cette classe est
  **réutilisée telle quelle** par le modèle de démo `model/demo_kafka.json`
  (pas de classe `application` dupliquée sous `demo_kafka`, qui entrait en
  collision de nom avec celle-ci) : `demo_role` (`select`
  frontend/backend/service), `demo_vm` (joint-1-1 → `vm` de `demo_kafka`),
  `demo_base_donnees` (joint-1-1 → `base_donnees` de `demo_kafka` —
  distinct de l'attribut `base_de_donnees` ci-dessus, qui pointe vers la
  classe CMDB `base_de_donnees`, elle-même inchangée), `demo_bus`
  (joint-1-1 → `bus_kafka` de `demo_kafka`), `demo_produit`/`demo_consomme`
  (joint-1-n → `type_donnee` de `demo_kafka`). `depends_on` de ce fichier
  complété avec `demo_kafka` (dépendance circulaire assumée avec
  `demo_kafka.json` → `cmdb`, même précédent que `cluster.json`↔
  `itil_cmdb.json`).
- `module` 🆕 : `nom`, `application` (joint-1-1). Layers `applicatif`.
- `container` 🆕 : `nom`, `image` (string), `namespace_kubernetes`
  (joint-1-1). Layers `applicatif`/`infra`.
- `namespace_kubernetes` 🆕 : `nom`, `kube` (joint-1-1 → `kube`, voir
  `model/cluster.json` ci-dessous). Layers `applicatif`/`infra`.
- `interface` 🆕 : `nom`, `type` (`select`,
  `REST`/`SOAP`/`file`/`queue`/`db`), `application` (joint-1-1,
  propriétaire du contrat exposé). Layers `applicatif`/`fonctionnel`.
- `flux_donnee` 🆕 : `nom`, `type_donnee` (string), `interface_source`/
  `interface_cible` (joint-1-1 → `interface` chacun — passe par le
  contrat exposé plutôt qu'un lien direct `application`→`application`).
  Layers `fonctionnel`/`metier`.
- `application_versionnee` 🆕 : `application` (joint-1-1), `version`
  (string, `autosuggest`), `modules_versionnes` (joint-1-n →
  `module_versionne`). Layers `applicatif`. ⚠️ Chevauchement repéré, non
  résolu : `model/ansible_inventory.json` porte déjà `version_logicielle`
  (`version`/`environnement`/`date_deploiement`/`application`), rôle
  proche — les deux coexistent sans fusion (voir aussi
  [`use case.md`](use%20case.md)).
- `module_versionne` 🆕 : `module` (joint-1-1), `version` (string,
  `autosuggest`). Layers `applicatif`. Chaîne de résolution complète :
  `application` →1-n→ `application_versionnee` →1-n→ `module_versionne`
  →1-1→ `module` →1-1→ `application`.
- `materiel` 🆕 : `nom`, `type` (`select`,
  `poste`/`imprimante`/`peripherique` — classe générique+`type` retenue
  plutôt qu'une classe par type de matériel), `numero_serie`,
  `personne_affectee` (joint-1-1 → `personne_physique`), `salle`
  (joint-1-1 → `salle` de `model/localisation.json` ci-dessous, porte
  `cascade: ["etage", "batiment"]` depuis plan-mark4.md action 6 — §3.2septies
  ci-dessous). Layers `infra`/`physique`.
- `service_metier`, `fournisseur`, `contrat_support` : classes
  préexistantes, inchangées par l'action 17.

**`model/cluster.json`** 🆕 (action 17) — meta-classe `cluster` :
- `kube` : `nom`, `version`, `namespace_defaut`. Layers `infra`.
- `hyperviseur` : `nom`, `type` (string libre, ex. vmware/proxmox),
  `capacite_cpu`/`capacite_ram` (integer). Layers `infra`.
- `cluster_applicatif` : `nom`, `vip` (joint-1-1 → `addresse_ip` de
  `model/reseau.json`, pas un string brut), `application` (joint-1-1),
  `serveurs` (joint-1-n → `serveur`). Layers `applicatif`/`infra`. Décision
  de conception explicite : 2 classes distinctes `kube`/`hyperviseur`
  plutôt qu'une classe générique `cluster`+`type`, pour pouvoir rattacher
  des VMs à un hyperviseur et des déploiements à un cluster Kubernetes
  sans confondre les deux modèles de rattachement.

**`model/localisation.json`** 🆕 (action 17) — meta-classe `localisation` :
- `batiment` : adresse structurée en 7 champs string (`numero`,
  `type_voie`, `nom_voie`, `pays`, `code_postal`, `ville`,
  `suffixe_ville`) plutôt qu'un champ libre unique.
- `etage` : `nom`, `batiment` (joint-1-1).
- `salle` : `nom`, `etage` (joint-1-1).
- Layers `infra` pour les trois classes.

**`model/besoin.json`** 🆕 (action 17) — meta-classe `besoin`, une seule
classe `besoin` : `nom`, `description`, `emerge_par`/`couvert_par`
(domaine `requirement`, joint-1-n, ciblant exactement `["serveur",
"application", "cluster_applicatif", "kube", "hyperviseur", "materiel",
"interface", "module"]` — les CI techniques, pas la totalité des classes
du modèle). Layers `fonctionnel`/`metier`.

**Retouches action 17 sur des meta-classes existantes** :
- `model/ticketing.json` (`ticket.ci_concerne.classes`) étendu à
  `["serveur", "application", "service_metier", "baie_serveur", "os",
  "module", "container", "namespace_kubernetes", "interface",
  "flux_donnee", "application_versionnee", "module_versionne",
  "materiel"]` (les 3 classes d'origine + les classes CMDB/hardware de
  `itil_cmdb.json` ajoutées ci-dessus, pas les classes de
  `cluster.json`/`reseau.json`).
- `model/planning.json` (`tache.assigne_a.classes`) élargi à
  `["personne_physique", "groupe"]` — une tâche assignable à une personne
  **ou** une équipe.

Dette assumée, non traitée par l'action 17 : `POST /api/init`
(`backend/routes/routes_init.py`) ne supprime jamais une ligne
`definition` dont le fichier modèle source a disparu — une base déjà
initialisée avec les anciens `organigramme.json`/`personnes.json` et
réinitialisée avec `organisation.json` sans ménage manuel garde en base
les anciennes lignes `meta_class = 'organigramme'`/`'personne'` en
doublon des classes désormais dans `organisation` (observé sur la DB dev
de ce projet, résolu par un nettoyage SQL manuel ponctuel, pas par un
mécanisme générique — aucune route de suppression/renommage de
meta-classe n'existe pour ce cas).

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

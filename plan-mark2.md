# Plan d'action — Mark 2 — suite des corrections et évolutions de miami-vice

> **Mark 2** : ce plan fait suite à [`plan-mark1.md`](plan-mark1.md)
> (clos le 2026-11-10). Il reprend telle quelle — contenu, analyse et
> correctifs proposés inchangés — la liste des points restés ouverts à
> la clôture de Mark 1 : 7a (résiduel), 8, 5, 6.0-6.4, 9, 10. Ce document
> devient le plan vivant à partir de maintenant ; toute nouvelle idée/
> évolution future se discute ici (ou dans un futur `plan-mark3.md` si ce
> document venait à son tour à se clore).

> **Suivi d'avancement** : mêmes conventions que Mark 1 — chaque action
> porte un champ **Statut** (⬜ à faire / 🔄 en cours / ✅ fait) mis à jour
> au fur et à mesure, par sous-point dès qu'il est validé (pas seulement
> en fin d'action complète), avec une date et un résumé de ce qu'ont
> confirmé `worker`/`testeur`/`arbitre`/`testeur-global`. Le tableau
> récapitulatif en fin de document doit rester synchronisé avec ces
> statuts. Toute décision qui annule/remplace un contenu déjà écrit ici
> doit être annotée explicitement (pas supprimée silencieusement).

## 5. [Absence de contrôle] Aucune validation de schéma/typage, ni de cohérence meta_class/class

- **Problème (1)** : `jsonschema` est déclaré en dépendance
  (`backend/requirements.txt`) mais jamais importé ni appelé ;
  `load_schema()` (`backend/app.py` lignes 28-30) n'est invoquée nulle
  part. Résultat : `POST /api/write/object`, `POST /api/write/class`,
  `POST /api/write/metaclass` et `POST /api/init` acceptent n'importe
  quelle structure, y compris une `meta_class`/`class` jamais définie, un
  attribut hors schéma, ou une valeur qui viole `constraint` (regex) —
  `sql_constraint` n'est de toute façon jamais traduit en contrainte SQL
  (non traité ici, voir action structurante distincte si demandée).
- **Problème (2), confirmé par lecture de code le 2026-11-10 (remarque
  utilisateur : « pour l'écriture ça devrait se baser sur le modèle de la
  classe/metaclasse pour avoir le type de chaque attribut »)** : le type
  de stockage d'une valeur n'est **jamais** déterminé à partir du type
  déclaré de l'attribut dans le modèle (`attr_def["type"]`,
  `model/schema.json`) — il est deviné à l'écriture, et cette devinette
  diffère même selon l'endpoint :
  - `_insert_value` (`backend/app.py` lignes 736-757, utilisée par
    `write_object`) choisit la colonne (`value_integer`/`value_float`/
    `value_string`/`joint_id`) uniquement par `isinstance()` sur la
    valeur JSON déjà décodée — fonctionne par coïncidence tant que le
    client envoie un type JSON cohérent avec l'intention, mais ignore
    totalement `attr_def["type"]`.
  - `write_attribute_value` (`PUT /api/write/attribute/<cls>/<id>/
    <attribute>/<value>`, lignes 832-850) reçoit `value` comme une
    **chaîne d'URL brute** et choisit la colonne par une cascade
    `try: int(value) / except: try: float(value) / except: str` — **sans
    jamais consulter le modèle**. Conséquence concrète et reproductible :
    un attribut déclaré `"type": "string"` dans le modèle (ex. un code
    postal, un numéro de téléphone, un matricule à zéro non significatif
    type `"007"`) dont la valeur ressemble à un nombre est **silencieusement
    stocké dans `value_integer`/`value_float`**, pas `value_string` —
    perte de format (zéros non significatifs, signe, notation) et
    incohérence avec le type déclaré par le modèle. `_build_object_payload`
    (lecture, lignes ~525-531) détermine ensuite le type uniquement par
    la colonne non-nulle trouvée, donc cette erreur de typage à
    l'écriture devient une erreur de typage persistante à la lecture,
    sans que rien ne la signale.
- **Correctif** :
  1. Dans `backend/app.py`, ajouter `import jsonschema` et appeler
     `jsonschema.validate(instance=data, schema=load_schema())` :
     - dans `write_metaclass` (lignes 431-475), juste après la construction de
       `data = {"meta_class": ..., "classes": ...}` (ligne 446), avant toute requête
       SQL — lever `400` (capturer `jsonschema.ValidationError` et faire
       `abort(400, description=str(e))`) si invalide.
     - dans `write_class` (ligne ~386), construire un objet
       `{"meta_class": meta_class_name, "classes": classes_apres_remplacement}`
       (le tableau `classes` complet après fusion/ajout, ligne 416) et le
       valider de la même façon avant le `UPDATE`.
     - dans `init_from_model_files` (lignes 482-514), valider chaque
       `data` chargé avec `jsonschema.validate` ; en cas d'échec, ne pas
       planter tout l'endpoint mais **ignorer ce fichier** (cohérent avec
       le comportement actuel « fichier sans meta_class/classes ignoré
       silencieusement ») — ou lever une erreur explicite listant le
       fichier fautif, au choix produit ; a minima ne pas insérer de
       données invalides en base. **Note (héritée du cycle multi-tenant,
       Mark 1 action 11)** : `init_from_model_files` fait déjà du
       skip-and-report par classe pour les raisons de portée tenant — la
       validation de schéma doit s'intégrer dans ce même pattern, pas le
       remplacer par un tout-ou-rien.
  2. Dans `write_object` (`backend/app.py`, lignes 172-264) :
     - après avoir résolu `class_def` (ligne ~199-204), si `defn` est
       `None` ou `class_def` reste `None`, répondre `400` (« meta_class/
       class non définie ») plutôt que de créer l'objet quand même ;
     - pour chaque attribut dont la définition (`attr_def`) a un type
       `string` et une clé `constraint` non vide, valider la ou les
       valeurs reçues avant l'insertion (`_insert_value`) : `attr_value`
       peut être une liste de valeurs (attribut multi-valué) et pas
       seulement un scalaire unique, donc itérer sur chaque élément de
       la liste et appliquer `re.fullmatch` à chacun plutôt que
       d'appliquer `re.fullmatch(attr_def["constraint"], str(attr_value))`
       directement sur une éventuelle liste entière (ce qui ne
       matcherait jamais correctement, `str(["a", "b"])` ne pouvant pas
       satisfaire une regex métier) :
       ```python
       values = attr_value if isinstance(attr_value, list) else [attr_value]
       for v in values:
           if not re.fullmatch(attr_def["constraint"], str(v)):
               abort(400, description=f"Valeur invalide pour l'attribut {attr_def['name']!r}: {v!r}")
       ```
       Répondre `400` listant l'attribut en échec si la regex ne
       correspond pas. Ajouter `import re` en tête de fichier.
  3. `sql_constraint` reste hors du périmètre « correction de bug » —
     spécifications.md le documente comme une fonctionnalité **jamais
     implémentée** (§8), pas un bug de code existant ; l'ajouter
     nécessiterait de la génération de DDL dynamique et sort du cadre
     « corriger les anomalies identifiées ». Ne pas y toucher ici.
  4. **Point nouveau (hérité de Mark 1 action 11)** : le champ `tenants`
     ajouté aux classes (`model/schema.json`) doit lui aussi être couvert
     par cette validation si le schéma effectivement chargé à l'exécution
     de cette action le contient déjà (c'est le cas : action 11 est faite
     dans Mark 1 avant la clôture).
  5. **Correctif du Problème (2), typage piloté par le modèle** : faire
     dépendre la colonne de stockage du **type déclaré** de l'attribut
     (`attr_def["type"]`), jamais d'une devinette sur la valeur reçue :
     - Factoriser une fonction unique (ex. `_store_typed_value(cur,
       attribute_id, attr_def, raw_value)`), appelée depuis `_insert_value`
       (donc `write_object`) **et** depuis `write_attribute_value`, pour
       que les deux endpoints appliquent exactement la même règle —
       aujourd'hui ils divergent déjà l'un de l'autre (JSON typé côté
       `write_object` vs cascade int/float/string côté
       `write_attribute_value`), ce qui est une incohérence en soi.
     - Selon `attr_def["type"]` : `"string"` → toujours `value_string`
       (ne jamais tenter `int()`/`float()` dessus, quelle que soit
       l'apparence de la valeur) ; `"integer"` → `int(raw_value)`, `400`
       si la conversion échoue ; `"float"`/`"number"` → `float(raw_value)`,
       `400` si la conversion échoue ; `"joint-1-1"`/`"joint-1-n"` →
       exiger la forme `{"joint_id": N}` (déjà le cas via `write_object`),
       `400` si une valeur scalaire est envoyée à la place (cohérent avec
       le choix déjà fait à l'action 4 de Mark 1 de ne jamais router un
       joint-1-1 par `write_attribute_value`/`apiWriteAttribute` côté
       frontend — ce correctif rend cette règle vraie aussi côté serveur,
       pas seulement par convention frontend).
     - **Décision à prendre au moment de l'implémentation** : si
       l'attribut n'est pas déclaré dans le modèle de la classe
       (`attr_def` introuvable) — cas qui devrait devenir rare une fois
       le Problème (1) corrigé (classe/attribut inconnu rejeté en amont),
       mais qui reste possible pour une classe non encore validée ou un
       nom d'attribut mal orthographié — deux options : conserver
       l'heuristique actuelle par type Python/cascade comme repli, ou
       rejeter `400` (« attribut non déclaré dans le modèle »). La
       seconde est plus cohérente avec l'esprit de cette action
       (« cohérence meta_class/class ») mais change le comportement
       actuel (silencieux aujourd'hui) — à trancher avec l'utilisateur
       avant implémentation, pas un choix à faire seul par le worker.
- **Effort** : moyen à conséquent (plusieurs points d'insertion, logique
  de validation ET de typage à écrire et tester sur les deux fichiers
  `model/*.json` existants, plus un cas de non-régression explicite pour
  un attribut `string` à valeur numérique-looking, ex. un code postal ou
  un matricule avec zéro non significatif).
- **Fichiers** : `backend/app.py`, `backend/requirements.txt` (vérifier
  que `jsonschema` y est bien listé — déjà le cas d'après
  specifications.md §3.2).
- **Dépendance** : doit être fait **après** l'action 8 (correction de
  `model/schema.json` pour accepter `$schema`), sinon activer la
  validation casse immédiatement le chargement des fichiers d'exemple
  fournis (`model/personnes.json`, `model/reseau.json`), qui contiennent
  tous deux une clé `$schema` non déclarée.
- **Statut** : ⬜ à faire.

## 6. [Absence de fonctionnalité] Aucune route de suppression — avec historisation

> Conception actée en Mark 1 (révision du 2026-11-09, voir
> `plan-mark1.md` et `specifications.md` §10.4) : suppression **logique**
> d'un objet (pose d'une date de fin), suivie d'une purge physique
> différée après une période de grâce. ~~Confirmée à une valeur fixe de
> 30 jours, non rediscutable (décision du 2026-11-10)~~ — **révisé le
> 2026-11-10, le même jour** : la période de grâce sera **configurable
> par l'administrateur** (pas une constante Python figée), 30 jours
> restant la valeur par défaut — voir 6.2 pour le détail de conception.
> La suppression d'une **classe** ou d'une **meta-classe** reste une
> suppression physique immédiate, sans changement — elle ne touche
> jamais `object`/`attribute_value`.

### 6.0 [Prérequis] Historisation du modèle de données

- **Problème** : `write_object` (`backend/app.py`) supprime aujourd'hui
  tous les attributs/valeurs existants de l'objet et les recrée
  intégralement à chaque sauvegarde (« ce n'est pas un merge »,
  `specifications.md` §4.3). Historiser « si un attribut est réécrit,
  ajouter une date de fin à l'actuel et une nouvelle valeur avec date de
  création » (demande utilisateur) est incompatible avec ce pattern
  delete-then-recreate : il n'y a aujourd'hui aucune corrélation entre
  l'ancienne ligne `attribute_value` et la nouvelle (id différent à
  chaque écriture), donc impossible de savoir quelle valeur « remplace »
  quelle autre sans un diff explicite.
- **Correctif schéma** (`sql/init.sql`) :
  - `attribute_value` : ajouter `valid_from TIMESTAMPTZ NOT NULL DEFAULT now()`
    et `valid_to TIMESTAMPTZ NULL`. La version courante d'une valeur est
    celle où `valid_to IS NULL`.
  - `object` : ajouter `deleted_at TIMESTAMPTZ NULL`. Un objet actif est
    celui où `deleted_at IS NULL`.
  - Les contraintes `ON DELETE CASCADE`/`ON DELETE SET NULL` existantes
    restent en place pour le jour où la purge physique (6.2) les
    déclenche réellement ; elles ne servent plus lors d'une suppression
    logique (aucune ligne n'est physiquement retirée à ce stade).
  - **Point nouveau (hérité de Mark 1 action 11)** : l'ajout de
    `object.tenants` par Mark 1 doit être pris en compte dans les
    requêtes de lecture réécrites ici (filtrage tenant **et**
    `deleted_at IS NULL`/`valid_to IS NULL` combinés, pas l'un au
    détriment de l'autre).
- **Correctif applicatif** : réécrire `write_object` en logique de diff
  plutôt que delete-then-recreate :
  1. Charger les valeurs actuellement actives (`valid_to IS NULL`) de
     l'objet, regroupées par `(domain, name)`.
  2. Pour chaque attribut du corps de la requête : valeur identique à la
     version active → ne rien faire ; valeur différente →
     `UPDATE attribute_value SET valid_to = now() WHERE id = <ancienne>`
     puis `INSERT` de la nouvelle valeur (`valid_from = now()`,
     `valid_to = NULL`).
  3. Attribut actif non repassé dans le corps de la requête (cohérent
     avec la sémantique « remplacement complet » déjà documentée en
     §4.3) : `UPDATE attribute_value SET valid_to = now()` sans nouvelle
     insertion — l'attribut devient « fermé », plus de version active.
- **Correctif lecture** : toutes les requêtes qui lisent
  `attribute`/`attribute_value` (`_build_object_payload`, `list_objects`,
  etc.) doivent filtrer `WHERE av.valid_to IS NULL` par défaut (version
  courante uniquement) ; toute lecture d'objet doit filtrer
  `WHERE deleted_at IS NULL` par défaut.
- **Hors périmètre explicite (TODO documenté, pas implémenté ici)** :
  l'affichage d'un historique des versions (UI de consultation des
  anciennes valeurs d'un attribut, ou des objets supprimés) est reporté —
  demande explicite de l'utilisateur (« on gérera l'affichage d'historique
  par la suite »). Seul le stockage historisé est mis en place ici ; noté
  en TODO dans `specifications.md` §10.4.
- **Fichiers** : `sql/init.sql`, `backend/app.py` (`write_object`,
  `_build_object_payload`, `list_objects`, et toute autre requête de
  lecture des attributs).
- **Statut** : ⬜ à faire.

### 6.1 Suppression logique d'un objet

- **Correctif** : `DELETE /api/delete/object/<int:object_id>` : vérifier
  l'existence et que l'objet n'est pas déjà supprimé (404 si absent ou
  si `deleted_at IS NOT NULL`), puis dans la même transaction :
  `UPDATE object SET deleted_at = now() WHERE id = %s`, et
  `UPDATE attribute_value SET valid_to = now() WHERE valid_to IS NULL AND attribute_id IN (SELECT id FROM attribute WHERE object_id = %s)`
  (ferme toutes les valeurs actives de l'objet), `conn.commit()`,
  réponse `200 {"status":"ok","id":object_id,"deleted_at":"..."}`.
- **Jointures entrantes** : `joint_id` reste intact (l'objet existe
  toujours physiquement tant que la purge 6.2 n'est pas passée) — la
  résolution `deref` (Mark 1 action 2bis) doit considérer un objet cible
  `deleted_at IS NOT NULL` comme non résolvable par défaut (même
  traitement que le cas « orphelin » déjà géré : `{"joint_id": N}` sans
  `resolved`), sauf si l'équipe préfère exposer un flag `deleted: true`
  explicite — à trancher au moment de l'implémentation.
- **Câblage frontend minimal** : `apiDeleteObject` dans `api.ts`, bouton
  de suppression dans `NavigationPage.tsx` pour un objet — le strict
  minimum pour que la fonctionnalité soit utilisable.
- **Point nouveau (hérité de Mark 1 action 11)** : la suppression d'un
  objet doit respecter le RBAC déjà en place — `tenant-readonly` → 403 ;
  `tenant-admin` → autorisé uniquement sur les objets dans son périmètre
  tenant (même logique que l'écriture, §11.2 de `plan-mark1.md`).
- **Fichiers** : `backend/app.py`, `frontend/src/api.ts`,
  `frontend/src/pages/NavigationPage.tsx`.
- **Dépendance** : nécessite 6.0 (colonnes `deleted_at`/`valid_to`).
- **Statut** : ⬜ à faire.

### 6.2 Purge physique différée

> **Révision de conception (2026-11-10, même jour que la confirmation
> initiale)** : décision utilisateur — « la grâce sera configurable par
> l'administrateur ». Remplace la constante Python figée
> `PURGE_GRACE_PERIOD_DAYS` envisagée plus haut par un paramètre modifiable
> à chaud (sans redéploiement), 30 jours restant la valeur par défaut.

- **Principe** : après une période de grâce suivant `deleted_at`, un
  mécanisme de purge supprime **physiquement** les lignes
  `attribute_value`/`attribute` de l'objet. Décision à prendre au moment
  de l'implémentation : conserver la ligne `object` elle-même (avec juste
  ses attributs purgés, préservant la trace des jointures entrantes) ou
  la supprimer entièrement (active le `ON DELETE SET NULL`/`CASCADE` déjà
  en place sur les jointures restantes).
- **Stockage de la période de grâce (configurable)** :
  - Nouvelle table `sql/init.sql` : `app_config (key TEXT PRIMARY KEY,
    value TEXT NOT NULL)`, générique (clé/valeur), pour rester cohérent
    avec la philosophie dynamique du reste du projet plutôt que d'ajouter
    une colonne dédiée de plus à chaque nouveau paramètre futur.
    Initialisée avec une ligne `('purge_grace_period_days', '30')` (seed
    dans `sql/init.sql`, cohérent avec la valeur par défaut déjà actée).
  - **Lecture** : `GET /api/config/purge_grace_period_days` → réservé à
    `global-admin` (même raisonnement que la route de purge elle-même :
    paramètre qui affecte tous les tenants).
  - **Écriture** : `PUT /api/config/purge_grace_period_days`, body
    `{"value": N}`, réservé à `global-admin` ; valider `N` entier
    strictement positif (`400` sinon — en particulier rejeter `0` et les
    valeurs négatives, qui purgeraient immédiatement ou jamais).
  - La route de purge (ci-dessous) lit cette valeur en base **à chaque
    appel** (pas une constante chargée une fois au démarrage du process
    Gunicorn) — un changement par l'administrateur doit être pris en
    compte sans redémarrage du backend.
  - **Câblage frontend minimal** : un champ dans `ConfigurationPage.tsx`
    (visible uniquement pour `global-admin`, même pattern de masquage que
    le reste du RBAC UI de Mark 1 action 11.3) pour lire/modifier cette
    valeur — pas une page de configuration générique pour d'éventuels
    futurs paramètres, seulement celui-ci, pour rester dans le périmètre
    demandé.
- **Déclenchement** : pas de scheduler dans l'architecture actuelle
  (Flask simple, pas de worker de tâches de fond) — prévoir dans un
  premier temps une route déclenchable manuellement/administrativement
  (`POST /api/purge`, protégée par l'authentification Keycloak déjà en
  place depuis Mark 1 — réservée à `global-admin` uniquement, pas aux
  `tenant-admin`, par cohérence avec une opération qui traverse tous les
  tenants), qui traite tous les objets dont
  `deleted_at < now() - (valeur courante de purge_grace_period_days)`
  jours. Une automatisation (cron externe, ou scheduler Python type
  APScheduler) est une amélioration possible mais hors périmètre de ce
  correctif minimal.
- **Fichiers** : `backend/app.py`, `sql/init.sql`,
  `frontend/src/pages/ConfigurationPage.tsx`.
- **Dépendance** : nécessite 6.1.
- **Statut** : ⬜ à faire.

### 6.3 Suppression d'une classe (schéma — suppression physique)

- **Correctif** : `DELETE /api/delete/class/<string:meta_class>/<string:cls>` :
  charger `definition` par `meta_class` (404 si absente), retirer
  l'élément de `data["classes"]` dont `class == cls` (404 si absent),
  `UPDATE definition SET data = %s` avec `json.dumps(data)` comme
  paramètre (pas le dict Python brut), cohérent avec le pattern déjà
  utilisé partout ailleurs dans `app.py` pour écrire la colonne JSONB
  `definition.data` (`write_class`, `write_metaclass`), réponse `200`.
  Documenter explicitement que ceci ne supprime pas et ne modifie pas
  les objets déjà créés sous cette classe (aucune FK entre `object` et
  `definition`, §3.4).
- **Point nouveau (hérité de Mark 1 action 11)** : réservée aux rôles
  `global-admin`/`tenant-admin`, avec restriction de `tenant-admin` à ses
  propres classes (même garde que `write_class`, §11.2 de
  `plan-mark1.md`).
- **Fichiers** : `backend/app.py`.
- **Statut** : ⬜ à faire.

### 6.4 Suppression d'une meta-classe (schéma — suppression physique)

- **Correctif** : `DELETE /api/delete/metaclass/<string:meta_class>` :
  `DELETE FROM definition WHERE meta_class = %s` (404 si 0 ligne
  affectée), réponse `200`. Documenter explicitement que ceci ne
  supprime pas les objets déjà créés sous cette meta-classe (cohérent
  avec le constat §3.4 : aucune FK entre `object` et `definition`).
- **Fichiers** : `backend/app.py`.
- **Statut** : ⬜ à faire.

- **Effort global de l'action 6** : conséquent (6.0 = réécriture d'un
  endpoint central + migration de schéma ; 6.1/6.2 = nouvelles routes ;
  6.3/6.4 = routes simples déjà conçues).
- **Statut global** : ⬜ à faire (sous-actions détaillées ci-dessus).

## 7a. [Résiduel, hérité de Mark 1] Propagation du prop `readOnly` à `DiagramPage`

> **Portée réduite (2026-11-10)** : à l'origine (`plan-mark1.md` action 7),
> ce point couvrait aussi `ConfigurationPage.tsx` — devenu sans objet,
> cette page est désormais masquée pour de bon pour `tenant-readonly`
> (Mark 1 action 11.3, vrai masquage côté client + garde serveur), pas
> seulement désactivée. Seul le volet `DiagramPage.tsx` reste pertinent :
> cette page n'a aujourd'hui aucune action d'écriture, mais ne reçoit
> toujours pas le prop `readOnly` par cohérence d'interface avec les deux
> autres pages, pour anticiper toute future action d'écriture.

- **Correctif** :
  1. Dans `frontend/src/pages/DiagramPage.tsx`, ajouter `readOnly:
     boolean` à `DiagramPageProps`.
  2. Dans `frontend/src/App.tsx`, passer `readOnly={readOnly}` à l'appel
     `<DiagramPage>`, comme c'est déjà fait pour `<NavigationPage>`.
- **Effort** : trivial.
- **Fichiers** : `frontend/src/pages/DiagramPage.tsx`, `frontend/src/App.tsx`.
- **Statut** : ⬜ à faire — faible priorité (aucune action d'écriture
  réelle sur cette page aujourd'hui), à traiter si le temps le permet ou
  à laisser en l'état si jugé non prioritaire.

## 8. [Cohérence modèle] `$schema` non déclaré dans `model/schema.json`

- **Problème** : `model/personnes.json` et `model/reseau.json`
  contiennent une clé racine `"$schema": "schema.json"` (ligne 2 de
  chaque fichier), alors que `model/schema.json` déclare
  `"additionalProperties": false` au niveau racine (dernière ligne du
  fichier) sans lister `$schema` parmi les `properties` — ces fichiers
  d'exemple échoueraient donc leur propre validation dès qu'elle serait
  activée (action 5).
- **Correctif** : dans `model/schema.json`, ajouter `$schema` à l'objet
  `properties` racine, en propriété optionnelle (ne pas l'ajouter à
  `required`) :
  ```jsonc
  "properties": {
      "$schema": {
          "type": "string",
          "description": "Référence informative vers ce schéma, ignorée au runtime"
      },
      "meta_class": { ... },
      "classes": { ... }
  },
  "additionalProperties": false
  ```
  Alternative rejetée : retirer la clé `$schema` des fichiers
  `model/personnes.json`/`model/reseau.json` — moins bon, car cette clé
  est une convention JSON Schema standard utile aux éditeurs (autocomplétion/
  validation IDE) ; il est plus cohérent de la déclarer explicitement que
  de la supprimer des données.
- **Effort** : trivial.
- **Fichiers** : `model/schema.json`.
- **Dépendance** : doit précéder (ou accompagner dans le même commit)
  l'activation de la validation JSON Schema de l'action 5.
- **Statut** : ⬜ à faire.

## 9. Partitionnement PostgreSQL par type d'objet

- **Origine** : demande explicite de l'utilisateur malgré la réserve de
  l'équipe (voir `specifications.md` §10.5) sur la prématurité sans
  volumétrie réelle mesurée.
- **Problème/besoin** : la table `object` (`sql/init.sql`) n'est pas
  partitionnée ; à volumétrie importante, les requêtes filtrées par
  `class`/`meta_class` (très fréquentes : `write_object`,
  `write_attribute_value`, `list_objects` filtré côté client) pourraient
  bénéficier d'un partitionnement PostgreSQL par liste sur `class`.
- **Tension de conception à garder en tête pendant l'implémentation** :
  le modèle est entièrement dynamique (classes définies dans
  `definition.data`, JSON, créées/renommées/supprimées à chaud sans DDL,
  §1/§3.2 de `specifications.md`) alors que `PARTITION BY LIST (class)`
  exige un DDL (`CREATE TABLE ... PARTITION OF ... FOR VALUES IN (...)`,
  puis `ATTACH`/`DETACH PARTITION`) à chaque création/suppression/
  renommage de classe. Implémentation proposée en 2 étapes :
  1. **Évaluation préalable (à faire en premier, avant tout DDL)** :
     mesurer la distribution réelle du nombre d'objets par classe sur un
     jeu de données représentatif (ou, à défaut de données réelles,
     documenter explicitement l'hypothèse de volumétrie retenue) — ne
     pas implémenter le partitionnement sans ce chiffrage, pour éviter
     un chantier lourd sans bénéfice mesurable.
  2. **Si justifié** : partitionner `object` par `class`
     (`PARTITION BY LIST (class)`), et déclencher automatiquement
     `ALTER TABLE object ATTACH PARTITION object_<class> FOR VALUES IN ('<class>')`
     (après création de la partition fille si elle n'existe pas) depuis
     `write_class`/`write_metaclass` (`backend/app.py`), au moment où une
     nouvelle classe est déclarée. Gérer symétriquement le cas
     suppression de classe (action 6.3) : ne **pas** détacher/supprimer
     automatiquement la partition (les objets existants doivent rester
     lisibles, cohérent avec « aucune FK entre `object` et `definition` »,
     §3.4) — documenter cette asymétrie explicitement.
  - `attribute`/`attribute_value` ne portent pas `class` aujourd'hui (FK
    uniquement vers `object_id`/`attribute_id`) : les partitionner de la
    même façon nécessiterait de dénormaliser `class` sur ces deux tables,
    changement de schéma plus large, hors périmètre de cette action sauf
    si l'évaluation de l'étape 1 le justifie explicitement.
- **Effort** : important (DDL dynamique déclenché depuis l'application,
  jamais fait ailleurs dans ce projet ; risque de régression sur les
  contraintes FK existantes, qui imposent des règles supplémentaires
  avec des tables partitionnées).
- **Fichiers** : `sql/init.sql`, `backend/app.py` (`write_class`,
  `write_metaclass`).
- **Statut** : ⬜ à faire (commencer par l'évaluation préalable).

## 10. Liens transitifs du graphe au filtrage de classe

- **Origine** : amélioration UX demandée par l'utilisateur, voir
  `specifications.md` §10.6.
- **Problème** : dans `frontend/src/pages/DiagramPage.tsx`, la
  construction des arêtes du graphe (fonction `graphData`, bloc qui
  construit `links`) ne garde une arête que si les **deux** extrémités
  sont visibles (`visibleIds.has(val.joint_id)`) — masquer une classe via
  les chips de filtre fait disparaître toutes les arêtes passant par un
  nœud de cette classe, y compris quand ça casse une chaîne de jointures
  (A→B→C, B masqué) qui aurait pu rester visible sous forme de lien
  direct A→C.
- **Correctif** :
  1. Changer l'ordre des opérations : construire **d'abord** le graphe
     d'adjacence complet (tous les objets, toutes les arêtes, y compris
     vers/depuis des nœuds qui seront masqués), à partir de `details`
     (le cache complet non filtré), avant d'appliquer le filtre de
     visibilité — actuellement le filtre est appliqué pendant la
     construction (ligne qui exclut directement une arête si la cible
     n'est pas visible), ce qui empêche toute reconstruction ultérieure.
  2. Pour chaque arête dont une extrémité est masquée, suivre
     récursivement les arêtes sortantes du nœud masqué jusqu'à atteindre
     un nœud visible (ou s'arrêter sans créer d'arête si aucun nœud
     visible n'est atteignable) — fermeture transitive locale. Protéger
     contre les cycles (le modèle a des jointures récursives réelles :
     `groupe.membres` → `groupe`) avec un ensemble de nœuds déjà visités
     sur le chemin de traversée courant, à l'image de la protection
     `in_progress` déjà utilisée côté backend pour `deref`/`depth`
     (Mark 1 action 2bis, `backend/app.py`).
  3. **Distinction visuelle obligatoire** : une arête reconstituée (via
     un ou plusieurs nœuds masqués) doit être visuellement distincte
     d'une vraie jointure directe (ex. trait pointillé dans la config
     ECharts de la série `graph`), pour ne pas laisser croire à
     l'utilisateur qu'une relation directe existe réellement en base.
  4. **Label de l'arête reconstituée** : une chaîne A→B→C avec des noms
     d'attributs différents à chaque saut (ex. `membres` puis
     `employeur`) ne peut pas porter un label unique sans perte
     d'information — ne pas afficher de label sur les arêtes
     reconstituées (seulement sur les arêtes directes), plutôt que
     d'inventer une concaténation ambiguë.
  5. **Garde-fou de volume** : un nœud masqué à fort fan-in/fan-out peut
     générer une explosion combinatoire d'arêtes synthétiques
     (ex. 10 entrées × 10 sorties = 100 arêtes reconstituées) — prévoir
     un plafond raisonnable (ex. ne pas reconstituer au-delà d'un certain
     nombre d'arêtes par nœud masqué, ou limiter la fermeture transitive
     à une profondeur de nœuds masqués consécutifs, ex. 2) pour éviter de
     dégrader le rendu ECharts sur un graphe très connecté.
  6. Vérifier la cohérence avec le layout « Organigramme » (reconstruction
     d'arbre à partir de `graphData.links`) : le changement de
     construction des liens doit rester cohérent entre les 3 layouts
     (Force/Circulaire/Organigramme), qui consomment tous la même
     structure de données.
- **Effort** : moyen (logique de fermeture transitive + anti-cycle +
  garde-fou de volume à tester sur un graphe réaliste avec plusieurs
  niveaux de jointures masquées).
- **Fichiers** : `frontend/src/pages/DiagramPage.tsx`.
- **Statut** : ⬜ à faire.

## Ordre d'exécution recommandé

**Vague 1 — activer les validations manquantes (actions 8 puis 5)**
L'action 8 (déclarer `$schema` dans `model/schema.json`) doit précéder
l'action 5 (appeler enfin `jsonschema.validate`), sans quoi activer la
validation casse immédiatement le chargement des fichiers d'exemple
fournis avec le dépôt.

**Vague 2 — combler les fonctionnalités absentes (action 6 dans l'ordre
6.0→6.1→6.2→6.3/6.4)**
Dépendance interne stricte : 6.0 (historisation du modèle, colonnes
`valid_from`/`valid_to`/`deleted_at` + réécriture de `write_object`) doit
précéder 6.1 (suppression logique, qui s'appuie sur `deleted_at`), qui
doit elle-même précéder 6.2 (purge physique, qui s'appuie sur des objets
déjà marqués `deleted_at`). 6.3/6.4 (suppression physique de
classe/meta-classe) sont indépendantes de 6.0-6.2 et peuvent être faites
en parallèle. La route `POST /api/purge` (6.2) est protégée par
l'authentification Keycloak déjà en place depuis Mark 1.

**Vague 3 — évolutions de confort (actions 9 et 10)**
Indépendantes l'une de l'autre et du reste du plan. L'action 9
(partitionnement) doit commencer par son évaluation préalable de
volumétrie avant tout DDL. L'action 10 (liens transitifs du graphe) est
purement frontend, sans dépendance sur le backend.

**Hors vague, faible priorité — action 7a résiduelle**
Indépendante du reste, peut être traitée à tout moment ou laissée de côté.

## Récapitulatif d'avancement

> Tableau à tenir à jour en même temps que le champ **Statut** de chaque
> action ci-dessus — une ligne par action, pas par vague.

| # | Vague | Action | Fait ? |
|---|-------|--------|--------|
| 8 | 1 | `$schema` non déclaré dans `model/schema.json` | ⬜ |
| 5 | 1 | Validation de schéma/`constraint`, cohérence meta_class/class, **typage de stockage piloté par le modèle** | ⬜ |
| 6.0 | 2 | Historisation du modèle (`valid_from`/`valid_to`/`deleted_at` + réécriture `write_object`) | ⬜ |
| 6.1 | 2 | Suppression logique d'un objet | ⬜ |
| 6.2 | 2 | Purge physique différée (période de grâce **configurable par l'admin**, défaut 30 jours) | ⬜ |
| 6.3 | 2 | Suppression d'une classe (physique) | ⬜ |
| 6.4 | 2 | Suppression d'une meta-classe (physique) | ⬜ |
| 9 | 3 | Partitionnement PostgreSQL par type d'objet (évaluation puis implémentation conditionnelle) | ⬜ |
| 10 | 3 | Liens transitifs du graphe au filtrage de classe | ⬜ |
| 7a | hors vague | Propagation du prop `readOnly` à `DiagramPage.tsx` (résiduel, faible priorité) | ⬜ |

**Décision actée (2026-11-10, révisée le même jour)** : la période de
grâce de purge (action 6.2) est **configurable par l'administrateur**
(`global-admin`, table `app_config`, pas une constante Python), avec
**30 jours** comme valeur par défaut au seed initial.

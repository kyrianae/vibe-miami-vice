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
- **Statut** : ✅ fait (2026-11-10). Option B actée (attribut non déclaré
  dans le modèle → 400). `_store_typed_value` factorisée (`write_object` +
  `write_attribute_value`), typage piloté par `attr_def["type"]`,
  validation `constraint` (regex) et `jsonschema.validate`
  (`write_class`/`write_metaclass`/`init_from_model_files`,
  skip-and-report) en place. 2 itérations de revue : it.1 a trouvé
  2 points bloquants convergents (regex contournable via
  `write_attribute_value` ; regex malformée → 500 non catché) + 1 point
  d'harmonisation (ordre RBAC/validation dans `write_metaclass`) ; it.2 :
  les 3 corrigés et revérifiés (28/28 tests, tests dédiés ajoutés dans
  `backend/test_model_driven_typing.py` et
  `backend/test_rbac_class_tenant_scope.py`). Arbitre final ✅ OK. Dette
  non bloquante actée : messages jsonschema verbeux/anglais, `skipped` à
  2 formes, type `"number"` mort, pas de validation de compilabilité de
  `constraint` à la déclaration de classe. Non commité.

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
  `WHERE deleted_at IS NULL` par défaut — concrètement, dans
  `_build_object_payload` (`backend/app.py` lignes ~487-496), ajouter
  `AND deleted_at IS NULL` dans **les deux branches** de la requête objet
  (celle utilisée quand `tenant_filter is None` et celle avec le filtre
  `string_to_array(tenants, ',') && %s::text[]`) — oublier une seule des
  deux rendrait le comportement incohérent entre `global-admin` et un
  rôle tenant face à un objet supprimé. Avec ce filtre, un objet cible
  soft-deleted produit `obj = None`, donc `_resolve_joint_value` retombe
  naturellement sur le chemin orphelin déjà existant (`{"joint_id": N}`
  sans `resolved`) — pas de nouvelle clé `deleted` nécessaire, cf. 6.1.
- **Index requis (conception finalisée du 2026-11-10, issue de l'arbitrage
  6.1/6.2)** : `CREATE INDEX idx_attribute_value_joint_id ON
  attribute_value(joint_id);` dans `sql/init.sql`, à créer en même temps
  que les colonnes ci-dessus — requis par la cascade de 6.1 et la purge
  de 6.2, qui filtrent toutes deux sur `joint_id` ; sans lui, chaque
  suppression/purge scanne `attribute_value` entièrement.
- **Hors périmètre explicite (TODO documenté, pas implémenté ici)** :
  l'affichage d'un historique des versions (UI de consultation des
  anciennes valeurs d'un attribut, ou des objets supprimés) est reporté —
  demande explicite de l'utilisateur (« on gérera l'affichage d'historique
  par la suite »). Seul le stockage historisé est mis en place ici ; noté
  en TODO dans `specifications.md` §10.4.
- **Fichiers** : `sql/init.sql`, `backend/app.py` (`write_object`,
  `_build_object_payload`, `list_objects`, et toute autre requête de
  lecture des attributs).
- **Statut** : ✅ fait (2026-11-12).
  Historique 2026-11-10 — implémentation worker initiale :
  schéma migré (`valid_from`/`valid_to` sur `attribute_value`,
  `deleted_at` sur `object`, index `idx_attribute_value_joint_id`),
  migration manuelle appliquée sur le volume `pgdata` existant via
  `docker compose exec db psql -U miami -d miami_vice -c "ALTER TABLE ..."`
  (voir rapport worker pour le détail des 4 commandes), `write_object`
  réécrit en logique de diff (réutilise la même ligne `attribute`
  existante, ferme/insère uniquement les `attribute_value` effectivement
  changées), lectures (`_build_object_payload` x2 branches, `list_objects`)
  filtrées `valid_to IS NULL`/`deleted_at IS NULL`. Vérifié réellement
  (stack Docker, `/api/init`, écritures/lectures via `psql`) : historisation
  scalaire, diff ciblé sur un attribut multi-valué (`groupe.membres`,
  1 seul membre historisé sur 5), fermeture complète d'un attribut omis,
  lecture n'exposant jamais l'historique, filtre `deleted_at` effectif
  (objet masqué + chemin orphelin `{"joint_id":...}` sans `resolved`).
  Suites pytest (28 tests, `test_rbac_class_tenant_scope.py` +
  `test_model_driven_typing.py`) toutes vertes après ajout d'un seul
  pattern SQL au `FakeCursor` (`UPDATE attribute_value SET valid_to`).
  Cycle d'arbitrage final (2026-11-12, non commité dans le même cycle que
  l'implémentation initiale) : `write_attribute_value` historisée à son
  tour via `_apply_attribute_diff` factorisée (partagée avec
  `write_object`), verrou `FOR NO KEY UPDATE` posé sur la ligne `object`
  (préféré à `FOR UPDATE` pour rester compatible avec le `KEY SHARE` pris
  par toute FK `joint_id`, évite un deadlock), contrainte
  `UNIQUE(object_id, name)` ajoutée sur `attribute` dans `sql/init.sql`,
  `domain` (`attribute.domain`) réaligné sur le modèle à l'écriture s'il a
  évolué, `joint_id` casté en `int()`, harnais FakeDB/FakeCursor corrigé en
  conséquence. Revue croisée (testeur + pessimiste + candide) sur cette
  correction : 2 points bloquants remontés par pessimiste et corrigés en
  2e itération — (1) contrainte `UNIQUE(object_id,name)` : vérifiée sans
  effet sur le volume Postgres existant (`miami-vice_pgdata`, créé avant
  cette correction, `init.sql` ne s'applique qu'à un volume neuf) ;
  vérification directe sur le volume réel : 0 doublon existant, contrainte
  appliquée dessus (confirmé `\d attribute`) ; (2) `_coerce_typed_value`
  (cast `joint_id`) durci : rejette désormais explicitement un bool et un
  float non entier (évitait une jointure silencieusement corrompue, ex.
  `5.7` tronqué en `5`), accepte toujours int/string entière/float entier.
  Dette actée non bloquante (décision orchestrateur, pas de correction
  dans ce cycle) : réalignement du `domain` effectué seulement au
  prochain write de l'attribut (un objet jamais réécrit garde un `domain`
  périmé si le modèle change — limite inhérente à une historisation
  diff-based, acceptée) ; absence de tests d'intégration contre un vrai
  Postgres pour le verrou `FOR NO KEY UPDATE`/la contrainte UNIQUE (suite
  pytest 100% FakeDB, vérifications réelles faites manuellement par
  testeur/testeur-global via `psql` mais pas automatisées). Validation
  finale : suite pytest complète verte (37 passed, 5 échecs pré-existants
  hors scope liés à `/model/schema.json`, confirmés identiques à master,
  non liés à ce diff), testeur-global OK (stack docker compose complète
  démarrée, `/api/init` + routes read + écriture d'attribut existant +
  création d'objet neuf testés sur la vraie DB, historisation confirmée
  bout en bout, DB nettoyée après test). 2 itérations de correction au
  total sur ce cycle d'arbitrage.

### 6.1 Suppression logique d'un objet

> **Conception finalisée (2026-11-10)** : les points ci-dessous, laissés
> ouverts à la rédaction initiale puis objets d'une proposition de
> l'utilisateur ("gérer à la suppression la cascade sur les jointures et
> passer la jointure à supprimée en ajoutant la date de fin"), ont été
> tranchés après une revue croisée (optimiste/pessimiste/candide) ayant
> révélé une vraie brèche RBAC dans la proposition brute, puis un
> arbitrage de synthèse. Décision finale ci-dessous — ne plus rediscuter
> sans élément nouveau.

- **Correctif** : `DELETE /api/delete/object/<int:object_id>` : dans une
  seule transaction, `SELECT id, deleted_at FROM object WHERE id = %s FOR
  UPDATE` (verrou explicite, voir garde-fous d'écriture ci-dessous — 404
  si absent, 404 si `deleted_at IS NOT NULL` déjà supprimé, 403 RBAC si
  `tenant-admin` hors de son périmètre), puis
  `UPDATE object SET deleted_at = now() WHERE id = %s`, puis
  `UPDATE attribute_value SET valid_to = now() WHERE valid_to IS NULL AND attribute_id IN (SELECT id FROM attribute WHERE object_id = %s)`
  (ferme toutes les valeurs actives de l'objet lui-même), `conn.commit()`,
  réponse `200 {"status":"ok","id":object_id,"deleted_at":"..."}`.
- **Cascade sur les jointures entrantes — scopée au périmètre tenant de
  l'acteur** : une cascade immédiate et non scopée (fermer *toutes* les
  jointures entrantes dès la suppression logique, quel que soit le tenant
  de l'objet source) ouvrirait une brèche confirmée en lisant le code :
  aucune contrainte ne lie le tenant d'un objet source à celui de la
  cible d'un `joint_id`, et le RBAC de `write_object`/de cette route ne
  vérifie que le périmètre de l'objet qu'on écrit/supprime directement —
  un `tenant-admin` du tenant A supprimant X déclencherait sinon un effet
  d'écriture sur un objet Y d'un tenant B, sans aucun contrôle RBAC sur Y.
  Décision : fermer uniquement les jointures entrantes dont l'objet
  source Y est dans le **même périmètre tenant que l'acteur** (ou toutes,
  si l'acteur est `global-admin`). Les jointures cross-tenant résiduelles
  restent actives mais inoffensives (le filtre `deleted_at IS NULL` de
  6.0 les masque déjà en lecture, cf. ci-dessus) et seront nettoyées
  définitivement à la purge (6.2, `global-admin`, autorité universelle).
  Pas de clé `deleted: true` explicite — le traitement orphelin existant
  suffit (voir le correctif lecture de 6.0 ci-dessus). SQL (à filtrer
  **directement** sur `av.joint_id`, jamais via un sous-select sur
  `attribute_id`, qui fermerait à tort les valeurs sœurs d'un attribut
  multi-valué `joint-1-n`) :
  ```sql
  -- global-admin (pas de restriction tenant) :
  UPDATE attribute_value SET valid_to = now()
  WHERE joint_id = %s AND valid_to IS NULL;

  -- tenant-admin (restreint aux objets sources de son périmètre) :
  UPDATE attribute_value av
  SET valid_to = now()
  FROM attribute a, object o
  WHERE av.attribute_id = a.id AND a.object_id = o.id
    AND av.joint_id = %s AND av.valid_to IS NULL
    AND (o.tenants IS NULL OR o.tenants = '' OR string_to_array(o.tenants, ',') && %s::text[]);
  ```
- **Garde-fous d'écriture contre une cible/un objet déjà supprimé
  (nouveau, issu de l'arbitrage)** — sans ça, un gap confirmé permettrait
  de créer indéfiniment de nouvelles jointures vers un objet déjà
  supprimé, ou d'éditer un objet déjà soft-deleted (état « zombie »
  invisible de l'UI mais présent en base) :
  - `_insert_value` (`backend/app.py` lignes 736-757) : avant d'insérer
    un `{"joint_id": N}`, `SELECT deleted_at FROM object WHERE id = %s
    FOR SHARE` ; `400` si absent ou déjà supprimé. Ce verrou partagé et
    le `FOR UPDATE` de la suppression (ci-dessus) portent sur la même
    ligne `object` : ils s'excluent mutuellement le temps de la
    transaction, fermant la fenêtre de course sans risque de deadlock
    (une seule ressource verrouillée par transaction). Ne pas appliquer
    ce garde dans `write_attribute_value` : les jointures ne transitent
    jamais par cette route (déjà acté actions 4/5 de ce plan).
  - `write_object` (branche UPDATE, ligne ~672) : charger aussi
    `deleted_at` dans le `SELECT` existant, `404` si non NULL — même
    sémantique que « n'existe pas ».
  - `write_attribute_value` (ligne ~774) : même garde, `404` si
    `deleted_at IS NOT NULL`, avant toute vérification RBAC.
- **Câblage frontend minimal** : `apiDeleteObject` dans `api.ts`, bouton
  de suppression dans `NavigationPage.tsx` pour un objet — le strict
  minimum pour que la fonctionnalité soit utilisable.
- **Point nouveau (hérité de Mark 1 action 11)** : la suppression d'un
  objet doit respecter le RBAC déjà en place — `tenant-readonly` → 403 ;
  `tenant-admin` → autorisé uniquement sur les objets dans son périmètre
  tenant (même logique que l'écriture, §11.2 de `plan-mark1.md`).
- **Fichiers** : `backend/app.py`, `frontend/src/api.ts`,
  `frontend/src/pages/NavigationPage.tsx`.
- **Dépendance** : nécessite 6.0 (colonnes `deleted_at`/`valid_to`, index
  `idx_attribute_value_joint_id`).
- **Statut** : ✅ fait (2026-11-12).
  Implémentation : `DELETE /api/delete/object/<int:object_id>` posant le
  verrou `FOR UPDATE` sur l'objet cible, `404` si absent ou déjà
  supprimé, RBAC conforme (`tenant-readonly` 403, `tenant-admin` scopé à
  son périmètre, `global-admin` libre), fermeture des valeurs actives de
  l'objet lui-même puis cascade sur les jointures entrantes scopée au
  tenant de l'acteur via un filtre direct sur `av.joint_id` (pas de
  sous-select sur `attribute_id`, pour ne pas fermer à tort les valeurs
  sœurs d'un attribut multi-valué). Garde-fous zombie posés : `_apply_attribute_diff`
  refuse désormais la création d'une nouvelle jointure vers un objet
  supprimé (`FOR SHARE` + `400`), `write_object`/`write_attribute_value`
  renvoient `404` sur un objet cible déjà soft-deleted. Câblage frontend
  minimal : `apiDeleteObject` (`api.ts`), bouton « suppr. » dans
  `NavigationPage.tsx`. Revue croisée (testeur + pessimiste + candide), 2
  points bloquants remontés par pessimiste et corrigés en 2e itération :
  (1) le commentaire initial annonçant « une seule ressource verrouillée,
  pas de deadlock possible » était faux — un deadlock réel (pas
  théorique) existe entre `delete_object` (`FOR UPDATE` sur l'objet
  cible) et `write_object`/`write_attribute_value` (ferme une valeur
  jointe puis `FOR SHARE` sur un objet cible), cycle à 2 ressources
  possible sous interleaving concurrent précis ; mitigé par un catch
  ciblé `psycopg2.errors.DeadlockDetected` → `409` (rollback propre) dans
  les 3 routes concernées, sans refonte du schéma de verrouillage (jugée
  disproportionnée pour ce scope) ; (2) les tests de validation,
  initialement écrits hors dépôt (scratchpad, vraie DB), ont été
  rapatriés dans `backend/test_model_driven_typing.py` sur le harnais
  `FakeDB` existant — 15 tests réels (12 sur `delete_object`/RBAC/cascade/
  garde-fou zombie + 3 sur le catch deadlock), le chiffre initialement
  annoncé par worker (23) étant erroné, corrigé après vérification par
  testeur. Dette actée non bloquante : gap du harnais de test
  (`FakeCursor` ne simule pas le filtre `deleted_at IS NULL` sur
  `GET /api/read/object`, le vrai code le fait bien — gap de mock, pas de
  code) ; les tests deadlock déclenchent `DeadlockDetected` sur un point
  générique plutôt que le chemin exact narré (capture quand même le
  comportement) ; `FakeConn.rollback()` ne simule pas un vrai rollback
  atomique (limite du harnais, Postgres réel le fait correctement).
  Validation finale : suite pytest complète verte (52 passed, 5 échecs
  pré-existants hors scope liés à `/model/schema.json`, confirmés
  identiques à master), testeur-global OK (stack docker compose
  complète, cycle réel sur vraie DB : création objet+jointure, DELETE
  soft, objet masqué en lecture, jointure fermée, garde-fous zombie x2
  vérifiés en conditions réelles, RBAC vérifié, DB nettoyée après test ;
  `npm run build` échoue sur 3 erreurs TypeScript préexistantes dans
  `DiagramPage.tsx` non liées à 6.1, déjà documentées dans
  plan-mark1.md/plan-mark2.md ; `vite build` seul et les fichiers touchés
  par 6.1 compilent proprement). Point remonté par testeur-global pour
  6.2 (pas un défaut de 6.1) : confirme que la purge physique de 6.2 doit
  bien fermer/retirer toutes les `attribute_value.joint_id` référençant
  l'objet avant le `DELETE FROM object`, exactement comme déjà prévu dans
  la conception actée de 6.2 — rien à changer à cette conception. 2
  itérations de correction au total sur ce cycle d'arbitrage.

### 6.2 Purge physique différée

> **Révision de conception (2026-11-10, même jour que la confirmation
> initiale)** : décision utilisateur — « la grâce sera configurable par
> l'administrateur ». Remplace la constante Python figée
> `PURGE_GRACE_PERIOD_DAYS` envisagée plus haut par un paramètre modifiable
> à chaud (sans redéploiement), 30 jours restant la valeur par défaut.

- **Principe** : après une période de grâce suivant `deleted_at`, un
  mécanisme de purge supprime **physiquement** les lignes
  `attribute_value`/`attribute` de l'objet.
- **Conception finalisée (2026-11-10, arbitrage 6.1/6.2)** : **suppression
  totale** de la ligne `object` elle-même (pas de coquille vide), à
  condition impérative que la purge supprime d'abord, explicitement et
  **inconditionnellement**, TOUTE ligne `attribute_value` référençant cet
  objet en `joint_id` — active (`valid_to IS NULL`) **ou déjà fermée**
  (`valid_to IS NOT NULL`, par une édition normale avant la suppression,
  ou par la cascade de 6.1). Cette garde est nécessaire : si la purge ne
  nettoyait que les jointures entrantes encore actives et oubliait des
  lignes déjà historiquement closes qui référencent encore l'objet,
  supprimer sa ligne `object` déclencherait quand même le FK
  `ON DELETE SET NULL` sur ces lignes résiduelles → les 4 colonnes de
  `attribute_value` deviendraient NULL → violation de la contrainte CHECK
  → `POST /api/purge` échouerait de façon répétée et bloquante pour cet
  objet (le même piège déjà rencontré et corrigé en Mark 1 action 6).
  En purgeant TOUTES les jointures entrantes sans condition avant de
  supprimer la ligne `object`, plus aucune ligne ne la référence au
  moment du `DELETE FROM object` : le FK `ON DELETE SET NULL` n'a plus
  rien à faire, le risque CHECK est éliminé structurellement — pas besoin
  de prouver un nettoyage exhaustif au cas par cas. SQL (ordre strict,
  même transaction, `now()` stable via `transaction_timestamp()`) :
  ```sql
  WITH candidates AS (
      SELECT id FROM object
      WHERE deleted_at IS NOT NULL
        AND deleted_at < now() - make_interval(days => %(grace_days)s::integer)
  )
  -- 1. D'ABORD : purge inconditionnelle des jointures entrantes (actives ou closes)
  DELETE FROM attribute_value WHERE joint_id IN (SELECT id FROM candidates);

  -- 2. ENSUITE : suppression des objets eux-mêmes (cascade déjà en place vers
  --    attribute puis attribute_value pour les propres attributs de l'objet,
  --    plus aucun risque CHECK puisque l'étape 1 a déjà tout nettoyé)
  DELETE FROM object WHERE id IN (SELECT id FROM candidates);
  ```
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
- **Statut** : ✅ fait (2026-11-12).
  Implémentation : table `app_config` (clé/valeur générique) + seed
  `purge_grace_period_days=30` dans `sql/init.sql` ; `GET`/
  `PUT /api/config/purge_grace_period_days` et `POST /api/purge`, tous
  réservés strictement `global-admin` (premier cas du projet où une
  route rejette aussi `tenant-admin`, pas seulement `tenant-readonly`) ;
  validation stricte de `PUT` (bool/float non entier/zéro/négatif
  rejetés `400`, même piège que le cast `joint_id` de 6.0) ;
  `POST /api/purge` relit la période de grâce en base à chaque appel
  (jamais une constante figée), purge d'abord TOUTES les
  `attribute_value.joint_id` référençant les objets candidats (actives
  et déjà fermées) PUIS les objets eux-mêmes, en 2 requêtes
  séquentielles dans la même transaction (le bloc SQL unique du plan
  n'était pas exécutable tel quel, un `WITH` ne peut précéder qu'une
  seule instruction — chaque requête recalcule indépendamment la même
  CTE `candidates`) ; catch `psycopg2.errors.DeadlockDetected` → `409`
  comme 6.0/6.1 ; câblage frontend minimal (`apiGetPurgeGracePeriod`/
  `apiSetPurgeGracePeriod`, champ dans `ConfigurationPage.tsx` visible
  uniquement `global-admin`).
  Revue croisée (testeur + pessimiste + candide), 1 point bloquant
  corrigé en 2e itération : la table `app_config` ajoutée à
  `sql/init.sql` ne s'applique qu'à un volume Postgres neuf (même piège
  que la contrainte UNIQUE de 6.0 et que `sql/00-keycloak-db.sql`, déjà
  documenté dans README.md) — sur le volume réel du projet
  (`miami-vice_pgdata`, déjà initialisé), la table n'existe jamais
  automatiquement. Corrigé : migration manuelle appliquée sur le volume
  réel (`CREATE TABLE IF NOT EXISTS` + seed `ON CONFLICT DO NOTHING`),
  documentée dans `README.md` (nouveau paragraphe après la note
  existante sur keycloak, même format/structure).
  Dette actée non bloquante (décision orchestrateur) : `int(row[0])`
  non protégé si la valeur de `app_config` est corrompue manuellement en
  base directe (nécessite un accès SQL hors API, cohérent avec
  l'absence généralisée de handler DB-error déjà acceptée en 6.0/6.1) ;
  le frontend avale silencieusement les erreurs de chargement initial
  du champ purge (`catch(() => {})`) ; pas d'index sur
  `object(deleted_at)` (perf, impact nul tant que la table reste
  petite) ; le champ `purged` de la réponse ne compte que les objets
  supprimés, pas les `attribute_value` nettoyées (moins d'info
  diagnostique, pas un défaut fonctionnel).
  Validation finale : suite pytest complète verte (76 passed, 5 échecs
  pré-existants hors scope liés à `/model/schema.json`, confirmés
  identiques à master), testeur-global OK (stack docker compose
  complète, RBAC vérifié avec vrais tokens Keycloak sur les 3 routes,
  scénario bout en bout sur vraie DB : purge avant échéance →
  `purged:0`, purge après échéance (`deleted_at` antidaté) → objet
  physiquement supprimé, `attribute_value` propres et jointure entrante
  déjà fermée purgées sans violation CHECK, objet source de la
  jointure resté intact ; `npm run build` échoue sur 3 erreurs
  TypeScript préexistantes dans `DiagramPage.tsx` non liées à cette
  action, déjà documentées ; fichiers touchés par 6.2 compilent
  proprement).
  1 itération de correction au total sur ce cycle d'arbitrage.

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
- **Statut** : ✅ fait (2026-11-12).
  Implémentation : `DELETE /api/delete/class/<meta_class>/<cls>` —
  charge `definition`, retire la classe de `data["classes"]` (404 si
  meta-classe ou classe absente), RBAC héritée de `write_class`
  (`tenant-readonly` 403, `tenant-admin` restreint à son périmètre via
  `_check_existing_class_tenant_scope` réutilisé tel quel), `UPDATE
  definition SET data = ...` (`json.dumps`), ne touche jamais aux objets
  déjà créés (aucune FK `object`/`definition`, §3.4).
  Revue croisée (testeur + pessimiste + candide), 1 point mineur corrigé
  (partagé avec 6.4, voir ci-dessous : `FOR UPDATE` ajouté par
  cohérence).
  Dette actée non bloquante : en cas de doublon de nom de classe dans
  `data["classes"]` (anomalie de données déjà possible via
  `write_class`/`write_metaclass`, non validée par `uniqueItems` dans
  `model/schema.json`), seule la première occurrence est retirée —
  comportement hérité identique à `write_class`, pas une régression
  introduite par 6.3, non corrigé ce cycle (un fix de fond type
  `uniqueItems` serait un changement de schéma plus large, hors scope).

### 6.4 Suppression d'une meta-classe (schéma — suppression physique)

- **Correctif** : `DELETE /api/delete/metaclass/<string:meta_class>` :
  `DELETE FROM definition WHERE meta_class = %s` (404 si 0 ligne
  affectée), réponse `200`. Documenter explicitement que ceci ne
  supprime pas les objets déjà créés sous cette meta-classe (cohérent
  avec le constat §3.4 : aucune FK entre `object` et `definition`).
- **Fichiers** : `backend/app.py`.
- **Statut** : ✅ fait (2026-11-12).
  Implémentation : `DELETE /api/delete/metaclass/<meta_class>` — `DELETE
  FROM definition WHERE meta_class = %s` (404 si absente), réponse 200.
  Revue croisée, 1 point bloquant corrigé en 1re itération : le premier
  jet n'avait que la garde `tenant-readonly` → 403, sans restriction
  tenant-admin — incohérence RBAC face à `write_metaclass`/6.3
  (suppression d'une meta-classe entière au moins aussi sensible qu'un
  remplacement complet). Corrigé : boucle
  `_check_existing_class_tenant_scope` sur chaque classe existante de la
  meta-classe avant suppression (même pattern que `write_metaclass`),
  403 si une seule classe est hors périmètre tenant-admin (aucune
  suppression partielle).
  1 point mineur corrigé en 2e itération (6.3 ET 6.4) : `SELECT ... FOR
  UPDATE` ajouté sur la ligne `definition` dans les deux routes
  (cohérence avec `delete_object`) — fermait une fenêtre de course
  étroite où un `write_metaclass` concurrent aurait pu ajouter une
  classe hors périmètre tenant entre la vérification RBAC et la
  suppression, sans être vérifiée (risque confirmé faible : un
  tenant-admin ne peut pas fabriquer seul la classe hors-périmètre
  nécessaire, `_check_class_tenant_write_permission` force l'auto-tag
  sur son propre tenant — nécessite un 2e acteur indépendant agissant
  dans une fenêtre très étroite).
  Validation finale (commune 6.3+6.4) : suite pytest complète verte (96
  passed, 5 échecs pré-existants hors scope liés à `/model/schema.json`),
  testeur-global OK (stack docker compose complète, RBAC vérifié avec
  vrais tokens Keycloak, cycle e2e réel : suppression classe isolée avec
  sœur et objet intacts, suppression meta-classe totale avec objet
  restant lisible après coup faute de FK, routes voisines non
  régressées).
  2 itérations de correction au total sur ce cycle d'arbitrage (commun
  6.3+6.4).

- **Effort global de l'action 6** : conséquent (6.0 = réécriture d'un
  endpoint central + migration de schéma ; 6.1/6.2 = nouvelles routes ;
  6.3/6.4 = routes simples déjà conçues).
- **Statut global** : ✅ fait (6.0/6.1/6.2/6.3/6.4 toutes closes).

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
- **Statut** : ✅ fait (2026-11-10). testeur 5/5 PASS (validité du schéma,
  validation réelle de personnes.json/reseau.json, non-régression
  additionalProperties:false, $schema confirmé non-required). Analyse
  croisée combinée (optimiste/pessimiste/candide) : accepté tel quel,
  re-dérivation indépendante convergente. Remarques non bloquantes :
  collision de nom $schema méta-schéma/instance (note de clarté). Non
  commité.

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
  7. **Correctif doublon visuel (verdict arbitre 🔧 à corriger, 2026-11-11)** :
     avant d'ajouter un lien reconstitué (pointillé) pour une paire
     `(obj.id, targetId)`, vérifier qu'aucun lien **direct** n'existe déjà
     pour cette même paire — sans ce garde-fou, un groupe et un sous-groupe
     partageant un membre direct (`model/personnes.json`, classe `groupe`
     masquée) peuvent produire un trait plein (direct) **et** un pointillé
     (reconstitué) superposés entre les deux mêmes nœuds. Implémenté via un
     `Set` `addedDirectLinks` (clé `${source}=>${target}`), alimenté au fil
     de l'ajout des arêtes directes et consulté, en plus de
     `addedReconstructedLinks`, avant tout ajout d'arête reconstituée.
  8. **Correctif complémentaire — construction en 2 passes (réserve testeur
     de confirmation finale, 2026-11-11)** : le garde-fou du point 7
     (`addedDirectLinks`) ne protégeait correctement contre le doublon
     visuel que si, dans la boucle unique mêlant arêtes directes et
     masquées, l'arête directe vers une cible était itérée **avant**
     l'arête masquée résolvant vers la même cible — ordre qui dépendait de
     `ORDER BY a.id, av.id` côté backend (`sql/init.sql`/`backend/app.py`).
     Non exploitable avec le schéma à 3 classes actuel du projet, mais
     risque latent en cas d'évolution du modèle (classe à 2 attributs
     joints distincts vers des cibles masquables indépendamment). Ce risque
     a été **éliminé structurellement** en remplaçant la boucle unique par
     une construction en 2 passes : passe 1, itération de toutes les
     arêtes de tous les objets visibles, ajout de toutes les arêtes
     directes dans `links` et remplissage complet de `addedDirectLinks`
     (les arêtes vers une cible masquée sont seulement collectées dans
     `hiddenEdgesToProcess`, pas encore traitées) ; passe 2, traitement des
     seules arêtes collectées en passe 1, avec consultation d'un
     `addedDirectLinks` désormais complet pour tous les objets visibles
     avant tout ajout de lien reconstitué. Le dédoublonnage ne dépend plus
     de l'ordre d'itération des arêtes, quelle que soit la requête SQL
     source.
- **Effort** : moyen (logique de fermeture transitive + anti-cycle +
  garde-fou de volume à tester sur un graphe réaliste avec plusieurs
  niveaux de jointures masquées).
- **Fichiers** : `frontend/src/pages/DiagramPage.tsx`.
- **Dette actée (non bloquante, documentée par l'arbitre, pas à corriger ce
  cycle)** :
  1. **Organigramme — perte silencieuse de branches en cas de fan-in** : le
     layout « Organigramme » (`buildTree`, `visited` global) a une
     limitation **préexistante** (pas introduite par cette action) : en cas
     de fan-in (plusieurs sources vers un même nœud cible), une branche peut
     se retrouver vide sans erreur ni signal (le `visited` global fait que
     le premier parent à atteindre un nœud se l'approprie, les suivants le
     filtrent silencieusement via `.filter(Boolean)`). Ce diff (liens
     transitifs) **exacerbe** cette limitation (plus de liens reconstitués
     = plus de fan-in possible) mais ne l'introduit pas. Une vraie
     correction nécessiterait de passer d'une structure d'arbre à un DAG
     pour ce layout — hors périmètre de l'action 10, qui ne demandait
     qu'une vérification de cohérence (faite, limitation documentée ici).
  2. **Plafond `MAX_RECONSTRUCTED_EDGES_PER_HIDDEN_NODE` par nœud masqué,
     pas global** : masquer plusieurs classes simultanément pourrait
     cumuler un nombre d'arêtes reconstituées non plafonné globalement
     (N nœuds masqués × 20). Sans impact sur le dataset actuel du projet ;
     à surveiller si le modèle grossit significativement.
  Par ailleurs, l'absence de style pointillé sur les arêtes reconstituées
  dans le layout Organigramme (série ECharts `tree`) a été évaluée et jugée
  **non pertinente à corriger** : le point 3 ci-dessus (« distinction
  visuelle obligatoire ») ciblait explicitement la série `graph`
  (Force/Circulaire), pas `tree`.
- **Statut** : ✅ fait (2026-11-10) — implémentation worker terminée puis
  validée. Résumé : la fonction `graphData` construit d'abord une map
  d'adjacence complète (`adjacency`, depuis `objects`/`details` non
  filtrés), puis pour chaque arête dont la cible est masquée,
  `resolveVisibleTargets` suit récursivement les arêtes sortantes du nœud
  masqué (anti-cycle via `visitedOnPath`, même principe que `in_progress`
  dans `backend/app.py`) jusqu'à un nœud visible. Arêtes directes en trait
  plein avec label d'attribut ; arêtes reconstituées en trait pointillé
  (`lineStyle.type: 'dashed'`) sans label. Garde-fous :
  `MAX_HIDDEN_CHAIN_DEPTH = 2` (profondeur de nœuds masqués consécutifs) et
  `MAX_RECONSTRUCTED_EDGES_PER_HIDDEN_NODE = 20` (plafond d'arêtes
  reconstituées par nœud masqué, toutes sources confondues) — validé par un
  test synthétique (fan-in 10 × fan-out 10 → 20 arêtes au lieu de 100) et
  par un test de cycle réel (chaîne récursive type `groupe.membres` →
  `groupe` avec boucle A↔B, 1ms, pas de dépassement de pile). Correctif
  doublon visuel (point 7 ci-dessus, verdict arbitre 🔧) appliqué :
  `addedDirectLinks` empêche la superposition d'un lien reconstitué par-
  dessus un lien direct déjà présent pour la même paire — vérifié par
  script Node synthétique exerçant directement la logique extraite de
  `graphData` (adjacence + `resolveVisibleTargets` + construction des
  liens), sur un cas générique propriétaire→cible directe+indirecte et sur
  un cas à la frontière exacte du schéma `model/personnes.json`
  (groupe/sous-groupe/membre partagé, classe `groupe` masquée : analyse et
  script ont montré que ce schéma précis, strictement limité à ses 3
  classes, n'offre aucun point d'entrée visible vers le sous-graphe
  `groupe` une fois cette classe entièrement masquée — aucun lien n'est
  alors produit, ni doublon ni reconstruction ; le motif doublon se
  manifeste dès qu'un objet visible porte à la fois un lien direct et un
  lien vers un nœud masqué résolvant vers la même cible, démontré avec un
  rôle visible portant ces deux arêtes) ; non-régression des garde-fous
  anti-cycle/profondeur/volume reconfirmée par le même script (scénarios 4
  et 5 : plafond 20 toujours respecté, cycle réel toujours résolu sans
  dépassement de pile). `tsc -b --force` dans le conteneur frontend : 3
  erreurs préexistantes identiques avant/après (mêmes causes, lignes
  décalées par l'ajout de code), aucune nouvelle. Les 2 points de dette et
  la non-pertinence du style pointillé sur l'Organigramme sont documentés
  ci-dessus, actés par l'arbitre, non corrigés ce cycle.
  **Correctif complémentaire (2026-11-11, point 8 ci-dessus)** : la
  dépendance à l'ordre d'itération des arêtes identifiée par le testeur de
  confirmation finale est éliminée par passage à une construction en 2
  passes (direct d'abord sur tous les objets visibles, reconstitué
  ensuite). Vérifié par un script Node synthétique reproduisant exactement
  le cas qui faisait échouer la réserve (arête masquée placée **avant**
  l'arête directe vers la même cible dans le tableau source d'adjacence) :
  un seul lien 1→3 produit (direct, trait plein), aucun doublon. Non-
  régression reconfirmée sur anti-cycle (chaîne récursive A↔B, aucun lien
  réflexif produit), plafond `MAX_RECONSTRUCTED_EDGES_PER_HIDDEN_NODE`
  (25 entrées vers un même nœud masqué → exactement 20 arêtes reconstituées
  conservées) et dédoublonnage entre deux arêtes reconstituées convergeant
  vers la même paire source/cible (un seul lien produit). `tsc -b --force`
  dans le conteneur frontend : toujours et uniquement les 3 mêmes erreurs
  préexistantes, aucune nouvelle.

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
| 8 | 1 | `$schema` non déclaré dans `model/schema.json` | ✅ |
| 5 | 1 | Validation de schéma/`constraint`, cohérence meta_class/class, **typage de stockage piloté par le modèle** | ✅ |
| 6.0 | 2 | Historisation du modèle (`valid_from`/`valid_to`/`deleted_at` + réécriture `write_object`/`write_attribute_value` via `_apply_attribute_diff`, verrou `FOR NO KEY UPDATE`, `UNIQUE(object_id,name)`) | ✅ |
| 6.1 | 2 | Suppression logique d'un objet (`DELETE /api/delete/object`, cascade jointures scopée tenant, garde-fous zombie, catch deadlock) | ✅ |
| 6.2 | 2 | Purge physique différée (`app_config`, `POST /api/purge` réservé `global-admin`, période de grâce **configurable**, défaut 30 jours ; migration manuelle appliquée sur le volume réel) | ✅ |
| 6.3 | 2 | Suppression d'une classe (physique, `DELETE /api/delete/class/<meta_class>/<cls>`, RBAC héritée `write_class`) | ✅ |
| 6.4 | 2 | Suppression d'une meta-classe (physique, `DELETE /api/delete/metaclass/<meta_class>`, RBAC alignée `write_metaclass`) | ✅ |
| 9 | 3 | Partitionnement PostgreSQL par type d'objet (évaluation puis implémentation conditionnelle) | ⬜ |
| 10 | 3 | Liens transitifs du graphe au filtrage de classe | ✅ |
| 7a | hors vague | Propagation du prop `readOnly` à `DiagramPage.tsx` (résiduel, faible priorité) | ⬜ |

**Décision actée (2026-11-10, révisée le même jour)** : la période de
grâce de purge (action 6.2) est **configurable par l'administrateur**
(`global-admin`, table `app_config`, pas une constante Python), avec
**30 jours** comme valeur par défaut au seed initial.

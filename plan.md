# Plan d'action — correction des anomalies de miami-vice

> Ce plan découle directement de `specifications.md`, en particulier de sa
> section §9 « Récapitulatif des anomalies constatées (par gravité) ». Les
> huit actions ci-dessous reprennent cet ordre de gravité décroissante. Les
> références de fichiers/lignes ont été vérifiées sur le code actuel du
> dépôt (certaines diffèrent légèrement des numéros de ligne cités en
> prose dans `specifications.md` du fait de commentaires environnants ; le
> contenu désigné est le même).

> **Suivi d'avancement** : ce document est vivant — chaque action porte un
> champ **Statut** (⬜ à faire / 🔄 en cours / ✅ fait) à mettre à jour au fur
> et à mesure que l'équipe (ou les agents `worker`/`testeur`/`arbitre`)
> réalise et valide les correctifs, en précisant la date et, le cas échéant,
> la référence du commit/PR correspondant. Ne pas attendre la fin complète
> du plan pour le faire : un statut à jour après chaque action permet de
> savoir à tout moment où en est l'avancement réel sans relire tout
> l'historique git.

## 1. [Bloquant] `backend/app.py` ne compile pas

- **Problème** : `IndentationError` dans `get_classes_by_meta_class`
  (`backend/app.py`, route `GET /api/read/<meta_class>`). La ligne
  `row = cur.fetchone()` (ligne 97) est indentée à 12 espaces, un niveau de
  plus que le bloc `with ... as cur:` auquel elle appartient (8 espaces).
  Le module entier devient non importable : aucune route ne démarre.
- **Correctif** : dans `backend/app.py`, lignes 92-97, remettre
  `row = cur.fetchone()` à la même indentation que `cur.execute(` juste
  au-dessus (8 espaces), pour qu'elle fasse partie du corps du `with` :
  ```python
  with get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
      cur.execute(
              "SELECT id, meta_class, data FROM definition WHERE meta_class = %s",
              (meta_class,)
          )
      row = cur.fetchone()
  ```
  (la ré-indentation des arguments de `cur.execute(` aux lignes 94-96 est
  cosmétique et peut être laissée telle quelle, l'erreur ne vient que de
  la ligne 97).
- **Effort** : trivial (une ligne).
- **Fichiers** : `backend/app.py`.
- **Statut** : ✅ fait (2026-11-09). Corrigé par `worker`, validé par `testeur`
  (exécution réelle : `docker compose up`, endpoints `/api/read/meta_class`,
  `/api/read/personne`, `/api/read/element_avec_ip`, `/api/read/inexistante`
  tous répondent correctement 200/404), analyse croisée sans réserve
  bloquante, arbitre ✅ OK, `testeur-global` ✅ OK (aucune régression sur les
  endpoints voisins ; le 500 observé sur `/api/read/object/1` est le bug
  préexistant de l'action 2, pas une régression de ce correctif). Non
  commité à ce stade.

## 2. [Bloquant fonctionnel] `GET /api/read/object/<id>` ne renvoie jamais les attributs

- **Problème** : dans `get_object_by_id` (`backend/app.py`, lignes
  121-165), tout le code qui construit et retourne la réponse (le second
  bloc `with conn.cursor(...) as cur:` et le `return jsonify(obj)` final,
  lignes 132-165) est indenté **à l'intérieur** du `if not obj:` (lignes
  129-130), donc après le `abort(404, ...)`. Pour un objet existant,
  `if not obj` est faux, tout ce bloc est sauté, et la fonction se termine
  sans `return` → Flask lève une `TypeError` → `500` systématique.
- **Correctif** : dans `backend/app.py`, dédenter les lignes 132-165
  (du second `with conn.cursor(...)` jusqu'à `return jsonify(obj)` inclus)
  d'un niveau, pour qu'elles soient au même niveau d'indentation que le
  `if not obj:` (4 espaces, niveau du corps de la fonction), et donc
  exécutées **après** le bloc `if`, pas dedans :
  ```python
  with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
      cur.execute("SELECT id, meta_class, class FROM object WHERE id = %s", (object_id,))
      obj = cur.fetchone()

  if not obj:
      abort(404, description="Objet non trouvé")

  with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
      cur.execute("""
          SELECT a.id AS attribute_id, a.domain, a.name,
                 av.id AS value_id, av.value_integer, av.value_float, av.value_string, av.joint_id
          FROM attribute a
          LEFT JOIN attribute_value av ON av.attribute_id = a.id
          WHERE a.object_id = %s
          ORDER BY a.id, av.id
      """, (object_id,))
      attr_rows = cur.fetchall()

  attributes = {}
  for row in attr_rows:
      ...

  obj["attributes"] = list(attributes.values())
  return jsonify(obj)
  ```
- **Effort** : trivial (ré-indentation, pas de logique à changer).
- **Fichiers** : `backend/app.py`.
- **Statut** : ✅ fait (2026-11-09). Validé en 1 itération, aucune
  correction nécessaire. `testeur` : objet existant → `200` avec
  attributs corrects, objet inexistant → `404` (non-régression).
  Analyse croisée convergente (candide a reconstruit indépendamment la
  même solution). Arbitre ✅ OK. `testeur-global` ✅ PASS (tous les
  endpoints voisins fonctionnent toujours, `docker compose config`
  cohérent). Réserve mineure notée par pessimiste, non bloquante : le cas
  `joint_id` orphelin (objet cible supprimé) devient atteignable via cet
  endpoint mais n'est pas spécifiquement couvert — pertinent pour
  l'action 6 (routes de suppression), pas un bug introduit ici. Non
  commité à ce stade.

## 2bis. [Évolution d'API, demandée en cours de vague 2] Déréférencement optionnel des jointures (`deref`/`depth`) sur `GET /api/read/object/<id>`

- **Origine** : discussion avec l'utilisateur pendant l'implémentation de
  l'action 2 — pas une anomalie de `specifications.md` §9, mais une
  évolution de confort décidée en cours de route. Le constat qui la
  motive : le frontend (`DiagramPage.tsx` lignes 49-61,
  `NavigationPage.tsx` lignes 147-151/181-185/261-269/399-407/425-433)
  fait aujourd'hui des cascades manuelles de `apiReadObject(id)` pour
  résoudre chaque jointure (`{"joint_id": N}`) en objet affichable, avec
  un cache client (`detailCache`) alimenté de façon incertaine (`#id`
  affiché tant que l'objet cible n'est pas en cache).
- **Décision de conception (issue d'une revue croisée optimiste/
  pessimiste/candide avant implémentation)** :
  1. Deux paramètres de requête optionnels sur
     `GET /api/read/object/<int:object_id>` : `deref` (booléen, valeurs
     acceptées explicitement `1`/`true`/`True`, tout le reste = faux —
     ne pas tester `if request.args.get('deref')` nu, une chaîne non
     vide comme `"false"` serait sinon considérée vraie) et `depth`
     (entier, profondeur de résolution récursive).
  2. **`joint_id` n'est PAS renommé** (décision explicite, après revue :
     un renommage en `id` casserait silencieusement 9+ sites frontend
     qui testent `'joint_id' in v`, et comme `POST /api/write/object`
     remplace intégralement les attributs d'un objet, une migration mal
     coordonnée supprimerait silencieusement des jointures existantes en
     base à la prochaine édition — risque de perte de données, pas
     seulement d'affichage). À la place : une clé séparée **`resolved`**
     est ajoutée à côté de `joint_id`, uniquement présente quand l'objet
     cible a effectivement été résolu :
     ```json
     {
       "domain": "liens", "name": "employeur",
       "values": [
         {
           "joint_id": 4,
           "resolved": {
             "id": 4, "meta_class": "personne", "class": "personne_physique",
             "attributes": [{"domain": "details", "name": "nom", "values": ["Doe"]}]
           }
         }
       ]
     }
     ```
     Sans `deref=true` (comportement par défaut, inchangé), aucune clé
     `resolved` n'apparaît — **changement strictement additif et
     rétrocompatible** pour tout appelant existant.
  3. **Garde-fous de profondeur** (le modèle a des jointures récursives
     réelles : `model/personnes.json`, `groupe.membres` est `joint-1-n`
     vers `personne_physique` **ou** `groupe` lui-même, sans contrainte
     DB empêchant un cycle A→B→A) :
     - si `deref=true` sans `depth` fourni : défaut `depth=1` (jamais
       illimité) ;
     - plafond serveur absolu (`MAX_DEPTH = 5`, constante dans
       `backend/app.py`) appliqué **quel que soit** le `depth` demandé
       par le client : `depth` invalide (non entier, négatif, ou
       `> MAX_DEPTH`) → `400` explicite, pas de clamp silencieux ;
     - **mémoïsation par requête** : un dict `{object_id: objet_résolu}`
       tenu pour toute la durée de résolution d'une requête HTTP, pour
       (a) éviter de refaire la même requête SQL si plusieurs branches
       pointent vers le même objet (cas réaliste : plusieurs `groupe`
       partageant un même `personne_physique` membre), et (b) servir de
       détection de cycle explicite : si un `object_id` est déjà en
       cours de résolution **sur le chemin courant** (pas seulement déjà
       vu globalement) quand on retombe dessus, renvoyer
       `{"joint_id": N, "cycle": true}` (pas de clé `resolved`) au lieu
       de récurser à nouveau — robuste même si `depth` n'a pas encore
       atteint 0 sur un cycle court.
  4. Implémentation : factoriser la construction du schéma
     `{id, meta_class, class, attributes}` (actuellement dupliquée telle
     quelle dans `get_object_by_id`) dans une fonction interne
     réutilisable, appelée récursivement avec `depth - 1` pour chaque
     valeur de type jointure rencontrée, tant que `depth > 0` et que
     l'id cible n'est pas déjà sur le chemin de résolution courant.
- **Effort** : moyen (logique récursive + garde-fous à tester sur le cas
  réel `groupe.membres`, notamment avec `model/personnes.json` chargé via
  `/api/init`).
- **Fichiers** : `backend/app.py`.
- **Dépendance** : doit être fait **après** l'action 2 (modifie la même
  fonction `get_object_by_id`), pour éviter un diff qui mélange un
  correctif de bug et une évolution de fonctionnalité.
- **Statut** : ✅ fait (2026-11-09). Implémenté par `worker`
  (`MAX_DEPTH=5`, factorisation `_build_object_payload`, résolution
  récursive avec cache + détection de cycle via `in_progress`). Validé en
  2 itérations d'arbitrage : 1ʳᵉ itération OK fonctionnellement, 2
  corrections cosmétiques demandées (message d'erreur formaté avec
  `MAX_DEPTH`, commentaire sur le compromis du cache multi-profondeur) ;
  2ᵉ itération ✅ OK. `testeur` : cycle réel A→B→A testé (`groupe`
  imbriqués), `{"joint_id":N,"cycle":true}` sans boucle infinie,
  `depth` invalide → 400 propre, jointure orpheline gérée sans `resolved`.
  `testeur-global` ✅ PASS (endpoints voisins, écriture, `/api/init`,
  frontend non touché). Non commité à ce stade.

## 3. [Fonctionnel] `displayname` n'est jamais renvoyé par les endpoints de lecture de classes

- **Problème** : les trois endpoints qui exposent des définitions de
  classe ne recopient jamais la clé `displayname` dans leur réponse JSON,
  bien qu'elle soit stockée telle quelle dans `definition.data` :
  - `list_classes` (`GET /api/read/class`) — construction du dict,
    `backend/app.py` lignes 49-53 ;
  - `get_class_by_id` (`GET /api/read/class/<id>`) — lignes 80-85 ;
  - `get_classes_by_meta_class` (`GET /api/read/<meta_class>`) —
    lignes 105-108.
  Conséquence : `resolveDisplayName` côté frontend (`NavigationPage.tsx`,
  `DiagramPage.tsx`) ne peut jamais utiliser le gabarit `{{attribut}}` et
  retombe systématiquement sur la concaténation du domaine `details`.
- **Correctif** : ajouter la clé `"displayname": cls.get("displayname")`
  dans chacun des trois dicts construits :
  - `list_classes`, bloc `classes.append({...})` (ligne ~49) :
    ```python
    classes.append({
        "meta_class": row["meta_class"],
        "class": cls["class"],
        "displayname": cls.get("displayname"),
        "attributes": cls["attributes"]
    })
    ```
  - `get_class_by_id`, bloc `return jsonify({...})` (ligne ~80) : ajouter
    `"displayname": cls.get("displayname"),` entre `"class"` et
    `"attributes"`.
  - `get_classes_by_meta_class`, bloc `classes.append({...})`
    (ligne ~105) : ajouter la même clé entre `"class"` et `"attributes"`.
  Utiliser `cls.get("displayname")` (pas `cls["displayname"]`) car la clé
  est optionnelle dans `model/schema.json`.
- **Effort** : petit (3 ajouts d'une ligne, aucun changement de contrat
  côté frontend : `types.ts`/`ClassInfo` attend déjà ce champ).
- **Fichiers** : `backend/app.py`.
- **Statut** : ✅ fait (2026-11-09). Implémenté dans la même passe `worker`
  que l'action 2 (même fichier). `testeur` confirme `displayname` présent
  et correct (`"{{prenom}} {{nom}}"` pour `personne_physique`) dans les 3
  endpoints. Arbitre ✅ OK, `testeur-global` ✅ PASS. Non commité à ce
  stade.

## 4. [Fonctionnel] L'édition inline (cellule scalaire / jointure 1-1) n'écrit jamais rien

- **Problème** : `saveInlineEdit` (`frontend/src/pages/NavigationPage.tsx`,
  lignes 448-476) ne fait aucun appel réseau d'écriture — le code contient
  un commentaire indiquant qu'`apiWriteAttribute` « devrait » être appelé
  (lignes 454-460), puis se contente de re-télécharger l'objet et d'afficher
  un toast de succès trompeur (ligne 471). `apiWriteAttribute` existe déjà
  et fonctionne côté backend (`PUT /api/write/attribute/<cls>/<id>/<attribute>/<value>`,
  `backend/app.py` ligne 291) mais n'est importée nulle part dans
  `NavigationPage.tsx`.
- **Correctif** :
  1. Dans `frontend/src/pages/NavigationPage.tsx`, ajouter `apiWriteAttribute`
     à l'import existant d'`api.ts` (en haut du fichier, à côté des autres
     `apiRead*`/`apiWrite*`).
  2. Remplacer le corps de `saveInlineEdit` (lignes 448-476) par un appel
     réel, mais en branchant sur le **type** de l'attribut édité plutôt
     que d'envoyer systématiquement `value` à `apiWriteAttribute` : cette
     fonction ne sait écrire que des valeurs scalaires, et une cellule
     `joint-1-1` stocke dans `inlineEdit.value` l'id de l'objet cible
     (voir `startInlineEdit`, branche `attrDef.type === 'joint-1-1'`,
     lignes 413-421) — l'envoyer tel quel à `apiWriteAttribute` écrirait
     une chaîne dans une colonne censée porter un `joint_id`, ce qui
     échouerait ou corromprait la valeur côté backend. Pour ce cas, suivre
     le même pattern que `saveJointEdit` existant (lignes 479-522, qui
     gère déjà les jointures `joint-1-n`) : reconstruire le payload
     `attributes` complet de l'objet à partir de `detailCache`/`def`, en
     remplaçant seulement la valeur de l'attribut édité par
     `{ joint_id: Number(value) }`, puis sauvegarder via
     `apiWriteObject` :
     ```ts
     const saveInlineEdit = async () => {
       if (!inlineEdit) return
       const { objectId, attrName, value } = inlineEdit
       const obj = objects.find((o) => o.id === objectId)
       if (!obj) return

       const def = getClassDef(obj.meta_class, obj.class)
       const attrDef = def?.attributes.find((a) => a.name === attrName)

       try {
         if (attrDef?.type === 'joint-1-1') {
           const detail = detailCache[obj.id]
           const attributes: Record<string, unknown> = {}
           if (def && detail) {
             for (const ad of def.attributes) {
               const attrVal = detail.attributes.find((a) => a.name === ad.name)
               if (ad.name === attrName) {
                 attributes[ad.name] = { joint_id: Number(value) }
               } else if (ad.type === 'joint-1-1' || ad.type === 'joint-1-n') {
                 if (attrVal) {
                   const jointIds = attrVal.values.filter((v): v is { joint_id: number } => typeof v === 'object' && 'joint_id' in v)
                   if (jointIds.length > 0) attributes[ad.name] = jointIds.length === 1 ? jointIds[0] : jointIds
                 }
               } else if (attrVal && attrVal.values.length > 0) {
                 attributes[ad.name] = String(attrVal.values[0])
               }
             }
           }
           await apiWriteObject({
             meta_class: obj.meta_class,
             class: obj.class,
             attributes,
             id: obj.id,
           } as unknown as { meta_class: string; class: string; attributes: Record<string, unknown> });
         } else {
           await apiWriteAttribute(obj.class, obj.id, attrName, value);
         }
         const refreshed = await apiReadObject(obj.id);
         setDetailCache((prev) => ({ ...prev, [obj.id]: refreshed }));
         addToast('success', `Attribut "${attrName}" mis à jour`);
       } catch (e: unknown) {
         addToast('error', e instanceof Error ? e.message : 'Erreur');
       }
       setInlineEdit(null);
     };
     ```
  3. Supprimer les commentaires de code mort devenus obsolètes (lignes
     454-460, 462-467).
- **Effort** : petit.
- **Fichiers** : `frontend/src/pages/NavigationPage.tsx`.
- **Dépendance** : ce correctif doit être testé **après** la correction
  de l'action 2 (`GET /api/read/object/<id>`), car le `apiReadObject`
  de rafraîchissement utilisé ici échouait systématiquement tant que ce
  bug n'était pas corrigé.
- **Statut** : ✅ fait (2026-11-09). Validé en 2 itérations. 1ʳᵉ itération :
  pessimiste et candide (convergence indépendante) ont détecté un bug
  bloquant introduit par le snippet même du plan : choisir « -- Aucun -- »
  sur une jointure 1-1 envoyait `{joint_id: Number('')}` = `{joint_id: 0}`,
  provoquant une violation de contrainte FK (500), rendant impossible
  l'effacement d'une jointure existante ; garde manquante avant l'appel
  réseau si le cache de détail n'était pas chargé. 2ᵉ itération : garde
  `value !== ''` (omission de la clé au lieu d'envoyer `joint_id:0`) +
  sortie anticipée `if (!def || !detail)` ajoutées par `worker`, confirmé
  résolu par retest ciblé. Arbitre ✅ OK. `testeur-global` ✅ PASS (stack
  complète démarrée réellement — le conflit de port 3000 avait disparu —,
  `tsc -b --force` sans erreur sur les fichiers touchés, persistance
  vérifiée par `curl` scalaire et `joint-1-1`). Dette documentée non
  bloquante : effacer un scalaire (`value=''`) donne 404 côté
  `PUT /api/write/attribute/...` (limitation du endpoint, pas de ce
  fichier) ; suppression silencieuse d'une jointure via « -- Aucun -- »
  (cohérent avec le reste du pattern d'édition inline, pas une
  régression). Non commité à ce stade.

## 5. [Absence de contrôle] Aucune validation de schéma, de `constraint` ni de cohérence meta_class/class

- **Problème** : `jsonschema` est déclaré en dépendance
  (`backend/requirements.txt`) mais jamais importé ni appelé ;
  `load_schema()` (`backend/app.py` lignes 28-30) n'est invoquée nulle
  part. Résultat : `POST /api/write/object`, `POST /api/write/class`,
  `POST /api/write/metaclass` et `POST /api/init` acceptent n'importe
  quelle structure, y compris une `meta_class`/`class` jamais définie, un
  attribut hors schéma, ou une valeur qui viole `constraint` (regex) —
  `sql_constraint` n'est de toute façon jamais traduit en contrainte SQL
  (non traité ici, voir action structurante distincte si demandée).
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
       données invalides en base.
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
- **Effort** : moyen (plusieurs points d'insertion, logique de validation
  à écrire et tester sur les deux fichiers `model/*.json` existants).
- **Fichiers** : `backend/app.py`, `backend/requirements.txt` (vérifier
  que `jsonschema` y est bien listé — déjà le cas d'après
  specifications.md §3.2).
- **Dépendance** : doit être fait **après** l'action 8 (correction de
  `model/schema.json` pour accepter `$schema`), sinon activer la
  validation casse immédiatement le chargement des fichiers d'exemple
  fournis (`model/personnes.json`, `model/reseau.json`), qui contiennent
  tous deux une clé `$schema` non déclarée.
- **Statut** : ⬜ à faire.

## 6. [Absence de fonctionnalité] Aucune route de suppression — révisée pour intégrer l'historisation

> **Révision de conception (2026-11-09)** : lors de la discussion de
> `tocheck.md` (voir `specifications.md` §10.4), l'équipe a identifié un
> conflit direct entre la suppression **physique** immédiate initialement
> prévue ici pour un objet, et une demande d'historisation des
> objets/attributs. Décision de l'utilisateur : implémenter
> l'historisation, avec une suppression **logique** de l'objet (pose
> d'une date de fin), suivie d'une purge physique différée après une
> période de grâce. La suppression d'une **classe** ou d'une
> **meta-classe** (schéma dans `definition.data`, pas instance) reste une
> suppression physique immédiate, sans changement par rapport à la
> conception initiale — elle ne touche jamais `object`/`attribute_value`,
> donc pas de conflit avec l'historisation des données d'instance.

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
  résolution `deref` (action 2bis) doit considérer un objet cible
  `deleted_at IS NOT NULL` comme non résolvable par défaut (même
  traitement que le cas « orphelin » déjà géré : `{"joint_id": N}` sans
  `resolved`), sauf si l'équipe préfère exposer un flag `deleted: true`
  explicite — à trancher au moment de l'implémentation.
- **Câblage frontend minimal** : `apiDeleteObject` dans `api.ts`, bouton
  de suppression dans `NavigationPage.tsx` pour un objet — le strict
  minimum pour que la fonctionnalité soit utilisable.
- **Fichiers** : `backend/app.py`, `frontend/src/api.ts`,
  `frontend/src/pages/NavigationPage.tsx`.
- **Dépendance** : nécessite 6.0 (colonnes `deleted_at`/`valid_to`).
- **Statut** : ⬜ à faire.

### 6.2 Purge physique différée

- **Principe** : après une période de grâce suivant `deleted_at`
  (constante `PURGE_GRACE_PERIOD_DAYS`, **valeur provisoire proposée :
  30 jours — à confirmer/ajuster par l'utilisateur**), un mécanisme de
  purge supprime **physiquement** les lignes `attribute_value`/
  `attribute` de l'objet. Décision à prendre au moment de l'implémentation :
  conserver la ligne `object` elle-même (avec juste ses attributs
  purgés, préservant la trace des jointures entrantes) ou la supprimer
  entièrement (active le `ON DELETE SET NULL`/`CASCADE` déjà en place
  sur les jointures restantes).
- **Déclenchement** : pas de scheduler dans l'architecture actuelle
  (Flask simple, pas de worker de tâches de fond) — prévoir dans un
  premier temps une route déclenchable manuellement/administrativement
  (`POST /api/purge`, à protéger par la future garde d'authentification
  de l'action 7b dès qu'elle existe), qui traite tous les objets dont
  `deleted_at < now() - PURGE_GRACE_PERIOD_DAYS`. Une automatisation
  (cron externe, ou scheduler Python type APScheduler) est une
  amélioration possible mais hors périmètre de ce correctif minimal.
- **Fichiers** : `backend/app.py`.
- **Dépendance** : nécessite 6.1.
- **Statut** : ⬜ à faire.

### 6.3 Suppression d'une classe (schéma — suppression physique, inchangée)

- **Correctif** (identique à la conception initiale, aucun changement) :
  `DELETE /api/delete/class/<string:meta_class>/<string:cls>` : charger
  `definition` par `meta_class` (404 si absente), retirer l'élément de
  `data["classes"]` dont `class == cls` (404 si absent),
  `UPDATE definition SET data = %s` avec `json.dumps(data)` comme
  paramètre (pas le dict Python brut), cohérent avec le pattern déjà
  utilisé partout ailleurs dans `app.py` pour écrire la colonne JSONB
  `definition.data` (`write_class`, `write_metaclass`), réponse `200`.
  Documenter explicitement que ceci ne supprime pas et ne modifie pas
  les objets déjà créés sous cette classe (aucune FK entre `object` et
  `definition`, §3.4).
- **Fichiers** : `backend/app.py`.
- **Statut** : ⬜ à faire.

### 6.4 Suppression d'une meta-classe (schéma — suppression physique, inchangée)

- **Correctif** (identique à la conception initiale, aucun changement) :
  `DELETE /api/delete/metaclass/<string:meta_class>` :
  `DELETE FROM definition WHERE meta_class = %s` (404 si 0 ligne
  affectée), réponse `200`. Documenter explicitement que ceci ne
  supprime pas les objets déjà créés sous cette meta-classe (cohérent
  avec le constat §3.4 : aucune FK entre `object` et `definition`).
- **Fichiers** : `backend/app.py`.
- **Statut** : ⬜ à faire.

- **Effort global de l'action 6** : conséquent (6.0 = réécriture d'un
  endpoint central + migration de schéma ; 6.1/6.2 = nouvelles routes ;
  6.3/6.4 = routes simples déjà conçues, inchangées).
- **Statut global** : ⬜ à faire (sous-actions détaillées ci-dessus).

## 7. [Absence de sécurité] Aucune authentification/autorisation

- **Problème (partie structurelle)** : l'API Flask est entièrement
  ouverte (pas d'auth, pas de session) ; le toggle lecture seule du
  frontend n'a aucune portée serveur.
- **Problème (bug frontend concret et corrigible immédiatement,
  documenté en §6.2)** : dans `frontend/src/App.tsx`, lignes 42-50, le
  prop `readOnly` n'est passé qu'à `<NavigationPage>` (ligne 55) ; les
  appels à `<ConfigurationPage>` (lignes 43-45) et `<DiagramPage>`
  (lignes 47-50) ne le reçoivent pas du tout, et
  `ConfigurationPageProps`/`DiagramPageProps` ne déclarent même pas ce
  prop — un utilisateur en mode lecture seule peut donc créer/modifier
  librement meta-classes, classes et attributs via la page Configuration
  sans aucun signal ni restriction.
- **Correctif (partie frontend, immédiatement actionnable)** :
  1. Dans `frontend/src/pages/ConfigurationPage.tsx`, ajouter `readOnly:
     boolean` à `ConfigurationPageProps` (ligne ~5-7) et au destructuring
     des props (ligne ~19) ; désactiver (attribut `disabled`) les
     boutons « Charger depuis model/ » et « Sauvegarder », ainsi que les
     contrôles d'ajout/suppression de classe et d'attribut, lorsque
     `readOnly` est vrai (même logique que `NavigationPage.tsx`).
  2. Dans `frontend/src/pages/DiagramPage.tsx`, ajouter `readOnly:
     boolean` à `DiagramPageProps` (ligne ~20-23) même si la page est
     actuellement en lecture seule de fait (pas d'action d'écriture) —
     par cohérence d'interface et pour anticiper toute future action
     d'écriture sur cette page.
  3. Dans `frontend/src/App.tsx`, passer `readOnly={readOnly}` aux deux
     appels `<ConfigurationPage>` (ligne 43-45) et `<DiagramPage>`
     (ligne 47-50), comme c'est déjà fait pour `<NavigationPage>`
     (ligne 55).
  Ce correctif reste un artifice **côté client** : il rend le
  comportement cohérent entre les 3 pages, mais n'ajoute toujours aucune
  vérification serveur — c'est exactement la limite documentée dans
  specifications.md pour cette anomalie, pas un fait nouveau introduit
  par ce correctif.
- ~~**Correctif (étape intermédiaire immédiate, avant Keycloak)**~~ —
  **annulé (2026-11-09)** : l'utilisateur a choisi de passer directement
  à l'implémentation Keycloak ci-dessous plutôt que de livrer d'abord
  cette étape intermédiaire ; conservé ici pour mémoire (contenu original
  non modifié), mais ce correctif n'a pas été implémenté et ne le sera
  pas séparément. Description d'origine : mettre
  en place une authentification minimale sur `backend/app.py` (clé API
  statique via en-tête `Authorization`, vérifiée dans un hook
  `before_request` pour toutes les routes `/api/write/*`, `/api/delete/*`
  — lister explicitement chaque route mutante, y compris `/api/init` et
  la future `/api/purge` de l'action 6.2, plutôt qu'un simple filtrage de
  préfixe qui les oublierait), et faire porter le toggle `readOnly` du
  frontend sur l'envoi (ou non) de cet en-tête, avec rejet `403` serveur
  si absent. Correctif petit et sans risque de régression, à livrer avant
  le chantier Keycloak plus large.

- **Correctif (partie structurante, authentification serveur réelle) —
  Keycloak, décision actée le 2026-11-09 (voir `doc/choix-authent.md` et
  `specifications.md` §10.3)** :
  1. **Infrastructure** (`docker-compose.yml`) : ajouter un service
     `keycloak` (image `quay.io/keycloak/keycloak`), configuré pour
     utiliser une base dédiée dans l'instance Postgres déjà présente
     (nouvelle base `keycloak`, pas une nouvelle instance Postgres — évite
     d'ajouter un 2ᵉ service stateful lourd). Realm `miami-vice` à
     provisionner (export JSON versionné dans le dépôt, ex.
     `keycloak/miami-vice-realm.json`, importé au démarrage via
     `--import-realm`), avec :
     - **Scope du premier passage (décision utilisateur du 2026-11-09)** :
       utilisateurs **locaux Keycloak** uniquement pour commencer (créés
       directement dans le realm). La fédération LDAP et l'intégration
       Google (voir options 3/4 de `doc/choix-authent.md`) sont
       explicitement différées à un test ultérieur, une fois ce premier
       passage validé — ne pas les implémenter dans cette itération.
     - Un client confidentiel `miami-vice-backend` (le Flask backend
       valide les tokens, n'a pas besoin d'un flux de login lui-même).
     - Un client confidentiel `miami-vice-service` avec **Service
       Accounts Enabled** : flux `client_credentials`
       (`POST /realms/miami-vice/protocol/openid-connect/token`,
       `grant_type=client_credentials` + `client_id`/`client_secret`) →
       Bearer JWT, pour l'automatisation (scripts, future purge
       périodique de l'action 6.2, intégrations externes).
     - Un client avec **Direct Access Grants Enabled** (Resource Owner
       Password Credentials) pour la connexion humaine directe
       login/mot de passe sans redirection — pertinent tant que le
       frontend n'a pas de routeur pour un flux OIDC Authorization Code
       complet (limite documentée dans `doc/choix-authent.md`).
  2. **Backend** (`backend/app.py`) :
     - Au démarrage (ou en cache avec rafraîchissement périodique, **pas**
       un appel réseau par requête — le backend tourne avec un seul
       worker Gunicorn synchrone, cf. `backend/Dockerfile` : un appel
       JWKS non caché à chaque requête gèlerait tout le backend sur la
       moindre lenteur de Keycloak), récupérer les clés publiques JWKS de
       Keycloak (`/realms/miami-vice/protocol/openid-connect/certs`).
     - Ajouter un hook `before_request` (lib `PyJWT` ou `python-jose`)
       qui : extrait `Authorization: Bearer <token>`, vérifie la
       signature contre le JWKS caché, vérifie `iss`/`aud`, applique ce
       garde sur la liste explicite des routes mutantes (même liste que
       l'étape intermédiaire ci-dessus) ; `401` si absent/invalide.
     - **Point de vigilance explicite** (relevé par l'équipe) : ne pas
       confondre les groupes/rôles Keycloak (autorisation) avec les
       classes métier `role`/`groupe` du modèle applicatif
       (`model/personnes.json`, éditables librement via l'UI générique
       `POST /api/write/object`) — objets de nature complètement
       différente malgré le nom proche ; documenter cette distinction
       explicitement dans le code (commentaire) au moment de
       l'implémentation pour éviter toute confusion future.
  3. **Frontend** : formulaire de login minimal (dans l'état `page`
     existant, pas besoin d'un routeur pour ce flux direct) qui POST
     username/password à l'endpoint token de Keycloak (Direct Access
     Grants), stocke le Bearer obtenu (mémoire ou `localStorage`), et
     l'attache en en-tête `Authorization` sur les appels mutants
     existants (`apiWriteObject`, `apiWriteAttribute`, etc., dans
     `api.ts`). Le toggle `readOnly` peut rester tel quel côté UI, mais
     n'a plus besoin de porter la sécurité : c'est la présence/validité
     du Bearer qui protège réellement le serveur désormais.
  4. **Hors périmètre de cette action** (amélioration future) : flux OIDC
     Authorization Code complet avec redirection vers la page de login
     hébergée par Keycloak — nécessite d'abord un routeur frontend
     (`react-router` ou équivalent), non requis pour satisfaire le besoin
     actuel (comptes de service + login direct).
- **Effort** : petit pour la partie frontend `readOnly` et l'étape clé API
  statique intermédiaire ; important pour Keycloak (nouveau service
  d'infrastructure, provisioning de realm, intégration JWT backend et
  frontend).
- **Fichiers** : `frontend/src/App.tsx`,
  `frontend/src/pages/ConfigurationPage.tsx`,
  `frontend/src/pages/DiagramPage.tsx` (volet frontend `readOnly`) ;
  `backend/app.py`, `docker-compose.yml`, `keycloak/miami-vice-realm.json`
  (nouveau), `frontend/src/api.ts` (volet Keycloak).
- **Statut** :
  - ⬜ à faire (volet frontend `readOnly` propagé à Configuration/Diagramme — action 7a, non traité dans ce cycle).
  - ~~⬜ clé API statique intermédiaire~~ — **annulé (2026-11-09)**, voir note ci-dessus.
  - ✅ **fait (2026-11-09)** — Keycloak (utilisateurs locaux). Validé en
    2 itérations d'arbitrage : 1ʳᵉ itération OK fonctionnellement, 4
    corrections demandées (toutes mineures : runbook rebuild backend,
    runbook volume `pgdata` déjà initialisé, activer `bruteForceProtected`
    dans le realm vu le client ROPC public, reformuler un commentaire
    trop optimiste sur le cache JWKS) ; 2ᵉ itération ✅ OK. `testeur-global`
    ✅ PASS (stack démarrée réellement, non-régression confirmée sur
    toutes les routes de lecture existantes y compris `deref`/`depth`,
    écriture de bout en bout testée avec les 2 types de token, `tsc -b
    --force` sans nouvelle erreur). LDAP/Google explicitement hors scope,
    realm conçu pour les accueillir plus tard sans reconstruction (voir
    `doc/choix-authent.md`). Dette documentée et acceptée pour ce premier
    passage (non bloquante) : `verify_aud` désactivé au profit de `azp`
    (équivalent aujourd'hui, plus fragile si l'architecture ajoute des
    clients/scopes) ; secret `miami-vice-service-secret-dev` versionné en
    clair dans `keycloak/miami-vice-realm.json` (acceptable en dev
    uniquement) ; pas de gestion de refresh token côté frontend ;
    credentials Postgres réutilisés pour la base `keycloak` (pas de rôle
    dédié), à durcir avant toute exposition hors dev. Identifiants de
    test : admin Keycloak `admin`/`admin` ; client `miami-vice-service` +
    secret `miami-vice-service-secret-dev` (`client_credentials`) ;
    utilisateur `testuser`/`testuser123` via client `miami-vice-direct`
    (`password` grant). Non commité à ce stade.
  - Fichiers touchés : `docker-compose.yml`, `sql/00-keycloak-db.sql`
    (nouveau), `keycloak/miami-vice-realm.json` (nouveau),
    `keycloak/provision-realm.sh` (nouveau), `backend/requirements.txt`,
    `backend/app.py`, `frontend/src/api.ts`,
    `frontend/src/components/Navbar.tsx`, `README.md`.

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

## 9. [Évolution, ajoutée le 2026-11-09] Partitionnement PostgreSQL par type d'objet

- **Origine** : `tocheck.md` point 2 — pas une anomalie de
  `specifications.md` §9, une piste de performance demandée explicitement
  par l'utilisateur malgré la réserve de l'équipe (voir
  `specifications.md` §10.5) sur la prématurité sans volumétrie réelle
  mesurée.
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

## 10. [Évolution, ajoutée le 2026-11-09] Liens transitifs du graphe au filtrage de classe

- **Origine** : `tocheck.md` point 4 — amélioration UX demandée par
  l'utilisateur, aucun conflit avec le reste du plan (voir
  `specifications.md` §10.6).
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
     (action 2bis, `backend/app.py`).
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

**Vague 1 — débloquer le démarrage (action 1)**
Rien d'autre n'est observable ni testable tant que `backend/app.py` ne
compile pas : c'est un préalable strict à toutes les vagues suivantes,
y compris pour simplement vérifier qu'une correction ultérieure fonctionne.

**Vague 2 — corriger les bugs backend qui faussent le comportement visible
(actions 2 et 3)**
Une fois le backend démarrable, corriger en premier les deux bugs qui
produisent des réponses API incorrectes silencieusement acceptées par le
frontend (500 sur la lecture d'un objet existant, `displayname` jamais
renvoyé). Ces deux corrections sont indépendantes entre elles mais toutes
deux nécessaires avant de toucher au frontend, car plusieurs correctifs
frontend (vague 3) dépendent d'un backend qui répond correctement.

**Vague 3 — corriger les bugs/messages trompeurs côté frontend (action 4,
et le volet frontend de l'action 7)**
`saveInlineEdit` (action 4) doit être corrigé après la vague 2 : son
rafraîchissement post-écriture (`apiReadObject`) ne peut être validé tant
que l'action 2 n'est pas en place. Le volet frontend de l'action 7
(propagation de `readOnly` à `ConfigurationPage`/`DiagramPage`) est
indépendant et peut être traité en parallèle, sans dépendance sur le
backend.

**Vague 4 — activer les validations manquantes (actions 8 puis 5)**
L'action 8 (déclarer `$schema` dans `model/schema.json`) doit précéder
l'action 5 (appeler enfin `jsonschema.validate`), sans quoi activer la
validation casse immédiatement le chargement des fichiers d'exemple
fournis avec le dépôt. Cette vague est placée après les vagues 2-3 car
elle introduit des réponses `400` nouvelles qui doivent être testées sur
un backend déjà fonctionnellement correct, pour ne pas confondre un rejet
de validation légitime avec un bug résiduel des actions précédentes.

**Vague 5 — combler les fonctionnalités absentes (action 6 dans l'ordre
6.0→6.1→6.2→6.3/6.4, puis volet structurant de l'action 7)**
L'action 6 révisée a une dépendance interne stricte : 6.0 (historisation
du modèle, colonnes `valid_from`/`valid_to`/`deleted_at` + réécriture de
`write_object`) doit précéder 6.1 (suppression logique, qui s'appuie sur
`deleted_at`), qui doit elle-même précéder 6.2 (purge physique, qui
s'appuie sur des objets déjà marqués `deleted_at`). 6.3/6.4 (suppression
physique de classe/meta-classe, inchangées) sont indépendantes de 6.0-6.2
et peuvent être faites en parallèle. Cette vague est placée après la
vague 4 pour être testée sur un backend déjà validé par la validation de
schéma, notamment parce que la suppression d'une classe doit respecter le
même format JSON que les écritures désormais validées.
L'authentification serveur réelle (volet structurant de l'action 7) est
traitée en dernier : c'est le changement le plus large (nouvelle
configuration, secret partagé, garde sur toutes les routes d'écriture et
de suppression), et il doit s'appliquer à une API dont les routes
d'écriture/suppression sont déjà stabilisées, pour éviter de devoir
retoucher la garde d'authentification à chaque nouvelle route ajoutée.
Elle doit aussi protéger la nouvelle route `POST /api/purge` (6.2).

**Vague 6 — évolutions ajoutées le 2026-11-09 (actions 9 et 10)**
Indépendantes l'une de l'autre et du reste du plan (aucune des deux ne
modifie une route existante ni n'est modifiée par une vague précédente).
L'action 9 (partitionnement) doit commencer par son évaluation préalable
de volumétrie avant tout DDL — elle peut être menée à tout moment, y
compris en parallèle des autres vagues, mais sa partie implémentation
(si justifiée) est plus sûre une fois le modèle stabilisé par les vagues
1-5. L'action 10 (liens transitifs du graphe) est purement frontend,
sans dépendance sur le backend ; peut être traitée à tout moment après
la vague 1.

## Récapitulatif d'avancement

> Tableau à tenir à jour en même temps que le champ **Statut** de chaque
> action ci-dessus — une ligne par action, pas par vague.

| # | Vague | Action | Fait ? |
|---|-------|--------|--------|
| 1 | 1 | `backend/app.py` ne compile pas | ✅ |
| 2 | 2 | `GET /api/read/object/<id>` ne renvoie jamais les attributs | ✅ |
| 2bis | 2 | Déréférencement optionnel des jointures (`deref`/`depth`) | ✅ |
| 3 | 2 | `displayname` jamais renvoyé par les endpoints de lecture de classes | ✅ |
| 4 | 3 | Édition inline (scalaire / jointure 1-1) n'écrit jamais rien | ✅ |
| 7a | 3 | Propagation du prop `readOnly` à Configuration/Diagramme (volet frontend) | ⬜ |
| 8 | 4 | `$schema` non déclaré dans `model/schema.json` | ⬜ |
| 5 | 4 | Validation de schéma, `constraint`, cohérence meta_class/class | ⬜ |
| 6.0 | 5 | Historisation du modèle (`valid_from`/`valid_to`/`deleted_at` + réécriture `write_object`) | ⬜ |
| 6.1 | 5 | Suppression logique d'un objet | ⬜ |
| 6.2 | 5 | Purge physique différée (période de grâce à confirmer) | ⬜ |
| 6.3 | 5 | Suppression d'une classe (physique, inchangée) | ⬜ |
| 6.4 | 5 | Suppression d'une meta-classe (physique, inchangée) | ⬜ |
| 7b-intermédiaire | 5 | ~~Clé API statique (avant Keycloak)~~ | ❌ annulé |
| 7b-keycloak | 5 | Authentification Keycloak (comptes de service + login direct, users locaux) | ✅ |
| 9 | 6 | Partitionnement PostgreSQL par type d'objet (évaluation puis implémentation conditionnelle) | ⬜ |
| 10 | 6 | Liens transitifs du graphe au filtrage de classe | ⬜ |

**Décision en attente de confirmation** : `PURGE_GRACE_PERIOD_DAYS`
(action 6.2) — valeur provisoire proposée de 30 jours, à confirmer ou
ajuster avant l'implémentation de 6.2.
**Point encore ouvert, non planifié dans le tableau ci-dessus** :
notion de tenant (`specifications.md` §10.2) — authentification désormais
tranchée (Keycloak, §10.3), donc ce point peut être conçu en détail
quand souhaité ; pas encore une action du plan.

# Plan d'action — Mark 3 — suite des corrections et évolutions de miami-vice

> **Mark 3** : ce plan fait suite à [`plan-mark2.md`](plan-mark2.md) (clos
> le 2026-11-12). Contrairement au passage Mark 1 → Mark 2, **aucune
> action n'a été reportée** : toutes les actions de Mark 2 (5, 6.0-6.4, 7a,
> 8, 9, 10) sont closes — voir la section « Clôture de Mark 2 » en fin de
> `plan-mark2.md`. Ce document démarre donc sans backlog hérité, prêt à
> recevoir les prochaines demandes/évolutions au fur et à mesure.

> **Suivi d'avancement** : mêmes conventions que Mark 1/Mark 2 — chaque
> action porte un champ **Statut** (⬜ à faire / 🔄 en cours / ✅ fait) mis
> à jour au fur et à mesure, par sous-point dès qu'il est validé (pas
> seulement en fin d'action complète), avec une date et un résumé de ce
> qu'ont confirmé `worker`/`testeur`/`pessimiste`/`candide`/
> `testeur-global` (équipe actuelle depuis le 2026-11-12 : pas
> d'`optimiste` — le résumé de fin de tâche de `worker` tient lieu de
> regard favorable — ni d'`arbitre` dédié — l'arbitrage est rendu par
> `orchestrateur` lui-même). Le tableau récapitulatif en fin de document
> doit rester synchronisé avec ces statuts. Toute décision qui annule/
> remplace un contenu déjà écrit ici doit être annotée explicitement (pas
> supprimée silencieusement).

> **En attente** : ajouter ici chaque nouvelle demande (bug, feature,
> évolution) au même format que Mark 1/Mark 2 (Problème / Correctif /
> Effort / Fichiers / Statut), avec un numéro d'action, dès qu'elle est
> formulée.

## 1. [Dette technique] Découpage de `backend/app.py` en modules

> Demande utilisateur (`tocheck.md` point 21, 2026-11-13) : « app.py
> devient gros, splitter ou faire des classes, que l'équipe propose des
> découpages ».

- **Problème** : `backend/app.py` fait 1628 lignes et concentre tout —
  client JWKS/hook d'authentification Keycloak (lignes ~18-133), RBAC
  multi-tenant (`AuthContext` et helpers, ~134-350), accès DB/schéma
  (~352-371), tous les endpoints de lecture (~373-673), tous les
  endpoints d'écriture/suppression d'objets (~675-1270), le chargement
  `/api/init` (~1272-1373), et les endpoints d'administration
  (purge/suppression de schéma, ~1374-1627) — un seul fichier plat.
  Chaque action Mark 1/Mark 2 a ajouté du code dans ce même fichier ;
  la taille augmente la charge de lecture pour `worker`/`testeur`/
  `pessimiste`/`candide` à chaque revue et le risque de collision sur un
  fichier unique.
- **Correctif** : scinder par responsabilité, **sans changer le
  comportement** (déplacement de code, pas de refactor fonctionnel), en
  gardant `app.py` comme point d'entrée mince qui construit
  `app = Flask(__name__)` et enregistre des Blueprints Flask :
  1. `backend/auth.py` — `get_jwk_client`, `_requires_auth`,
     `require_auth` (le hook d'authentification lui-même).
  2. `backend/rbac.py` — `AuthContext`, `get_auth_context`,
     `_tenant_read_filter`, `_normalize_tenants_input`,
     `_tenants_list_to_db`/`_tenants_db_to_list`,
     `_check_class_tenant_write_permission`,
     `_existing_class_out_of_tenant_scope`,
     `_check_existing_class_tenant_scope`, `_determine_object_tenants`.
  3. `backend/db.py` — `get_db`, `close_db`, `load_schema`.
  4. `backend/routes_read.py` (Blueprint) — tous les
     `GET /api/read/...` + helpers `_decode_attribute_value_column`,
     `_load_active_attributes_by_name`, `_build_object_payload`.
  5. `backend/routes_write.py` (Blueprint) — `POST/PUT /api/write/...`,
     `DELETE /api/delete/object/<id>` + helpers `_coerce_typed_value`,
     `_apply_attribute_diff`.
  6. `backend/routes_init.py` (Blueprint) — `POST /api/init`.
  7. `backend/routes_admin.py` (Blueprint) —
     `GET/PUT /api/config/purge_grace_period_days`, `POST /api/purge`,
     `DELETE /api/delete/class/...`, `DELETE /api/delete/metaclass/...`.
  8. `backend/app.py` : ne garde que la création de l'app Flask,
     `app.before_request(require_auth)`, l'enregistrement des
     Blueprints (`app.register_blueprint(...)`), et **ré-exporte
     explicitement** `AuthContext` et `_existing_class_out_of_tenant_scope`
     (`from rbac import AuthContext, _existing_class_out_of_tenant_scope`)
     — requis pour que `backend/test_rbac_class_tenant_scope.py`
     continue de fonctionner tel quel (`import app as miami_app` puis
     `miami_app.app`/`miami_app.AuthContext`/
     `miami_app._existing_class_out_of_tenant_scope`), sans modifier le
     test.
  9. Relancer `backend/test_rbac_class_tenant_scope.py` (9 tests) après
     découpage pour confirmer la non-régression ; pas de nouveau test à
     écrire pour cette action (dette technique, aucun comportement
     nouveau).
- **Effort** : moyen (déplacement mécanique de ~1600 lignes en 6
  fichiers + Blueprints, pas de nouvelle logique ; risque principal :
  casser un import croisé, ou l'ordre d'enregistrement d'un Blueprint
  vis-à-vis de `before_request`/`g`).
- **Fichiers** : `backend/app.py` (réduit), nouveaux `backend/auth.py`,
  `backend/rbac.py`, `backend/db.py`, `backend/routes_read.py`,
  `backend/routes_write.py`, `backend/routes_init.py`,
  `backend/routes_admin.py`.
- **Statut** : ✅ fait (2026-11-13, `worker`). Découpage mécanique
  effectué sans changement de comportement HTTP : `backend/app.py`
  (1628 lignes) réduit à un point d'entrée mince (38 lignes) qui crée
  `app = Flask(__name__)`, enregistre `app.before_request(require_auth)`
  et `app.teardown_appcontext(close_db)` par appel explicite, enregistre
  les 4 Blueprints, et ré-exporte `AuthContext`,
  `_existing_class_out_of_tenant_scope`, `get_db`, `get_auth_context`
  (ce dernier couple requis, pas seulement les deux premiers cités au
  point 8 ci-dessus, car monkeypatchés directement sur `app` par
  `test_rbac_class_tenant_scope.py`, `test_model_driven_typing.py` et
  `test_purge_action_6_2.py`). Nouveaux fichiers : `backend/db.py` (28
  lignes), `backend/auth.py` (118), `backend/rbac.py` (219),
  `backend/routes_read.py` (310, inclut `MAX_DEPTH` et
  `_load_active_attributes_by_name` malgré son usage aussi côté écriture,
  conformément au point 4 ci-dessus), `backend/routes_write.py` (617,
  inclut `write_class`/`write_metaclass` en plus de ce qui était prévu
  au point 5), `backend/routes_init.py` (114), `backend/routes_admin.py`
  (262). Tous les commentaires RBAC/historisation du code déplacé ont été
  conservés tels quels. `routes_read.py`/`routes_write.py`/
  `routes_init.py`/`routes_admin.py` font chacun `import app` en tête de
  fichier et appellent `app.get_db()`/`app.get_auth_context()` à
  l'intérieur des corps de fonctions (jamais au niveau module), pour que
  le monkeypatch direct sur `miami_app.get_db`/`miami_app.get_auth_context`
  (vu dans les 3 fichiers de test ci-dessus) agisse bien sur l'appel réel ;
  pas de souci d'import circulaire constaté (confirmé par import direct de
  `app` en script autonome, cf. ci-dessous). Vérification par grep :
  17 routes au total avant (`@app.route` dans l'ancien `app.py`) et 17
  après (`@read_bp.route`/`@write_bp.route`/`@init_bp.route`/
  `@admin_bp.route` cumulés), aucune manquante ni dupliquée ; confirmé
  aussi par dump de `app.url_map.iter_rules()` après import (17 routes
  applicatives + `/static/<path:filename>` de Flask). Tests :
  `SCHEMA_PATH=model/schema.json .venv/bin/pytest
  backend/test_rbac_class_tenant_scope.py -v` → **9/9 passés**. Suite
  complète du dossier (`backend/`, avec `SCHEMA_PATH` en chemin absolu)
  → **96/96 passés**, y compris `test_model_driven_typing.py` et
  `test_purge_action_6_2.py` qui monkeypatchent eux aussi
  `miami_app.get_db`/`miami_app.get_auth_context` sur les routes de
  `routes_write.py` et `routes_admin.py` — aucune régression, aucun des 5
  échecs pré-existants (liés au chemin relatif `/model/schema.json`) ne
  s'est manifesté ici car la commande utilisée pour la suite complète
  pointait un chemin absolu. Pas de nouveau test écrit (dette technique,
  aucun comportement nouveau, conforme au point 9 ci-dessus).

## 2. [Nouvelle fonctionnalité] Interface de stockage de fichiers (abstraite, impl. à plat)

> Demande utilisateur (`tocheck.md` point 13, décision 2026-11-13) : « on
> passe par une implémentation d'interface qu'on pourra facilement
> remplacer, ça permettra de choisir fichier à plat ou S3 en fonction des
> besoins ». Détail de conception : `specifications/07-roadmap.md` §10.7.

- **Problème** : aucun mécanisme de stockage de fichiers n'existe ;
  prérequis bloquant pour `tocheck.md` #14 (attribut « fichier »), #15
  (« image »), #16 (logo surchargeable par objet).
- **Correctif** :
  1. Créer `backend/file_storage.py` avec une classe abstraite
     `FileStorage` (ABC) définissant `save`, `read`, `delete`,
     `list_versions`.
  2. Implémenter `LocalFileStorage(FileStorage)` : racine configurable
     via `FILE_STORAGE_ROOT` (env var, même pattern que
     `SCHEMA_PATH`/`MODEL_DIR`, défaut `/data/files`), arborescence
     `<root>/<class>/<object_id>/<attribute_name>/<version>/<filename>`.
  3. Nom de fichier reçu = entrée utilisateur : l'assainir avant toute
     écriture disque (refuser `..`, séparateur de chemin, chemin
     absolu) — empêcher tout path traversal hors de l'arborescence
     prévue.
  4. Versionnement : entier incrémental par `(class, object_id,
     attribute_name)`, déterminé par listing du dossier existant —
     jamais d'écrasement, cohérent avec l'historisation déjà en place
     (`plan-mark2.md` action 6.0).
  5. Portée volontairement limitée à cette brique : **pas de route
     HTTP, pas de câblage à un type d'attribut** dans cette action —
     ça reste le périmètre de #14 (action future, distincte).
  6. Ajouter `FILE_STORAGE_ROOT` (volume) à `docker-compose.yml`, sur
     le même principe que le montage `./model`.
  7. Écrire `backend/test_file_storage.py` : round-trip save/read,
     versions multiples incrémentales, refus de nom de fichier
     dangereux (`../../etc/passwd` etc.), delete.
- **Effort** : faible à moyen (code neuf mais borné, fichier autonome,
  aucune dépendance sur `routes_*.py`/`app.py` existants).
- **Fichiers** : nouveaux `backend/file_storage.py`,
  `backend/test_file_storage.py` ; `docker-compose.yml` (volume).
- **Statut** : ✅ fait (2026-11-13, `worker`). Créé
  `backend/file_storage.py` (155 lignes) : classe abstraite `FileStorage`
  (ABC, module `abc`) avec les 4 méthodes minimales `save`/`read`/
  `delete`/`list_versions`, et `LocalFileStorage(FileStorage)` qui les
  implémente sur le filesystem local. Racine configurable via
  `FILE_STORAGE_ROOT` (défaut `/data/files`, même pattern que
  `SCHEMA_PATH`) — mais relue dynamiquement dans `LocalFileStorage.__init__`
  via `os.environ.get(...)` plutôt que via la constante de module figée à
  l'import, pour rester monkeypatchable en tests (même logique que
  `MODEL_DIR` dans `routes_init.py`, lu dans le corps de fonction et non en
  constante de module). Arborescence
  `<root>/<class>/<object_id>/<attribute_name>/<version>/<filename>`.
  Versionnement entier incrémental déterminé par listing des sous-dossiers
  numériques existants (pas de compteur en mémoire/DB) ; jamais
  d'écrasement, `save` crée toujours un nouveau dossier de version. Tous
  les segments de chemin (`class_name`, `object_id`, `attribute_name`,
  `filename`) passent par `_sanitize_segment` (interne, pas seulement
  `filename` comme demandé a minima par la spec — choix : appliquer la même
  règle stricte partout plutôt que de ne protéger que `filename`, pour ne
  pas laisser un `object_id`/`attribute_name` non fiable ouvrir un path
  traversal par un autre segment) : refuse valeur vide, `..`, séparateur de
  chemin (`/`, `os.sep`, `\\`), chemin absolu, ou tout écart entre
  `os.path.basename(valeur)` et la valeur — lève `ValueError`. `read` lève
  `FileNotFoundError` si absent. Signature de `delete(class_name,
  object_id, attribute_name, version=None)` : `version=None` supprime tout
  l'historique de l'attribut (tout le dossier `<attribute_name>/`),
  `version=<int>` ne supprime que ce dossier de version ; `shutil.rmtree(...,
  ignore_errors=True)` dans les deux cas, donc pas d'exception si déjà
  absent (documenté dans la docstring). `list_versions` retourne `[]` si
  jamais aucune version (pas d'exception). Créé
  `backend/test_file_storage.py` (153 lignes, 18 tests, fixture
  `tmp_path`/`monkeypatch.setenv("FILE_STORAGE_ROOT", ...)`) : round-trip
  save/read, versions multiples incrémentales (non-écrasement vérifié sur
  disque), refus de 4 noms de fichiers dangereux en `save` et en `read`
  (`../../etc/passwd`, `/etc/passwd`, `..`, `sub/dir/file.txt`) avec
  vérification qu'aucun fichier n'est écrit dans `tmp_path` lors d'un refus,
  delete avec/sans version (historique partiel préservé, delete sur
  triplet déjà absent sans exception), list_versions (vide avant tout
  save, trié après plusieurs save, correct après delete partiel,
  indépendant par triplet classe/objet/attribut). Résultat :
  `.venv/bin/pytest backend/test_file_storage.py -v` → **18/18 passés**.
  Suite complète `SCHEMA_PATH=.../model/schema.json .venv/bin/pytest
  backend/ -v` → **114/114 passés** (96 préexistants + 18 nouveaux),
  aucune régression. Ajouté à `docker-compose.yml` : volume
  `./files:/data/files` et `FILE_STORAGE_ROOT: /data/files` explicite dans
  `environment:` du service `backend`, même principe que `./model:/model`.
  Fichier 100% autonome (aucun import de `app.py`/`routes_*.py`/`db.py`),
  pas de route Flask, pas de câblage à un type d'attribut, conformément au
  périmètre fixé.

## 3. [Nouvelle fonctionnalité] Types d'attribut "fichier", "image" et "csv"

> Demande utilisateur (`tocheck.md` points 14, 15 et 20, 2026-11-13).
> Détail de conception : `specifications/07-roadmap.md` §10.8. Dépend de
> l'action 2 (`FileStorage`/`LocalFileStorage`).

- **Problème** : pas de moyen d'attacher un fichier (ou une image, ou un
  csv) à un objet ; l'interface de stockage (action 2) existe mais n'est
  câblée à rien, ni côté backend ni côté IHM.
- **Correctif** :
  1. `model/schema.json` : ajouter `"file"`, `"image"` et `"csv"` à
     l'enum `attributes[].type` (aux côtés de `string|integer|float|
     joint-1-1|joint-1-n`) ; ces trois types n'utilisent ni `constraint`/
     `sql_constraint` ni `classes`. `csv` porte en plus un champ
     `"separator"` (défaut `,`) sur la définition d'attribut.
  2. Aucune nouvelle colonne en base : la valeur stockée dans
     `attribute_value.value_string` est un pointeur
     `"<version>:<nom_fichier_original>"` vers le contenu réel géré par
     `FileStorage`, pas le contenu lui-même. Historisation inchangée
     (`valid_from`/`valid_to`, `_apply_attribute_diff`,
     `plan-mark2.md` action 6.0) : une nouvelle valeur ferme l'ancienne
     ligne et ouvre une nouvelle ligne pointant une nouvelle version
     `FileStorage` ; l'ancien fichier n'est jamais effacé tant que sa
     ligne reste dans la fenêtre de grâce (action 6.2).
  3. Nouvelle route `POST /api/write/object/<int:object_id>/file/
     <string:attribute>` (`multipart/form-data`, champ `file`) : objet
     existant et non supprimé logiquement, attribut déclaré `file`/
     `image` sur la classe de l'objet, contrôle RBAC tenant en écriture
     identique aux autres endpoints d'écriture, puis
     `FileStorage.save(...)` + fermeture/ouverture de la ligne
     `attribute_value`.
  4. Nouvelle route `GET /api/read/object/<int:object_id>/file/
     <string:attribute>` (`?version=N` optionnel, sinon version active) :
     même filtre de lecture tenant que `_build_object_payload`, puis
     `FileStorage.read(...)` avec `Content-Type` déduit de l'extension et
     `Content-Disposition`.
  5. Limite de taille d'upload explicite (`MAX_CONTENT_LENGTH` Flask ou
     contrôle avant écriture) — même logique que le refus du `depth`
     illimité (§10.1) : pas de limite de taille de corps = vecteur de
     déni de service par remplissage disque, même avec authentification.
  6. Validation spécifique au type `image` : extension dans
     `{jpg, jpeg, png, svg}` **et** contenu vérifié (signature binaire
     jpg/png ; XML bien formé racine `<svg>` pour svg). ⚠️ **Point de
     sécurité à trancher explicitement à l'implémentation, pas une simple
     validation d'extension** : un SVG peut embarquer du script
     (`<script>`, gestionnaires d'évènements, entités externes) — resservi
     tel quel à un navigateur, c'est un vecteur de XSS stocké classique.
     Servir en `Content-Disposition: attachment` (pas de rendu inline
     direct) ou sanitizer le SVG à l'upload — choisir l'un des deux, pas
     les ignorer.
  7. Tests : upload/download round-trip, versions multiples (historique
     conservé), upload refusé si taille dépassée, upload `image` refusé
     si extension/contenu hors liste blanche, SVG avec `<script>` refusé
     ou neutralisé selon l'option choisie au point 6, lecture tenant-
     scopée (un tenant ne doit pas pouvoir lire/écrire le fichier d'un
     objet hors de son périmètre).
  8. **IHM** (`frontend/src/pages/NavigationPage.tsx`, détail
     `specifications/07-roadmap.md` §10.8) : ajouter une branche de rendu
     par type, aujourd'hui absente (seuls `joint-1-1`/`joint-1-n` ont une
     branche dédiée — le reste tomberait dans le champ texte générique et
     afficherait le pointeur brut) :
     - `file` : nom + bouton **téléchargement** (route de lecture du
       point 4).
     - `image` : **aperçu** inline (`<img>`) + bouton téléchargement —
       le SVG ne bascule en aperçu inline que si le point 6 a tranché
       pour la sanitization ; sinon traitement `file` (téléchargement
       seul) pour le SVG.
     - `csv` : **affichage** en tableau lecture seule (parsing client
       via `separator`) + bouton téléchargement du fichier brut.
     - Formulaire de création/modif : `<input type="file">` pour les
       trois types (remplace la valeur = nouvelle version).
     - Tests frontend : rendu des trois branches + cohérence du choix
       d'aperçu SVG avec le backend.
- **Cas d'usage débloqués** (`specifications/use case.md`) : coffre-fort documentaire/GED
  — versions de fichiers par classe/id/attribut (ligne 15) ; inventaire
  physique avec photos — parc matériel, immobilier, flotte véhicules
  (ligne 19) ; bibliothèque/vinothèque — image de couverture/étiquette et
  import catalogue en csv (ligne 25) ; migration/interconnexion en masse
  via import csv (ligne 29) ; outil de ticket — pièces jointes (ligne 21,
  le volet icône de ce cas dépend de l'action 4 ci-dessous).
- **Effort** : moyen à conséquent (2 nouvelles routes avec RBAC tenant +
  historisation + validation de contenu binaire + rendu IHM dédié par
  type, point de sécurité SVG à ne pas bâcler).
- **Fichiers** : `model/schema.json`, `backend/routes_write.py` (ou
  nouveau module dédié), `backend/file_storage.py` (consommé, pas
  modifié), `frontend/src/pages/NavigationPage.tsx`, nouveaux fichiers de
  test (backend et frontend).
- **Statut** : ✅ fait (2026-11-14, `worker`/`testeur`/`pessimiste`/
  `candide`). Livré en 2 itérations.

  **Itération 1** : `model/schema.json` — ajout `"file"`, `"image"`,
  `"csv"` à l'enum `attributes[].type`, champ `"separator"` (défaut `,`)
  sur `csv`. Nouveau `backend/routes_files.py` (Blueprint `files_bp`) :
  `POST /api/write/object/<id>/file/<attribute>` (`write_object_file`,
  multipart) et `GET /api/read/object/<id>/file/<attribute>`
  (`read_object_file`, `?version=N` optionnel), RBAC tenant identique aux
  autres routes d'écriture/lecture, pointeur `"<version>:<nom_fichier>"`
  dans `attribute_value.value_string`, historisation via
  `_apply_attribute_diff` inchangée. Garde ajoutée dans le JSON
  `write_object`/`write_attribute_value` (`routes_write.py`) : un attribut
  `file`/`image`/`csv` ne peut jamais être fourni comme valeur JSON
  classique, seulement via le champ multipart dédié — erreur 400 explicite
  sinon. IHM `frontend/src/pages/NavigationPage.tsx` : 3 branches de rendu
  ajoutées (`file` = nom + téléchargement, `image` jpg/jpeg/png = aperçu
  `<img>` inline + téléchargement, `csv` = tableau lecture seule parsé
  côté client selon `separator` + téléchargement brut), `<input
  type="file">` au formulaire de création/modif pour les trois types.
  **Décision sécurité SVG tranchée** (point 6 du correctif) : pas de
  sanitization du contenu SVG à l'upload (jugée trop fragile sans lib
  dédiée) — validation structurelle seule (XML bien formé, racine
  `<svg>`) et **attachment systématique** en lecture, y compris pour le
  SVG (jamais de rendu `<img>` inline pour ce format) — neutralise le
  vecteur XSS stocké sans prétendre nettoyer le contenu.

  **Itération 2**, suite à revue croisée (pessimiste/candide) +
  décision utilisateur : 4 corrections intégrées sans revenir sur
  l'itération 1 — (a) fusion création objet + fichier(s) en une seule
  transaction Postgres (`_write_object_multipart` dans
  `routes_write.py`) : la création d'un objet portant des attributs
  `file`/`image`/`csv` à l'upload n'est plus un POST objet suivi d'un
  second POST fichier (fenêtre d'incohérence si le second échoue), les
  deux sont désormais atomiques ; (b) nettoyage des fichiers orphelins
  (`POST /api/admin/sweep_orphan_files` dans `routes_admin.py`,
  `sweep_orphan_files`) pour couvrir le cas résiduel d'un crash process
  entre écriture disque et commit, réservé global-admin ; (c) fix DoS XML
  sur la validation SVG : `defusedxml` remplace `xml.etree.ElementTree`
  brut (entités externes/bombes XML) dans `backend/file_validation.py` ;
  (d) fixes de noms de fichiers limites (`"."`, séparateurs,
  `IsADirectoryError` non catché) catchés proprement en 400 via
  `save_file_or_400` plutôt qu'en 500 brute ; validation CSV basique
  ajoutée (`validate_csv_content`, extension `.csv` + décodabilité
  texte UTF-8/latin-1 — limite assumée et documentée dans la docstring
  de la fonction : le repli latin-1 n'échoue jamais en pratique, donc ne
  rejette en pratique que par l'extension, pas une détection de binaire
  robuste).

  **Tests** : `backend/test_file_attribute_type.py` (632 lignes) et
  `backend/test_file_sweep_orphans.py` (109 lignes) ajoutés — round-trip
  upload/download, versions multiples (historique conservé), refus taille/
  extension/contenu hors liste blanche, SVG avec script refusé en
  validation stricte mais toujours servi en attachment, lecture
  tenant-scopée, atomicité `_write_object_multipart`, sweep orphelins.
  Suite complète : `SCHEMA_PATH=.../model/schema.json .venv/bin/pytest
  backend/ -v` → **157/157 passés**, 0 régression sur les 96 tests
  préexistants (actions 1 et 2). Pas de tests frontend ajoutés — le
  projet n'a pas de script `test` dans `frontend/package.json` ni de
  suite de tests frontend existante avant cette action (pattern déjà en
  place, pas introduit ici) ; revue du rendu des 3 branches faite par
  `pessimiste`/`candide` en lecture de code et test manuel, pas par
  automatisation.

  **3 dettes identifiées en revue croisée finale, arbitrées acceptées
  telles quelles pour Mark 3 (documentées en commentaire dans le code,
  aucune correction comportementale requise)**, closes pour cette action
  avec cette dette assumée :
  1. Transaction Postgres ouverte pendant l'I/O disque de
     `FileStorage.save` dans `_write_object_multipart`
     (`backend/routes_write.py`) — acceptable avec `LocalFileStorage`
     (I/O locale rapide), à revisiter si un backend `FileStorage` réseau
     (S3 ou autre) est implémenté un jour (transaction longue, verrous
     tenus plus longtemps) — commentaire ajouté juste avant la boucle
     d'upload dans `_write_object_multipart`.
  2. `sweep_orphan_files` fait une requête SQL par fichier scanné sans
     commit intermédiaire (`backend/routes_admin.py`) — acceptable au
     volume actuel, à traiter (requête groupée ou chunking) avant un
     volume important — commentaire ajouté en tête de la boucle de
     sweep.
  3. `validate_csv_content` (`backend/file_validation.py`) ne rejette en
     pratique que par l'extension `.csv`, pas par le contenu (repli
     latin-1 n'échoue jamais) — déjà documenté explicitement dans la
     docstring existante de la fonction depuis l'itération 2, confirmé
     suffisant en revue finale, aucun changement nécessaire.

## 4. [Nouvelle fonctionnalité] Logo surchargeable par objet et icône par défaut par classe

> Demande utilisateur (`tocheck.md` points 16 et 17, 2026-11-13). Détail
> de conception : `specifications/07-roadmap.md` §10.8. Dépend de
> l'action 3 (type d'attribut `image`) pour le logo ; l'icône de classe
> est indépendante (pas de dépendance au stockage de fichiers).

- **Problème** : aucune représentation visuelle configurable par classe
  (icône) ni par objet (logo) dans `DiagramPage`/`NavigationPage` —
  aujourd'hui une couleur de palette fixe par classe uniquement (§6.4).
- **Correctif** :
  1. **Icône de classe (#17)** : ajouter un champ optionnel `"icon"` sur
     une classe dans `model/schema.json` (chaîne = identifiant choisi
     dans un **jeu fixe** d'icônes embarquées côté frontend, pas un
     upload libre). Sélecteur (grille) dans `ConfigurationPage.tsx`.
     Utilisée par `DiagramPage`/`NavigationPage` comme représentation par
     défaut d'un objet de cette classe, après le logo s'il existe.
  1bis. **Icône par défaut auto-récupérée** (demande 2026-11-14, détail
     `specifications/07-roadmap.md` §10.8) : si pas d'icône choisie
     manuellement, fonction backend mot-clé (nom de classe) → SVG
     svgrepo.com, passée par une étape d'homogénéisation configurable
     (couleur/traits/viewBox normalisés), résultat mis en cache. Fallback
     obligatoire si échec/pas de résultat : SVG généré localement, rond +
     nom de classe. ⚠️ svgrepo.com n'a pas d'API de recherche publique
     documentée — à vérifier avant implémentation (point ouvert).
  2. **Logo d'objet (#16)** : convention — une classe qui « a un logo »
     porte un attribut réservé de type `image` (ex. nom `logo`, domaine
     `display`), réutilisant intégralement la plomberie de l'action 3 —
     backend (upload/download) **et** IHM (action 3, point 8) : aperçu
     inline dans `NavigationPage.tsx`, **cliquable** pour ouvrir le
     sélecteur de fichier (pas de bouton séparé — clic sur l'aperçu =
     ouverture directe de l'upload), `DiagramPage.tsx` restant la vue
     spécialisée en lecture seule (rendu dans le diagramme, point 4
     ci-dessous — pas d'interaction clic sur les nœuds du diagramme dans
     le périmètre de cette action, `DiagramPage.tsx` n'a aujourd'hui aucun
     binding clic sur les nœuds, ce serait une brique distincte). Sur un
     objet, l'UI permet d'importer un fichier **ou** de sélectionner un
     logo déjà présent parmi ceux d'autres objets de classes à logo.
  3. **Point de conception tranché (décision utilisateur, 2026-11-14)** :
     réutiliser un logo existant fait pointer `attribute_value` vers le
     `(classe, object_id, attribut, version)` d'un *autre* objet —
     **référence, pas duplication d'octets**. Conséquences à implémenter :
     - La purge différée (§10.4, action 6.2) doit vérifier, avant de
       supprimer une version de fichier, qu'**aucun** `attribute_value`
       de n'importe quel objet/classe ne pointe encore dessus — pas
       seulement l'historique propre de l'objet propriétaire. Supprimer
       (et purger) l'objet source ne doit **pas** supprimer le fichier
       tant qu'une référence externe existe ailleurs.
     - Avertissement à la suppression (souhaitable, non bloquant pour
       cette action si le temps manque) : si l'objet qu'on supprime
       possède un logo référencé par d'autres objets, avertir l'
       utilisateur (« logo utilisé par N autres objets ») avant de
       confirmer la suppression.
     - **Garde-fou obligatoire (auto-réparation)** : à l'affichage du
       logo d'un objet, si le fichier pointé est introuvable (référence
       cassée malgré la purge sécurisée ci-dessus — cas limite), ne pas
       laisser une image cassée indéfiniment : nettoyer la valeur de cet
       attribut `logo` sur l'objet affecté (retour à vide) pour qu'il
       retombe sur le fallback normal (icône de classe puis couleur,
       point 4) dès l'affichage suivant.
  4. `DiagramPage.tsx` : rendu `symbol: 'image://<url de lecture>'`
     (route de l'action 3) si logo résolu, sinon icône de classe (point
     1), sinon fallback couleur actuel (§6.4) — ordre de priorité
     explicite à respecter. Le garde-fou du point 3 (nettoyage si fichier
     introuvable) s'applique aussi ici : un logo cassé ne doit jamais
     bloquer le rendu du diagramme, juste retomber au niveau de fallback
     suivant.
  5. Tests : rendu avec logo seul, icône seule, aucun des deux (fallback
     couleur) ; réutilisation d'un logo par référence puis suppression de
     l'objet source (fichier conservé, toujours lisible depuis l'objet
     référent) ; référence cassée simulée → affichage retombe sur le
     fallback et la valeur de l'attribut est nettoyée côté serveur.
- **Cas d'usage débloqués** (`specifications/use case.md`) : CMDB avec supervision
  intégrée — icône de classe + logo par objet pour les diagrammes
  (ligne 11) ; outil de ticket — icône par type de ticket (ligne 21, le
  volet pièce jointe de ce cas dépend de l'action 3 ci-dessus).
- **Effort** : moyen (frontend — sélecteurs, clic-pour-éditer, rendu
  graphe — plus la logique backend de purge référence-consciente et
  l'auto-réparation du point 3).
- **Fichiers** : `model/schema.json`, `frontend/src/pages/
  ConfigurationPage.tsx`, `frontend/src/pages/DiagramPage.tsx`,
  `frontend/src/pages/NavigationPage.tsx`, backend : job/route de purge
  (action 6.2, probablement `backend/routes_admin.py`) à rendre
  référence-consciente (point 3), route de lecture fichier (action 3,
  `backend/routes_files.py`) à adapter pour l'auto-réparation.
- **Statut** : ✅ fait (2026-11-14, `worker`/`testeur`/`pessimiste`/
  `candide`). Livré en 2 itérations.

  **Itération 1** : `model/schema.json` — champ optionnel `"icon"` sur
  une classe (identifiant dans un jeu fixe côté frontend). Nouveau
  `frontend/src/classIcons.tsx` : 18 icônes SVG inline embarquées,
  sélecteur en grille ajouté dans `ConfigurationPage.tsx`.
  **Décision tranchée sur svgrepo.com** (point 1bis) : vérification
  faite avant implémentation — pas d'API de recherche publique
  documentée, page de recherche est une SPA non scrappable de façon
  fiable (404 constaté sur tentative d'endpoint API), conforme à la
  clause de repli prévue par la spec : le fallback rond+initiales
  devient le comportement **permanent** (pas une tentative réseau puis
  repli, directement le repli). Nouveau `backend/class_icon.py` :
  génère ce SVG fallback (rond coloré par hash déterministe du nom de
  classe sur une palette dupliquée de `CLASS_COLORS`, initiales
  centrées), cache disque, servi par nouvelle route
  `GET /api/class_icon/<meta_class>/<class>` (volontairement non
  filtrée tenant, documenté — l'icône de classe n'est pas une donnée
  sensible). Attribut réservé `logo` (type `image`, domaine `display`)
  ajouté en démo sur la classe `serveur` de `model/itil_cmdb.json`.
  `backend/routes_files.py` : format de pointeur étendu
  `"ref:<classe>:<object_id>:<attribut>:<version>:<nom_fichier>"` pour
  qu'un logo pointe vers le fichier d'un **autre** objet (référence, pas
  duplication), résolution anti-chaîne, nouvelle route
  `POST .../file/<attribute>/reference` et `GET /api/logos` (liste des
  logos existants, filtrée RBAC tenant). Garde-fou auto-réparation :
  fichier référencé introuvable à la lecture → nettoyage de l'attribut
  sur l'objet affiché, 404 propre. `backend/routes_admin.py` :
  `sweep_orphan_files` (purge physique différée, action 6.2) rendu
  référence-conscient — vérifie **toute** la table `attribute_value`
  (pas que l'objet propriétaire) avant de supprimer un fichier
  physique. `frontend/src/pages/NavigationPage.tsx` : aperçu logo
  cliquable (ouvre directement l'input file), sélecteur de réutilisation
  d'un logo existant d'un autre objet. `frontend/src/pages/
  DiagramPage.tsx` : ordre de priorité logo → icône classe manuelle →
  icône fallback backend → couleur (§6.4). **Limite connue documentée,
  non bloquante** : avertissement à la suppression d'un objet dont le
  logo est référencé ailleurs — pas implémenté (skip assumé,
  explicitement non-bloquant selon la spec).

  **Itération 2**, 3 bugs trouvés en revue croisée pessimiste/candide/
  testeur, corrigés : (a) `frontend/src/pages/NavigationPage.tsx`
  (`parseFilePointer`) ne reconnaissait pas le préfixe `ref:` → aperçu
  vide en édition pour un logo référencé — fix : parsing dédié qui
  saute les 5 premiers `:` et préserve un nom de fichier contenant
  lui-même `:`. (b) `frontend/src/pages/DiagramPage.tsx` : logo rendu
  via URL brute (`image://<url>`) — bug réel et permanent, pas
  transitoire : `<img>`/ECharts ne peut jamais attacher de header
  `Authorization: Bearer`, et le RBAC tenant est fail-closed
  (`rbac.py`), donc tout objet tenant-scoped avec logo était invisible
  dans le diagramme pour tout viewer — fix : résolution du logo via
  fetch authentifié (`apiReadObjectFileBlob`, même pattern que
  `NavigationPage.tsx`) → object URL mis en cache, assigné au `symbol`
  une fois résolu, fallback icône/couleur en attendant. (c)
  `backend/routes_files.py` (`_self_heal_broken_pointer`) fermait
  aveuglément la valeur active au moment de l'appel (race condition
  étroite avec une réécriture concurrente) — fix : filtre désormais sur
  le `value_string` exact qui a échoué.

  **Testeur-global : OK (182/182, démarrage Flask propre, aucune
  régression RBAC/purge/file storage/typage modèle).**

## 5. [Dette technique / préparation] Versionnage des fichiers modèle

> Demande utilisateur (2026-11-14) : documenter que `/api/init` charge
> bien tous les fichiers `model/*.json` montés via docker-compose (déjà
> vrai en code, spec à mettre à jour car en retard sur le comportement
> réel), et ajouter un champ `"version"` au niveau d'un document modèle
> pour préparer une future gestion de migrations — **sans construire le
> mécanisme de migration lui-même maintenant** (« on verra par la
> suite ») : juste le champ, persisté, visible dans la réponse de
> chargement.

- **Problème (volet doc)** : `specifications/04-api-backend.md` §4.5 est
  en retard sur `backend/routes_init.py` réel : dit encore « Aucune
  validation JSON Schema n'est appliquée » et ne mentionne ni le champ
  `skipped` ni la logique RBAC tenant-admin (fusion classe par classe,
  jamais de suppression silencieuse d'une classe absente du fichier
  rechargé) qui existent déjà dans le code depuis l'action 11 (RBAC
  multi-tenant, antérieure à Mark 3).
- **Problème (volet version)** : un document modèle (`model/*.json`,
  champs `meta_class`/`classes`) n'a aujourd'hui aucun identifiant de
  version. Impossible de distinguer "ce fichier a changé de forme depuis
  la dernière fois qu'il a été chargé" d'un simple remplacement intégral
  — toute future logique de migration (transformer les objets existants
  quand la définition d'une classe change de façon incompatible) a
  besoin d'un point de comparaison explicite avant/après.
- **Correctif** :
  1. **Doc** : réécrire `specifications/04-api-backend.md` §4.5 pour
     refléter le comportement réel actuel de `/api/init` — parcourt
     `MODEL_DIR` (défaut `/model`, monté via `docker-compose.yml` ligne
     `./model:/model` sur le service `backend`) ; charge **tous** les
     fichiers `*.json` du dossier sauf `schema.json`, silencieusement
     ignorés si `meta_class`/`classes` absents ; validation JSON Schema
     désormais appliquée (fichier invalide → listé dans `skipped`, pas
     une erreur HTTP) ; RBAC tenant-admin fait une fusion classe par
     classe (classe hors périmètre → `skipped`, inchangée en base,
     jamais re-taguée ; classe absente du fichier rechargé → jamais
     supprimée silencieusement) ; global-admin remplace intégralement les
     classes du fichier. Réponse `{"status":"ok","loaded":[...],
     "skipped":[...]}`.
  2. **Champ `version`** : ajouter une propriété top-level optionnelle
     `"version"` (entier, `minimum: 1`) dans `model/schema.json`, à côté
     de `meta_class`/`depends_on`/`classes`. Absence = version 1 par
     défaut (pas de migration à l'historique zéro).
  3. `backend/routes_init.py` : lire `data.get("version", 1)`, l'inclure
     dans `store_data` (les deux branches, tenant-admin **et**
     global-admin — actuellement aucune des deux ne propage un champ
     top-level autre que `meta_class`/`classes`, ce correctif ajoute la
     propagation pour `version` uniquement, pas pour `depends_on` qui
     reste une limite préexistante hors périmètre de cette action).
     Ajouter un nouveau champ `"versions"` à la réponse JSON (dict
     `{meta_class: version}` pour les meta-classes effectivement
     chargées) — **additif**, ne change pas la forme de `loaded` (liste
     de noms, inchangée, pour ne pas casser
     `ConfigurationPage.tsx:249` qui fait `res.loaded.join(', ')`).
  4. `backend/routes_write.py` (`write_metaclass`) : même propagation —
     `data["version"] = body.get("version", 1)` avant la validation JSON
     Schema, pour qu'un appel direct à cette route (hors fichier modèle)
     puisse aussi déclarer une version.
  5. Pas de nouvelle colonne SQL : `version` reste dans le JSONB `data`
     de `definition` (même traitement que `depends_on` aujourd'hui) —
     une colonne dédiée pour requêter efficacement les versions sera
     ajoutée plus tard, seulement quand un vrai mécanisme de migration en
     aura besoin (décision explicitement reportée par l'utilisateur).
  6. Tests : chaque fichier `model/*.json` existant reste chargeable sans
     `version` (défaut 1, non-régression) ; un document avec `version`
     explicite la conserve après chargement (`/api/init` et
     `/api/write/metaclass`) ; réponse `/api/init` contient bien
     `versions` sans changer la forme de `loaded` ; RBAC tenant-admin
     (fusion classe par classe) continue de fonctionner avec un document
     versionné.
- **Effort** : faible (champ de schéma + propagation dans 2 endpoints +
  doc). Pas de migration réelle implémentée — juste la donnée pour la
  construire plus tard.
- **Fichiers** : `model/schema.json`, `backend/routes_init.py`,
  `backend/routes_write.py`, `specifications/04-api-backend.md`,
  nouveaux tests backend.
- **Statut** : ✅ fait, en 2 itérations suite à revue croisée.
  **Itération 1** : `model/schema.json` — propriété top-level
  optionnelle `"version"` (integer, `minimum: 1`), non `required`.
  `backend/routes_init.py` : version propagée dans `store_data` des
  deux branches (fusion tenant-admin et remplacement global-admin) ;
  nouveau champ `versions` ajouté à la réponse JSON (additif), `loaded`
  inchangé. `backend/routes_write.py` (`write_metaclass`) : propage
  `version` avant validation JSON Schema. Doc
  `specifications/04-api-backend.md` §4.5 relue, déjà conforme.
  **Itération 2** (suite revue croisée pessimiste) : rejet explicite
  d'un `version` flottant même à valeur entière (ex. `2.0`, accepté à
  tort par `jsonschema` pour `type: integer` — comportement de la spec
  JSON Schema, pas un bug de lib) — skip dans `backend/routes_init.py`,
  `abort(400)` dans `backend/routes_write.py`. Dans la branche
  tenant-admin de `backend/routes_init.py`, la version du document
  n'est plus écrasée par celle du fichier rechargé quand au moins une
  classe a été réellement skippée pour hors-périmètre pendant la
  fusion (flag `any_class_skipped`) — affiné une 2e fois en cours
  d'itération pour ne figer la version QUE dans ce cas précis (pas dès
  qu'une ligne existait déjà, sinon un tenant-admin qui retouche 100%
  de son périmètre ne pourrait jamais faire avancer la version). Doc
  `specifications/04-api-backend.md` §4.4 complétée (ne mentionnait pas
  le champ `version` sur `write_metaclass`). Tests :
  `backend/test_model_version_action_5.py` — 193/193 tests backend au
  final (aucune régression). Testeur-global : OK (docker compose, logs
  propres, pas de nouvelle dépendance donc pas de rebuild nécessaire,
  curl réel confirme routes/auth OK).
  **Limite connue acceptée** (pas corrigée, décision explicite de ne
  pas itérer une 3e fois dessus vu le scope volontairement minimal de
  cette action — champ purement informatif, aucune logique de
  migration réelle ne le consomme encore) : le champ `version` peut
  avancer (suivre la version du fichier rechargé) même si une classe
  est omise du fichier sans avoir été réellement skippée pour raison
  RBAC (cas différent du skip RBAC explicite, qui lui gèle bien la
  version) — cette classe omise reste en fait inchangée en base, mais
  la version du document progresse quand même comme si tout avait été
  retouché. Acceptable tant qu'aucune logique de migration ne consomme
  ce champ ; à revoir si/quand un vrai mécanisme de migration est
  construit.

## 6. [Dette documentaire] Synchronisation `specifications/` avec les actions 1-5

> Demande utilisateur (2026-11-21) : « regarde entre les specs et plan mark
> 3 est ce qu'on est à jour » puis, après constat d'un retard par audit
> (hors-agent) : « ajoute ce qu'il faut au plan pour être à jour et
> corrige specs si besoin ».

- **Problème** : `specifications/` ne reflétait pas tout ce qui a été livré
  par les actions 1-5 de ce plan, constaté précisément en comparant le code
  réel (`model/schema.json`, `model/itil_cmdb.json`, `backend/routes_files.py`,
  `backend/class_icon.py`, `backend/routes_admin.py`,
  `backend/file_validation.py`, `backend/app.py`, `frontend/src/pages/
  NavigationPage.tsx`, `frontend/src/pages/DiagramPage.tsx`,
  `frontend/src/pages/ConfigurationPage.tsx`, `frontend/src/classIcons.tsx`)
  aux 5 fichiers `specifications/*.md` concernés :
  - `specifications/03-modele-donnees.md` : aucune mention des types
    d'attribut `file`/`image`/`csv` (ni du champ `separator` propre à
    `csv`), du champ `icon` sur une classe, de la convention d'attribut
    réservé `logo`, ni du champ top-level `version` d'un document modèle
    (action 5).
  - `specifications/04-api-backend.md` : aucune section sur
    `backend/routes_files.py` — ni les 2 routes d'upload/lecture de
    fichier, ni la route de référence de logo, ni `GET /api/logos`, ni
    `GET /api/class_icon/<meta_class>/<class>`, ni
    `POST /api/admin/sweep_orphan_files`, ni les 2 formats de pointeur
    (direct et `ref:`), ni le garde-fou d'auto-réparation.
  - `specifications/05-frontend.md` : aucune mention du rendu des types
    `file`/`image`/`csv` dans `NavigationPage.tsx` (téléchargement, aperçu
    `<img>`, tableau csv, SVG jamais inline), du logo cliquable + sélecteur
    de réutilisation, du jeu de 18 icônes `classIcons.tsx` + sélecteur
    grille dans `ConfigurationPage.tsx`, ni de l'ordre de priorité
    logo/icône/couleur dans `DiagramPage.tsx` ; tableau du client API
    (§6.6) incomplet (6 fonctions manquantes).
  - `specifications/02-architecture.md` : aucune description du découpage
    de `backend/app.py` en Blueprints (action 1, ni les modules ajoutés
    par les actions 2-4).
  - `specifications/07-roadmap.md` : §10.7/§10.8 avaient des en-têtes
    « tranché »/« conçu » au lieu de « fait », et leur corps décrivait
    encore les points ouverts/options envisagées d'origine plutôt que les
    décisions finales réellement prises (sécurité SVG, fallback svgrepo,
    format de pointeur `ref:`, sweep des orphelins, 2 itérations de
    bugfix) ; la ligne de statut de fin de section 10 datait du
    2026-11-13 et disait encore les actions 3/4 « à faire ».
- **Correctif** : 5 fichiers `specifications/*.md` corrigés, basés sur une
  lecture du code réel (pas seulement de ce plan) :
  1. `specifications/03-modele-donnees.md` : nouvelle section « 3.2bis
     Extensions Mark 3 » — types `file`/`image`/`csv` et `separator` sur
     `csv`, champ `icon` sur une classe, convention d'attribut réservé
     `logo` (exemple concret : classe `serveur` de `model/itil_cmdb.json`),
     champ top-level `version`.
  2. `specifications/04-api-backend.md` : nouvelle section « 4.6 Fichiers
     (file/image/csv), logos et icônes de classe » — les 2 formats de
     pointeur, `POST`/`GET .../file/<attribute>`, `POST
     .../file/<attribute>/reference`, `GET /api/logos`,
     `GET /api/class_icon/<meta_class>/<class>` (non filtrée tenant,
     expliqué), `POST /api/admin/sweep_orphan_files` (global-admin,
     référence-consciente), garde-fou d'auto-réparation. §4.4/§4.5
     (champ `version`, action 5) non touchés, déjà corrects.
  3. `specifications/05-frontend.md` : nouvelle section « 6.8 Fichiers,
     logos, icônes de classe » — rendu des 3 branches de type dans
     `NavigationPage.tsx`, logo cliquable + sélecteur de réutilisation,
     `classIcons.tsx` (18 icônes vérifiées) + sélecteur grille dans
     `ConfigurationPage.tsx`, ordre de priorité logo > icône classe >
     icône fallback backend > couleur dans `DiagramPage.tsx` (fetch
     authentifié) ; tableau §6.6 complété (6 fonctions `api.ts`
     manquantes).
  4. `specifications/02-architecture.md` — **deux corrections distinctes** :
     - Nouvelle section « 2bis » décrivant le découpage réel de
       `backend/app.py` en 5 Blueprints et les modules ajoutés par les
       actions 1 à 4 (`auth.py`, `rbac.py`, `db.py`, `routes_read.py`,
       `routes_write.py`, `routes_init.py`, `routes_admin.py`,
       `routes_files.py`, `class_icon.py`, `file_storage.py`,
       `file_validation.py`).
     - **Correction séparée, sans rapport avec Mark 3** : ce fichier
       contenait des passages datés prédatant même Mark 1 (« sans
       authentification », « l'API est entièrement ouverte », « cet
       import échoue » pour `gunicorn app:app`) — un rattrapage
       antérieur découvert au passage, pas une régression ni un trou
       de Mark 3. Corrigés pour refléter l'état réel vérifié dans le
       code : authentification Keycloak active (`backend/auth.py`), RBAC
       multi-tenant actif (`backend/rbac.py`), `backend/app.py` s'importe
       et démarre normalement sous gunicorn.
  5. `specifications/07-roadmap.md` : §10.7/§10.8 passés de
     « tranché »/« conçu » à « fait », corps complété par un bloc
     « décisions finales retenues » (sécurité SVG = attachment
     systématique jamais sanitizé, fallback svgrepo devenu permanent,
     format de pointeur `ref:`, `sweep_orphan_files`, 3 bugfix post-revue
     croisée des actions 3/4) ; ligne de statut de fin de section 10 mise
     à jour (2026-11-21, actions 1-5 toutes closes, action 6 ajoutée).
     §10.9 (champ `version`, action 5) **non ajouté** : jugé redondant,
     §4.4/§4.5 de `04-api-backend.md` documentent déjà ce champ en détail
     et §3.2bis de `03-modele-donnees.md` le couvre côté schéma.
- **Effort** : faible (doc only, aucun fichier backend/frontend/model
  modifié — lecture seule pour vérifier la forme réelle).
- **Fichiers** : `plan-mark3.md`, `specifications/02-architecture.md`,
  `specifications/03-modele-donnees.md`, `specifications/04-api-backend.md`,
  `specifications/05-frontend.md`, `specifications/07-roadmap.md`.
- **Statut** : ✅ fait (2026-11-21, `worker`/`pessimiste`/`candide`), en 2
  itérations suite à revue croisée. Chaque point relu contre le code
  source réel (pas seulement contre ce plan). Aucun comportement de code
  modifié.

## 7. [Nouvelle fonctionnalité] Type d'attribut select/enum

> Choix utilisateur du 2026-11-22 parmi les idées de `tocheck.md`, par
> ordre de priorité explicite (celle-ci en premier). Détail de
> conception : `specifications/07-roadmap.md` §10.9.

- **Problème** : pas de type d'attribut pour une liste de valeurs fixes
  (ex. statut, priorité d'un workflow type ticket) — `tocheck.md` #18.
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.9 (pas de
  duplication du contenu ici) — nouveau type `select` dans l'enum
  `attributes[].type`, champ `values` sur la définition d'attribut,
  validation serveur d'appartenance, rendu `<select>` dédié dans
  `NavigationPage.tsx`.
- **Effort** : faible (cohérent avec la difficulté 2/5 de `tocheck.md`
  #18 — nouveau type simple, pas de nouvelle colonne, pas de
  chiffrement ni de brique d'exécution associée).
- **Fichiers** : `specifications/07-roadmap.md` (§10.9, conception déjà
  écrite) ; fichiers d'implémentation réels à déterminer à
  l'implémentation (rien n'est codé).
- **Statut** : ✅ fait (2026-11-22, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Livré en 2 itérations (1 correction suite
  revue croisée).

  **Itération 1** : implémentation initiale — `model/schema.json` (ajout
  `"select"` à l'enum `attributes[].type`, nouveau champ `values`,
  restructuration de l'`if`/`then` unique en `allOf` à 2 branches :
  branche `joint-1-1`/`joint-1-n` → `classes` inchangée, branche
  `select` → `values` nouvelle), `backend/routes_write.py`
  (`_coerce_typed_value` : nouveau bloc de validation d'appartenance à
  `values`, `abort(400)` sinon, stockage en `value_string`),
  `frontend/src/types.ts` (type élargi + `values?: string[]`),
  `frontend/src/pages/NavigationPage.tsx` (branche `<select>` dans le
  formulaire modal d'édition/création). Nouveau fichier de test
  `backend/test_attribute_type_select.py`.

  **Itération 2**, suite à revue croisée (pessimiste/candide, gap
  confirmé indépendamment par les deux, vérifié par l'orchestrateur dans
  le code avant correction) : l'édition inline de cellule dans
  `frontend/src/pages/NavigationPage.tsx` tombait dans le champ texte
  générique au lieu du `<select>` — ajout d'une branche `<select>`
  dédiée pour l'édition inline de cellule.

  **Tests** : suite backend complète — **202/202 passés**, dont 9
  nouveaux tests select (valeur autorisée acceptée, valeur hors liste
  rejetée en 400, `schema.json` valide Draft7, `select` sans `values`
  rejeté par le schema, `joint-1-1` sans `classes` toujours rejeté —
  non-régression de la restructuration `allOf`, string simple toujours
  accepté). `model/schema.json` validé aussi contre les fichiers modèle
  réels existants (aucune régression). Import backend propre, `docker
  compose config` OK.

  **Limite connue documentée** : pas de typecheck/build frontend
  automatisé exécuté (contrainte d'environnement sandbox, pas d'accès à
  un `node_modules`/conteneur frontend démarré) — relecture manuelle du
  JSX acceptée à la place, cohérent avec le précédent déjà posé aux
  actions 3/4 (pas de suite de tests frontend automatisée dans ce
  projet).

  **Point ouvert non traité, volontairement hors scope** (déjà signalé
  en conception §10.9 de `specifications/07-roadmap.md`) : valeurs
  orphelines si `values` est modifié/réduit après coup sur un attribut
  déjà utilisé — aucune migration automatique.

  **Gap mineur accepté sans correction** (cohérent avec le précédent
  file/image/csv des actions 3/4) : `ConfigurationPage.tsx` (IHM d'admin
  du modèle) n'ajoute pas `select` à sa liste de types gérés à la
  création d'attribut.

## 8. [Nouvelle fonctionnalité] Type d'attribut secret/password

> Choix utilisateur du 2026-11-22 parmi les idées de `tocheck.md`, par
> ordre de priorité explicite (priorité 2). Détail de conception :
> `specifications/07-roadmap.md` §10.10.

- **Problème** : pas de type d'attribut pour une valeur sensible
  (mot de passe, secret) — `tocheck.md` #19.
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.10 (pas de
  duplication du contenu ici). Rappel : le chiffrement réel (algo, clé,
  masquage à l'affichage) reste à trancher — ce n'est pas qu'un
  masquage UI, plusieurs points ⚠️ restent ouverts dans la conception.
- **Effort** : faible à moyen (difficulté 2/5 affichée dans `tocheck.md`
  #19, mais incertitude explicite liée au chiffrement réel et à la
  gestion de clé, non encore tranchés — effort réel potentiellement
  supérieur à l'estimation initiale).
- **Fichiers** : `specifications/07-roadmap.md` (§10.10, conception déjà
  écrite) ; fichiers d'implémentation réels à déterminer à
  l'implémentation (rien n'est codé).
- **Statut** : ✅ fait (2026-11-22, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Livré en 2 itérations (1 correction suite
  revue croisée).

  **Conception tranchée par l'utilisateur le 2026-11-22**, 3 points :
  clé de chiffrement Fernet globale via la variable d'environnement
  `SECRET_ENCRYPTION_KEY`, lue dynamiquement (pas de cache en mémoire
  figé au démarrage) ; masquage strict en lecture générique (toute
  lecture standard renvoie une valeur masquée, jamais le plaintext ni le
  ciphertext) accompagné d'une route reveal dédiée réservée
  global-admin uniquement ; écriture via JSON classique (pas de route
  dédiée), chiffrement effectué côté `_coerce_typed_value`.

  **Itération 1** : implémentation initiale — `model/schema.json` (ajout
  `"secret"` à l'enum `attributes[].type`), nouveau `backend/secret_crypto.py`
  (chiffrement/déchiffrement Fernet, lecture dynamique de
  `SECRET_ENCRYPTION_KEY`), `backend/routes_write.py`
  (`_coerce_typed_value` : chiffrement de la valeur avant stockage en
  `value_string`), `backend/routes_read.py` (masquage générique en
  lecture), `backend/auth.py` (garde global-admin pour la route reveal),
  `docker-compose.yml` (variable d'environnement `SECRET_ENCRYPTION_KEY`),
  `frontend/src/pages/NavigationPage.tsx` (rendu masqué + action reveal),
  `frontend/src/types.ts` (type élargi). Nouveau fichier de test
  `backend/test_attribute_type_secret.py`, 17 tests.

  **Itération 2**, suite à revue croisée (pessimiste/candide, point
  bloquant confirmé) : la route `PUT
  /api/write/attribute/<cls>/<id>/<attribute>/<value>` n'excluait pas
  `secret` du tuple de types bloqués en écriture via URL-path, alors que
  `file`/`image`/`csv` l'étaient déjà — risque de fuite du plaintext dans
  des logs d'accès proxy/APM via l'URL (pas un défaut de chiffrement DB).
  Fix : `secret` ajouté au garde-fou, `abort(400)` avec message dédié.
  Test ajouté.

  **Tests** : suite backend complète — **235/235 passés**.

  **Preuve bout en bout réelle** (`testeur-global`, docker-compose) :
  objet créé avec un secret réel, valeur en DB chiffrée Fernet
  (`gAAAAA...`), jamais le plaintext ; masquage en lecture générique
  confirmé ; route reveal fonctionnelle réservée global-admin ; 401 sans
  token ; écriture via URL PUT bloquée en 400.

  **Limite connue acceptée, documentée, non corrigée** (décision
  orchestrateur) : aucune voie API pour effacer/fermer explicitement un
  attribut `secret` existant — l'omission ne ferme jamais un secret par
  garde-fou volontaire, une valeur vide serait chiffrée et stockée comme
  active, pas comme une fermeture. À traiter dans une action future si
  besoin.

## 9. [Nouvelle fonctionnalité] Type d'attribut datasource

> Choix utilisateur du 2026-11-22 parmi les idées de `tocheck.md`, par
> ordre de priorité explicite (priorité 3). Détail de conception :
> `specifications/07-roadmap.md` §10.11.

- **Problème** : pas de type d'attribut porté par une définition JSON +
  meta-class (ex. Prometheus, PostgreSQL) — `tocheck.md` #1.
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.11 (pas de
  duplication du contenu ici). Lien prérequis noté : `tocheck.md` cite
  cette idée comme prérequis conceptuel des idées ML/ingestion #2/#6/
  #7/#8 — non engagées, non conçues ici, simple rappel de dépendance
  future.
- **Effort** : moyen (difficulté 3/5 dans `tocheck.md` #1, nouveau type
  + champ structuré de définition de connexion, point ouvert sur
  meta-class dédiée vs blob JSON).
- **Fichiers** : `specifications/07-roadmap.md` (§10.11, conception déjà
  écrite) ; fichiers d'implémentation réels à déterminer à
  l'implémentation (rien n'est codé).
- **Statut** : ✅ fait (2026-11-22, `worker`). Décision utilisateur du
  2026-11-22 tranchant le point ⚠️ ouvert de §10.11 : meta-classe dédiée
  par type de datasource (ex. `datasource_prometheus`), réutilisant le
  modèle objet dynamique existant (classes/attributs `model/*.json`,
  RBAC tenant, historisation `attribute_value`) — jamais un blob JSON
  opaque dans la définition d'attribut. Livré en 1 itération.

  **Fichiers touchés** : `model/schema.json` (nouveau type `"datasource"`
  dans l'enum `attributes[].type` ; champ `classes` — déjà requis pour
  `joint-1-1`/`joint-1-n` — réutilisé tel quel pour lister les classes
  `datasource_*` autorisées par l'attribut, restructuration `allOf`
  étendue à 3 branches plutôt qu'une 3e couple if/then séparé) ;
  `model/datasource.json` (nouveau fichier, meta-classe de démo
  `datasource` avec une seule classe `datasource_prometheus`, attributs
  `url`/`query` string, aucun champ credential/secret) ;
  `backend/routes_write.py` (`_coerce_typed_value` : nouveau bloc
  `datasource`, format = identifiant entier, stocké en `value_string`
  jamais `joint_id` ; `_apply_attribute_diff` : nouveau bloc de
  validation de cible dans la boucle d'insertion — existence + non
  supprimée, classe cible appartenant à `attr_def["classes"]`, et
  périmètre tenant de l'acteur courant pour un tenant-admin — `abort(400)`
  sur cible inexistante/mauvaise classe, `abort(403)` sur dépassement de
  périmètre tenant) ; `frontend/src/types.ts` (type élargi +
  commentaire `classes` mis à jour) ; `frontend/src/pages/
  NavigationPage.tsx` (branche `datasource` dans le formulaire modal
  création/édition — sélecteur d'objet cible via `getCandidates`/
  `getCandidateLabel`, valeur gérée comme un attribut scalaire ordinaire
  dans `newAttrs`, jamais dans `jointValues` — ET dans l'édition inline
  de cellule, `handleCellClick` + nouvelle branche de rendu dédiée dans
  le tableau, **en explicitant ce second point dès ce premier passage**
  pour ne pas reproduire l'oubli de l'action 7 ; affichage en lecture
  réutilise `formatValue` en ré-enveloppant la chaîne stockée dans
  `{joint_id}` ; `loadCandidatesForDef` étendu pour précharger les
  labels des objets `datasource_*` candidats). Nouveau fichier de test
  `backend/test_attribute_type_datasource.py` ; `backend/
  test_model_driven_typing.py` (nouvelle branche SQL `FakeCursor` pour
  `SELECT class, tenants, deleted_at FROM object WHERE id`, infra de
  test partagée).

  **Choix de conception** : valeur reçue en écriture = identifiant
  d'objet brut (entier ou chaîne numérique), jamais enveloppée dans
  `{'joint_id': ...}` comme `joint-1-1` — le stockage physique est
  `value_string` (jamais la colonne `joint_id`), donc en lecture la
  valeur ressort telle quelle (chaîne), pas un objet `{joint_id}`. Ce
  choix garde `datasource` symétrique en écriture/lecture et permet de
  réutiliser tel quel `write_attribute_value` (édition inline via URL)
  sans la complication du format dict réservée à la colonne physique
  `joint_id`.

  **Incertitude signalée** : la consigne initiale supposait que
  `joint-1-1` empêche déjà l'écriture d'une jointure vers un objet hors
  du tenant courant ou vers un objet d'une classe non listée dans son
  champ `classes` — vérifié faux à la lecture du code
  (`_apply_attribute_diff` ne vérifie pour `joint_id` que l'existence et
  la non-suppression de la cible, jamais sa classe ni son tenant ;
  confirmé par `test_delete_object_cascade_scoped_to_tenant_for_tenant_admin`
  dans `backend/test_model_driven_typing.py`, qui crée sans rejet une
  jointure `tenant2` → objet `tenant1`). `datasource` va donc plus loin
  que `joint-1-1` sur ce point (validation classe + tenant ajoutée,
  demandée explicitement par cette action), au prix d'une incohérence
  assumée entre les deux types le temps qu'un futur correctif
  éventuel de `joint-1-1` (hors scope ici) aligne les deux.

  **Tests** : suite backend complète — **214/214 passés**, dont 12
  nouveaux tests datasource (round-trip création/lecture en
  `value_string`, rejet 400 cible inexistante, rejet 400 mauvaise classe
  cible, rejet 403 cible hors périmètre tenant pour un tenant-admin,
  acceptation pour la même cible en global-admin et en tenant propre,
  mêmes cas rejoués via `write_attribute_value` (édition inline, URL),
  rejet 400 valeur non entière, `schema.json` valide Draft7, règle
  `allOf` `classes` requis/accepté pour `datasource`). `model/schema.json`
  revalidé aussi contre tous les fichiers modèle réels existants,
  `model/datasource.json` inclus (aucune régression). Import backend
  propre, `docker compose config` OK.

  **Limite connue documentée** : pas de typecheck/build frontend
  automatisé exécuté (même contrainte d'environnement sandbox que les
  actions 3/4/7) — relecture manuelle du JSX acceptée à la place.

  **Report explicite** (périmètre de cette action, cf. consigne) :
  aucun champ credential/secret/username/password sur
  `datasource_prometheus` — l'action 8 (type `secret`/`password`) n'est
  pas faite ; le jour où une meta-classe `datasource_*` a besoin
  d'identifiants de connexion, ce champ devra utiliser le type `secret`
  de l'action 8 une fois livré, en cohérence avec §10.10, jamais un
  champ texte en clair. Aucun câblage d'exécution de requête (pas de
  route interrogeant Prometheus) : uniquement le type, la référence, et
  la meta-classe de démo, comme demandé.

  **Gap mineur accepté sans correction** (cohérent avec le précédent
  file/image/csv/select des actions 3/4/7) : `ConfigurationPage.tsx`
  (IHM d'admin du modèle) n'ajoute pas `datasource` à sa liste de types
  gérés à la création d'attribut (`ATTR_TYPES`).

  **Itération 2** (2026-11-22, `worker`), suite revue croisée
  pessimiste — 2 corrections sur `backend/routes_write.py` :
  (a) **bloquant** — `delete_object` ne fermait aucune valeur `attribute_value`
  pointant (en `datasource`) vers l'objet supprimé : cascade ajoutée
  (recherche `value_string = str(object_id)` sur attributs actifs,
  filtrée tenant comme pour `joint_id`, revalidée via l'`attr_def` réel —
  ferme uniquement si type `datasource` et classe source dans
  `attr_def["classes"]`) ; (b) mineur — garde `isinstance(..., float) and
  not .is_integer()` → 400 ajoutée, alignée sur `joint-1-1`. 3 tests
  ajoutés dans `test_attribute_type_datasource.py`. Fix connexe découvert
  en cours : `test_model_driven_typing.py` (`FakeCursor` partagé)
  reconnaît désormais aussi la requête SQL de cascade (10 tests cassés
  par la nouvelle requête, réparés par l'ajout d'une branche, aucun des
  10 n'avait de rapport avec le comportement testé lui-même).

  **Tests finaux** : suite complète **217/217 passés** (214 + 3), suite
  rejouée et reconfirmée manuellement a posteriori (2026-11-22, agent
  top-level, hors cycle orchestrateur — voir note ci-dessous) :
  `SCHEMA_PATH=.../model/schema.json .venv/bin/pytest backend/ -q` →
  217/217 ; `docker compose config` OK.

  **Note de suivi** : l'itération 2 a été dispatchée et confirmée
  fonctionnelle (testeur), mais le cycle orchestrateur ne m'a jamais
  renvoyé la confirmation finale pessimiste/candide + `testeur-global`
  sur cette itération précise avant de s'arrêter silencieusement — à
  l'inverse des actions 1-8 précédentes. Code/tests revérifiés
  manuellement comme ci-dessus (217/217, config OK), mais pas de second
  regard croisé formel sur l'itération 2 à ce jour. Cause probable : les
  garde-fous ajoutés en cours de session aux `.claude/agents/*.md`
  (clôture du Statut uniquement après `testeur-global` vert) ne
  s'appliquent qu'aux agents lancés après l'édition des fichiers, pas à
  une instance déjà en cours d'exécution.

  **Travail additionnel direct (2026-11-22, agent top-level, hors cycle
  orchestrateur)**, suite à demande utilisateur de peupler la DB réelle
  et d'affiner le modèle :
  - `model/datasource.json` scindé : `datasource_prometheus` (`url`
    seul) et nouvelle classe `query` (`name`/`expression` +
    `joint-1-1` vers `datasource_prometheus`) — une datasource et une
    requête sont deux concepts distincts, la requête référence sa
    datasource (demande utilisateur explicite).
  - `model/itil_cmdb.json` : `serveur.monitoring` (type `datasource`)
    retargeté de `datasource_prometheus` vers `query` (pointer vers la
    requête à afficher, pas la connexion brute).
  - Objets réels créés dans la DB (volontairement conservés, pas de
    cleanup — cf. garde-fou `testeur`/`testeur-global` mis à jour) :
    `datasource_prometheus` #129 (`url=http://prometheus:9090`), `query`
    #134 (`expression=rate(node_cpu_seconds_total{...}[1m])`,
    `datasource→129`), `serveur` #130 (`monitoring→134`), `ticket` #131
    (`statut=ouvert`, `priorite=haute`, démontre le type `select` de
    l'action 7).
  - Validé : `jsonschema` sur les 2 fichiers modifiés, round-trip
    `/api/init` + `/api/write/object` + `/api/read/object` réel via
    token Keycloak (`testuser`/global-admin), lecture confirmant la
    chaîne serveur→query→datasource.
  - **Pas encore passé par pessimiste/candide** (changement de modèle
    direct, hors cycle orchestrateur) — à challenger si besoin.

## 10. [Nouvelle fonctionnalité] Framework de dashboard/affichage configurable

> Choix utilisateur du 2026-11-22 parmi les idées de `tocheck.md`, par
> ordre de priorité explicite (priorité 4). Détail de conception :
> `specifications/07-roadmap.md` §10.12.

- **Problème** : pas de framework de dashboard/tabs configurables dans
  l'IHM — `tocheck.md` #9, qualifié explicitement de « gros chantier
  frontend, à découper en sous-actions ».
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.12 (pas de
  duplication du contenu ici — découpage proposé 10a-10e). Cette action
  10 ne sera **pas** implémentée telle quelle : elle sera probablement
  scindée en actions 10a/10b/... une fois le découpage §10.12 validé/
  affiné.
- **Effort** : élevé (difficulté 5/4 dans `tocheck.md` #9 — gros
  chantier frontend, portée volontairement non détaillée ici en
  attendant la validation du découpage).
- **Fichiers** : `specifications/07-roadmap.md` (§10.12, découpage déjà
  écrit) ; fichiers d'implémentation réels à déterminer à
  l'implémentation (rien n'est codé).
- **Statut** : 🔀 scindée (2026-11-22) — voir note ci-dessous et actions
  10a-10d. N'est plus directement actionnable telle quelle.

> **Scission actée** (2026-11-22) : découpage §10.12 validé. Cette
> action 10 est scindée en **10a** (modèle de données dashboard/tab),
> **10b** (IHM lecture seule), **10c** (édition CRUD des tabs), **10d**
> (sélection des sous-objets par tab/filtre). **10e** du découpage
> §10.12 reste **exclu, hors scope** (dépend d'une idée future,
> `tocheck.md` #10). Voir les 4 actions dédiées ci-dessous.

## 10a. [Nouvelle fonctionnalité] Modèle de données dashboard/tab configurable

> Sous-action issue de la scission de l'action 10 (§10.12 `specifications/
> 07-roadmap.md`, validée le 2026-11-22). Détail de conception : même
> section §10.12.

- **Problème** : pas de modèle de données pour stocker la configuration
  d'un dashboard/tab — préalable à toute IHM (10b/10c/10d).
- **Correctif** : réutilisation du modèle dynamique existant (principe
  déjà en place pour toutes les autres meta-classes du projet, ex.
  action 9 `datasource`) — nouvelle meta-classe `dashboard` (fichier
  `model/dashboard.json`), **pas** de table applicative dédiée. Deux
  classes : `dashboard` (attribut `name`) et `tab` (attributs `name`,
  `dashboard` en `joint-1-1` vers la classe `dashboard`,
  `target_meta_class` **et** `target_class` en `string` libres décrivant
  la meta-classe et la classe précise à afficher — deux champs, pas un
  seul, car une meta-classe peut porter plusieurs classes (ex. `cmdb` :
  7 classes, `datasource` : 2) et `target_meta_class` seul ne suffirait
  pas à désambiguïser laquelle afficher ; pas encore de rendu ni de
  filtre, cf. 10d. Même principe à retenir si la question se repose
  pour l'action 11 (stockage de la config de binding).
- **Effort** : faible/moyen (un seul fichier modèle, pas de code
  backend nouveau, pattern déjà connu).
- **Fichiers** : `model/dashboard.json`.
- **Statut** : ✅ fait (2026-11-22, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Meta-classe `dashboard` créée (classes
  `dashboard`/`tab`), validée contre `model/schema.json`
  (`jsonschema.Draft7Validator`), aucun code backend nécessaire ni
  touché — confirmé par grep exhaustif (`routes_init.py` charge tout
  `model/*.json` de façon générique, aucune whitelist/blacklist de
  meta-classe). `target_class` ajouté en cours de revue (candide +
  pessimiste ont indépendamment signalé que `target_meta_class` seul
  était insuffisant pour désambiguïser une meta-classe à plusieurs
  classes). Tests : suite complète 235/235 ; round-trip réel via l'API
  (pas que pytest) — objet `dashboard` #149 (`name=Monitoring`) et objet
  `tab` #151 (`name=Serveurs`, `dashboard` → joint-1-1 vers #149,
  `target_meta_class=datasource`, `target_class=datasource_prometheus`)
  créés et relus correctement, apparition confirmée dans `loaded` après
  `/api/init` ; objets laissés en DB (démo/référence, pas de cleanup).
  `testeur-global` : stack up, aucune régression.

## 10b. [Nouvelle fonctionnalité] IHM lecture seule d'un dashboard existant

> Sous-action issue de la scission de l'action 10 (§10.12), dépend de
> 10a.

- **Problème** : aucun rendu frontend d'une configuration dashboard/tab,
  même statique.
- **Correctif** : rendu en lecture seule, dans l'IHM, d'un dashboard et
  de ses tabs déjà présents en base (config créée manuellement via les
  routes génériques d'objets) — pas d'édition, pas de sélection de
  sous-objets dynamique (10c/10d).
- **Effort** : moyen à élevé (nouveau frontend, dépend de 10a livré).
- **Fichiers** : `frontend/src/` (composants à déterminer à
  l'implémentation).
- **Statut** : ✅ fait (2026-11-22, 2 itérations). Fichiers :
  nouveau `frontend/src/pages/DashboardPage.tsx` (page top-level lecture
  seule, liste les dashboards via `apiReadObjects`/`apiReadObject`
  génériques — pas de nouvelle route backend), câblage
  `frontend/src/components/Navbar.tsx` (nouveau bouton "Dashboard",
  sans gating RBAC, cohérent avec le bouton "Diagramme" existant),
  `frontend/src/App.tsx` (nouvelle branche de rendu),
  `frontend/src/components/Sidebar.tsx` (1 ligne de type élargie,
  déviation de périmètre signalée par le worker et jugée acceptable par
  l'orchestrateur — pure signature TS, aucune logique nouvelle).
  Logique : auto-sélection si un seul dashboard, sélecteur si
  plusieurs, état vide si aucun ; tabs d'un dashboard retrouvés par
  filtre côté client sur l'attribut joint-1-1 `dashboard` (même
  principe que `getParentIds`/`resolveDisplayName` de
  `NavigationPage.tsx`, réimplémenté localement, composant
  indépendant) ; tab actif affiche `target_class`/`target_meta_class`
  en texte brut, aucun chargement des objets de la classe cible (hors
  scope, action 10d) ; aucun appel write/delete (lecture seule
  stricte). Itération 1 (worker) : implémentation initiale + build vite
  (591 modules, 0 erreur) + test manuel réel via CDP headless chrome
  sur la stack docker-compose vivante (login testuser/testuser123,
  dashboard #149 Monitoring + tab #151 Serveurs,
  target_meta_class=datasource/target_class=datasource_prometheus,
  rendu correct). `testeur` (itération 1) : 7/7 PASS — build, grep
  absence write/delete, cas nominal #149/#151, cas limite dashboard
  orphelin #138/tab #140 (sans attribut target_class, objet pré-10a)
  sans crash ni erreur console. `candide` : convergence totale avec
  l'implémentation (même choix structurants : page top-level, pas de
  nouvelle route, filtre client par joint_id, gestion de l'attribut
  absent) — aucun angle mort trouvé, divergences relevées purement
  cosmétiques sans impact. `pessimiste` (itération 1) : 1 point
  bloquant confirmé — `DashboardPage.tsx` utilisait `Promise.all` (pas
  `Promise.allSettled`) pour charger le détail de tous les
  dashboards/tabs ; un seul objet en échec (ex. suppression
  concurrente) faisait planter TOUTE la page via le `catch`/`setError`
  global, alors que `NavigationPage.tsx` utilise `Promise.allSettled` à
  6 endroits précisément pour éviter ce cas. Point non bloquant noté
  comme limite connue : chargement de TOUS les dashboards/tabs du
  système sans narrowing (contrairement à `NavigationPage.tsx` qui
  filtre par sidebar) — coût non borné si le volume grossit, acceptable
  au volume actuel, limite documentée (pattern déjà vu aux actions
  3/4/7/9/13). Itération 2 (worker, fix ciblé) : remplacement des 2
  `Promise.all` par `Promise.allSettled` + filtre `status ===
  'fulfilled'` (objets en échec ignorés silencieusement, catch global
  réservé à l'échec de `apiReadObjects()` seul) — pattern aligné sur
  `NavigationPage.tsx`. Build vite re-confirmé (0 erreur),
  non-régression cas nominal #149/#151 reconfirmée en réel. `testeur`
  (retest itération 2) : 5/5 PASS (build, cas nominal via curl
  authentifié, cas limite orphelin, absence write/delete) ; simulation
  réelle d'un échec individuel d'objet non testable (CDP bloqué par le
  sandbox cette fois, sans lien avec la stack), tranchée par relecture
  de code (non ambiguë : `allSettled` + filtre `fulfilled` + catch
  externe isolé = propagation impossible). `pessimiste` (revalidation) :
  fix confirmé correct, plus bloquant, aucun nouveau problème
  introduit. `testeur-global` : OK — 234/235 pytest backend (1 échec
  pré-existant hors scope, `test_file_attribute_type.py`,
  posix/windows backslash, fichier non touché par 10b) ; build
  frontend : les 4 fichiers de l'action 10b compilent sans erreur, 3
  erreurs TS pré-existantes dans `DiagramPage.tsx` déjà documentées
  (ligne ~1339 du plan, non liées à 10b) ; dashboard bout-en-bout
  confirmé via API réelle (objets #138/#140/#149/#151), endpoints
  voisins non régressés, Keycloak/Prometheus up.

## 10c. [Nouvelle fonctionnalité] Édition des tabs dans l'IHM

> Sous-action issue de la scission de l'action 10 (§10.12), dépend de
> 10a/10b.

- **Problème** : pas de CRUD de la configuration dashboard/tab dans
  l'IHM, seule la création manuelle d'objets via les routes génériques
  est possible.
- **Correctif** : écrans d'édition (création/modification/suppression)
  des tabs d'un dashboard, au-dessus du rendu lecture seule de 10b.
- **Effort** : moyen à élevé (nouveau frontend, formulaires CRUD).
- **Fichiers** : `frontend/src/` (composants à déterminer à
  l'implémentation).
- **Statut** : ✅ fait (2026-11-22, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Livré en 2 itérations (1 correction
  bloquante suite revue croisée). Itération 1 : CRUD ajouté dans
  `frontend/src/pages/DashboardPage.tsx` (passé de ~177 à ~300 lignes,
  tout en un seul composant, pas de sous-composant dédié) au-dessus du
  rendu lecture seule existant (10b) : nouvelle prop `readOnly: boolean`
  câblée depuis `frontend/src/App.tsx` (1 ligne, même pattern que
  `NavigationPage`/`DiagramPage`), toutes les sections de mutation
  cachées (pas juste désactivées) sous `{!readOnly && (...)}` ;
  création dashboard (name) via `apiWriteObject` ; création/édition de
  tab (name/target_meta_class/target_class, `dashboard` en
  `{joint_id:...}`) via `apiWriteObject`, champs texte vides omis du
  payload (convention `NavigationPage.tsx` : un attribut omis ferme la
  valeur active côté serveur) ; suppression de tab via
  `window.confirm` + `apiDeleteObject` ; `loadData()` extrait du
  montage initial pour être réutilisé après chaque mutation, mécanisme
  `Promise.allSettled` de 10b préservé (pas de régression vers
  `Promise.all`) ; état `mutationError` dédié et transitoire, distinct
  de l'erreur de chargement initial, jamais avalé silencieusement. Pas
  de CRUD de dashboard au-delà de la création (modifier/supprimer un
  dashboard hors scope de cette action). Pas de nouvelle route backend
  (routes génériques `/api/write/object`, `/api/delete/object/<id>`
  réutilisées, cohérent avec 10a/10b). Pas de branche à ajouter dans
  `NavigationPage.tsx` (convention inline-edit des actions 7/9/13 jugée
  non pertinente ici : `DashboardPage` a son propre rendu
  pills/formulaire dédié, pas le tableau générique d'attributs).
  Bug bloquant trouvé en revue croisée (pessimiste), confirmé par
  l'orchestrateur en lecture de code : `handleSaveTab` lisait
  `selectedDashboardId` (state live) au lieu d'un snapshot pris à
  l'ouverture du formulaire — changer le `<select>` Dashboard pendant
  qu'un formulaire d'édition de tab restait ouvert reparentait
  silencieusement ce tab vers le mauvais dashboard à l'enregistrement,
  sans confirmation ni avertissement. Itération 2 (fix) :
  `TabFormState` porte désormais `dashboardId: number`, snapshoté à
  l'ouverture du formulaire (création : depuis `selectedDashboardId` ;
  édition : depuis l'attribut `dashboard` du tab lui-même, plus
  robuste) ; `handleSaveTab` utilise exclusivement
  `tabForm.dashboardId`, plus jamais le state live ; un `useEffect` sur
  `selectedDashboardId` ferme automatiquement le formulaire ouvert si
  la sélection de dashboard change (skip du montage initial) ; un clic
  sur une pill d'un autre tab ferme aussi le formulaire d'édition en
  cours s'il ne correspond pas au tab cliqué. Revalidé PASS par testeur
  et pessimiste (double verrou confirmé, scénario d'attaque original
  rejoué impossible). Tests : build frontend (`tsc -b`/`vite build`,
  591 modules, 0 nouvelle erreur, 3 erreurs TS pré-existantes dans
  `DiagramPage.tsx` sans rapport) ; CRUD réel testé contre la stack
  docker-compose vivante (`testuser`/`testuser123`) — création/édition/
  suppression de tab et de dashboard round-trip confirmées via API
  réelle, scénario du bug reparentage rejoué et confirmé résolu après
  fix ; objets de démo `#138`/`#140`/`#149`/`#151` (actions 10a/10b)
  confirmés inchangés après tous les tests. `testeur-global` : OK —
  suite backend 235/235 (aucun fichier backend touché par cette
  action), build frontend conforme, stack 6 services up, endpoints
  voisins non régressés, démo intacte. 4 points mineurs relevés en
  revalidation (pessimiste), non corrigés, dette acceptée (cohérent
  avec le seuil déjà posé aux actions 7/9/13) : (1) le `useEffect` de
  fermeture auto du formulaire sur changement de dashboard peut faire
  perdre une saisie en cours sans avertissement (UX régressive mais pas
  de corruption de données, préférable au bug corrigé) ; (2) le ref de
  skip du premier rendu (`firstDashboardRenderRef`) n'est fiable que
  parce que `selectedDashboardId` démarre à `null` et que
  l'auto-sélection survient après un `await` — latent, pas actif, à
  revoir si une future init synchrone non-null est introduite ; (3) le
  clic sur une pill d'un autre tab ne ferme le formulaire que si
  `tabForm.mode === 'edit'`, le mode `'create'` reste ouvert au
  changement de tab sélectionné (sans risque car le dashboard ne change
  pas dans ce cas, juste une incohérence visuelle mineure) ; (4)
  `mutationError` n'est pas réinitialisé quand le formulaire se ferme
  automatiquement (effet secondaire cosmétique : un message d'erreur
  obsolète peut rester affiché). Autres points mineurs acceptés sans
  correction (signalés en revue initiale) : `mountedRef` pas appliqué
  dans `handleCreateDashboard`/`handleSaveTab`/`handleDeleteTab`
  (seulement dans `loadData`) ; pas de bouton d'édition/suppression par
  pill dans la liste des tabs (seulement pour le tab actuellement
  actif, affiché sous le contenu) ; pas de classe CSS `btn-danger`
  dédiée pour "Supprimer" (cohérent avec l'absence de cette classe
  ailleurs dans le projet, style `btn-secondary` réutilisé comme pour
  "Modifier"). Fichiers touchés : `frontend/src/pages/DashboardPage.tsx`
  (seul fichier substantiellement modifié), `frontend/src/App.tsx`
  (1 ligne).

## 10d. [Nouvelle fonctionnalité] Sélection des sous-objets affichés par tab

> Sous-action issue de la scission de l'action 10 (§10.12), dépend de
> 10a/10b/10c.

- **Problème** : `target_meta_class`/`target_class` de 10a ne sont que
  des strings libres — pas de filtre/requête configurable pour choisir
  quels objets afficher dans un tab.
- **Correctif** : mécanisme de sélection/filtre des sous-objets affichés
  (requête configurable sur la meta-classe/classe ciblée), conception
  détaillée à faire au moment de l'implémentation.
- **Effort** : moyen à élevé (nouveau frontend + logique de filtre,
  portée la plus ouverte des 4 sous-actions).
- **Fichiers** : `frontend/src/` et potentiellement `model/dashboard.json`
  (champs supplémentaires sur `tab`, à déterminer à l'implémentation).
- **Statut** : ✅ fait (2026-11-22, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Livré en 2 itérations (1 correction suite
  revue croisée). Conception tranchée par l'orchestrateur (pas de blob
  JSON) : réutilisation du modèle objet dynamique — 2 nouveaux attributs
  string optionnels sur la classe `tab` de `model/dashboard.json` :
  `filter_attribute`/`filter_value` (domaine `affichage`, même pattern
  que `target_meta_class`/`target_class` de 10a : champs scalaires
  séparés plutôt qu'un objet JSON). Filtre volontairement minimal :
  égalité stricte `String(valeur) === filter_value.trim()` après
  extraction de l'id si la valeur est une jointure (`getJointId`), pas
  d'opérateurs (contains/</>), pas de multi-critères. Itération 1 :
  `frontend/src/pages/DashboardPage.tsx` (358→482 lignes) — nouveau
  `useEffect` lazy déclenché par le changement de tab actif
  (`selectedTabId`/`targetMetaClass`/`targetClass`/`filterAttribute`/
  `filterValue`) : charge les colonnes via `apiReadMetaClass(
  target_meta_class)` (attributs déclarés sur `target_class`), charge
  les candidats via `apiReadObjects()` filtré client `meta_class`/
  `class`, puis `apiReadObject` par candidat (`Promise.allSettled`, flag
  `cancelled` local pour ignorer une réponse tardive si le tab change
  entre-temps) — explicitement scopé au tab ACTIF uniquement, jamais
  tous les tabs (pas d'aggravation de la limite connue de 10b/10c sur le
  chargement non borné des dashboards/tabs). Rendu = tableau HTML
  lecture seule (colonnes = attributs de la classe cible, lignes =
  objets candidats après filtre). Formulaire de tab (10c) étendu avec 2
  champs optionnels `filter_attribute`/`filter_value`, convention "vide =
  omis du payload" réutilisée. Revue croisée (pessimiste + candide,
  convergence sur 2 points réels) : (1) filtre sur un attribut jointure
  (`{joint_id}`) ne matchait jamais — `String({joint_id:N})` =
  `"[object Object]"`, candide a noté que `getJointId` existait déjà
  dans le fichier mais n'était pas réutilisé côté comparaison ; (2) un
  attribut `file`/`image`/`csv` de la classe cible s'affichait en texte
  brut (pointeur interne `"<version>:<nom>"` ou `"ref:..."`) dans le
  tableau, contraste avec `NavigationPage.tsx` qui a un rendu dédié pour
  ces types et ne les affiche jamais bruts — `secret` écarté de ce point
  car déjà masqué côté serveur générique (`backend/routes/
  routes_read.py`, `_build_object_payload`, placeholder fixe quel que
  soit l'appelant), confirmé non concerné. Itération 2 (fix, `worker`) :
  filtre réutilise désormais `getJointId(raw)` pour extraire l'id
  jointure avant comparaison, fallback `String(raw)` sinon
  (comportement scalaire inchangé) ; `formatCellValue` reçoit le type de
  l'attribut cible et retourne un placeholder neutre
  (`(fichier — non affiché ici)` / `(image — non affichée ici)` /
  `(csv — non affiché ici)`) pour `file`/`image`/`csv` au lieu du
  pointeur brut. Tests : `jsonschema` sur `model/dashboard.json` modifié
  (Draft7) OK ; build frontend (`tsc -b`/`vite build`) 0 nouvelle erreur
  (3 erreurs TS pré-existantes `DiagramPage.tsx`, sans rapport) ; test
  réel stack docker-compose (`testuser`/`testuser123`) — dashboard #149/
  tab #151 (target_meta_class=datasource, target_class=
  datasource_prometheus) affiche bien l'objet #129
  (`url=http://prometheus:9090`) en tableau ; filtre réel testé avec
  tabs temporaires créés puis nettoyés (ex. ticket statut=ouvert, et
  objet `query` #134 joint vers `datasource_prometheus` #129 via tab de
  test `filter_attribute=datasource`/`filter_value=129` — matche
  correctement après le fix, ne matchait pas avant) ; tab sans
  `target_meta_class`/`target_class` ne crashe pas (message existant
  conservé) ; CRUD 10c (création/édition/suppression de tab) toujours
  fonctionnel avec les 2 nouveaux champs de formulaire ; objets de démo
  #129/#130/#131/#134/#138/#140/#149/#151 inchangés après tous les
  tests. Limites connues documentées, non corrigées (portée
  volontairement minimale du filtre, décision orchestrateur) : (1) un
  attribut `joint-1-n` (multi-valué) n'est testé par le filtre que sur
  sa 1ère valeur (`attr.values[0]`), un objet dont la jointure cible est
  en 2e position ou plus ne matchera jamais — limite déjà présente avant
  le fix du point joint, pas une régression de cette itération,
  maintenant nommée explicitement plutôt que silencieuse ; (2)
  comparaison par égalité de chaîne stricte imparfaite sur un flottant
  (`String(3.0)` donne `"3"`, un filtre saisi littéralement `"3.0"` ne
  matche pas `3`) ; (3) pas de validation croisée de `filter_attribute`
  contre les attributs réels de `target_class` — un nom d'attribut mal
  orthographié donne silencieusement "Aucun objet trouvé",
  indiscernable d'un vrai 0 résultat. `testeur-global` : OK — 235/235
  pytest backend (aucun fichier backend touché par 10d), `model/
  dashboard.json` valide, build frontend 0 nouvelle erreur, stack 6
  services up, `/api/init` 401/200 confirmés, chaîne
  dashboard→tab→datasource confirmée end-to-end au niveau API/données,
  objets de démo tous intacts. Pas de vérification pixel navigateur
  réelle possible (limite d'environnement sandbox déjà actée aux actions
  précédentes), contournée par rejeu de la même logique via appels API
  réels.

## 11. [Nouvelle fonctionnalité] Outil d'ingestion avec binding

> Choix utilisateur du 2026-11-22 parmi les idées de `tocheck.md`, par
> ordre de priorité explicite (priorité 5). Détail de conception :
> `specifications/07-roadmap.md` §10.13.

- **Problème** : pas d'outil générique de mapping champs source →
  attributs — `tocheck.md` #11.
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.13 (pas de
  duplication du contenu ici) — définition d'un mapping/binding,
  réutilisation du type `csv` (§10.8) comme première source possible,
  pas d'exécution/scheduler dans cette action (reste `tocheck.md` #12,
  hors scope).
- **Effort** : élevé (difficulté 4/4 dans `tocheck.md` #11, fondation
  réutilisable, point ouvert sur le stockage de la config de binding).
- **Fichiers** : `specifications/07-roadmap.md` (§10.13, conception déjà
  écrite) ; fichiers d'implémentation réels à déterminer à
  l'implémentation (rien n'est codé).
- **Statut** : ⬜ à faire — priorité 5, choix utilisateur 2026-11-22.

## 12. [Dette technique] Réorganisation de backend/ en packages (auth, data, files, routes, tests)

- **Problème** : `backend/` plat (tous modules Python + tests à la
  racine), charge de lecture/collision élevée pour les futures actions.
  Demande utilisateur du 2026-11-22 : « pour backend faire des
  libs/répertoires : auth, data/files, routes, tests ».
- **Correctif** : déplacement mécanique en 5 packages —
  `backend/auth/` (`auth.py`, `rbac.py`), `backend/data/` (`db.py`),
  `backend/files/` (`file_storage.py`, `file_validation.py`,
  `class_icon.py`), `backend/routes/` (`routes_read.py`,
  `routes_write.py`, `routes_init.py`, `routes_admin.py`,
  `routes_files.py`), `backend/tests/` (tous les `test_*.py`, 11
  fichiers). `backend/app.py` et `backend/secret_crypto.py` restent à
  la racine de `backend/` (`secret_crypto.py` jugé module de
  chiffrement générique, sans lien direct avec un seul des 4
  domaines). Imports internes corrigés vers les nouveaux chemins de
  package (ex. `from files.file_storage import`, `from auth.rbac
  import`, `from data.db import`). Pattern `import app` bare + appel
  `app.get_db()`/`app.get_auth_context()` dans le corps des fonctions
  préservé dans `backend/routes/*.py` (hérité de l'action 1), pour
  compatibilité avec le monkeypatch direct sur `app` utilisé par
  `test_rbac_class_tenant_scope.py`, `test_model_driven_typing.py`,
  `test_purge_action_6_2.py`. Aucun changement requis au Dockerfile
  (`COPY backend/ .` copie tout le dossier, `CMD gunicorn app:app`
  reste valide, `WORKDIR /app` contient directement `auth/`, `data/`,
  `files/`, `routes/`, `app.py` en conteneur). `backend/tests/__init__.py`
  volontairement non créé (non requis par pytest). Commande de test
  inchangée : `SCHEMA_PATH=<chemin absolu>/model/schema.json pytest
  backend/ -v` depuis la racine du repo.
- **Effort** : moyen (déplacement mécanique de ~12 fichiers de code +
  11 fichiers de test en 5 packages, ajustement d'imports, aucune
  nouvelle logique).
- **Fichiers** : `backend/app.py` (imports mis à jour), nouveaux
  `backend/auth/` (`auth.py`, `rbac.py`, `__init__.py`),
  `backend/data/` (`db.py`, `__init__.py`), `backend/files/`
  (`file_storage.py`, `file_validation.py`, `class_icon.py`,
  `__init__.py`), `backend/routes/` (`routes_read.py`,
  `routes_write.py`, `routes_init.py`, `routes_admin.py`,
  `routes_files.py`, `__init__.py`), `backend/tests/` (11 fichiers
  `test_*.py` déplacés).
- **Statut** : ✅ fait (2026-11-22, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Livré en 1 itération (aucune correction
  bloquante remontée). Suite complète : 235/235 avant/après, aucune
  régression de compte. Vérifications croisées (pessimiste + candide,
  convergence totale, aucun point bloquant) : imports internes tous
  corrigés vers les nouveaux chemins de package, aucun import resté
  sur un ancien chemin plat, `__init__.py` cohérents (vides,
  suffisants), rien oublié à la racine de `backend/` selon le mapping
  demandé, `secret_crypto.py` confirmé bien placé. Preuve d'exécution
  réelle (pas seulement `import app`) : chaque Blueprint
  (read/write/init/admin/files) exercé via les tests existants,
  monkeypatchs `get_db`/`get_auth_context` confirmés actifs sur les 3
  fichiers qui en dépendent. Comptage des routes Flask : 25 routes
  applicatives cohérentes avant/après refactor (25 car le dépôt
  incluait déjà, avant ce refactor, la route reveal secret de l'action
  8). `testeur-global` : `docker compose config` OK, rebuild + boot
  réel du conteneur backend confirmé (logs propres, aucun
  ImportError/ModuleNotFoundError, `GET /api/init` répond 401
  applicatif = pile complète fonctionnelle de bout en bout, pas
  seulement le process qui démarre). Point mineur corrigé dans cette
  même clôture : 11 fichiers de `backend/tests/` avaient une
  docstring citant l'ancienne commande d'invocation à chemin plat
  (`pytest backend/test_X.py`), corrigée en `pytest
  backend/tests/test_X.py`. Dette documentaire restante, hors scope
  de cette action (même nature que l'action 6) : `README.md` et
  plusieurs fichiers `specifications/*.md` référencent encore les
  anciens chemins plats des modules backend déplacés — à traiter dans
  une future action de synchronisation documentaire si jugé utile.

## 13. [Dette technique] IHM de configuration : types d'attribut manquants (file/image/csv/select/secret/datasource)

- **Problème** : `frontend/src/pages/ConfigurationPage.tsx` (IHM admin
  de création/édition de classe) limitait `ATTR_TYPES` à 5 types
  (string/integer/float/joint-1-1/joint-1-n) alors que le
  backend/schema supportaient déjà 11 types depuis les actions 3
  (file/image/csv), 7 (select), 8 (secret), 9 (datasource) — gap signalé
  et accepté comme dette mineure à chaque action concernée (cf. notes
  « Gap mineur accepté sans correction » des actions 7 et 9 ci-dessus),
  désormais signalé par l'utilisateur comme un vrai manque à corriger.
- **Correctif** (seul fichier modifié : `ConfigurationPage.tsx`) :
  `ATTR_TYPES` étendu aux 11 types. Colonne « Options » : `datasource`
  réutilise le bloc JSX de sélection de classes cibles déjà utilisé par
  `joint-1-1`/`joint-1-n` (même `attr.classes`, même
  `toggleJointClass`, pas de duplication) ; `select` reçoit un nouvel
  éditeur de chips (`attr.values`, input + bouton Ajouter + suppression
  par chip) ; `csv` reçoit un input pour `attr.separator` (placeholder
  `,`) ; `file`/`image`/`secret` affichent « Aucune option ».
  Initialisation propre des champs au changement de type
  (`patch.classes` pour joint/datasource, `patch.values` pour select).
  `handleSave` nettoie/sérialise `classes` (joint+datasource), `values`
  (select), `separator` (csv si renseigné). Validation front bloquante
  ajoutée (extension jugée légitime en cours de revue) : empêche la
  sauvegarde si joint/datasource a `classes` vide, ou select a `values`
  vide, avec toast d'erreur nommant l'attribut et la classe — comble un
  vrai trou (`model/schema.json` n'impose que la présence de la clé via
  `required`, pas `minItems`, donc un tableau vide passerait la
  validation JSON Schema et planterait plus tard, de façon confuse, à
  la première écriture de valeur).
- **Effort** : faible à moyen (un seul fichier frontend, aucun
  changement backend/schema, réutilisation de JSX existant +
  validation front).
- **Fichiers** : `frontend/src/pages/ConfigurationPage.tsx` (seul
  fichier modifié).
- **Statut** : ✅ fait (2026-11-22, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Livré en 2 itérations (1 correction
  suite revue croisée).

  **Itération 1** : implémentation initiale — `ATTR_TYPES` + colonne
  Options + initialisation des champs + `handleSave` + validation
  front.

  **Itération 2**, suite à revue croisée (bug réel trouvé par
  pessimiste) : le state `selectValueDrafts` (saisie en cours de valeur
  select, indexé par position `classIdx-attrIdx`) se désynchronisait
  silencieusement quand `moveAttribute`/`removeAttribute`/`removeClass`
  changeaient les indices (texte tapé pouvait atterrir sur le mauvais
  attribut après un réordonnancement). Fix : reset de
  `selectValueDrafts` dans ces 3 fonctions. + 2 améliorations mineures :
  toast d'erreur si ajout d'une valeur select déjà présente (au lieu
  d'un no-op silencieux), clé React composite `${v}-${i}` sur les chips
  (robustesse si doublons existants importés via `apiInit`).

  **Validation** : `testeur` (itération 1) — payload des 6 nouveaux
  types testé contre `POST /api/write/metaclass`, tous PASS, confirme
  que la validation front comble un vrai trou backend (schema accepte
  classes/values vides, `write_object` échouerait sinon en 400
  systématique) ; `tsc -b` réel dans le conteneur frontend, zéro erreur
  sur ce fichier. `pessimiste`/`candide` (itération 1) : candide
  converge (diff jugé meilleur que sa propre tentative indépendante) ;
  pessimiste trouve le bug réel ci-dessus + 2 mineurs, tous traités en
  itération 2. `testeur-global` (après itération 2) : OK — stack up,
  backend 25 routes, endpoints 200, HMR propre sur
  `ConfigurationPage.tsx`, diff confirmé couvrir les 3 points de
  désync, 3 erreurs TS pré-existantes dans `DiagramPage.tsx` confirmées
  sans rapport (identique à HEAD, hors de ce diff).

## 14. [Nouvelle fonctionnalité] Layers sur les classes et filtre IHM/diagramme

> Demande utilisateur (2026-11-22) : « analyser l'ajout d'une info layers
> au classe et metaclasse, chaque classe fait partie d'un ou plusieurs
> layers, dans l'ihm on sélectionne les layers avec lesquels on travaille
> pour filtrer, idem pour les diagrammes ». 3 points de conception tranchés
> par l'utilisateur après analyse :
> 1. Classe sans layer (champ absent/vide) = **toujours visible**, quel
>    que soit le filtre actif (même convention que `tenants` — non
>    régressif, aucune classe existante ne disparaît tant que son champ
>    `layers` n'est pas édité).
> 2. Sélection des layers actifs = **persistée en localStorage** (survit
>    à un reload), cohérent avec l'idée de « contexte de travail ».
> 3. Registre des layers = **tag texte libre par classe** (comme
>    `tenants`), **pas** de nouvelle meta-classe dédiée — mais la liste
>    des layers connus (union/déduplication des `layers` de toutes les
>    classes) doit être **visible dans `ConfigurationPage.tsx`**, pas
>    seulement déduite silencieusement côté Sidebar.

- **Problème** : aucune notion de « layer » (calque thématique) sur une
  classe aujourd'hui — pas de moyen de grouper des classes transverses à
  plusieurs meta-classes pour les activer/désactiver ensemble à l'affichage
  (ex. layer « physique », « réseau », « sécurité » dans un CMDB). Le seul
  filtre existant (`Sidebar.tsx`) est mono-sélection `meta_class`/`class`
  (un seul actif à la fois) ; `DiagramPage.tsx` a un filtre par classe
  individuelle (`hiddenClasses`, non persisté, non partagé avec
  `NavigationPage.tsx`).
- **Correctif** :
  1. `model/schema.json` : nouveau champ optionnel `"layers"` (array de
     string) sur une classe, même emplacement/pattern que `tenants`/
     `icon`. Absent/vide = visible quel que soit le filtre layer actif
     (point 1 ci-dessus).
  2. `frontend/src/types.ts` : `ClassDefinition`/`ClassInfo` étendus avec
     `layers?: string[]`.
  3. `frontend/src/pages/ConfigurationPage.tsx` : input texte
     comma-separated pour `layers` sur la classe (même pattern que
     `tenants`, ligne ~447-449) ; **et** affichage de la liste des layers
     connus (union dédupliquée de tous les `layers` de toutes les classes
     du modèle chargé) — en lecture au minimum, pour que l'utilisateur
     voie/réutilise les noms de layers déjà existants au lieu de les
     retaper/fauter.
  4. Nouvel état `selectedLayers` (Set de strings, **multi-sélection** —
     contrairement à `selectedMetaClass`/`selectedClass` qui restent
     mono-sélection), remonté dans `frontend/src/App.tsx`, persisté en
     `localStorage` (lecture au montage, écriture à chaque changement).
     Vide/absent = pas de filtre actif (tous les layers visibles, défaut
     non régressif).
  5. `frontend/src/components/Sidebar.tsx` : nouvelle section de
     sélection des layers (checkboxes ou chips togglables, multi), liste
     déduite dynamiquement des classes chargées (`apiReadClasses()`),
     au-dessus ou en dessous de l'arbre `meta_class`/`class` existant.
  6. `frontend/src/pages/NavigationPage.tsx` : filtre supplémentaire sur
     `selectedLayers` (classe visible si `layers` vide/absent **ou**
     intersection non vide avec `selectedLayers`), appliqué là où la
     liste d'objets est déjà filtrée par meta_class/class.
  7. `frontend/src/pages/DiagramPage.tsx` : même predicate layer ajouté
     dans `filteredObjects` (`useMemo`, à côté de `selectedMetaClass`/
     `selectedClass`/`hiddenClasses` existants).
  8. Aucun changement backend — filtre 100% frontend, pas un mécanisme de
     sécurité/RBAC (contrairement à `tenants`), cohérent avec le filtre
     `meta_class`/`class`/`hiddenClasses` déjà 100% côté client.
  9. Tests : classe sans layer toujours visible quel que soit le filtre ;
     classe avec layer visible seulement si son layer fait partie de
     `selectedLayers` (ou si `selectedLayers` vide) ; persistance
     localStorage (filtre retrouvé après reload) ; non-régression du
     filtre `meta_class`/`class`/`hiddenClasses` existant (orthogonal,
     pas de remplacement) ; `ConfigurationPage.tsx` affiche bien l'union
     dédupliquée des layers de toutes les classes.
- **Effort** : faible à moyen (1 champ de schéma + types + éditeur
  `ConfigurationPage` + nouvel état multi-sélection persisté + 1 section
  Sidebar + 1 predicate dans 2 pages) — aucune nouvelle route backend,
  pattern texte libre déjà éprouvé (`tenants`).
- **Fichiers** : `model/schema.json`, `frontend/src/types.ts`,
  `frontend/src/App.tsx`, `frontend/src/components/Sidebar.tsx`,
  `frontend/src/pages/ConfigurationPage.tsx`,
  `frontend/src/pages/NavigationPage.tsx`,
  `frontend/src/pages/DiagramPage.tsx`.
- **Statut** : ✅ fait (2026-11-22, 2 itérations). Conception tranchée par
  l'utilisateur le 2026-11-22 (3 points, rappelés en tête de section :
  classe sans layer toujours visible, sélection persistée en
  localStorage, registre layers = tag texte libre visible dans
  `ConfigurationPage.tsx`, pas de meta-classe dédiée). Itération 1
  (implémentation worker) : `model/schema.json` (champ `layers` array
  string, pattern `tenants`), `frontend/src/types.ts` (`layers?:
  string[]` sur `ClassDefinition`/`ClassInfo`), `ConfigurationPage.tsx`
  (éditeur comma-separated + carte "Layers connus" union dédupliquée non
  scopée à la meta-classe courante), `App.tsx` (state `selectedLayers:
  Set<string>` persisté localStorage clé
  `miami-vice-selected-layers`), `Sidebar.tsx` (section chips togglables
  multi-sélection), `NavigationPage.tsx` et `DiagramPage.tsx` (predicate
  `isClassVisibleForLayers` ajouté dans le filtre d'objets existant),
  `model/itil_cmdb.json` (layers de test : `datacenter`→physique,
  `serveur`→physique+reseau, `base_de_donnees`→securite). Fix backend
  imprévu (non prévu par le plan initial qui disait "aucun changement
  backend") : `backend/routes/routes_read.py`, 3 routes de lecture
  (`list_classes`, `get_class_by_id`, `get_classes_by_meta_class`) ne
  projetaient pas la clé `layers` du JSONB stocké — persistée en
  écriture mais invisible en lecture. Fix = simple passthrough
  `cls.get("layers")`, même statut que `icon`, zéro RBAC. Itération 2
  (suite arbitrage sur rapport pessimiste) : `NavigationPage.tsx` ligne
  ~334, `filtered` enveloppé dans `useMemo` (deps `objects`/
  `selectedMetaClass`/`selectedClass`/`visibleClasses`/`classes`/
  `selectedLayers`) — régression perf réelle introduite par le nouveau
  `classes.find()` par objet dans le filter, corrigée. Résultats
  testeur (tsc 0 nouvelle erreur, jsonschema 9/9 model/*.json valides,
  API confirme `layers` bien renvoyé par les 3 routes pour les 3
  classes de test, absent=null sans erreur sur les autres), candide
  (convergence totale avec implémentation indépendante, fix backend
  jugé correct et justifié par précédent `icon`), pessimiste (fix
  backend sans risque RBAC vérifié directement dans le code, 3 points
  mineurs dont perf corrigée en itération 2), testeur-global (OK
  complet : build, stack docker-compose, `/api/init`, routes non
  régressées, RBAC tenant testé sans erreur mais sans différenciation
  observable faute de données taguées en base — limite d'environnement,
  pas un défaut de code, bout-en-bout objet créé/relu). Limites connues
  documentées (acceptées, non bloquantes) : Sidebar ne recharge
  `classes` que sur changement de page donc staleness après save sur
  ConfigurationPage tant qu'on ne change pas de page ; predicate
  `isClassVisibleForLayers` dupliqué verbatim dans `NavigationPage.tsx`
  et `DiagramPage.tsx` sans factorisation (pas de convention établie
  dans le projet pour ce cas) ; pas de normalisation de casse sur les
  noms de layers (même risque déjà accepté pour `tenants`) ; RBAC
  tenant différentiel non testé faute de données de test taguées en
  base actuellement.

## 15. [Nouvelle fonctionnalité] Restructuration IHM : menu, Sidebar par layer, filtres texte, combo layers Diagramme

> Demande utilisateur (2026-11-23), 5 points. 4 points de conception
> ambigus tranchés par l'utilisateur après clarification (options
> recommandées retenues) :
> 1. Filtre texte `NavigationPage.tsx` = **une seule case globale** par
>    table de classe (pas une case par colonne) — ligne visible si une
>    de ses cellules contient le texte tapé.
> 2. Sidebar : l'arbre par layer (nouveau) **coexiste** avec l'arbre par
>    meta_class (existant) — rien retiré, section ajoutée en plus.
> 3. Filtre texte Configuration = **le même filtre Sidebar** (point C
>    ci-dessous) — aucune nouvelle liste dédiée dans
>    `ConfigurationPage.tsx`, puisque Sidebar y liste déjà toutes les
>    classes sans filtre meta_class.
> 4. Diagramme : la combo-list de layers **remplace** les chips Sidebar
>    partagées sur cette page uniquement (Sidebar garde ses chips sur
>    Navigation/Configuration).

- **Problème** : 5 demandes UX distinctes constatées à l'usage après
  l'action 14 (layers) :
  1. Menu (`Navbar.tsx`) : Configuration doit être tout à gauche (avant
     Navigation), actuellement 2e bouton après Navigation.
  2. Dashboard (`App.tsx`) : le panneau Sidebar reste affiché (vide de
     sens) sur cette page — pas de meta_class/class/layers pertinent
     puisque `DashboardPage.tsx` ne les consomme pas.
  3. Navigation/Diagramme/Configuration (`Sidebar.tsx`) : l'arbre de
     classes n'est groupé que par meta_class — demande d'un groupement
     supplémentaire par layer (une classe apparaît dans chaque groupe
     layer auquel elle appartient, doublons acceptés), avec repli/
     dépli, replié par défaut.
  4. `NavigationPage.tsx` : aucun moyen de filtrer les lignes d'une
     table de classe par texte libre.
  5. `DiagramPage.tsx` : le filtre layers (chips Sidebar, action 14) doit
     devenir une combo-list dédiée à cette page, dont la sélection narrow
     aussi la liste des classes proposées aux layers sélectionnés.
- **Correctif** :
  1. `frontend/src/components/Navbar.tsx` : réordonner les boutons —
     Configuration en premier (avant Navigation), reste inchangé
     (Diagramme, Dashboard).
  2. `frontend/src/App.tsx` : ne plus rendre `<Sidebar>` ni le bouton
     `sidebar-toggle` quand `page === 'dashboard'` (retrait conditionnel,
     pas juste un `open=false`).
  3. `frontend/src/components/Sidebar.tsx` :
     - Nouvelle section "Par layer" (sous ou à côté de la section
       meta_class existante) : classes groupées par layer (une classe
       apparaît sous chaque layer de `c.layers`, classes sans layer
       absentes de cette section — cohérent avec la convention "absent =
       toujours visible" déjà actée côté filtre, ici c'est un
       regroupement d'affichage, pas un filtre). Clic sur une classe du
       groupe layer = même comportement que clic dans l'arbre meta_class
       (`onSelectMetaClass`/`onSelectClass`).
     - Chaque groupe (meta_class existant ET layer nouveau) repliable/
       dépliable indépendamment, **replié par défaut** (changement de
       comportement : aujourd'hui `selectedMetaClass === mc` pilote
       l'ouverture, à réconcilier avec un état de repli local propre,
       distinct de la sélection active).
     - Nouveau champ texte filtre au-dessus de l'arbre (une seule case,
       cohérent avec le point 1 Navigation) : filtre les classes/
       meta_class affichées par sous-chaîne sur le nom de classe (et/ou
       meta_class), appliqué aux deux arbres (meta_class et layer).
     - Sur la page `diagramme` uniquement (`page === 'diagramme'`) : la
       section chips layers existante (action 14) est remplacée par une
       combo-list (`<select multiple>` ou composant dédié) — la
       sélection pilote `selectedLayers` comme aujourd'hui, et narrow en
       plus l'arbre de classes affiché (meta_class + layer) aux classes
       des layers sélectionnés.
  4. `frontend/src/pages/NavigationPage.tsx` : état de filtre texte par
     groupe de classe affiché (un input par card, au-dessus du
     `<table>`), une ligne visible si une des cellules affichées (ID
     inclus ou non, à trancher à l'implémentation si ambigu) contient le
     texte tapé (insensible à la casse).
  5. Tests : navbar ordre des boutons ; Dashboard sans Sidebar visible
     (et sans bouton toggle) ; Sidebar arbre layer affiche bien les
     doublons, replié par défaut, filtre texte narrow les deux arbres ;
     NavigationPage filtre texte narrow les lignes visibles sans toucher
     aux données chargées ; DiagramPage combo-list remplace bien les
     chips sur cette page uniquement (Navigation/Configuration gardent
     les chips), sélection combo narrow la liste de classes proposée.
- **Effort** : moyen (5 points distincts mais tous frontend, aucun
  changement backend/schema attendu — réorganisation de composants
  existants + ajout d'inputs de filtre, pas de nouvelle donnée modèle).
- **Fichiers** : `frontend/src/components/Navbar.tsx`,
  `frontend/src/App.tsx`, `frontend/src/components/Sidebar.tsx`,
  `frontend/src/pages/NavigationPage.tsx`,
  `frontend/src/pages/DiagramPage.tsx`.
- **Statut** : ✅ fait (2026-11-23, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Implémentation itération 1 : les 5 points
  du correctif appliqués — `Navbar.tsx` (Configuration repositionné en
  premier bouton, masquage tenant-readonly préservé), `App.tsx` (Sidebar
  + bouton toggle retirés du DOM sur page dashboard, condition
  `page !== 'dashboard'`), `Sidebar.tsx` (réécrit, +219 lignes : filtre
  texte unique au-dessus des 2 arbres meta_class+layer, 2 états de repli
  indépendants `expandedMeta`/`expandedLayerGroups` repliés par défaut
  et distincts de la sélection active, nouvel arbre "par layer" avec
  doublons de classe entre groupes layer, classes sans layer absentes
  de cette section, combo `<select multiple>` remplaçant les chips
  uniquement sur page diagramme et narrowant en plus les 2 arbres aux
  layers sélectionnés — classe sans layer restant visible dans ce
  narrow), `NavigationPage.tsx` (filtre texte par groupe/card au-dessus
  du tableau, visible si groupe déplié, matche texte plat de ligne
  incluant l'ID et les valeurs formatées via `formatValue`/
  `parseFilePointer`, sans toucher aux données chargées),
  `specifications/05-frontend.md` §6.1/6.2/6.11/6.12 mis à jour +
  nouvelle §6.13. Itération 2 : fix ciblé suite rapport pessimiste —
  `NavigationPage.tsx` ligne 332, ajout `setGroupFilters({})` dans le
  useEffect de reset sur changement de sélection sidebar (lignes
  309-333), pour éviter qu'un filtre texte résiduel masque silencieusement
  des objets en revenant sur une classe déjà visitée. Limite connue
  assumée (pas une dérive, autorisée explicitement par le plan) : le
  `<select multiple>` natif sur la page Diagramme nécessite Ctrl+clic
  pour sélection multiple, contrairement aux chips ailleurs — ergonomie
  légèrement différente mais le plan autorisait explicitement ce choix
  d'implémentation ("select multiple ou composant dédié"). Résultats
  validation : testeur 13/13 OK (navbar, Sidebar absente dashboard,
  filtre texte 2 arbres, repli indépendant de la sélection, doublons
  multi-layer, exclusivité select-multiple diagramme / chips ailleurs,
  narrow layers, filtre NavigationPage non mutant, specs cohérentes,
  tsc/build/HMR/curl OK) ; pessimiste sans bloquant (1 point mineur réel
  corrigé en itération 2, 1 limite connue acceptée) ; candide convergent,
  juge l'implémentation réelle supérieure à sa propre esquisse sur la
  réutilisation de `formatValue`/`parseFilePointer` dans le filtre ;
  testeur-global OK (build frontend+backend, tsc 0 nouvelle erreur sur
  les 3 préexistantes DiagramPage.tsx, HMR propre, 4 pages SPA
  accessibles, API OK, layers action 14 non régressés).

## 16. [Dette documentaire] Synchronisation specifications/ avec actions 7-14

> Demande utilisateur (2026-11-23) : avant de lancer l'action 15, vérifier
> si `specifications/` est à jour par rapport au plan — constat : seule
> `specifications/07-roadmap.md` (doc de design/décisions) mentionne
> `select`/`secret`/`datasource`/`dashboard`/`layers` ; `03-modele-
> donnees.md`/`04-api-backend.md`/`05-frontend.md`/`02-architecture.md`
> n'ont pas été resynchronisés depuis l'action 6 (2026-11-21, qui ne
> couvrait que les actions 1-5). Même nature que l'action 6, portée
> étendue aux actions 7-14 (select, secret, datasource, dashboard
> 10a-10d, réorganisation backend en packages, IHM ConfigurationPage
> types manquants, layers).
- **Problème** : `specifications/` en retard sur le code réel livré par
  les actions 7 à 14 — à vérifier précisément par relecture du code
  (pas seulement de ce plan) avant de rédiger les corrections, même
  méthode que l'action 6.
- **Correctif** : relecture des fichiers `specifications/*.md` face au
  code réel (`model/schema.json`, `backend/routes/`, `backend/auth/`,
  `backend/data/`, `backend/files/`, `frontend/src/pages/
  ConfigurationPage.tsx`/`NavigationPage.tsx`/`DiagramPage.tsx`/
  `DashboardPage.tsx`, `frontend/src/components/Sidebar.tsx`), mise à
  jour des sections concernées : types `select`/`secret`/`datasource`
  (action 7/8/9), modèle dashboard/tab (action 10a-10d), découpage
  `backend/` en packages (action 12, remplace la description de l'action
  1 qui référence encore l'ancienne structure plate), `ConfigurationPage`
  types d'attribut complets (action 13), champ `layers`/filtre IHM
  (action 14). Dette documentaire déjà notée hors scope à l'action 12
  (README.md + specs référençant encore les anciens chemins plats) — à
  inclure si jugé pertinent dans la même passe.
- **Effort** : faible (doc only, lecture seule du code pour vérifier la
  forme réelle, même méthode éprouvée à l'action 6).
- **Fichiers** : `specifications/02-architecture.md`,
  `specifications/03-modele-donnees.md`,
  `specifications/04-api-backend.md`, `specifications/05-frontend.md`,
  `specifications/07-roadmap.md` (ligne de statut fin de section 10 à
  mettre à jour), `README.md` (si inclus).
- **Statut** : ✅ fait (2026-11-23, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`).
  - Travail repris d'une session parallèle antérieure :
    `specifications/02-architecture.md`, `03-modele-donnees.md`,
    `04-api-backend.md`, `05-frontend.md` déjà modifiés (514 ins/82 del),
    vérifié exact par relecture croisée du code.
  - Complété : 2 chemins obsolètes dans `02-architecture.md`
    (`backend/auth.py`/`backend/rbac.py` → `backend/auth/auth.py`,
    `backend/auth/rbac.py`), `README.md` (vues 3→4 + Dashboard,
    `DashboardPage.tsx` dans l'arbre, mention layers Sidebar, chemins
    tests `backend/tests/`). `specifications/07-roadmap.md` déjà à jour
    par la session parallèle, rien à corriger.
  - Revue croisée (testeur + analyste combiné pessimiste/candide) : 1
    point bloquant trouvé — affirmation fausse répétée « displayname
    jamais renvoyé par l'API » dans `04-api-backend.md` et
    `05-frontend.md`, alors que `backend/routes/routes_read.py:39,82,111`
    le renvoie bien — + 3 points secondaires (contradiction interne
    `03-modele-donnees.md` sur l'existence de `delete_object`,
    contradiction `README.md` 5 vs 11 types d'attribut, comptage routes
    25 vs 24 réel dans `02-architecture.md`). Tous corrigés en 1
    itération.
  - Revalidation ciblée (testeur + analyste) : 4/4 OK, 1 point mineur
    résiduel trouvé — pointeur mort « détail §3.2 ci-dessus » dans
    `03-modele-donnees.md:219`, devait être §3.2ter — corrigé en
    micro-fix.
  - **Testeur-global final : OK** — stack 6 services up, 235/235 pytest
    backend, endpoints 200, frontend servi 200, logs propres. Seul point
    KO relevé (`tsc -b` strict sur `DiagramPage.tsx`) confirmé
    préexistant, hors scope de cette action (aucun fichier de code
    touché).
  - **Décision assumée** : 2 points plus larges de `README.md` (liste
    types d'attribut détaillée ailleurs, pattern URL API) laissés hors
    scope, dette documentaire plus large déjà notée hors scope à
    l'action 12.

## 17. [Nouvelle fonctionnalité] Extension du modèle CMDB embarqué

> Demande utilisateur (2026-11-23) : enrichir le catalogue de
> classes/meta-classes embarquées avant d'attaquer les dashboards —
> compute (baies/clusters/hyperviseurs/OS), applicatif (modules,
> interfaces, flux de données, versioning), réseau (VIP, zones,
> équipements), organisation (société/département/contact unifiés),
> localisation (bâtiment/étage/salle), hardware, et une classe `besoin`
> transverse. Détail de conception complet, classe par classe, déjà
> écrit (pas à dupliquer ici) : `specifications/07-roadmap.md` §10.14.

- **Problème** : le modèle CMDB actuel (`model/itil_cmdb.json` 7
  classes, `model/organigramme.json`/`personnes.json`/`reseau.json`
  épars) ne couvre pas : la hiérarchie physique serveur (baie/
  hyperviseur/VM), les clusters (Kubernetes et applicatif/VIP), les
  modules/interfaces/flux de données entre applications, le versioning
  applicatif, les équipements réseau (routeur/switch/firewall/DNS), une
  organisation unifiée avec société/département/contact, la
  localisation physique (bâtiment/étage/salle), l'inventaire matériel
  générique, et aucune notion de besoin métier reliant les objets.
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.14 (pas
  de duplication du contenu ici) — nouvelle meta-classe `cluster`
  (classes `kube`/`hyperviseur`/`cluster_applicatif`), nouvelle
  meta-classe `organisation` (remplace `organigramme.json`+
  `personnes.json`), nouvelle meta-classe `localisation`, extensions
  de `cmdb` (`baie_serveur`, `os`, `module`, `container`,
  `namespace_kubernetes`, `interface`, `flux_donnee`,
  `application_versionnee`, `module_versionne`, `materiel`, `besoin`),
  extensions de `reseau` (`zone_reseau`, `equipement_reseau`,
  `entree_dns`, `addresse_ip.vlan`), retouches `ticketing.json`
  (`ci_concerne.classes` réétendu) et `planning.json`
  (`tache.assigne_a.classes` élargi à personne+groupe). Chaque classe
  porte un `layers` (action 14) choisi dans la taxonomie
  `applicatif`/`infra`/`organisationnel`/`fonctionnel`/`metier`,
  cumulable avec les tags existants `physique`/`reseau`/`securite`.
  **Dépend de l'action 19** (`os.active` a besoin du type `boolean`) et
  **profite de l'action 20** (autosuggest sur les champs version) sans
  en dépendre strictement (peut être livré sans, champs texte simples
  en attendant).
- **Points ouverts, non tranchés par l'utilisateur** (listés en détail
  avec recommandation dans `specifications/07-roadmap.md` §10.14, à
  trancher à l'implémentation, pas bloquants pour écrire le modèle) :
  `equipement_reseau` classe unique+type vs 3 classes séparées ;
  `materiel` classe générique+type vs une classe par type ; périmètre
  exact des classes cibles de `besoin.emerge_par`/`couvert_par` ;
  chevauchement `application_versionnee` / `ansible_inventory.
  version_logicielle` non résolu.
- **Effort** : élevé (catalogue large, ~20 nouvelles classes/
  extensions réparties sur 3 nouvelles meta-classes + 4 fichiers
  modèle existants retouchés — aucun changement backend/frontend
  attendu en soi, le modèle dynamique existant absorbe tout ça sans
  code nouveau, sauf pour les dépendances sur les actions 19/20).
- **Fichiers** : `model/itil_cmdb.json`, `model/reseau.json`,
  `model/ticketing.json`, `model/planning.json`, nouveaux
  `model/cluster.json`, `model/organisation.json`,
  `model/localisation.json` (remplace `model/organigramme.json` et
  `model/personnes.json`, à supprimer si la fusion est confirmée à
  l'implémentation).
- **Statut** : ⬜ à faire — conception tranchée (2026-11-23), pas encore
  implémentée.

## 18. [Nouvelle fonctionnalité] Layer dynamique piloté par un attribut select

> Demande utilisateur (2026-11-23), née du constat qu'un `serveur` ne
> peut pas porter un layer `physique` statique si son `type` (nouveau
> champ, action 17) vaut `vm`. Détail de conception :
> `specifications/07-roadmap.md` §10.15.

- **Problème** : le champ `layers` de l'action 14 est statique par
  classe — ne peut pas refléter un layer qui dépend de la valeur d'un
  attribut de l'objet (ex. `serveur.type` physique/vm).
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.15 (pas
  de duplication du contenu ici) — nouveau champ optionnel `layer_map`
  sur une définition d'attribut `select` (`{valeur: [layers]}`), layer
  effectif d'un objet = union du `layers` statique de sa classe et des
  `layer_map` de ses attributs `select` concernés. Portée limitée à
  `NavigationPage.tsx`/`DiagramPage.tsx` (objets réels) — la Sidebar
  (action 15, arbre de classes) reste sur le `layers` statique, elle ne
  manipule que des définitions de classe, pas des objets. Aucun
  changement backend attendu (calcul 100% frontend, cohérent avec le
  principe déjà posé à l'action 14).
- **Effort** : moyen (schéma + predicate de résolution de layer
  étendu + UI d'édition `layer_map` dans `ConfigurationPage.tsx`,
  réutilise le pattern chips déjà construit à l'action 14 — portée
  circonscrite mais touche à nouveau les 3 pages déjà modifiées par les
  actions 14/15).
- **Fichiers** : `model/schema.json`, `frontend/src/pages/
  ConfigurationPage.tsx`, `frontend/src/pages/NavigationPage.tsx`,
  `frontend/src/pages/DiagramPage.tsx`.
- **Statut** : ✅ fait (2026-11-23, `worker`/`testeur`/`pessimiste`/
  `candide`/`testeur-global`). Conception tranchée par l'utilisateur le
  2026-11-23, détail complet `specifications/07-roadmap.md` §10.15
  (déjà à jour, synchronisée en fin de cycle).
  - **Itération 1 — implémentation initiale** (2 workers successifs, le
    même jour) :
    - Volet A (`layer_map`, worker 1) : `model/schema.json` (nouveau
      champ optionnel `layer_map`, objet `{valeur: [layers]}`, sur une
      définition d'attribut `type: select`, sibling de `values`) ;
      `frontend/src/types.ts` (`AttributeDefinition.layer_map?:
      Record<string, string[]>`) ; `NavigationPage.tsx` et
      `DiagramPage.tsx` (nouvelle fonction
      `getObjectEffectiveLayers(classDef, detail)` dans chaque fichier
      — dette de duplication déjà acceptée au même titre que
      `isClassVisibleForLayers` depuis l'action 14 — appelée juste
      avant le predicate existant, au point du filtre qui porte sur une
      liste d'objets réels [pas sur des classes] : union du `layers`
      statique de la classe et des `layer_map[valeur_actuelle]` de
      chaque attribut select concerné, repli sur `classDef.layers`
      statique seul si le détail de l'objet n'est pas encore chargé
      [lazy loading `NavigationPage.tsx`], sans blocage) ;
      `ConfigurationPage.tsx` (UI d'édition `layer_map`, champ texte
      comma-séparé par valeur de `values[]`, purge des clés orphelines
      si une valeur select est retirée — limite connue documentée plus
      bas) ; `model/itil_cmdb.json` (cas de test concret : attribut
      `select` `serveur.type` physique/vm avec `layer_map:
      {"physique": ["physique"]}`, `serveur.layers` statique réduit de
      `["physique","reseau"]` à `["reseau"]` pour rendre le mécanisme
      dynamique démontrable — a entraîné une régression de donnée
      corrigée en itération 2, voir plus bas) ;
      `specifications/07-roadmap.md` §10.15 passée de « conçu, pas
      implémenté » à implémentée. Sidebar.tsx confirmée hors scope
      (reste sur `classDef.layers` statique, ne manipule que des
      définitions de classe) — vérifié par l'orchestrateur avant
      dispatch, confirmé par la revue croisée.
    - Volet B (`default_layers`, worker 2, ajout demandé par
      l'utilisateur en cours de cycle, absent de la conception §10.15
      écrite à l'origine, documenté a posteriori) : `sql/init.sql`
      (seed `app_config` clé `default_layers` =
      `["applicatif","infra","organisationnel","fonctionnel","metier"]`,
      JSON en TEXT) ; `backend/routes/routes_admin.py` (nouvelles
      routes GET/PUT `/api/config/default_layers`, même pattern que
      `purge_grace_period_days` avec une différence volontaire : GET
      ouvert sans aucune vérification d'auth — métadonnée d'affichage
      UI, pas RBAC, principe déjà posé à l'action 14, nécessaire car
      `Sidebar.tsx` est consommé par tous les utilisateurs — PUT
      réservé `global-admin` [`is_global_admin`, 403 sinon] mais chemin
      volontairement pas ajouté à `_PROTECTED_EXACT_PATHS`
      [`backend/auth/auth.py`] car cette liste gate par chemin seul,
      pas par méthode HTTP, et aurait forcé un 401 systématique aussi
      sur le GET, cassant la lecture anonyme requise) ;
      `frontend/src/api.ts` (`apiGetDefaultLayers`/
      `apiSetDefaultLayers`), `Sidebar.tsx` (`availableLayers` = union
      scan classes + fetch persisté), `ConfigurationPage.tsx` (union
      carte « Layers connus » + nouvelle carte admin-only d'édition
      `default_layers` près de la carte retention/purge).
  - **Revue croisée itération 1** : testeur (8/8 PASS côté
    logique/schema/tsc, mais E2E réel du mécanisme `layer_map` bloqué —
    DB dev périmée, `/api/init` pas rejoué depuis le changement de
    modèle) ; candide (convergence sur l'essentiel : point d'intégration
    du predicate, flag par simple présence de `layer_map`, RBAC
    `default_layers` ; 4 écarts dont 2 de traçabilité —
    `default_layers` absent de `_PROTECTED_EXACT_PATHS` non justifié en
    commentaire à l'époque, `default_layers` absent des specs) ;
    pessimiste (confirme les écarts de traçabilité + trouve un vrai gap
    de données vérifié en base réelle : l'unique objet `serveur`
    existant, id 130 `web-prod-01`, n'avait aucune valeur sur
    l'attribut `type` → perdait le layer `physique` qu'il avait
    implicitement avant ce changement, régression réelle ; + limite
    mineure sur `removeSelectValue` qui purge immédiatement `layer_map`
    en state local sans restauration si la valeur est retapée avant
    sauvegarde).
  - **Itération 2 — correctifs** (arbitrage orchestrateur, 1 worker) :
    (1) resynchronisation — `POST /api/init` (token admin réel,
    Keycloak) rejoué pour mettre à jour la DB dev avec le modèle
    `itil_cmdb.json` à jour (confirmé non destructif, UPSERT par
    meta-classe), régression corrigée en réel via `PUT
    /api/write/attribute/serveur/130/type/physique` sur l'objet
    existant, restaure son layer `physique` effectif ; (2)
    `backend/auth/auth.py` et `backend/routes/routes_admin.py` :
    commentaires explicatifs ajoutés (pas de changement de
    comportement) justifiant l'absence volontaire de
    `/api/config/default_layers` dans `_PROTECTED_EXACT_PATHS` ; (3)
    `ConfigurationPage.tsx` : commentaire « limite connue » ajouté
    au-dessus de `removeSelectValue` (pas de changement de
    comportement — décision explicite de ne pas complexifier le state
    tracking pour un edge case rare) ; (4) `specifications/07-
    roadmap.md` §10.15 : paragraphe ajouté documentant le registre
    `default_layers` (absent de la conception écrite initialement).
  - **Revalidation ciblée** : testeur (14/14 PASS, E2E réel confirmé —
    objet #130 type=physique → layer effectif `{reseau,physique}`, 2e
    objet de démo créé #170 type=vm → layer effectif `{reseau}` seul
    correctement filtré ; RBAC `default_layers` GET 200 anonyme / PUT
    403 sans token confirmés, route sœur `purge_grace_period_days` PUT
    401 inchangée ; diffs itération 2 sanity-checkés = commentaires
    purs) ; pessimiste (4/4 points confirmés OK : pas d'autre objet
    serveur orphelin en base, `/api/init` confirmé non destructif,
    commentaires exacts, doc §10.15 exacte contre code+DB live).
  - **Testeur-global final : OK.** Build backend (py_compile) OK, suite
    pytest existante 235/235 (0 échec), stack docker-compose 6 services
    up sans crash, endpoints réels confirmés (`layer_map` bien
    sérialisé par la lecture objet, `default_layers` GET 200 anonyme),
    9/9 fichiers `model/*.json` valides contre le schema étendu,
    navigation IHM de base non cassée. Seul point noté (non bloquant,
    dette pré-existante hors scope) : build prod frontend `tsc -b`
    cassé par une dette echarts déjà présente avant cette action dans
    `DiagramPage.tsx`, confirmé identique avant/après via `git stash` —
    déploiement réel en mode dev server, pas de build prod utilisé.
  - **Limites connues acceptées** (non bloquantes) : (a)
    `removeSelectValue` purge immédiatement la clé `layer_map`
    correspondante en state local sans restauration si la même valeur
    est retapée avant sauvegarde ; (b) asymétrie RBAC volontaire sur
    `default_layers` (GET ouvert/PUT global-admin, documentée en
    commentaire, différente du pattern `purge_grace_period_days` qui
    est global-admin sur GET et PUT) ; (c) validation JSON Schema de
    `layer_map` non stricte (n'impose pas que ses clés soient un
    sous-ensemble de `values[]`, cohérent avec le niveau de validation
    déjà accepté ailleurs dans `schema.json`) ; (d) predicate
    `getObjectEffectiveLayers` dupliqué verbatim dans
    `NavigationPage.tsx`/`DiagramPage.tsx`, même dette déjà acceptée
    pour `isClassVisibleForLayers` depuis l'action 14.
  - **Fichiers finaux touchés** : `model/schema.json`,
    `model/itil_cmdb.json`, `frontend/src/types.ts`,
    `frontend/src/pages/NavigationPage.tsx`,
    `frontend/src/pages/DiagramPage.tsx`,
    `frontend/src/pages/ConfigurationPage.tsx`,
    `frontend/src/components/Sidebar.tsx`, `frontend/src/api.ts`,
    `sql/init.sql`, `backend/routes/routes_admin.py`,
    `backend/auth/auth.py`, `specifications/07-roadmap.md`.

## 19. [Nouvelle fonctionnalité] Type d'attribut boolean

> Demande utilisateur (2026-11-23), née du besoin `os.active` (action
> 17). Détail de conception : `specifications/07-roadmap.md` §10.16.

- **Problème** : aucun type booléen dans le schéma actuel (11 types
  existants, aucun n'est une case à cocher simple).
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.16 (pas
  de duplication du contenu ici) — nouveau type `boolean` dans l'enum
  `attributes[].type`, stockage texte (`"true"`/`"false"`) dans
  `value_string` comme les autres types scalaires, rendu case à cocher
  dans `NavigationPage.tsx` (formulaire **et** édition inline de
  cellule — rappel explicite de l'oubli déjà fait une fois à l'action
  7, à ne pas reproduire), `ATTR_TYPES` de `ConfigurationPage.tsx`
  étendu à 12 types.
- **Effort** : faible (type scalaire le plus simple du jeu actuel,
  aucune nouvelle colonne SQL, pas de validation complexe).
- **Fichiers** : `model/schema.json`, `backend/routes/
  routes_write.py`, `frontend/src/pages/NavigationPage.tsx`,
  `frontend/src/pages/ConfigurationPage.tsx`, `frontend/src/types.ts`.
- **Statut** : ⬜ à faire — conception tranchée (2026-11-23), pas encore
  implémentée.

## 20. [Nouvelle fonctionnalité] Autosuggest : suggestions de valeurs apprises sur un attribut texte

> Demande utilisateur (2026-11-23), née des champs texte répétitifs
> (ville/pays de `batiment`, versions applicatives — action 17). 3
> points tranchés par l'utilisateur : nom du flag `autosuggest`,
> valeurs actives seulement (pas tout l'historique), tri par distance
> d'édition via `rapidfuzz`. Détail de conception complet :
> `specifications/07-roadmap.md` §10.17.
- **Problème** : pas de mécanisme d'auto-complétion pour un champ texte
  libre répétitif (ex. ville, version) — seule alternative actuelle est
  `select` (liste figée par l'admin, pas adaptée à des valeurs qui
  grandissent au fil de la saisie utilisateur).
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.17 (pas
  de duplication du contenu ici) — nouveau champ optionnel
  `"autosuggest": true` sur un attribut `string`, nouvelle route
  `GET /api/suggest/<meta_class>/<class>/<attribute>?q=...` (valeurs
  actives uniquement, RBAC tenant identique aux autres lectures, tri
  par distance d'édition via la nouvelle dépendance `rapidfuzz`),
  dropdown de suggestions dans `NavigationPage.tsx` (formulaire **et**
  édition inline — même rappel que l'action 19), case à cocher dans
  `ConfigurationPage.tsx`.
- **Effort** : moyen (nouvelle route + nouvelle dépendance Python +
  UI d'autocomplétion débouncée des deux côtés édition de
  `NavigationPage.tsx`).
- **Fichiers** : `model/schema.json`, `backend/requirements.txt`,
  nouveau endpoint dans `backend/routes/routes_read.py` (ou nouveau
  module dédié), `frontend/src/pages/NavigationPage.tsx`,
  `frontend/src/pages/ConfigurationPage.tsx`, `frontend/src/api.ts`.
- **Statut** : ⬜ à faire — conception tranchée (2026-11-23), pas encore
  implémentée.

## 21. [Nouvelle fonctionnalité] Recherche globale

> Demande utilisateur (2026-11-23) : nouvel onglet « Recherche » — champ
> texte + 2 switches (`fuzzy`, `history`, désactivés par défaut),
> cherche dans les attributs de tous les objets toutes classes/
> meta-classes confondues, résultat = facettes layers/classes/attributs
> qui filtrent la liste d'objets en dessous. Détail de conception
> complet, déjà écrit (pas à dupliquer ici) :
> `specifications/07-roadmap.md` §10.18.

- **Problème** : aucun moyen de chercher un objet par le contenu de ses
  attributs à travers tout le modèle — seule navigation possible
  aujourd'hui est par classe (Sidebar) ou par layer (action 14/15),
  jamais par valeur.
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.18 (pas
  de duplication du contenu ici) — nouvelle route
  `GET /api/search?q=...&fuzzy=...&history=...`, nouvelle page
  `frontend/src/pages/RecherchePage.tsx` + entrée Navbar. Par défaut :
  attributs actifs seulement (`history=false`), correspondance
  substring directe (`fuzzy=false`). `history=true` étend la recherche
  à l'historique complet (y compris valeurs fermées). `fuzzy=true`
  propose des valeurs proches sélectionnables (réutilise la dépendance
  `rapidfuzz` de l'action 20). Exclusion explicite du type `secret`
  (sécurité, pas juste une optimisation). Facettes layers (statique,
  action 14 — pas le layer effectif par objet de l'action 18, trop
  coûteux à calculer sur un résultat de recherche large), classes,
  attributs, filtrage en ET progressif par sélection de facette.
- **Dépend de l'action 20** (réutilise `rapidfuzz`, déjà ajouté comme
  dépendance Python à cette occasion) pour le mode `fuzzy` — peut être
  livré sans si l'action 20 n'est pas encore faite (mode fuzzy
  simplement non disponible/grisé en attendant).
- **Points ouverts, non tranchés par l'utilisateur** (listés en détail
  avec recommandation dans `specifications/07-roadmap.md` §10.18, à
  trancher à l'implémentation) : limite de résultats/pagination (pas de
  `LIMIT` = requête potentiellement énorme) ; comportement de recherche
  sur les pointeurs `file`/`image`/`csv` (matche le nom de fichier
  intégré au pointeur, pas le contenu — accepté par défaut).
- **Effort** : moyen à élevé (nouvelle route backend avec requête
  cross-table + RBAC tenant, nouvelle page frontend avec facettes et
  filtrage progressif, intégration `rapidfuzz` pour le mode fuzzy).
- **Fichiers** : nouveau endpoint dans `backend/routes/
  routes_read.py` (ou nouveau module dédié `backend/routes/
  routes_search.py`), nouveau `frontend/src/pages/RecherchePage.tsx`,
  `frontend/src/components/Navbar.tsx`, `frontend/src/App.tsx`,
  `frontend/src/api.ts`.
- **Statut** : ⬜ à faire — conception tranchée (2026-11-23), pas encore
  implémentée.

## 22. [Dette technique / validation] Création de classe : meta_class auto-déduite, nom de classe unique

> Demande utilisateur (2026-11-23) : dans `ConfigurationPage.tsx`, si
> `meta_class` est vide à la création, le prendre égal au nom de la
> classe plutôt que de bloquer la sauvegarde ; vérifier que la classe
> n'existe pas déjà ; le nom de classe doit être unique. Détail de
> conception complet : `specifications/07-roadmap.md` §10.19.

- **Problème** : `handleSave` (`ConfigurationPage.tsx:315-319`) bloque
  aujourd'hui toute sauvegarde si `metaClassName` est vide, sans défaut
  automatique. Aucune vérification d'unicité du nom de classe (ni
  frontend ni backend) — deux meta-classes différentes pourraient
  porter une classe du même nom sans avertissement.
- **Correctif** : renvoi à `specifications/07-roadmap.md` §10.19 (pas
  de duplication du contenu ici) — `meta_class` vide auto-déduit du nom
  de classe si une seule classe dans le formulaire (sinon blocage
  explicite conservé, cas ambigu avec 2+ classes) ; vérification
  d'existence/unicité du nom de classe contre `allClassNames` avant
  sauvegarde (une classe déjà présente dans la meta-classe en cours
  d'édition n'est pas un conflit).
- **Points ouverts, non tranchés par l'utilisateur** (détaillés avec
  recommandation dans `specifications/07-roadmap.md` §10.19) : défaut
  meta_class=class uniquement si une seule classe dans le formulaire
  (recommandé) ; vérification unicité frontend seule (garde UX) vs
  aussi backend (garantie réelle, recommandé mais pas fait
  aujourd'hui — aucun contrôle d'unicité de classe visible côté
  `write_class`/`write_metaclass`).
- **Effort** : faible à moyen (validation frontend bornée +
  éventuellement un contrôle backend symétrique si retenu).
- **Fichiers** : `frontend/src/pages/ConfigurationPage.tsx`,
  potentiellement `backend/routes/routes_write.py` si le contrôle
  backend est retenu.
- **Statut** : ⬜ à faire — conception tranchée (2026-11-23), pas encore
  implémentée.

## Récapitulatif d'avancement

> Tableau à tenir à jour en même temps que le champ **Statut** de chaque
> action ci-dessus — une ligne par action, pas par vague.

| # | Action | Fait ? |
|---|--------|--------|
| 1 | Découpage de `backend/app.py` en modules | ✅ fait |
| 2 | Interface de stockage de fichiers (abstraite, impl. à plat) | ✅ fait |
| 3 | Types d'attribut "fichier", "image" et "csv" | ✅ fait |
| 4 | Logo surchargeable par objet et icône par défaut par classe | ✅ fait |
| 5 | Versionnage des fichiers modèle (préparation migrations) | ✅ fait |
| 6 | [Dette documentaire] Synchronisation specifications/ avec actions 1-5 | ✅ fait |
| 7 | Type d'attribut select/enum | ✅ fait |
| 8 | Type d'attribut secret/password | ✅ fait |
| 9 | Type d'attribut datasource | ✅ fait |
| 10 (scindée, voir 10a-10d) | Framework de dashboard/affichage configurable | 🔀 scindée |
| 10a | Modèle de données dashboard/tab configurable | ✅ fait |
| 10b | IHM lecture seule d'un dashboard existant | ✅ fait |
| 10c | Édition des tabs dans l'IHM | ✅ fait |
| 10d | Sélection des sous-objets affichés par tab | ✅ fait |
| 11 | Outil d'ingestion avec binding | ⬜ à faire |
| 12 | Réorganisation de backend/ en packages (auth, data, files, routes, tests) | ✅ fait |
| 13 | IHM de configuration : types d'attribut manquants (file/image/csv/select/secret/datasource) | ✅ fait |
| 14 | Layers sur les classes et filtre IHM/diagramme | ✅ fait |
| 15 | Restructuration IHM : menu, Sidebar par layer, filtres texte, combo layers Diagramme | ✅ fait |
| 16 | [Dette documentaire] Synchronisation specifications/ avec actions 7-14 | ✅ fait |
| 17 | Extension du modèle CMDB embarqué | ⬜ à faire |
| 18 | Layer dynamique piloté par un attribut select | ✅ fait |
| 19 | Type d'attribut boolean | ⬜ à faire |
| 20 | Autosuggest : suggestions de valeurs apprises sur un attribut texte | ⬜ à faire |
| 21 | Recherche globale | ⬜ à faire |
| 22 | ajouter les use case mieux que ca | a faire|
| 22 | enlever ou deplacer ce aui est implementé de la roadmap et le deplacer dasn fonctionnel ou autre (emplacement adequat) | a faire|
| 23 | tout faire sauf 11 fermer ce plan et passer au mark4 | a faire |

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
- **Cas d'usage débloqués** (`use case.md`) : coffre-fort documentaire/GED
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
- **Cas d'usage débloqués** (`use case.md`) : CMDB avec supervision
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
- **Statut** : ⬜ à faire — priorité 2, choix utilisateur 2026-11-22.

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
- **Statut** : ⬜ à faire — priorité 4, découpage en sous-actions à
  valider avant implémentation, choix utilisateur 2026-11-22.

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
| 8 | Type d'attribut secret/password | ⬜ à faire |
| 9 | Type d'attribut datasource | ✅ fait |
| 10 | Framework de dashboard/affichage configurable | ⬜ à faire |
| 11 | Outil d'ingestion avec binding | ⬜ à faire |

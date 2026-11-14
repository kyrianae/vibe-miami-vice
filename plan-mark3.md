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
- **Statut** : ⬜ à faire.

## Récapitulatif d'avancement

> Tableau à tenir à jour en même temps que le champ **Statut** de chaque
> action ci-dessus — une ligne par action, pas par vague.

| # | Action | Fait ? |
|---|--------|--------|
| 1 | Découpage de `backend/app.py` en modules | ✅ fait |
| 2 | Interface de stockage de fichiers (abstraite, impl. à plat) | ✅ fait |
| 3 | Types d'attribut "fichier", "image" et "csv" | ✅ fait |
| 4 | Logo surchargeable par objet et icône par défaut par classe | ⬜ à faire |

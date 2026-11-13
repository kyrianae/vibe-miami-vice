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

## Récapitulatif d'avancement

> Tableau à tenir à jour en même temps que le champ **Statut** de chaque
> action ci-dessus — une ligne par action, pas par vague.

| # | Action | Fait ? |
|---|--------|--------|
| 1 | Découpage de `backend/app.py` en modules | ✅ fait |
| 2 | Interface de stockage de fichiers (abstraite, impl. à plat) | ✅ fait |

# 10. Pistes d'évolution et décisions en cours (roadmap)

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

> Section ajoutée le 2026-11-09, suite à une discussion des notes brutes
> de `tocheck.md` avec l'équipe de revue (optimiste/pessimiste/candide).
> Distincte de §9 : il ne s'agit pas d'anomalies du code actuel, mais
> d'évolutions futures, certaines actées et planifiées, d'autres encore
> ouvertes. **Mise à jour du 2026-11-12** : le plan de suivi a depuis été
> scindé en `plan-mark1.md` (clos le 2026-11-10) puis `plan-mark2.md` (clos
> ce jour, voir sa section « Clôture de Mark 2 ») — les renvois `plan.md`
> ci-dessous sont historiques ; chaque sous-section précise désormais le
> fichier et le statut réels. §0-§9 ci-dessus restent un instantané figé de
> l'audit du 2026-11-07 (bugs depuis corrigés en Mark 1/Mark 2, non
> remis à jour ici pour préserver la trace de l'état initial).

## 10.1 Décisions tranchées (pour mémoire)

- **Déréférencement illimité (`depth=-1`) sur `GET /api/read/object/<id>?deref=true`
  — refusé.** Proposé pour accepter une profondeur illimitée en plus de
  l'intervalle `[0, MAX_DEPTH=5]` actuellement imposé (voir `plan.md`
  action 2bis). Refusé après analyse de l'équipe : le backend tourne avec
  un unique worker Gunicorn synchrone (`backend/Dockerfile`, pas de
  `--workers`/`--threads`), sans aucune authentification sur l'API — une
  requête à profondeur illimitée sur un graphe large (même acyclique,
  donc sans déclencher la détection de cycle déjà en place) peut
  bloquer tout le backend pour tous les utilisateurs, un vecteur de déni
  de service trivial à exploiter. `MAX_DEPTH` reste figé à 5.

## 10.2 Multi-tenant (fait — `plan-mark1.md` action 11)

Idée : ajouter une notion de tenant dans la configuration — des classes
accessibles seulement dans certains tenants, des objets rattachés à un ou
plusieurs tenants à la création, et une option « hors tenant » rendant un
objet/une classe accessible depuis n'importe quel tenant.

Analysé comme un changement transversal profond (schéma `object` et
`definition.data`, toutes les routes de lecture/écriture existantes,
UI de sélection de tenant) plutôt qu'un simple filtre. Point bloquant
identifié par l'équipe : **sans authentification réelle, un filtre
tenant n'est qu'un filtre cosmétique** — rien n'empêche un client de
prétendre appartenir à n'importe quel tenant via un simple paramètre/
en-tête, l'API étant entièrement ouverte (§2). L'authentification étant
désormais tranchée (§10.3 : Keycloak), ce point peut être conçu en
détail : les groupes/rôles Keycloak sont un candidat naturel pour porter
la notion de tenant plutôt que de la dupliquer dans une table
applicative — reste à concevoir, pas encore une action du plan.
concevoir en détail qu'une fois l'authentification tranchée.

> ⚠️ Corps de section laissé tel quel (dérive documentaire connue, voir
> `plan-mark1.md:1255-1257` : cette note est explicitement marquée
> obsolète là-bas — « tranchée et implémentée en totalité par l'action
> 11 »). Le **titre** ci-dessus (« fait ») reflète l'état réel du code ;
> le **corps** ci-dessus n'a jamais été réécrit après la clôture de
> l'action 11 et décrit un état antérieur à la décision Keycloak.

## 10.3 Authentification (fait — Keycloak, `plan-mark1.md` action 7b)

Décision utilisateur (2026-11-09) : **Keycloak**, pour couvrir à la fois
des comptes de service (flux `client_credentials`, Bearer JWT sans
interaction utilisateur — automatisation/intégrations) et une connexion
humaine directe par login/mot de passe (*Direct Access Grants*, pertinent
tant que le frontend n'a pas de routeur pour un flux OIDC avec
redirection complet). Comparatif détaillé des 7 options envisagées et
justification : voir `doc/choix-authent.md`. Conception technique
d'implémentation : voir `plan.md` action 7b.

Éléments déjà réunis par l'équipe, à discuter avant de trancher :
- `docker-compose.yml` contient déjà deux services `ldap`/`lam`
  **entièrement commentés et inertes** (§7) — un investissement de départ
  jamais câblé au code.
- Keycloak fédérerait LDAP (service déjà présent), Google (OIDC) et SSO
  (SAML/OIDC) derrière un seul protocole côté backend (validation JWT),
  réduisant la surface de code d'authentification custom dans `app.py` —
  mais ajoute un service stateful supplémentaire à l'infrastructure
  (actuellement « stateless côté HTTP », §2).
- `plan.md` action 7b prévoit déjà une étape intermédiaire volontairement
  minimale (clé API statique via en-tête `Authorization`) avant toute
  authentification structurante — à clarifier si LDAP/Google/SSO/Keycloak
  remplace ou prolonge cette étape.
- Dépendance avec §10.2 (tenant) : les groupes/rôles Keycloak pourraient
  directement porter la notion de tenant plutôt que de la dupliquer dans
  une table applicative séparée — à trancher conjointement.

## 10.4 Historisation des objets et attributs (fait — `plan-mark2.md` actions 6.0-6.4)

Décision utilisateur (2026-11-09) : implémenter une historisation
temporelle des attributs (`valid_from`/`valid_to` sur `attribute_value`)
et une suppression **logique** des objets (`deleted_at` sur `object`,
fermeture de tous les attributs actifs), suivie d'une **purge physique
différée** après une période de grâce. **Implémenté et clos le
2026-11-12** (voir `plan-mark2.md`, « Clôture de Mark 2 ») :
`write_object`/`write_attribute_value` réécrits en diff versionné via
`_apply_attribute_diff` (action 6.0) ; `DELETE /api/delete/object/<id>`
pour la suppression logique, cascade sur les jointures entrantes scopée
au tenant de l'acteur (action 6.1) ; période de grâce **configurable** à
chaud (table `app_config`, défaut 30 jours) et `POST /api/purge` réservé
`global-admin` (action 6.2) ; `DELETE /api/delete/class/...` et
`DELETE /api/delete/metaclass/...` pour la suppression physique du schéma,
sans effet sur les objets déjà créés (action 6.3/6.4). L'affichage d'un
historique de versions dans l'UI reste hors périmètre, reporté à une
action future (TODO conservé).

## 10.5 Partitionnement PostgreSQL par type d'objet (évalué, non implémenté — `plan-mark2.md` action 9)

Idée : partitionner la table `object` (et éventuellement
`attribute`/`attribute_value`) par `class`/`meta_class` pour la
performance. Réserve de l'équipe : le modèle est entièrement dynamique
(classes définies en JSON dans `definition.data`, créées/renommées à chaud
sans aucun DDL), alors que le partitionnement déclaratif PostgreSQL exige
de connaître les valeurs de partition à l'avance et un DDL (`ATTACH
PARTITION`) par nouvelle classe — tension de fond avec le principe même
du projet (§1). **Évaluation faite le 2026-11-12** (`plan-mark2.md` action
9) : aucune donnée de volumétrie réelle de production disponible ;
hypothèse de confort documentée (volumétrie modeste, quelques classes,
pas de signal de croissance massive) ; conclusion **non justifié à ce
stade**, coût (DDL dynamique jamais fait ailleurs dans ce projet, risque
sur les contraintes FK existantes) supérieur au bénéfice mesurable.
Conditions de réouverture : données réelles de prod montrant la table
`object` tendre vers plusieurs millions de lignes, ou symptôme de
performance mesuré sur des requêtes filtrées `class`/`meta_class`.

## 10.6 Liens transitifs du graphe au filtrage (fait — `plan-mark2.md` action 10)

Idée : dans la page Diagramme (`DiagramPage.tsx`), quand un filtre de
classe masque un nœud intermédiaire d'une chaîne de jointures (A→B→C, B
masqué), préserver la connexion logique en reliant A→C directement plutôt
que de perdre les deux arêtes. **Implémenté** : fermeture transitive
locale avec anti-cycle (`resolveVisibleTargets`), arêtes reconstituées
visuellement distinctes (trait pointillé, sans label), garde-fous de
profondeur et de volume (`MAX_HIDDEN_CHAIN_DEPTH`,
`MAX_RECONSTRUCTED_EDGES_PER_HIDDEN_NODE`), construction en 2 passes pour
un dédoublonnage indépendant de l'ordre d'itération SQL. Détail complet :
voir `plan-mark2.md` action 10.

## 10.7 Stockage de fichiers (fait — `plan-mark3.md` action 2)

Idée (`tocheck.md` point 13) : prérequis pour les attributs de type
« fichier » (#14), « image » (#15) et le logo surchargeable par objet
(#16) — définir comment stocker des fichiers liés à un objet, avec une
arborescence `/class/id/attribut/version`.

Décision utilisateur (2026-11-13) : implémentation **fichiers à plat**
pour commencer, mais posée **derrière une interface de stockage
abstraite** — remplaçable par S3/MinIO plus tard sans modifier le code
appelant (endpoints de #14 et au-delà), et sans refonte le jour où le
découpage microservices (`tocheck.md` #22, backend storage dédié) se
fait.

Design retenu :
- Interface `FileStorage` (classe abstraite), méthodes minimales :
  `save`, `read`, `delete`, `list_versions`.
- Implémentation `LocalFileStorage` : racine configurable (env var
  `FILE_STORAGE_ROOT`, même pattern que `SCHEMA_PATH`/`MODEL_DIR`),
  arborescence `<root>/<class>/<object_id>/<attribute_name>/<version>/
  <filename>`.
- Versionnement : entier incrémental par `(class, object_id,
  attribute_name)`, déterminé par listing du dossier existant — jamais
  d'écrasement, cohérent avec l'historisation déjà en place (§10.4,
  `plan-mark2.md` action 6.0 : aucune version n'est perdue).
- Nom de fichier reçu = entrée utilisateur : assaini avant toute
  écriture disque (refus de `..`, séparateur de chemin, chemin absolu)
  pour empêcher un path traversal hors de l'arborescence prévue.
- Portée volontairement limitée à la brique de stockage elle-même :
  **pas de route HTTP, pas de câblage à un type d'attribut** dans cette
  action — ça reste le périmètre de #14 (action future, distincte).

Détail complet et suivi : `plan-mark3.md` action 2.

> **Mise à jour (2026-11-21, fait)** : design ci-dessus intégralement
> implémenté sans écart — `backend/file_storage.py` (`FileStorage` ABC +
> `LocalFileStorage`), `FILE_STORAGE_ROOT` (défaut `/data/files`, volume
> `./files:/data/files` dans `docker-compose.yml`), versionnement par
> listing de dossier, assainissement strict de tous les segments de
> chemin (pas seulement le nom de fichier). 18/18 tests
> `backend/test_file_storage.py`. Détail : `plan-mark3.md` action 2.

## 10.8 Types d'attribut fichier/image/csv, logo d'objet, icône de classe (fait — `plan-mark3.md` actions 3-4)

Idée (`tocheck.md` points 14, 15, 16, 17, 20) : attribut de type
« fichier », spécialisation « image » (jpg/svg/png) et « csv », logo
surchargeable par objet (utilisé dans les diagrammes), icône par défaut
par classe. Dépend de §10.7 (interface de stockage).

### Types d'attribut « fichier », « image » et « csv » (`tocheck.md` #14/#15/#20 — `plan-mark3.md` action 3)

- Nouveaux types dans `model/schema.json` : `"file"`, `"image"` et
  `"csv"` ajoutés à l'enum `attributes[].type` (aux côtés de
  `string|integer|float|joint-1-1|joint-1-n`). `constraint`/
  `sql_constraint` restent sans objet pour ces trois types (pas de
  `classes` requis non plus, contrairement à `joint-1-1`/`joint-1-n`).
  Le type `csv` porte un champ supplémentaire propre à la définition
  d'attribut, `"separator"` (défaut `,`), au même niveau que `classes`
  pour `joint-1-1`/`joint-1-n` — c'est une propriété du schéma, pas de
  chaque valeur stockée.
- Représentation en base : **aucune nouvelle colonne**. La contrainte
  `CHECK` de `attribute_value` (exactement une des 4 colonnes non-NULL,
  §3.4) reste inchangée — la valeur stockée dans `value_string` est un
  pointeur `"<version>:<nom_fichier_original>"` vers le contenu réel géré
  par `FileStorage` (§10.7), pas le contenu lui-même. L'historisation
  existante (`valid_from`/`valid_to`, `plan-mark2.md` action 6.0)
  s'applique normalement à ce pointeur : une nouvelle valeur ferme
  l'ancienne ligne et en ouvre une nouvelle avec un pointeur vers une
  nouvelle version `FileStorage` — l'ancien fichier n'est jamais effacé
  tant que sa ligne `attribute_value` reste dans la fenêtre de grâce
  (cohérent avec la purge différée, action 6.2).
- Deux nouvelles routes (le contenu est binaire, `POST /api/write/object`
  reste JSON, inchangé) :
  - `POST /api/write/object/<int:object_id>/file/<string:attribute>`
    (`multipart/form-data`, champ `file`) : vérifie que l'objet existe et
    n'est pas supprimé logiquement, que l'attribut est bien déclaré de
    type `file`/`image` sur la classe de l'objet, applique le même
    contrôle RBAC tenant en écriture que les autres endpoints d'écriture
    (`_check_class_tenant_write_permission`/équivalent), appelle
    `FileStorage.save(...)`, puis ferme/ouvre la ligne `attribute_value`
    comme ci-dessus.
  - `GET /api/read/object/<int:object_id>/file/<string:attribute>`
    (`?version=N` optionnel, sinon la version active) : applique le même
    filtre de lecture tenant que `_build_object_payload`, puis sert les
    octets via `FileStorage.read(...)` avec `Content-Type` déduit de
    l'extension et `Content-Disposition`.
- Limite de taille d'upload explicite (`MAX_CONTENT_LENGTH` Flask ou
  contrôle avant écriture) — même logique de prudence que le refus du
  `depth` illimité (§10.1) : une API avec authentification mais sans
  limite de taille de corps reste un vecteur de déni de service par
  remplissage disque.
- Validation spécifique au type `image` : extension dans
  `{jpg, jpeg, png, svg}` **et** contenu vérifié (signature binaire pour
  jpg/png ; pour svg, XML bien formé avec racine `<svg>`). ⚠️ Point de
  sécurité à ne pas rater : un SVG peut embarquer du script
  (`<script>`, gestionnaires d'évènements, entités externes) — un SVG
  uploadé par un utilisateur et resservi tel quel est un vecteur de XSS
  stocké classique. Le servir en `Content-Disposition: attachment` (pas
  de rendu inline direct dans un `<img>`/`<iframe>` sans sanitization) ou
  le sanitizer au moment de l'upload — à trancher explicitement lors de
  l'implémentation, pas une simple validation d'extension.
- **IHM (`frontend/src/pages/NavigationPage.tsx`)** : les types `file`,
  `image` et `csv` n'ont aucun rendu dédié aujourd'hui — seuls les types
  `joint-1-1`/`joint-1-n` ont une branche spécifique (sélecteur d'objet
  lié) ; tout le reste tombe dans le rendu générique champ texte, ce qui
  afficherait le pointeur brut `"<version>:<nom_fichier>"` plutôt qu'un
  contrôle utilisable. Trois branches de rendu à ajouter, par type :
  - `file` : nom de fichier affiché + bouton **téléchargement** (lien
    vers la route `GET .../file/<attribute>` de l'action 3, pas de rendu
    inline — contenu de type arbitraire).
  - `image` : **aperçu intégré** (vignette/`<img>` pointant vers la même
    route de lecture) **et** bouton téléchargement. ⚠️ L'aperçu inline
    d'un SVG implique que le choix de sécurité ci-dessus (sanitization à
    l'upload) ait été tranché en faveur du rendu inline — si l'option
    retenue est « servir en attachment », l'aperçu `image` se limite aux
    formats raster (jpg/png) et le SVG retombe sur le même traitement
    que `file` (téléchargement seul, pas d'`<img>` direct). Ce choix doit
    être cohérent entre le point de sécurité backend et ce rendu.
  - `csv` : **affichage** sous forme de tableau en lecture seule (parsing
    client avec le `separator` défini sur l'attribut, pas de calcul
    serveur additionnel) **et** bouton téléchargement du fichier brut
    (même route que `file`). Pas d'édition de cellule dans ce tableau —
    l'édition reste le remplacement du fichier entier via upload.
  - Mode édition (formulaire de création/modif d'objet) : contrôle
    d'upload (`<input type="file">`) pour les trois types, remplaçant la
    valeur existante à la sauvegarde (nouvelle version, §10.7).
  - Tests frontend à ajouter en conséquence (rendu des trois branches,
    cohérence du choix d'aperçu SVG avec le backend).

### Logo surchargeable par objet et icône par défaut par classe (`tocheck.md` #16/#17 — `plan-mark3.md` action 4)

- **Icône de classe (#17)** : nouveau champ optionnel `"icon"` sur une
  classe dans `model/schema.json` (chaîne = identifiant choisi dans un
  **jeu fixe** d'icônes embarquées côté frontend, pas un upload libre —
  cohérent avec le texte `tocheck.md` : « sélection d'icône par défaut
  quand actif »). Sélecteur dans `ConfigurationPage.tsx` (grille des
  icônes du jeu fixe). Utilisée par `DiagramPage`/`NavigationPage` comme
  représentation par défaut d'un objet de cette classe, en dernier
  recours après le logo (ci-dessous) s'il existe.
- **Icône par défaut auto-récupérée (complément #17, demande
  2026-11-14)** : quand une classe n'a ni logo ni icône choisie
  manuellement, générer un défaut au lieu de retomber direct sur la
  couleur de palette (§6.4) :
  1. Fonction backend (module dédié, ex. `backend/class_icon.py`) qui
     prend un mot-clé (nom de la classe) et tente de récupérer un SVG
     correspondant sur svgrepo.com.
  2. **Homogénéisation** : les SVG de svgrepo.com ont des styles
     hétérogènes (tailles, couleurs, traits). Passer le SVG récupéré
     dans une étape de normalisation configurable — `viewBox` fixe,
     couleur de trait/remplissage recolorée vers une couleur unique
     (cohérent avec la palette actuelle par classe, §6.4), `stroke-width`
     normalisé — pilotée par une config centralisée (même pattern que
     `FILE_STORAGE_ROOT`/`SCHEMA_PATH` : constantes ou petit bloc JSON
     dédié), pour que toutes les icônes par défaut se ressemblent malgré
     des sources variées.
  3. **Fallback obligatoire** : si la recherche ne trouve rien ou que la
     requête échoue (réseau, timeout, SVG invalide), générer localement
     un SVG simple — un rond uni (couleur de palette de la classe,
     §6.4) avec le nom de la classe (ou ses initiales si trop long)
     centré dedans. Aucune dépendance externe sur ce chemin de repli.
  4. Résultat mis en cache/stocké (réutilise `FileStorage` de l'action 2
     une fois dispo, sinon fichier local) — pas d'appel réseau à chaque
     rendu de page, seulement à la création/configuration de la classe
     ou si forcé en rafraîchissement.
  5. ⚠️ **Point à trancher avant implémentation** : svgrepo.com n'a pas
     d'API de recherche publique documentée à ce jour — à vérifier
     (recherche par mot-clé côté site, convention d'URL de téléchargement
     par slug) et respecter leurs conditions d'usage/limites de débit
     avant de construire une dépendance dessus. Si indisponible ou trop
     fragile, le fallback rond+nom peut devenir le comportement par
     défaut permanent plutôt qu'un simple filet de sécurité.
- **Logo d'objet (#16)** : convention — une classe qui « a un logo »
  porte un attribut réservé de type `image` (ex. nom `logo`, domaine
  `display`), réutilisant intégralement la plomberie de l'action 3
  (upload/download, stockage versionné, aperçu+téléchargement §10.8
  IHM). Dans `NavigationPage.tsx`, l'aperçu du logo est **cliquable** et
  ouvre directement le sélecteur de fichier (pas de bouton séparé).
  `DiagramPage` reste en lecture seule côté rendu (`symbol:
  'image://<url de lecture>'`) — aucune interaction clic sur les nœuds
  n'est dans le périmètre de cette action.
- **Réutilisation d'un logo existant (décision utilisateur, 2026-11-14)**
  : sur un objet, l'UI permet d'importer un fichier **ou** de
  sélectionner un logo déjà présent parmi ceux d'autres objets de
  classes à logo. Tranché : le pointeur `attribute_value` **référence**
  le `(classe, object_id, attribut, version)` de l'*autre* objet (pas de
  duplication d'octets). Conséquences :
  - La purge différée (§10.4) doit compter les références croisées
    avant de supprimer une version de fichier — pas seulement
    l'historique propre de l'objet propriétaire — sinon supprimer
    l'objet source casserait le logo des objets qui le référencent.
  - Avertissement à la suppression d'un objet dont le logo est
    référencé ailleurs : souhaitable, pas strictement bloquant.
  - Garde-fou obligatoire : si le fichier référencé devient introuvable
    malgré tout (cas limite), l'affichage du logo doit nettoyer la
    valeur de l'attribut sur l'objet affecté plutôt que de rester cassé
    indéfiniment, pour retomber sur le fallback (icône de classe, puis
    couleur §6.4) dès l'affichage suivant.

> **Mise à jour (2026-11-21, fait) — décisions finales retenues**,
> remplaçant les points ouverts (⚠️) ci-dessus par leur tranchage réel :
> - **Sécurité SVG (point 6 ci-dessus)** : **pas de sanitization** du
>   contenu SVG à l'upload (jugée trop fragile sans lib dédiée) —
>   validation structurelle seule (XML bien formé, racine `<svg>`, via
>   `defusedxml` plutôt que `xml.etree.ElementTree` brut, pour éviter un
>   DoS par expansion d'entités XML) et **attachment systématique en
>   lecture, y compris pour le SVG** (jamais de rendu `<img>` inline pour
>   ce format, `backend/routes_files.py`) — neutralise le vecteur XSS
>   stocké sans prétendre nettoyer le contenu. Conséquence IHM : l'aperçu
>   `image` inline (`NavigationPage.tsx`) ne s'applique qu'aux formats
>   raster jpg/jpeg/png ; le SVG reçoit le même traitement que `file`
>   (téléchargement seul).
> - **svgrepo.com (point 1bis ci-dessus)** : non retenu — vérifié avant
>   implémentation, pas d'API de recherche publique documentée (404
>   constaté), page de recherche non scrappable de façon fiable. Le
>   fallback rond+initiales (`backend/class_icon.py`) devient le
>   comportement **permanent** dès le premier passage, pas un filet de
>   sécurité après tentative réseau : aucun appel réseau externe n'est
>   implémenté.
> - **Format de pointeur étendu** (réutilisation de logo par référence,
>   point ci-dessous) : `"ref:<classe>:<object_id>:<attribut>:<version>:
>   <nom_fichier>"`, construit par `POST .../file/<attribute>/reference`,
>   toujours aplati sur l'emplacement physique final — détail complet
>   (résolution, garde anti-chaîne, auto-réparation) : §4.6 de
>   [04-api-backend.md](04-api-backend.md).
> - **`POST /api/admin/sweep_orphan_files`** (`backend/routes_admin.py`,
>   action 3 point B de la revue croisée) : nettoyage des fichiers
>   orphelins (crash process entre écriture disque et commit), réservé
>   `global-admin`, référence-conscient (ne supprime jamais un fichier
>   encore référencé, directement ou via `ref:`, par un autre objet/
>   attribut) — détail : §4.6 de [04-api-backend.md](04-api-backend.md).
> - **2 itérations de bugfix post-revue croisée** (`plan-mark3.md` actions
>   3/4, statuts détaillés) :
>   1. `parseFilePointer` (`NavigationPage.tsx`) ne reconnaissait pas le
>      préfixe `ref:` → aperçu vide en édition pour un logo référencé ;
>      fix : parsing dédié qui saute les 5 premiers `:` et préserve un nom
>      de fichier contenant lui-même `:`.
>   2. `DiagramPage.tsx` rendait un logo via URL brute (`image://<url>`) —
>      bug permanent, pas transitoire : un `<img>`/ECharts ne peut jamais
>      attacher de header `Authorization: Bearer`, et le RBAC tenant est
>      *fail-closed* (`rbac.py`), donc tout objet tenant-scoped avec logo
>      était invisible dans le diagramme pour tout viewer ; fix :
>      résolution du logo via fetch authentifié (`apiReadObjectFileBlob`)
>      → object URL mis en cache, assigné au `symbol` une fois résolu,
>      fallback icône/couleur en attendant.
>   3. `_self_heal_broken_pointer` (`routes_files.py`) fermait aveuglément
>      la valeur active au moment de l'appel (race condition étroite avec
>      une réécriture concurrente) ; fix : filtre désormais sur le
>      `value_string` exact qui a échoué.
>
> Tests finaux : 157/157 (`backend/`, action 3), testeur-global 182/182
> (action 4) — voir `plan-mark3.md` actions 3 et 4 pour le détail complet.

Détail complet et suivi : `plan-mark3.md` actions 3 et 4.

> Statut courant (2026-11-21) : `plan-mark3.md` fait suite à `plan-mark2.md`
> sans report de backlog. Les 5 actions de `plan-mark3.md` sont closes :
> 1 (découpage `app.py` en Blueprints, fait), 2 (interface de stockage de
> fichiers, fait), 3 (types fichier/image/csv, fait), 4 (logo/icône de
> classe, fait), 5 (versionnage des fichiers modèle, fait). Action 6
> (synchronisation de `specifications/` avec les actions 1-5, dette
> documentaire) ajoutée ce jour — voir `plan-mark3.md`.
>
> **Mise à jour (2026-11-23)** : actions 7 à 14 également closes depuis —
> 7 (type `select`, fait, §10.9), 8 (type `secret`, fait, §10.10), 9 (type
> `datasource`, fait, §10.11), 10a-10d (framework dashboard, fait, §10.12 ;
> 10e exclu, hors scope), 12 (réorganisation de `backend/` en packages
> `auth`/`data`/`files`/`routes`/`tests`, fait, §2bis de
> [02-architecture.md](02-architecture.md)), 13 (IHM Configuration : les 11
> types d'attribut, fait, §10.12bis), 14 (champ `layers` et filtre IHM/
> diagramme, fait, §6.12 de [05-frontend.md](05-frontend.md)), 15
> (restructuration IHM menu/Sidebar/filtres texte, fait), 16
> (synchronisation de `specifications/` avec les actions 7-14, dette
> documentaire, fait). Action 11 (outil d'ingestion avec binding,
> §10.13) reste **à faire**.
>
> **Mise à jour (2026-11-23bis)** : 4 nouvelles actions **conçues,
> aucune implémentée** — 17 (extension du modèle CMDB embarqué :
> compute/cluster/applicatif/réseau/organisation/localisation/hardware/
> besoin, §10.14), 18 (layer dynamique piloté par un attribut `select`,
> §10.15), 19 (type d'attribut `boolean`, §10.16), 20 (autosuggest —
> suggestions de valeurs apprises sur un attribut texte, §10.17). Voir
> `plan-mark3.md` pour le détail et le statut de chacune.

## 10.9 Type d'attribut select/enum (`tocheck.md` #18, fait — `plan-mark3.md` action 7)

Idée : liste de valeurs fixes (ex. statut, priorité) pour un usage type
workflow de ticket — l'attribut ne pointe pas vers un autre objet, il ne
peut prendre qu'une valeur parmi un ensemble déclaré sur sa propre
définition.

Conception :
- Nouveau type `"select"` ajouté à l'enum `attributes[].type` de
  `model/schema.json` (plutôt que `"enum"` : `type` est déjà le mot-clé
  JSON Schema natif qui porte la liste de types possibles d'un attribut,
  et `"enum"` comme *valeur* de ce `type` entrerait en collision de sens
  avec le mot-clé JSON Schema `enum` lui-même, utilisé en interne pour
  contraindre ce même champ `type` — `"select"` nomme le type sans cette
  ambiguïté).
- Nouveau champ `"values"` (tableau de chaînes, ex.
  `["ouvert", "en_cours", "ferme"]`) au même niveau que `classes` pour
  `joint-1-1`/`joint-1-n` ou `separator` pour `csv` — propriété de la
  définition d'attribut dans le schéma, pas de chaque valeur stockée.
  `required` si `type: select` — même intention que le `required:
  ["classes"]` déjà posé pour les types jointure, mais pas réemployable
  tel quel : `model/schema.json` (lignes 91-97) porte aujourd'hui un
  seul couple `if/then` en sibling dans l'objet attribut, et JSON
  Schema interdit deux couples `if/then` sœurs dans le même objet.
  Ajouter cette 2e condition suppose de restructurer en `allOf:
  [{if,then}, {if,then}]` à deux branches.
  ⚠️ Point ouvert : forme exacte de cette restructuration (`allOf` à
  trancher à l'implémentation, pas un simple réemploi du mécanisme
  existant).
- Stockage : `value_string` existant suffit (la valeur sélectionnée est
  une des chaînes de `values`) — aucune nouvelle colonne, contrainte
  `CHECK` de `attribute_value` inchangée.
- Validation : à l'écriture, vérifier côté serveur que la valeur soumise
  appartient à `values` déclaré sur l'attribut, sinon rejet 400 — même
  esprit que `constraint` (regex, type string only) mais une autre
  forme de contrôle (appartenance à un ensemble fini plutôt qu'un motif).
- IHM (`NavigationPage.tsx`) : nouvelle branche de rendu `<select>`/
  dropdown, au même titre que les branches dédiées déjà prévues pour
  `file`/`image`/`csv` (§10.8) — sans cette branche, le type tomberait
  dans le champ texte générique.
- Différence explicite avec `joint-1-1`/`joint-1-n` : pas de référence à
  un autre objet ni à une classe cible, les valeurs possibles sont
  fixes et inlinées dans la définition d'attribut elle-même — deux
  patterns distincts à ne pas confondre.
- ⚠️ Point ouvert : renommage ou suppression d'une valeur de `values`
  déjà utilisée par des `attribute_value` existants — valeurs orphelines
  possibles (une ligne historisée continue de porter une chaîne qui ne
  figure plus dans `values`), aucune migration automatique prévue ici.

> **Mise à jour (2026-11-23, fait)** : conception ci-dessus implémentée
> sans écart majeur — `allOf` restructuré en **2 branches** (pas 3,
> `datasource` ajouté à l'enum de la 1ère branche aux côtés de
> `joint-1-1`/`joint-1-n` plutôt qu'une 3e couple `if`/`then` séparée,
> action 9 de `plan-mark3.md`), `_coerce_typed_value`
> (`backend/routes/routes_write.py`) valide l'appartenance à `values`.
> IHM : branche `<select>` dédiée dans le formulaire **et** l'édition
> inline de cellule de `NavigationPage.tsx` (2e branche ajoutée en
> itération 2, suite revue croisée — absente de l'itération 1).
> `ConfigurationPage.tsx` gère désormais aussi ce type (dette comblée par
> l'action 13, §10.12bis ci-dessous). Détail complet : §4.7 de
> [04-api-backend.md](04-api-backend.md), §3.2ter de
> [03-modele-donnees.md](03-modele-donnees.md), §6.9 de
> [05-frontend.md](05-frontend.md). Point ouvert toujours non traité
> (volontairement) : pas de migration automatique si `values` est réduit
> après coup sur un attribut déjà utilisé.

Détail complet et suivi : `plan-mark3.md` action 7.

## 10.10 Type d'attribut secret/password (`tocheck.md` #19, fait — `plan-mark3.md` action 8)

⚠️ Le score de difficulté 2/5 affiché dans `tocheck.md` ne reflète que
l'effort perçu avant analyse — à ne pas sous-estimer sur cette base :
cette section demande un chiffrement réel, pas un simple masquage
d'affichage, et plusieurs points restent explicitement non tranchés
ci-dessous.

- Nouveau type `"secret"` ajouté à l'enum `attributes[].type`.
- Stockage : valeur chiffrée dans `value_string` (jamais en clair). La
  bibliothèque `cryptography` est déjà présente dans
  `backend/requirements.txt` (utilisée aujourd'hui pour d'autres besoins
  du projet) — candidate naturelle pour un chiffrement symétrique type
  Fernet/AES-GCM, à vérifier/confirmer à l'implémentation plutôt qu'une
  nouvelle dépendance à ajouter.
- ⚠️ Gestion de clé, non tranchée : où est stockée la clé de
  chiffrement — une variable d'environnement type
  `SECRET_ENCRYPTION_KEY` (même pattern que `FILE_STORAGE_ROOT`/
  `SCHEMA_PATH`) ou un KMS externe (probablement hors scope à ce
  stade) ? Clé unique globale, ou une clé par tenant (RBAC multi-tenant
  existant, `backend/rbac.py`) ? Qui peut déchiffrer : est-ce un simple
  flag « masqué à l'affichage » réversible par quiconque a accès à
  l'API, ou un chiffrement réellement opaque, y compris pour un
  administrateur qui n'aurait pas la clé ? Ces questions sont posées
  ici comme point ouvert, volontairement non tranchées.
- ⚠️ Masquage à l'affichage, non tranché : `GET` ne doit jamais renvoyer
  la valeur déchiffrée en clair par défaut (comportement différent de
  tous les autres types d'attribut) — soit un flag `?reveal=true` avec
  un contrôle RBAC renforcé par rapport à la lecture générique, soit
  aucun déchiffrement via l'API de lecture générique et uniquement une
  route dédiée avec une permission spécifique. Choix à faire à
  l'implémentation.
- Historisation (`valid_from`/`valid_to`, §10.4) : une valeur secrète
  historisée reste chiffrée dans les versions passées aussi — aucune
  différence de traitement par rapport au reste du modèle.
- IHM : `<input type="password">` à la saisie, jamais pré-rempli avec la
  valeur réelle déchiffrée en édition — affichage de points/placeholder
  uniquement, comme un formulaire classique de changement de mot de
  passe.

> **Mise à jour (2026-11-23, fait) — les 3 points ouverts tranchés par
> l'utilisateur (2026-11-22)** : clé de chiffrement Fernet **globale**
> (pas par tenant) via `SECRET_ENCRYPTION_KEY`, lue dynamiquement (jamais
> mise en cache au démarrage, `backend/secret_crypto.py`) ; masquage
> **strict** en lecture générique (placeholder fixe, jamais de
> déchiffrement implicite) **avec une route reveal dédiée réservée
> global-admin uniquement** (jamais un tenant-admin, même dans son propre
> périmètre) — `GET /api/read/object/<id>/secret/<attribute>` ; écriture
> via le JSON classique de `POST /api/write/object` (pas de route dédiée),
> chiffrement effectué dans `_coerce_typed_value`. **Correctif
> post-revue** : `secret` ajouté au garde-fou d'écriture par URL (`PUT
> /api/write/attribute/...`), oubli initial aligné avec `file`/`image`/
> `csv`. Détail complet (RBAC, fail-fast vs runtime, non-déduplication
> Fernet) : §4.7 de [04-api-backend.md](04-api-backend.md), §3.2ter de
> [03-modele-donnees.md](03-modele-donnees.md), §6.9 de
> [05-frontend.md](05-frontend.md). Limite connue acceptée, non corrigée :
> aucune voie API pour fermer explicitement un attribut `secret` existant
> sans le remplacer.

Détail complet et suivi : `plan-mark3.md` action 8.

## 10.11 Type d'attribut datasource (`tocheck.md` #1, fait — `plan-mark3.md` action 9)

Idée : type d'attribut porté par une définition JSON et une meta-class
(ex. Prometheus, PostgreSQL). `tocheck.md` le note explicitement comme
prérequis conceptuel des idées ML/ingestion (#2, #6, #7, #8) — simple
rappel de dépendance future, ces idées ne sont ni conçues ni engagées
ici.

- Nouveau type `"datasource"` ajouté à l'enum `attributes[].type`.
- Champ complémentaire portant une définition structurée du type de
  source (ex. `"datasource_kind"`, ou un sous-schéma imbriqué décrivant
  Prometheus/PostgreSQL/etc. et les paramètres de connexion).
- ⚠️ Point ouvert, à ne pas trancher ici : faut-il une meta-class
  dédiée par type de datasource (ex. une classe `datasource_prometheus`
  portant ses propres attributs de connexion, en réutilisant le modèle
  objet dynamique existant) plutôt qu'un blob JSON opaque dans la
  définition d'attribut — cohérence à rechercher avec le principe déjà
  en place du projet (modèle entièrement dynamique, §1) plutôt que
  d'introduire un format propriétaire de plus.
- Stockage de la valeur : probablement `value_string` = pointeur/
  identifiant vers la config de connexion, pas les identifiants de
  connexion en clair dans l'attribut lui-même — ⚠️ risque de sécurité du
  même ordre que §10.10 (secrets de connexion), à traiter en cohérence
  avec cette section si les deux se font un jour.
- Pas de câblage d'exécution de requête ici (ça reste #7/#8 de
  `tocheck.md`, hors scope, non demandé) — uniquement la définition du
  type et son schéma.

> **Mise à jour (2026-11-23, fait) — point ouvert tranché par
> l'utilisateur (2026-11-22)** : **meta-classe dédiée par type de
> datasource** retenue (ex. `datasource_prometheus`), **pas** un blob
> JSON opaque — réutilisation intégrale du modèle objet dynamique
> existant (classes/attributs `model/*.json`, RBAC tenant, historisation).
> Nouveau fichier `model/datasource.json` (démo : classes
> `datasource_prometheus` et `query`, voir §3.2ter de
> [03-modele-donnees.md](03-modele-donnees.md)). Le champ `classes` —
> déjà requis pour `joint-1-1`/`joint-1-n` — est réutilisé tel quel pour
> les classes cibles autorisées. Validation serveur **plus stricte**
> qu'une jointure ordinaire (classe + tenant de la cible vérifiés,
> `abort(400)`/`abort(403)`), cascade de fermeture à la suppression de
> l'objet cible — détail complet : §4.7 de
> [04-api-backend.md](04-api-backend.md). Aucun câblage d'exécution de
> requête (pas de route interrogeant Prometheus) : uniquement le type, la
> référence, et la meta-classe de démo, comme prévu. Report explicite
> confirmé : aucun champ credential/secret sur `datasource_prometheus` à
> ce jour (le jour où ce besoin apparaît, il devra utiliser le type
> `secret` de §10.10, jamais un champ texte en clair).

Détail complet et suivi : `plan-mark3.md` action 9.

## 10.12 Framework de dashboard/affichage configurable (`tocheck.md` #9, actions 10a-10d fait, 10e hors scope — `plan-mark3.md` actions 10a-10d)

`tocheck.md` qualifie cette idée de « gros chantier frontend, à
découper en sous-actions ». Ce qui suit n'est donc pas un design détaillé
d'implémentation mais un **découpage proposé** en sous-actions, à
affiner/valider avant toute écriture de code — même prudence de portée
que l'action 2 du plan (brique isolée, pas de câblage prématuré) :

- **10a** : modèle de données d'un « dashboard »/« tab » configurable —
  où stocker la config (nouvelle classe du modèle dynamique existant, ou
  table applicative dédiée ?).
- **10b** : IHM minimale en lecture seule d'un dashboard existant (rendu
  d'une config statique déjà en base).
- **10c** : édition des tabs dans l'IHM (CRUD de la config).
- **10d** : sélection des sous-objets affichés par tab (filtre/requête
  configurable).
- **10e** : (si pertinent) lien avec `tocheck.md` #10 — générer des
  displays en lecture seule à partir des tabs éditées, avec RBAC fin par
  vue ; idée **suivante**, non incluse ici, dépendante de #9.

⚠️ Ce découpage lui-même reste à valider/affiner avant de devenir des
actions trackées dans un futur `plan-markN.md` — il n'est pas figé.

> **Mise à jour (2026-11-23)** : découpage validé le 2026-11-22 et
> **10a-10d livrés**, **10e exclu** (dépend de `tocheck.md` #10, non
> engagé). Conception tranchée par l'orchestrateur (pas de blob JSON) :
> meta-classe dynamique `dashboard` (`model/dashboard.json`), deux
> classes `dashboard` (`name`) et `tab` (`name`, `dashboard` en
> `joint-1-1`, `target_meta_class`/`target_class` string libres — deux
> champs séparés car une meta-classe peut porter plusieurs classes —
> et, ajoutés en 10d, `filter_attribute`/`filter_value` optionnels,
> égalité stricte après extraction d'id de jointure). **Aucune table
> applicative dédiée, aucun code backend nouveau** (10a confirmé par
> grep exhaustif : `routes_init.py` charge tout `model/*.json` sans
> whitelist/blacklist de meta-classe). IHM 100% dans
> `frontend/src/pages/DashboardPage.tsx` (nouvelle page, 4e bouton
> Navbar), bâtie sur les routes génériques d'objets — aucune route
> dédiée dashboard. Détail complet (rendu, CRUD, filtre, bugs
> corrigés en revue croisée) : §6.11 de
> [05-frontend.md](05-frontend.md), §3.2ter de
> [03-modele-donnees.md](03-modele-donnees.md).

Détail complet et suivi : `plan-mark3.md` actions 10a-10d.

## 10.12bis IHM de configuration : les 11 types d'attribut (`tocheck.md` #14-20, fait — `plan-mark3.md` action 13)

Dette technique signalée et acceptée à chaque action concernée
(§10.8/§10.9/§10.11 ci-dessus) : `frontend/src/pages/ConfigurationPage.tsx`
(IHM admin de création/édition de classe) limitait `ATTR_TYPES` à 5 types
(`string`/`integer`/`float`/`joint-1-1`/`joint-1-n`) alors que le backend/
schema supportaient déjà 11 types depuis les actions 3 (`file`/`image`/
`csv`), 7 (`select`), 8 (`secret`), 9 (`datasource`). Corrigé : `ATTR_TYPES`
étendu aux 11 types, colonne « Options » dédiée par type (réutilisation du
bloc classes cibles pour `joint-1-1`/`joint-1-n`/`datasource`, nouvel
éditeur de chips pour `select`, input `separator` pour `csv`), validation
front bloquante ajoutée (classes/values vides refusées à la sauvegarde —
comble un trou réel du schema JSON, qui n'impose que la présence de la clé
via `required`, pas `minItems`). Détail complet : §6.10 de
[05-frontend.md](05-frontend.md).

Détail complet et suivi : `plan-mark3.md` action 13.

## 10.13 Outil d'ingestion avec binding (`tocheck.md` #11, conçu)

Idée : mapping champs source → attributs, pensé comme fondation
réutilisable (CSV, API...).

Conception à esquisser :
- Définition d'un « mapping »/« binding » : format (probablement JSON)
  décrivant source → champ → attribut cible d'une classe.
- Réutilisation du type `csv` existant (§10.8) comme première source
  d'entrée possible, ou upload direct.
- ⚠️ Point ouvert : où est stockée la config de binding — nouvelle
  classe du modèle dynamique, comme envisagé pour §10.12 ? Cohérence à
  rechercher avec §10.12 si les deux se font un jour : les deux ont
  besoin d'un endroit pour stocker de la config applicative, pas des
  objets métier.
- Pas d'exécution ni de scheduler ici (ça reste `tocheck.md` #12, hors
  scope, non demandé).

Détail complet et suivi : `plan-mark3.md` action 11.

## 10.14 Extension du modèle CMDB embarqué (conçu, pas implémenté — `plan-mark3.md` action 17)

> Demande utilisateur (2026-11-23) : enrichir le modèle `model/*.json`
> embarqué (compute, applicatif, réseau, organisation, localisation,
> société, hardware, besoin) avant d'attaquer les dashboards (action
> 10b-10d), pour avoir un jeu de données/classes représentatif. Décisions
> prises au fil de l'échange, consolidées ici — pure conception, **rien
> n'est codé**, c'est le rôle de `plan-mark3.md` action 17.

Chaque classe ci-dessous porte un champ `layers` (action 14) choisi
parmi la taxonomie retenue : `applicatif` / `infra` / `organisationnel`
/ `fonctionnel` / `metier`, cumulable avec les tags déjà en usage
`physique` / `reseau` / `securite` (ex. `serveur` = `infra`+`physique`+
`reseau`).

### Compute (`model/itil_cmdb.json`, meta-classe `cmdb`, extension)

- `baie_serveur` 🆕 : `nom`, `datacenter` (joint-1-1 → `datacenter`),
  `position_rack`. Layers : `infra`, `physique`.
- `serveur` (existant) : ajout `type` (`select`, `physique`/`vm`),
  `hyperviseur` (joint-1-1 → `hyperviseur`, uniquement pertinent si
  `type=vm`), `os` (joint-1-1 → `os`, nouvelle classe ci-dessous). Le
  tag `layers` statique actuel (`physique`+`reseau`) est **faux** pour
  un serveur VM — résolu par §10.15 (layer dynamique piloté par
  `type`), pas ici.
- `os` 🆕 : `nom` (`string`, autosuggest §10.17 envisageable, non
  tranché), `type` (`select`, `linux`/`windows`), `architecture`
  (`select`, `32`/`64`/`arm`), `version` (`string`), `code_version`
  (`string`), `active` (`boolean`, nouveau type §10.16 — bloquant tant
  que §10.16 n'est pas livré). Layers : `infra`.

### Cluster (nouvelle meta-classe `model/cluster.json`)

> Décision explicite : 2 classes distinctes `kube`/`hyperviseur` plutôt
> qu'une classe générique `cluster`+`type` — pour pouvoir rattacher des
> VMs à un hyperviseur et des déploiements à un cluster Kubernetes sans
> confondre les deux modèles de rattachement.

- `kube` 🆕 : `nom`, `version`, `namespace_defaut`. Layers : `infra`.
- `hyperviseur` 🆕 : `nom`, `type` (ex. vmware/proxmox), `capacite_cpu`,
  `capacite_ram`. Layers : `infra`.
- `cluster_applicatif` 🆕 : `nom`, `vip` (joint-1-1 → `addresse_ip`,
  réutilise la classe réseau existante plutôt qu'un string brut),
  `application` (joint-1-1 → `application`), `serveurs` (joint-1-n →
  `serveur`). Regroupe plusieurs serveurs hébergeant la même
  application derrière une VIP commune (HA/LB) — distinct de
  `hyperviseur` (hébergement VM) et `kube` (déploiements conteneurs).
  Layers : `applicatif`, `infra`.

### Applicatif, modules et versioning (`cmdb`, extension)

- `application` (existant) : ajout `modules` (joint-1-n → `module`).
- `module` 🆕 : `nom`, `application` (joint-1-1 → `application`).
  Layers : `applicatif`.
- `container` 🆕 : `nom`, `image`, `namespace_kubernetes` (joint-1-1).
  Layers : `applicatif`, `infra`.
- `namespace_kubernetes` 🆕 : `nom`, `kube` (joint-1-1 → `kube`).
  Layers : `applicatif`, `infra`.
- `interface` 🆕 : `nom`, `type` (`select`, ex.
  REST/SOAP/file/queue/db), `application` (joint-1-1, propriétaire du
  contrat exposé). Layers : `applicatif`, `fonctionnel`.
- `flux_donnee` 🆕 : `nom`, `type_donnee` (`string`), `interface_source`
  (joint-1-1 → `interface`), `interface_cible` (joint-1-1 →
  `interface`) — passe par le contrat exposé (`interface`) plutôt que
  par un lien direct `application`→`application`, pour garder la
  notion de contrat/format échangé. Layers : `fonctionnel`, `metier`.
- `application_versionnee` 🆕 : `application` (joint-1-1), `version`
  (`string`, **autosuggest**, §10.17), `modules_versionnes` (joint-1-n
  → `module_versionne`). Layers : `applicatif`.
- `module_versionne` 🆕 : `module` (joint-1-1), `version` (`string`,
  **autosuggest**, §10.17). Layers : `applicatif`.
- Chaîne de résolution : `application` →1-n→ `application_versionnee`
  →1-n→ `module_versionne` →1-1→ `module` →1-1→ `application` — une
  version d'application donne directement les versions de modules qui
  la composent.
- ⚠️ Chevauchement repéré, non résolu : `model/ansible_inventory.json`
  porte déjà `version_logicielle` (`version`, `environnement`,
  `date_deploiement`, `application` joint-1-1) — rôle proche de
  `application_versionnee`. À clarifier/fusionner à l'implémentation,
  pas tranché ici.

### Réseau (`model/reseau.json`, extension)

- `addresse_ip` (existant) : ajout `vlan` (joint-1-1 → `vlan`, sens
  inverse du `membres` existant sur `vlan`, pour naviguer depuis une IP
  vers son VLAN).
- `vlan` (existant) : **pas de classe `subnet` séparée** —
  `vlan.definition` porte déjà le CIDR, un `vlan` **est** déjà le
  subnet dans ce modèle. Point explicitement vérifié avant d'écrire
  cette section (évite un doublon qui avait été proposé puis écarté en
  cours d'échange).
- `zone_reseau` 🆕 (area/DMZ) : `nom`, `niveau_securite`. Layers :
  `infra`, `reseau`, `securite`.
- `equipement_reseau` 🆕 : `nom`, `type` (`select`,
  routeur/switch/firewall), `zone` (joint-1-1 → `zone_reseau`). ⚠️ Point
  ouvert, jamais tranché explicitement par l'utilisateur : classe
  unique `equipement_reseau`+`type` (recommandé ici, cohérent avec le
  pattern déjà retenu pour `serveur.type`) vs 3 classes séparées
  `routeur`/`switch`/`firewall` (plus de champs spécifiques possibles
  par type, mais plus de duplication). À confirmer à l'implémentation.
  Layers : `infra`, `reseau`.
- `entree_dns` 🆕 : `nom`, `type` (`select`, A/CNAME/MX/...), `cible`
  (`string`), `zone_dns` (`string`). Layers : `infra`, `reseau`.

### Organisation (nouvelle meta-classe `model/organisation.json`, remplace `organigramme.json`+`personnes.json`)

> Décision explicite : unifier `service_organisation`/`poste` (actuel
> `organigramme.json`) et `personne_physique`/`role`/`groupe` (actuel
> `personnes.json`) en **une seule** meta-classe.

- `societe` 🆕 : `nom`, `holding` (joint-1-1, auto-référence — même
  pattern que `service_parent` existant sur `service_organisation`).
- `departement` 🆕 : `nom`, `societe` (joint-1-1 → `societe`).
- `service_organisation` (repris tel quel) : `nom`, `responsable`
  (joint-1-1), `service_parent` (joint-1-1).
- `poste` (repris tel quel).
- `personne_physique` (repris tel quel).
- `role` (repris tel quel).
- `groupe` (repris tel quel).
- `contact` 🆕 : `type` (`select`, tel/mail), `valeur` (`string`),
  `cible` (joint-1-1, `classes: ["personne_physique", "societe",
  "service_organisation", "departement"]` — un joint-1-1 ciblant
  plusieurs classes à la fois est déjà nativement supporté par le
  schéma, rien de nouveau à construire ici).
- Layers : `organisationnel` (+ `metier` pour `societe`).

### Localisation (nouvelle meta-classe `model/localisation.json`)

- `batiment` 🆕 : adresse structurée en 7 champs `string` plutôt qu'un
  champ libre — `numero`, `type_voie` (ex. rue/avenue/boulevard),
  `nom_voie`, `pays`, `code_postal`, `ville`, `suffixe_ville` (optionnel,
  ex. « cedex »).
- `etage` 🆕 : `nom`, `batiment` (joint-1-1).
- `salle` 🆕 : `nom`, `etage` (joint-1-1).
- Layers : `infra`.
- `datacenter`/`baie_serveur` (`cmdb`) pourraient pointer `salle`
  (joint-1-1) plutôt que le `localisation: string` libre actuel sur
  `datacenter` — changement à faire sur `datacenter` en même temps que
  cette section si retenu.

### Hardware (`cmdb`, extension)

- `materiel` 🆕 : `nom`, `type` (`select`, ex.
  poste/imprimante/peripherique), `numero_serie`, `personne_affectee`
  (joint-1-1 → `personne_physique`), `salle` (joint-1-1 → `salle`).
  Layers : `infra`, `physique`. ⚠️ Point ouvert, jamais tranché :
  classe générique `materiel`+`type` (recommandé, cohérent avec
  `serveur.type`/`equipement_reseau.type`) vs une classe par type de
  matériel.

### Besoin (nouvelle classe, meta-classe à déterminer à l'implémentation)

- `besoin` 🆕 : `nom`, `description`, `emerge_par` (joint-1-n, objets
  qui font émerger ce besoin), `couvert_par` (joint-1-n, objets qui
  répondent à ce besoin) — les deux dans le domaine d'attribut
  `requirement` (groupage visuel gratuit dans l'IHM, le champ `domain`
  existe déjà sur tout attribut, aucune nouvelle brique nécessaire pour
  ça). Layers : `fonctionnel`, `metier`. ⚠️ Point ouvert, jamais
  tranché : `emerge_par`/`couvert_par` doivent cibler quelles classes ?
  Recommandé ici : les CI techniques (`serveur`, `application`,
  `cluster_applicatif`, `kube`, `hyperviseur`, `materiel`, `interface`,
  `module`), pas la totalité des ~20+ classes du modèle (personne/
  société/tâche n'ont a priori pas besoin de ce lien) — à confirmer à
  l'implémentation.

### Retouches sur les meta-classes existantes

- `model/ticketing.json` : `ticket.ci_concerne.classes` à réétendre
  pour couvrir les nouvelles classes CMDB/hardware ajoutées ci-dessus
  (actuellement limité aux 7 classes d'origine de `cmdb`).
- `model/planning.json` : `tache.assigne_a.classes` élargi à
  `["personne_physique", "groupe"]` (`groupe` existe déjà) — une tâche
  assignable à une personne **ou** une équipe.

Détail complet et suivi : `plan-mark3.md` action 17.

## 10.15 Layer dynamique piloté par un attribut `select` (conçu, pas implémenté — `plan-mark3.md` action 18)

> Demande utilisateur (2026-11-23) : un `serveur` ne peut pas porter le
> layer `physique` de façon statique si son `type` est `vm` — le champ
> `layers` de l'action 14 (statique par classe) ne suffit plus dès
> qu'un attribut de l'objet (ex. `type`) doit influencer le layer
> effectif. Demande explicite : configurer, sur un attribut `select`,
> une correspondance valeur → layer(s), éditable dans
> `ConfigurationPage.tsx`.

⚠️ Changement d'architecture par rapport à l'action 14 (pas un simple
ajout de champ) : les layers deviennent **par objet** (dépendants de la
valeur choisie sur un attribut `select` donné), pas uniquement par
classe. Le filtre (`Sidebar.tsx`/`NavigationPage.tsx`/`DiagramPage.tsx`)
devra, pour un attribut `select` marqué comme pilotant le layer,
résoudre le layer effectif à partir de la valeur réellement stockée sur
chaque objet — pas uniquement lire `classDef.layers` comme aujourd'hui.

Conception à esquisser (aucune implémentation) :
- `model/schema.json` : sur une définition d'attribut `type: select`,
  nouveau champ optionnel `layer_map` (objet `{valeur: [layers]}`,
  sous-ensemble de `values`). La seule présence de `layer_map` marque
  cet attribut comme pilotant le layer — pas de flag booléen séparé
  redondant (cohérent avec le pattern déjà en place : `values` requis
  sur `select` sans flag "a des valeurs" à côté).
- Layer effectif d'un objet = union(`classDef.layers` statique,
  `layer_map[valeur_actuelle]` pour chaque attribut `select` qui porte
  un `layer_map`).
- Portée du changement : la Sidebar (arbre meta_class/layer, action 15)
  reste basée sur `classDef.layers` statique uniquement — elle liste
  des **classes**, pas des objets, un layer dynamique par objet n'a pas
  de sens à ce niveau. Seuls `NavigationPage.tsx`/`DiagramPage.tsx`
  (qui manipulent des objets réels, pas juste des définitions de
  classe) ont besoin de résoudre le layer effectif par objet.
- `backend/routes/routes_read.py` : aucun changement a priori — le
  calcul reste 100% frontend à partir des `values` déjà renvoyées par
  la lecture d'objet standard, cohérent avec le principe déjà posé à
  l'action 14 (filtre layers = pas un mécanisme RBAC/sécurité).
- `ConfigurationPage.tsx` : UI d'édition de `layer_map` sur un attribut
  `select` — pour chaque valeur de `values[]`, un sélecteur de layers
  (réutilisation du pattern chips déjà construit pour l'éditeur `layers`
  de classe, action 14).
- ⚠️ Point ouvert : objets dont le détail n'est pas encore chargé au
  moment du filtre (concerne surtout `NavigationPage.tsx`, chargement
  lazy par groupe) — repli recommandé sur `classDef.layers` statique
  seul tant que le détail n'est pas disponible, pas de blocage/attente.

Détail complet et suivi : `plan-mark3.md` action 18.

## 10.16 Type d'attribut `boolean` (conçu, pas implémenté — `plan-mark3.md` action 19)

> Demande utilisateur (2026-11-23), née du besoin `os.active` (§10.14) :
> aucun type booléen n'existe dans le schéma actuel (`string`/
> `integer`/`float`/`joint-1-1`/`joint-1-n`/`file`/`image`/`csv`/
> `select`/`datasource`/`secret`, 11 types).

Conception à esquisser :
- `model/schema.json` : ajout `"boolean"` à l'enum `attributes[].type`
  — pas de champ requis supplémentaire (contrairement à
  `select`/`joint-*`/`datasource`), le type le plus simple du jeu
  actuel avec `string`/`integer`/`float`.
- Stockage : réutilisation de `value_string` (`"true"`/`"false"`),
  aucune nouvelle colonne SQL — même principe que tous les types
  scalaires existants.
- `backend/routes/routes_write.py` (`_coerce_typed_value`) : accepte un
  booléen JSON (`true`/`false`), `abort(400)` sinon ; stocke en texte.
- `frontend/src/pages/NavigationPage.tsx` : rendu/édition en case à
  cocher — **dans le formulaire modal ET dans l'édition inline de
  cellule** (rappel explicite : l'action 7 avait oublié l'édition
  inline au premier passage, corrigé en itération 2 — ne pas reproduire
  l'oubli dès ce premier passage, cf. actions 9/13).
- `frontend/src/pages/ConfigurationPage.tsx` : `ATTR_TYPES` étendu à 12
  types, `boolean` affiche « Aucune option » (comme `file`/`image`/
  `secret`).

Détail complet et suivi : `plan-mark3.md` action 19.

## 10.17 Autosuggest : suggestions de valeurs apprises sur un attribut texte (conçu, pas implémenté — `plan-mark3.md` action 20)

> Demande utilisateur (2026-11-23), née du besoin de champs texte
> répétitifs (ex. `ville`/`pays` de `batiment` §10.14,
> `application_versionnee.version`/`module_versionne.version`) :
> suggestions auto-apprises à partir des valeurs déjà saisies par les
> utilisateurs (pas une liste figée comme `select`), classées par
> proximité textuelle avec la saisie en cours. 3 points tranchés par
> l'utilisateur : nom du flag **`autosuggest`**, suggestions basées sur
> les **valeurs actives seulement** (pas tout l'historique, pour ne pas
> proposer une faute de frappe corrigée depuis), tri par distance
> d'édition via la librairie **`rapidfuzz`** (pas de réimplémentation
> maison).

Conception à esquisser :
- `model/schema.json` : nouveau champ optionnel `"autosuggest": true`
  sur une définition d'attribut `type: string` uniquement. Sans objet
  pour les autres types (même convention documentaire que `separator`/
  `values`/`classes`).
- `backend/requirements.txt` : ajout de la dépendance `rapidfuzz`.
- Nouvelle route `GET /api/suggest/<meta_class>/<class>/<attribute>
  ?q=<saisie>` : `SELECT DISTINCT value_string FROM attribute_value
  WHERE ... AND valid_to IS NULL` (valeurs actives seulement, décision
  utilisateur) pour le triplet (meta_class, class, attribute), RBAC
  tenant identique aux autres routes de lecture, tri par distance
  d'édition (`rapidfuzz.fuzz`/`process.extract`) entre `q` et chaque
  valeur candidate, top N (ex. 10) renvoyé.
- `frontend/src/pages/NavigationPage.tsx` : champ texte + dropdown de
  suggestions (fetch débouncé sur la nouvelle route) pour tout attribut
  `autosuggest` — **dans le formulaire modal ET dans l'édition inline
  de cellule** (même rappel explicite qu'au §10.16 : ne pas oublier
  l'inline dès ce premier passage).
- `frontend/src/pages/ConfigurationPage.tsx` : case à cocher
  « Suggestion auto (valeurs déjà saisies) » sur un attribut `string`.
- ⚠️ Non tranché par l'utilisateur, à décider à l'implémentation :
  activer `autosuggest` sur `os.nom`/`os.version` (§10.14) en plus de
  `application_versionnee.version`/`module_versionne.version`
  (explicitement demandés) — cohérent avec le pattern mais pas demandé
  nommément.

Détail complet et suivi : `plan-mark3.md` action 20.

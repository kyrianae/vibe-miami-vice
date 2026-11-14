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

## 10.7 Stockage de fichiers (tranché — `plan-mark3.md` action 2)

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

## 10.8 Types d'attribut fichier/image/csv, logo d'objet, icône de classe (conçu — `plan-mark3.md` actions 3-4)

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

Détail complet et suivi : `plan-mark3.md` actions 3 et 4.

> Statut courant (2026-11-13) : `plan-mark3.md` fait suite à `plan-mark2.md`
> sans report de backlog. Actions ouvertes à ce jour : 1 (découpage
> `app.py`, fait), 2 (interface de stockage de fichiers, en cours de
> revue croisée), 3 (types fichier/image, à faire), 4 (logo/icône, à
> faire).

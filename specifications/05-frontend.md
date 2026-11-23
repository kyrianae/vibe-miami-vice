# 6. Frontend

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

## 6.1 Structure générale

- `main.tsx` : point d'entrée, monte `<App />` dans `#root` (mode
  `StrictMode`).
- `App.tsx` : état global applicatif tenu en `useState` local (pas de
  state manager externe, pas de routeur — la « page » active est une
  simple variable d'état, type `Page` élargi à `'navigation' |
  'configuration' | 'diagramme' | 'dashboard'` depuis l'action 10b,
  §6.11) : page courante, repli de la sidebar, bascule lecture seule
  (`readOnly`), thème (`'dark' | 'midnight' | 'light'`), meta-classe/
  classe sélectionnées (partagées entre Sidebar et la page affichée), et
  depuis l'action 14 `selectedLayers: Set<string>` (§6.12, seul état
  persisté — en `localStorage` — le reste ne l'est toujours pas). Le
  thème est appliqué en posant l'attribut `data-theme` sur `<html>`.
  Thème/`readOnly`/sidebar ouverte restent non persistés : un rechargement
  de page les réinitialise toujours à `dark`, lecture-écriture, sidebar
  ouverte.
- `components/Navbar.tsx` : titre, **4** boutons de changement de page —
  ordre depuis l'action 15 (§6.13) : Configuration, Navigation, Diagramme,
  Dashboard (Configuration passée en tête ; ce dernier bouton Dashboard
  ajouté par l'action 10b, §6.11) —, sélecteur de thème, interrupteur
  RO/RW.
- `components/Sidebar.tsx` : charge `apiReadClasses()` au montage et à
  chaque changement de page. Depuis l'action 15 (§6.13) : un champ texte
  filtre (sous-chaîne, insensible casse, sur classe et/ou meta-classe)
  s'applique aux deux arbres ci-dessous ; deux arbres coexistent — « par
  meta-classe » (existant) et « par layer » (nouveau, une classe apparaît
  sous chaque layer de `c.layers`, doublons acceptés, classes sans layer
  absentes de cette section) —, chaque groupe repliable/dépliable
  indépendamment et **replié par défaut** (état local distinct de la
  sélection active) ; et une section `layers` sous les deux arbres — chips
  togglables sur Navigation/Configuration, combo-list (`<select
  multiple>`) sur Diagramme (§6.13), pilotant `selectedLayers`. Le choix
  dans les arbres alimente les pages via les props
  `selectedMetaClass`/`selectedClass`/`selectedLayers` de `App.tsx` ; sur
  la page Dashboard, `<Sidebar>` n'est plus montée du tout depuis l'action
  15 (§6.13 — retrait conditionnel, plus un simple affichage non
  filtrant).

## 6.2 Page Navigation (`pages/NavigationPage.tsx`)

Vue tableau des objets, groupés par (meta-classe, classe), avec panneaux
dépliables par groupe.
- Au montage : charge `apiReadObjects()` (liste légère) et
  `apiReadClasses()` (définitions, pour connaître colonnes/types/`displayname`).
- Quand un groupe est déplié (ou que le filtre sidebar change), charge en
  parallèle le détail (`apiReadObject(id)`) de chaque objet du groupe pour
  peupler un cache (`detailCache`), nécessaire pour afficher les valeurs
  réelles des attributs et résoudre les jointures en libellé lisible.
  ⚠️ Avec le bug §4.2 (`GET /api/read/object/<id>` en échec pour tout
  objet existant), ces appels échoueraient systématiquement et les cellules
  resteraient affichées en `…` (indicateur de chargement) indéfiniment.
  Ce même bug produit aussi, ailleurs dans cette page, des messages
  contradictoires ou trompeurs plutôt qu'un simple blocage silencieux :
  - `handleSave` (modale de création/édition, lignes ~356-366) : après un
    `apiWriteObject` réussi, un toast de succès (« Objet créé/mis à jour »)
    est affiché, puis le code tente de rafraîchir le cache de détail via
    `apiReadObject(editingObjectId)` en cas d'édition ; cet appel échouant à
    cause du bug, un toast d'erreur contradictoire apparaît juste après le
    toast de succès, alors que l'écriture a bien réussi.
  - `handleQuickCreateSave` (ligne ~554) : même mécanisme sur le chemin de
    création rapide (« quick-create ») d'un objet cible depuis un champ
    joint — `apiWriteObject` réussit et crée l'objet en base, mais le
    `apiReadObject(res.id)` qui suit pour peupler le cache de détail échoue,
    déclenchant un toast « Erreur création » qui est un **faux négatif** :
    l'objet existe bel et bien en base malgré le message d'erreur affiché.
- Filtres par classe (boutons à bascule) quand une meta-classe est
  sélectionnée dans la sidebar ; depuis l'action 14, filtre supplémentaire
  orthogonal par `layers` (`isClassVisibleForLayers`, §6.12), mémoïsé via
  `useMemo`. Depuis l'action 15 (§6.13) : un champ texte filtre
  supplémentaire par card de classe (groupe), purement d'affichage (ne
  touche jamais `objects`/`detailCache`), filtrant les lignes de son
  `<table>` par sous-chaîne (insensible casse) sur toutes les cellules
  rendues de la ligne, ID compris.
- Résolution du nom affiché (`resolveDisplayName`) : si `classDef.displayname`
  est défini, remplace chaque `{{attribut}}` par la première valeur de cet
  attribut (ou `#id` si c'est une jointure) ; sinon concatène les valeurs
  des attributs de domaine `details`. `GET /api/read/class` renvoie bien
  `displayname` (§4.1, `backend/routes/routes_read.py:39`) : cette branche
  est atteignable et s'applique normalement pour toute classe ayant un
  `displayname` configuré (ex. `"{{prenom}} {{nom}}"` de
  `personne_physique`) ; le fallback (concaténation du domaine `details`)
  ne joue que pour les classes sans `displayname` défini.
- Création/édition d'objet via une modale : sélection meta-classe/classe
  (ou préremplie depuis la sidebar), un champ par attribut scalaire, un
  `<select>` pour les jointures `joint-1-1`, une interface « disponibles /
  sélectionnés » à deux colonnes pour les jointures `joint-1-n`, avec
  possibilité de créer à la volée (« + Créer un X ») un objet cible
  directement depuis le champ joint (quick-create). Sauvegarde via
  `apiWriteObject` (avec `id` si édition).
- Édition inline au clic sur une cellule :
  - cellule `joint-1-n` → ouvre une modale dédiée (même UI deux colonnes)
    sauvegardée via `apiWriteObject` (reconstruit tout le corps `attributes`
    de l'objet, y compris les autres attributs, pour ne rien perdre lors
    du remplacement complet côté backend).
  - cellule `joint-1-1` → `<select>` inline.
  - cellule scalaire → `<input>` inline.
  - cellule `select` → `<select>` inline dédié (action 7 itération 2,
    §6.9) ; cellule `datasource` → `<select>` inline dédié (action 9,
    §6.9) ; cellule `file`/`image`/`csv`/`secret` → pas d'édition inline
    (clic ignoré, §6.8/§6.9).
  - **Correction (2026-11-23, action 16)** : la note historique présente
    ici affirmait que `saveInlineEdit` ne faisait aucun appel réseau
    d'écriture (`apiWriteAttribute` jamais invoquée) — **obsolète** dans
    le code actuel : `saveInlineEdit` appelle bien `apiWriteAttribute`
    (`PUT /api/write/attribute/...`) pour toute cellule non-`joint-1-1`
    (et `apiWriteObject` en reconstruction complète pour `joint-1-1`,
    même mécanisme que `joint-1-n` ci-dessus) — l'édition inline de
    valeurs scalaires/`select`/`datasource`/`joint-1-1` persiste
    réellement en base. Correction non datée précisément (changement
    antérieur à `plan-mark3.md`, découvert en relisant le code à
    l'occasion de la synchronisation de cette action 16) — voir aussi
    §6.6/§6.7 ci-dessous, à corriger pour cohérence.
- Bascule lecture seule (`readOnly`, héritée de `Navbar`) : désactive
  côté UI uniquement (pas de contrôle serveur) les boutons de création, le
  double-clic d'édition et le clic sur cellule.
  ⚠️ Ce prop `readOnly` n'est **toujours pas** transmis à
  `<ConfigurationPage>` dans `frontend/src/App.tsx` (seuls `authInfo` et
  `selectedMetaClass` le sont) : basculer en lecture seule ne restreint
  jamais rien sur la page Configuration — un utilisateur en mode RO peut y
  créer/modifier/supprimer librement meta-classes, classes et attributs,
  sans aucun signal visuel ni restriction côté UI, contrairement à la page
  Navigation où le toggle désactive au moins les contrôles correspondants.
  **Mise à jour (2026-11-23)** : `<DiagramPage>` (prop déjà présente dans
  son interface) et `<DashboardPage>` (action 10c, §6.11) reçoivent
  désormais `readOnly={readOnly}` depuis `App.tsx` — `DiagramPage.tsx`
  étant nativement en lecture seule (aucune action d'écriture dans cette
  page), ce prop y est accepté mais non consommé dans le corps du
  composant ; `DashboardPage.tsx` l'utilise réellement pour masquer ses
  sections de mutation (§6.11).
- Notifications « toast » (succès/erreur) en haut à droite, auto-disparition
  après 5 s avec animation de fondu.

## 6.3 Page Configuration (`pages/ConfigurationPage.tsx`)

Éditeur du schéma (CRUD des meta-classes/classes/attributs) :
- Si une meta-classe est sélectionnée dans la sidebar : charge sa
  définition via `apiReadMetaClass(nom)` (`GET /api/read/<meta_class>`) et
  préremplit le formulaire ; sinon formulaire vierge (création d'une
  nouvelle meta-classe).
  `GET /api/read/<meta_class>` renvoie bien `displayname` (§4.1,
  `backend/routes/routes_read.py:111`) : le champ « Displayname » est
  correctement prérempli au rechargement d'une classe existante si un
  `displayname` a été précédemment enregistré (l'écriture, elle, conserve
  bien `displayname` tel quel dans `definition.data`).
- Édition multi-classes : chaque classe est une carte dépliable, avec nom,
  `displayname`, et un tableau d'attributs (domaine, nom, type, options).
  Pour un attribut de type `joint-1-1`/`joint-1-n`, les « classes cibles »
  se choisissent par boutons à bascule parmi toutes les classes déjà
  connues (`apiReadClasses()`) + celles en cours de saisie localement ;
  sinon deux champs libres `constraint` (regex) et `sql_constraint`. Les 6
  autres types (`file`/`image`/`csv`/`select`/`secret`/`datasource`) ont
  chacun leur propre colonne « Options » — détail complet : §6.10 (action
  13, les 11 types d'attribut gérés par `ATTR_TYPES`).
  Attributs réordonnables (▲/▼), ajout/suppression de classes et
  d'attributs (toujours au moins 1 classe et 1 attribut par classe) ; champ
  `layers` comma-separated par classe et carte « Layers connus » — détail
  complet : §6.12 (action 14).
- Bouton « Charger depuis model/ » → `apiInit()` (`POST /api/init`).
- Bouton « Sauvegarder » → nettoie les classes/attributs vides puis envoie
  `apiWriteMetaClass` (`POST /api/write/metaclass`) avec **la totalité**
  des classes actuellement affichées dans le formulaire (remplacement
  complet de la meta-classe côté backend, cf. §4.4).

## 6.4 Page Diagramme (`pages/DiagramPage.tsx`)

Graphe interactif (bibliothèque **ECharts**, composant `series: graph` ou
`tree`) :
- Charge tous les objets (`apiReadObjects`), toutes les classes
  (`apiReadClasses`), puis le détail de chaque objet (`apiReadObject`,
  avec tolérance aux échecs individuels via `.catch(() => null)`) pour
  extraire les relations de jointure (`joint_id`) comme arêtes du graphe.
- 3 layouts sélectionnables : **Force** (disposition physique, répulsion/
  gravité), **Circulaire**, **Organigramme** (reconstruction d'un arbre à
  partir des nœuds sans arête entrante comme racines ; les nœuds orphelins
  non atteints sont ajoutés séparément).
- Chaque classe a une couleur assignée depuis une palette fixe de 10
  couleurs (cyclique si plus de 10 classes).
- Filtres : chips par classe (regroupées par meta-classe) pour
  masquer/afficher, boutons « Tout »/« Rien » ; depuis l'action 14, filtre
  supplémentaire orthogonal par `layers` (chips Sidebar partagées avec
  Navigation, §6.12) appliqué dans le même `useMemo` de calcul des objets
  visibles.
- Infobulle au survol d'un nœud (nom résolu + classe + id) ; redimensionnement
  automatique du graphe via `ResizeObserver` et l'événement `resize` de la
  fenêtre ; nettoyage (`dispose()`) de l'instance ECharts au démontage.
- Même logique `resolveDisplayName` que la page Navigation (§6.2) :
  `displayname` étant renvoyé par l'API, les étiquettes des nœuds utilisent
  le gabarit `displayname` quand une classe en définit un, sinon le
  fallback (concaténation du domaine `details`).

## 6.5 Thèmes

3 thèmes CSS définis dans `styles.css` via l'attribut `data-theme` sur la
racine du document : `dark` (défaut), `midnight`, `light`. Changement
instantané sans rechargement, non persisté entre sessions.

## 6.6 Client API (`src/api.ts`)

Wrapper `fetch` minimal (`fetchJson`), pas d'Axios, erreurs levées comme
`Error("<status>: <corps texte de la réponse>")` en cas de réponse non-`ok`.

| Fonction | Méthode + URL |
|---|---|
| `apiReadMetaClasses()` | `GET /api/read/meta_class` |
| `apiReadClasses()` | `GET /api/read/class` |
| `apiReadClassById(id)` | `GET /api/read/class/:id` |
| `apiReadMetaClass(metaClass)` | `GET /api/read/:metaClass` |
| `apiReadObjects()` | `GET /api/read/objects` |
| `apiReadObject(id)` | `GET /api/read/object/:id` |
| `apiWriteMetaClass(data)` | `POST /api/write/metaclass` |
| `apiWriteClass(metaClass, cls)` | `POST /api/write/class` |
| `apiWriteObject(data)` | `POST /api/write/object` |
| `apiWriteAttribute(cls, id, attribute, value)` | `PUT /api/write/attribute/:cls/:id/:attribute/:value` — appelée par `saveInlineEdit` (`NavigationPage.tsx`, édition inline de cellule non-`joint-1-1`) ; note historique « jamais appelée » obsolète, voir §6.2 |
| `apiDeleteObject(id)` | `DELETE /api/delete/object/:id` (suppression logique, `plan-mark2.md` action 6.1 ; consommée notamment par `DashboardPage.tsx`, suppression de tab, ajout Mark 3 action 10c) |
| `apiInit()` | `POST /api/init` |
| `apiWriteObjectCreateMultipart(...)` | `POST /api/write/object` (`multipart/form-data`, création atomique objet + fichiers, ajout Mark 3 action 3) |
| `apiWriteObjectFile(objectId, attribute, file)` | `POST /api/write/object/:id/file/:attribute` (ajout Mark 3 action 3) |
| `apiReadObjectFileBlob(objectId, attribute, version?)` | `GET /api/read/object/:id/file/:attribute[?version=N]` (ajout Mark 3 action 3) |
| `apiSetObjectFileReference(...)` | `POST /api/write/object/:id/file/:attribute/reference` (ajout Mark 3 action 4) |
| `apiListLogos()` | `GET /api/logos` (ajout Mark 3 action 4) |
| `apiClassIconUrl(metaClass, cls)` | construit l'URL `GET /api/class_icon/:meta_class/:class` (pas de `fetch`, utilisée directement comme `src`/`symbol`, ajout Mark 3 action 4) |

## 6.7 Récapitulatif des anomalies frontend

- `displayname` configuré dans le modèle a l'effet attendu : les 3
  endpoints de lecture des classes le renvoient (§4.1) et `NavigationPage`/
  `DiagramPage`/`ConfigurationPage` l'exploitent correctement (résolution
  du gabarit, préremplissage du formulaire).
- Le bug §4.2 (`GET /api/read/object/<id>`) ne se limite pas à un blocage
  silencieux (cellules bloquées sur `…`) : il produit aussi, via le
  re-fetch post-écriture, de **faux messages d'erreur** dans
  `NavigationPage.tsx` alors que l'écriture a réussi — toast d'erreur
  contradictoire juste après un toast de succès dans `handleSave` (édition,
  lignes ~356-366), et faux négatif « Erreur création » dans
  `handleQuickCreateSave` (ligne ~554) alors que l'objet est bien créé en
  base.
- ~~L'édition inline de cellules scalaires et de jointures `joint-1-1` dans
  la page Navigation ne sauvegarde rien côté serveur~~ — **obsolète**,
  corrigé avant `plan-mark3.md` (voir §6.2) : `saveInlineEdit` appelle
  bien `apiWriteAttribute`/`apiWriteObject` et persiste réellement.
- Le toggle lecture seule (RO/RW) et les thèmes sont des états purement
  côté client, non persistés et sans portée sur l'API (aucune autorisation
  réelle n'est appliquée côté serveur).

## 6.8 Fichiers, logos, icônes de classe (ajout 2026-11-21, `plan-mark3.md` actions 3-4)

**Rendu des types `file`/`image`/`csv` (`pages/NavigationPage.tsx`)** —
trois branches de rendu dédiées (`FileAttributeValueDisplay`), en plus des
branches déjà existantes `joint-1-1`/`joint-1-n` (§6.2) :
- `file`, et `image` au format `svg` : nom de fichier + bouton
  téléchargement seul (`FileDownloadButton`, fetch authentifié via
  `apiReadObjectFileBlob` + `URL.createObjectURL`) — **jamais d'aperçu
  `<img>` pour un SVG**, cohérent avec la décision de sécurité backend
  (toujours servi en `Content-Disposition: attachment`, §4.6 de
  [04-api-backend.md](04-api-backend.md)).
- `image` aux formats jpg/jpeg/png : aperçu inline (`ImagePreview`, `<img>`
  sur un object URL résolu par fetch authentifié) **et** bouton
  téléchargement.
- `csv` : tableau HTML en lecture seule (`CsvPreviewTable`, parsing client
  du blob texte selon `attr.separator` défini sur l'attribut, défaut `,`)
  **et** bouton téléchargement du fichier brut. Pas d'édition de cellule —
  l'édition reste le remplacement du fichier entier via upload.
- `parseFilePointer` reconnaît les deux formats de pointeur (direct
  `"<version>:<nom>"` et référence `"ref:<classe>:<object_id>:<attribut>:
  <version>:<nom>"`, §4.6) en ne découpant que les `:` significatifs, le
  nom de fichier pouvant lui-même contenir `:`.
- Formulaire de création/modif : `<input type="file">` pour les trois
  types, remplaçant la valeur existante à la sauvegarde (nouvelle
  version). Pas d'édition inline de cellule pour ces types (clic ignoré,
  seul le formulaire permet l'upload).

**Logo d'objet** — l'attribut réservé `logo` (type `image`, domaine
`display`) a un traitement spécifique dans le formulaire de
`NavigationPage.tsx` : aperçu **cliquable** (clic ouvre directement
l'`<input type="file">` caché, pas de bouton séparé, via une ref par
attribut) et sélecteur additionnel « …ou réutiliser un logo existant »
alimenté par `GET /api/logos` (`apiListLogos`), qui construit une référence
via `POST .../file/<attribute>/reference` (`apiSetObjectFileReference`)
plutôt que de ré-uploader les octets.

**Icônes de classe (`frontend/src/classIcons.tsx`)** — jeu fixe de **18**
icônes SVG inline embarquées (`CLASS_ICONS`, viewBox uniforme `0 0 24 24`,
trait gris fixe), encodées en data URI (`classIconDataUri`) pour un usage
direct comme symbole ECharts ou `<img src=...>` sans requête réseau.
Sélecteur en grille dans `pages/ConfigurationPage.tsx` (une classe choisit
au plus une icône via le champ `icon`, bouton « aucune icône » pour
revenir au fallback).

**Rendu logo/icône dans `pages/DiagramPage.tsx`** — ordre de priorité
explicite pour le `symbol` d'un nœud :
1. **Logo résolu de l'objet** (attribut `logo`, type `image`) — résolu par
   fetch **authentifié** (`apiReadObjectFileBlob`, même pattern que
   `NavigationPage.tsx`) transformé en object URL mis en cache
   (`logoBlobCache`), jamais une URL brute `image://<url>` : un `<img>`/
   ECharts ne peut pas attacher de header `Authorization: Bearer`, et le
   RBAC tenant est *fail-closed* (`rbac.py`) — un logo tenant-scoped serait
   donc invisible sans ce détour. Tant que la résolution asynchrone n'est
   pas terminée, le symbole retombe sur le niveau suivant (pas de case
   cassée affichée en attendant).
2. **Icône de classe choisie manuellement** (`classDef.icon`,
   `findClassIcon` + `classIconDataUri`, `frontend/src/classIcons.tsx`).
3. **Icône de secours générée par le backend**
   (`GET /api/class_icon/<meta_class>/<class>`, `apiClassIconUrl`, §4.6).
4. **Couleur de palette par classe** (§6.4, fallback final — aucun
   `symbol` n'est alors assigné, ECharts applique son rendu de nœud par
   défaut coloré).
Le garde-fou d'auto-réparation backend (§4.6) s'applique aussi ici : un
logo cassé ne bloque jamais le rendu, il retombe simplement sur le niveau
de priorité suivant à l'affichage suivant.

## 6.9 Types `select`/`secret`/`datasource` (ajout 2026-11-23, `plan-mark3.md` actions 7-9)

**Rendu dans `pages/NavigationPage.tsx`** — formulaire de création/édition
ET édition inline de cellule (les deux, contrairement à `file`/`image`/
`csv`) :
- `select` : `<select>` dédié, options = `attr.values` (§3.2ter de
  [03-modele-donnees.md](03-modele-donnees.md)) ; même branche dédiée en
  édition inline de cellule (ajoutée en itération 2 de l'action 7, suite à
  revue croisée — la première itération ne couvrait que le formulaire).
- `datasource` : `<select>` de sélection d'objet cible, réutilisant
  `getCandidates`/`getCandidateLabel` (même mécanisme que `joint-1-1`),
  mais la valeur est gérée comme un attribut scalaire ordinaire dans
  `newAttrs` (jamais dans `jointValues`) — cohérent avec le stockage
  `value_string` côté backend (§4.7 de
  [04-api-backend.md](04-api-backend.md)). Affichage en lecture : la
  chaîne stockée est ré-enveloppée dans `{joint_id}` pour réutiliser
  `formatValue` tel quel. Branche d'édition inline dédiée présente dès la
  première itération (explicitement pour ne pas reproduire l'oubli de
  l'action 7 sur ce point).
- `secret` : `<input type="password">`, jamais pré-rempli avec la valeur
  réelle (champ forcé vide à l'ouverture d'un formulaire d'édition) —
  laisser le champ vide en édition ne modifie pas la valeur active
  (convention standard d'un formulaire de mot de passe). **Aucune édition
  inline de cellule** (clic ignoré, comme `file`/`image`/`csv`) et
  **aucun bouton reveal dans l'IHM** — la révélation n'existe que via
  l'API dédiée (§4.7 de [04-api-backend.md](04-api-backend.md)), réservée
  global-admin ; en lecture, la cellule affiche le placeholder renvoyé par
  le backend (`"••••••••"`) tel quel, comme n'importe quelle autre valeur
  texte.

**`pages/ConfigurationPage.tsx`** (dette comblée par l'action 13, voir
§6.10) gère les 3 types dans `ATTR_TYPES` et leur colonne « Options »
dédiée — voir ci-dessous.

## 6.10 IHM de configuration : les 11 types d'attribut (ajout 2026-11-23, `plan-mark3.md` action 13)

`pages/ConfigurationPage.tsx` gère désormais la totalité des types déclarés
dans `model/schema.json` — `ATTR_TYPES` liste les **11** valeurs : `string`,
`integer`, `float`, `joint-1-1`, `joint-1-n`, `file`, `image`, `csv`,
`select`, `secret`, `datasource` (avant l'action 13, seuls les 5 premiers
étaient proposés à la création d'un attribut, bien que le backend/schema
supportait déjà les 6 autres depuis les actions 3/7/8/9).

Colonne « Options » de l'éditeur d'attribut, par type :
- `joint-1-1`/`joint-1-n`/`datasource` : même bloc JSX de sélection de
  classes cibles (`attr.classes`, `toggleJointClass`) — réutilisé tel quel
  pour les trois, cohérent avec `model/schema.json` qui réutilise le même
  champ `classes` pour `datasource` (§3.2ter de
  [03-modele-donnees.md](03-modele-donnees.md)).
- `select` : éditeur de chips (`attr.values`) — input texte + bouton
  « Ajouter » + suppression par chip ; toast d'erreur si la valeur ajoutée
  existe déjà (pas de no-op silencieux) ; clé React composite `${v}-${i}`
  (robustesse en cas de doublons importés via `apiInit`).
- `csv` : input pour `attr.separator` (placeholder `,`).
- `file`/`image`/`secret` : « Aucune option ».

**Validation front bloquante** (extension jugée légitime en cours de
revue, comble un vrai trou backend) : empêche la sauvegarde si un attribut
`joint-1-1`/`joint-1-n`/`datasource` a `classes` vide, ou si un attribut
`select` a `values` vide — `model/schema.json` n'impose que la présence de
la clé (`required`), pas `minItems`, donc un tableau vide passerait la
validation JSON Schema et échouerait plus tard, de façon confuse, à la
première écriture de valeur. Toast d'erreur nommant l'attribut et la
classe concernés.

État `selectValueDrafts` (saisie en cours d'une valeur `select`, indexé
par position `classIdx-attrIdx`) réinitialisé dans
`moveAttribute`/`removeAttribute`/`removeClass` — sans ce reset, un
réordonnancement d'attributs/classes pouvait faire atterrir une saisie en
cours sur le mauvais attribut (bug trouvé en revue croisée, corrigé en
itération 2 de l'action 13).

## 6.11 Page Dashboard (`pages/DashboardPage.tsx`, ajout 2026-11-23, `plan-mark3.md` actions 10a-10d)

4e page de l'application (`App.tsx`, type `Page` élargi à `'configuration'
| 'navigation' | 'diagramme' | 'dashboard'`), accessible via un 4e bouton
Navbar (« Dashboard », sans gating RBAC particulier, cohérent avec
« Diagramme »). Pas de nouvelle route backend : entièrement bâtie sur les
routes génériques d'objets (`apiReadObjects`/`apiReadObject`/
`apiWriteObject`/`apiDeleteObject`/`apiReadMetaClass`), consommant la
meta-classe `dashboard` (`model/dashboard.json`, §3.2ter de
[03-modele-donnees.md](03-modele-donnees.md)).

- **Modèle de données (10a)** : aucun code backend requis — la meta-classe
  `dashboard` est chargée comme toute autre meta-classe par `POST
  /api/init` (pas de whitelist/blacklist de meta-classe côté backend).
- **Lecture (10b)** : au montage, charge tous les objets `dashboard`/`tab`
  via `apiReadObjects()` + `apiReadObject()` par objet
  (`Promise.allSettled`, objets en échec individuellement ignorés plutôt
  que de faire planter toute la page — correction apportée en itération 2
  après qu'une revue croisée a trouvé un premier `Promise.all` non
  tolérant à l'échec). Auto-sélection si un seul dashboard existe,
  sélecteur `<select>` si plusieurs, état vide si aucun. Les tabs d'un
  dashboard sont retrouvés par filtre côté client sur l'attribut
  `joint-1-1` `dashboard` (`getJointId`, réimplémentation locale du même
  principe que `NavigationPage.tsx`). Limite connue acceptée : charge
  TOUS les dashboards/tabs du système sans narrowing (pas de filtre par
  sidebar, volume non borné) — acceptable au volume actuel.
- **CRUD (10c)** : prop `readOnly` câblée depuis `App.tsx` (même pattern
  que `NavigationPage`/`DiagramPage`) — toutes les sections de mutation
  masquées (pas juste désactivées) sous `{!readOnly && (...)}`. Création
  de dashboard (`name`) et création/édition/suppression de tab (`name`/
  `target_meta_class`/`target_class`/`filter_attribute`/`filter_value`,
  `dashboard` en `{joint_id:...}`) via `apiWriteObject`/`apiDeleteObject` ;
  champs texte vides omis du payload (convention déjà en place dans
  `NavigationPage.tsx` : un attribut omis ferme la valeur active côté
  serveur). Pas de CRUD de dashboard au-delà de la création (modifier/
  supprimer un dashboard est hors scope). `TabFormState.dashboardId` est
  un **snapshot** pris à l'ouverture du formulaire (jamais le state live
  `selectedDashboardId`) — fix d'un bug de reparentage silencieux trouvé
  en revue croisée : changer le dashboard sélectionné pendant qu'un
  formulaire d'édition de tab restait ouvert reparentait le tab vers le
  mauvais dashboard à l'enregistrement sans avertissement ; un
  `useEffect` ferme désormais aussi le formulaire ouvert si la sélection
  de dashboard change pendant l'édition.
- **Sélection des sous-objets par tab (10d)** : deux attributs
  supplémentaires optionnels sur `tab`, `filter_attribute`/`filter_value`
  (§3.2ter), exposés comme 2 champs de formulaire optionnels en plus de
  10c. Un `useEffect` lazy déclenché par le changement de tab actif charge
  les colonnes (`apiReadMetaClass(target_meta_class)`, attributs déclarés
  sur `target_class`) et les objets candidats
  (`apiReadObjects()` filtré client `meta_class`/`class`, puis
  `apiReadObject` par candidat, `Promise.allSettled`) — **scopé au tab
  ACTIF uniquement**, jamais tous les tabs (pas d'aggravation de la
  limite de 10b/10c). Rendu en tableau HTML lecture seule (colonnes =
  attributs de la classe cible). Filtre optionnel : égalité stricte après
  extraction d'id de jointure (`getJointId(raw)` puis
  `String(...) === filter_value.trim()`), pas d'opérateurs
  (contains/</>), pas de multi-critères — un attribut `joint-1-n`
  (multi-valué) n'est testé que sur sa 1ère valeur. `formatCellValue`
  retourne un placeholder neutre (`(fichier — non affiché ici)` /
  `(image — non affichée ici)` / `(csv — non affiché ici)`) pour un
  attribut `file`/`image`/`csv` de la classe cible, au lieu du pointeur
  brut — `secret` non concerné (déjà masqué côté serveur générique, donc
  déjà neutre dans ce tableau).
- **Câblage** (`App.tsx`) : nouvelle branche de rendu `page === 'dashboard'
  ? <DashboardPage readOnly={readOnly} /> : ...`. `components/Sidebar.tsx` :
  le type `page` accepte désormais aussi `'dashboard'` (pure signature TS,
  Sidebar ne branche sur aucune valeur spécifique de `page` au-delà de la
  dépendance de son `useEffect` de rechargement). `components/Navbar.tsx` :
  4e bouton « Dashboard », avant le sélecteur de thème. ⚠️ Mis à jour par
  l'action 15 (§6.13) : `<Sidebar>` (et le bouton `sidebar-toggle`) ne sont
  plus affichés sur la page Dashboard — retrait conditionnel complet du
  DOM dans `App.tsx` (`page !== 'dashboard'`), pas juste un affichage non
  filtrant comme décrit ici initialement.

## 6.12 Filtre `layers` (ajout 2026-11-23, `plan-mark3.md` action 14)

Nouveau mécanisme de filtrage 100% frontend (pas de RBAC, pas de
changement backend hormis un passthrough de lecture, voir ci-dessous),
orthogonal au filtre `meta_class`/`class` existant (mono-sélection) :

- **État** — `App.tsx` : `selectedLayers: Set<string>` (multi-sélection),
  remonté et partagé entre `Sidebar`/`NavigationPage`/`DiagramPage`.
  Persisté en `localStorage` (clé `miami-vice-selected-layers`, lu au
  montage, écrit à chaque changement ; clé supprimée plutôt que stocker un
  tableau vide quand le filtre est vidé). Vide/absent = pas de filtre
  actif (tous les layers visibles, comportement non régressif par
  défaut).
- **Registre des layers** — `frontend/src/types.ts` :
  `ClassDefinition`/`ClassInfo` étendus avec `layers?: string[]` (même
  pattern que `tenants`). Pas de meta-classe dédiée : la liste des layers
  connus est une union dédupliquée (et triée côté `Sidebar.tsx`) des
  `layers` de toutes les classes chargées, calculée indépendamment à deux
  endroits (`ConfigurationPage.tsx` et `Sidebar.tsx`, aucune
  factorisation).
- **`pages/ConfigurationPage.tsx`** : input texte comma-separated pour
  `layers` sur une classe (même pattern que `tenants`) ; carte « Layers
  connus » en lecture seule au-dessus du formulaire (union dédupliquée non
  scopée à la meta-classe actuellement affichée) — sert de référentiel
  visuel pour éviter de retaper/fauter un nom de layer déjà existant.
- **`components/Sidebar.tsx`** : nouvelle section « Layers » sous l'arbre
  meta-classe existant — chips togglables, liste déduite dynamiquement de
  `apiReadClasses()`. Clic = ajoute/retire le layer de `selectedLayers`,
  sans toucher à `selectedMetaClass`/`selectedClass`. ⚠️ Depuis l'action 15
  (§6.13), cette section chips n'est affichée que sur Navigation/
  Configuration ; sur Diagramme elle est remplacée par une combo-list qui
  narrow en plus les arbres de classes.
- **`pages/NavigationPage.tsx`/`pages/DiagramPage.tsx`** : predicate
  `isClassVisibleForLayers(def, selectedLayers)` — classe visible si
  `selectedLayers` est vide, ou si `def.layers` est vide/absent, ou si
  l'intersection avec `selectedLayers` est non vide — appliqué dans le
  filtre d'objets déjà existant (`meta_class`/`class`, et `hiddenClasses`
  pour `DiagramPage`). Fonction dupliquée verbatim dans les deux fichiers
  (pas de module partagé, aucune convention établie dans le projet pour ce
  cas). Dans `NavigationPage.tsx`, le filtre est enveloppé dans un
  `useMemo` (deps `objects`/`selectedMetaClass`/`selectedClass`/
  `visibleClasses`/`classes`/`selectedLayers`) — ajouté en itération 2
  suite à une régression de performance trouvée en revue croisée
  (`classes.find()` par objet dans le filtre, recalculé à chaque rendu
  sans mémoïsation).
- **Fix backend imprévu** (non prévu par la conception initiale, qui
  annonçait « aucun changement backend ») : `backend/routes/
  routes_read.py` — les 3 routes de lecture de schéma (`list_classes`,
  `get_class_by_id`, `get_classes_by_meta_class`) ne projetaient pas la
  clé `layers` du JSONB stocké en base (persistée en écriture mais
  invisible en lecture). Fix = simple passthrough `cls.get("layers")`,
  même statut que `icon` (§3.2bis), zéro impact RBAC.
- Pas de normalisation de casse sur les noms de layers (même risque déjà
  accepté pour `tenants`). Staleness connue : `Sidebar.tsx` ne recharge
  `classes` que sur changement de page (`useEffect` dépendant de `page`),
  donc un layer ajouté sur `ConfigurationPage.tsx` n'apparaît dans les
  chips qu'après un changement de page.

## 6.13 Restructuration IHM (ajout 2026-11-23, `plan-mark3.md` action 15)

5 ajustements UX 100% frontend, aucun changement backend/schéma :

- **`components/Navbar.tsx`** : ordre des boutons changé — Configuration
  déplacée en tête, avant Navigation (ordre final : Configuration,
  Navigation, Diagramme, Dashboard). Masquage RBAC du bouton Configuration
  pour le rôle tenant-readonly inchangé (`!authInfo.isTenantReadonly`).
- **`App.tsx`** : `<Sidebar>` et le bouton `.sidebar-toggle` ne sont plus
  rendus du tout (`page !== 'dashboard'`) sur la page Dashboard — absence
  complète du DOM, pas un simple `open={false}` (corrige la description
  initiale de §6.11).
- **`components/Sidebar.tsx`** :
  - Champ texte filtre (`filterText`, un seul input, en haut du composant) :
    sous-chaîne insensible casse sur `class`/`meta_class`, appliqué aux
    deux arbres ci-dessous (`textFiltered`, recalculé à chaque frappe).
  - Arbre « par meta-classe » (existant) et arbre « par layer » (nouveau) :
    coexistent, les deux pilotés par `treeClasses` (= `textFiltered`,
    narrow en plus par `selectedLayers` sur la page Diagramme, voir
    ci-dessous). L'arbre par layer groupe par `c.layers` — une classe
    apparaît sous chaque layer auquel elle appartient (doublons acceptés),
    classes sans layer absentes de cette section (differe du predicate
    `isClassVisibleForLayers`, §6.12, où l'absence de layer = toujours
    visible : ici c'est un regroupement d'affichage par layer, une classe
    sans layer n'a simplement aucun groupe où apparaître). Clic sur une
    classe de l'arbre layer = mêmes callbacks `onSelectMetaClass`/
    `onSelectClass` que l'arbre meta-classe.
  - Repli/dépli : deux `Set<string>` locaux (`expandedMeta`,
    `expandedLayerGroups`), un par arbre, **repliés par défaut** (Set
    vide) — remplace le pilotage par `selectedMetaClass === mc` de
    l'ouverture (comportement précédent) ; la sélection
    (`selectedMetaClass`/`selectedClass`) reste indépendante de l'état de
    repli (un groupe peut être sélectionné sans être déplié, et inversement).
  - Sur Diagramme uniquement (`page === 'diagramme'`) : la section chips
    `layers` (§6.12) est remplacée par une combo-list (`<select
    multiple>`), même état `selectedLayers`/`onSelectedLayersChange`.
    Quand au moins un layer est sélectionné sur cette page, `treeClasses`
    narrow en plus les deux arbres aux classes dont `layers` intersecte
    `selectedLayers` — classe sans layer toujours incluse (même convention
    que `isClassVisibleForLayers`, §6.12, pour rester cohérent avec le
    filtre appliqué simultanément aux objets affichés sur
    `DiagramPage.tsx`, qui consomme le même `selectedLayers`). Navigation/
    Configuration gardent les chips, jamais de narrow d'arbre sur ces
    pages.
- **`pages/NavigationPage.tsx`** : un filtre texte par card de classe
  (state `groupFilters: Record<groupKey, string>`), visible seulement si
  le groupe est déplié, au-dessus du `<table>`. Filtre d'affichage pur
  (`visibleObjects`, dérivé de `group.objects` sans jamais muter
  `objects`/`detailCache`) : une ligne est visible si une sous-chaîne
  (insensible casse) matche une valeur de cellule rendue — ID inclus
  (choix retenu : filtre sur toutes les cellules affichées, comportement
  le plus simple et prévisible) — via un texte reconstruit à partir des
  mêmes données que le rendu réel (`formatValue`, nom de fichier
  `parseFilePointer` pour `file`/`image`/`csv`).
- `pages/DiagramPage.tsx` : aucun changement de code — consomme déjà
  `selectedLayers` via `isClassVisibleForLayers` (§6.12) ; seule la source
  de ce filtre change (combo-list Sidebar au lieu des chips).
- `pages/ConfigurationPage.tsx` : aucun changement — réutilise le même
  filtre texte Sidebar (`selectedMetaClass` uniquement, pas de liste
  dédiée ; Sidebar y liste déjà toutes les classes sans filtre
  meta-classe).

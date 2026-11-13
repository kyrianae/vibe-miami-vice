# 6. Frontend

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

## 6.1 Structure générale

- `main.tsx` : point d'entrée, monte `<App />` dans `#root` (mode
  `StrictMode`).
- `App.tsx` : état global applicatif tenu en `useState` local (pas de
  state manager externe, pas de routeur — la « page » active est une
  simple variable d'état `'navigation' | 'configuration' | 'diagramme'`) :
  page courante, repli de la sidebar, bascule lecture seule (`readOnly`),
  thème (`'dark' | 'midnight' | 'light'`), meta-classe/classe sélectionnées
  (partagées entre Sidebar et la page affichée). Le thème est appliqué en
  posant l'attribut `data-theme` sur `<html>`. **Rien n'est persisté**
  (ni `localStorage` ni cookie) : un rechargement de page réinitialise
  toujours au thème `dark`, lecture-écriture, et sidebar ouverte.
- `components/Navbar.tsx` : titre, 3 boutons de changement de page,
  sélecteur de thème, interrupteur RO/RW.
- `components/Sidebar.tsx` : charge `apiReadClasses()` au montage et à
  chaque changement de page, affiche un arbre meta-classe → classes
  (regroupement calculé côté client), piloté par clic (toggle
  sélection/désélection). Le choix ici alimente les 3 pages via les props
  `selectedMetaClass`/`selectedClass` de `App.tsx`.

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
  sélectionnée dans la sidebar.
- Résolution du nom affiché (`resolveDisplayName`) : si `classDef.displayname`
  est défini, remplace chaque `{{attribut}}` par la première valeur de cet
  attribut (ou `#id` si c'est une jointure) ; sinon concatène les valeurs
  des attributs de domaine `details`. ⚠️ Comme `GET /api/read/class`
  ne renvoie jamais `displayname` (§4.1), **cette branche n'est en pratique
  jamais empruntée** : c'est toujours le fallback (concaténation du domaine
  `details`) qui s'applique, même pour des classes ayant un `displayname`
  configuré (ex. `"{{prenom}} {{nom}}"` de `personne_physique`).
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
  - ⚠️ **Bug** : la fonction `saveInlineEdit` (appelée au blur/Enter des
    éditions scalaires et `joint-1-1` inline) ne fait **aucun appel réseau
    d'écriture** — le code contient des commentaires indiquant qu'un appel à
    `apiWriteAttribute` (`PUT /api/write/attribute/...`) « devrait » être
    fait, mais cet appel est resté commenté/non implémenté : la fonction se
    contente de re-télécharger l'objet (`apiReadObject`) et d'afficher un
    toast de succès. **L'édition inline de valeurs scalaires et de jointures
    1-1 ne persiste donc jamais rien en base**, bien que l'UI affiche un
    message de succès. Seules la création/édition via la modale complète et
    l'édition des jointures `joint-1-n` (via `jointEdit`, qui appelle
    `apiWriteObject`) écrivent réellement.
- Bascule lecture seule (`readOnly`, héritée de `Navbar`) : désactive
  côté UI uniquement (pas de contrôle serveur) les boutons de création, le
  double-clic d'édition et le clic sur cellule.
  ⚠️ Ce prop `readOnly` n'est transmis qu'à `NavigationPage` : dans
  `frontend/src/App.tsx` (lignes 41-52), seul l'appel à `<NavigationPage>`
  reçoit `readOnly={readOnly}` ; les appels à `<ConfigurationPage>` et
  `<DiagramPage>` ne reçoivent pas ce prop du tout. Conséquence : basculer
  en lecture seule ne restreint jamais rien sur la page Configuration — un
  utilisateur en mode RO peut y créer/modifier/supprimer librement
  meta-classes, classes et attributs, sans aucun signal visuel ni
  restriction côté UI, contrairement à la page Navigation où le toggle
  désactive au moins les contrôles correspondants.
- Notifications « toast » (succès/erreur) en haut à droite, auto-disparition
  après 5 s avec animation de fondu.

## 6.3 Page Configuration (`pages/ConfigurationPage.tsx`)

Éditeur du schéma (CRUD des meta-classes/classes/attributs) :
- Si une meta-classe est sélectionnée dans la sidebar : charge sa
  définition via `apiReadMetaClass(nom)` (`GET /api/read/<meta_class>`) et
  préremplit le formulaire ; sinon formulaire vierge (création d'une
  nouvelle meta-classe).
  ⚠️ Comme `GET /api/read/<meta_class>` ne renvoie pas `displayname`
  (§4.1), le champ « Displayname » apparaît toujours vide au rechargement
  d'une classe existante, même si un `displayname` a été précédemment
  enregistré — perte d'affichage (pas de perte en base : l'écriture, elle,
  conserve bien `displayname` tel quel dans `definition.data`).
- Édition multi-classes : chaque classe est une carte dépliable, avec nom,
  `displayname`, et un tableau d'attributs (domaine, nom, type, options).
  Pour un attribut de type `joint-1-1`/`joint-1-n`, les « classes cibles »
  se choisissent par boutons à bascule parmi toutes les classes déjà
  connues (`apiReadClasses()`) + celles en cours de saisie localement ;
  sinon deux champs libres `constraint` (regex) et `sql_constraint`.
  Attributs réordonnables (▲/▼), ajout/suppression de classes et
  d'attributs (toujours au moins 1 classe et 1 attribut par classe).
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
  masquer/afficher, boutons « Tout »/« Rien ».
- Infobulle au survol d'un nœud (nom résolu + classe + id) ; redimensionnement
  automatique du graphe via `ResizeObserver` et l'événement `resize` de la
  fenêtre ; nettoyage (`dispose()`) de l'instance ECharts au démontage.
- Même logique `resolveDisplayName` que la page Navigation, avec la même
  limitation (§6.2) : `displayname` n'étant jamais renvoyé par l'API, les
  étiquettes des nœuds utilisent toujours le fallback (concaténation du
  domaine `details`).

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
| `apiWriteAttribute(cls, id, attribute, value)` | `PUT /api/write/attribute/:cls/:id/:attribute/:value` — ⚠️ définie mais jamais appelée dans le code frontend actuel |
| `apiInit()` | `POST /api/init` |

## 6.7 Récapitulatif des anomalies frontend

- `displayname` configuré dans le modèle n'a aucun effet visible, car
  aucun endpoint de lecture ne le renvoie (cause backend, §4.1) — impacte
  `NavigationPage` et `DiagramPage`.
- Le bug §4.2 (`GET /api/read/object/<id>`) ne se limite pas à un blocage
  silencieux (cellules bloquées sur `…`) : il produit aussi, via le
  re-fetch post-écriture, de **faux messages d'erreur** dans
  `NavigationPage.tsx` alors que l'écriture a réussi — toast d'erreur
  contradictoire juste après un toast de succès dans `handleSave` (édition,
  lignes ~356-366), et faux négatif « Erreur création » dans
  `handleQuickCreateSave` (ligne ~554) alors que l'objet est bien créé en
  base.
- L'édition inline de cellules scalaires et de jointures `joint-1-1` dans
  la page Navigation ne sauvegarde rien côté serveur (`saveInlineEdit` ne
  fait pas d'appel réseau d'écriture) tout en affichant un toast de succès
  trompeur.
- Le toggle lecture seule (RO/RW) et les thèmes sont des états purement
  côté client, non persistés et sans portée sur l'API (aucune autorisation
  réelle n'est appliquée côté serveur).

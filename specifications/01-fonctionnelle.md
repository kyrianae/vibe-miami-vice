# 1. Objectif du projet et catalogue des fonctionnalités livrées

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

Miami Vice est un **modélisateur de données générique** : il permet de définir
un schéma de données (meta-classes → classes → attributs typés, avec
jointures 1-1 et 1-N entre objets) sous forme de JSON, de le charger dans
PostgreSQL, puis de créer/lire/modifier des instances (« objets ») conformes
à ce schéma via une API REST Flask et une interface React.

Le modèle n'est pas figé dans des tables SQL métier : il est entièrement
dynamique — toute entité (« classe ») et ses attributs sont décrits dans des
documents JSON stockés en base, interprétés à la volée par le backend et le
frontend. Deux exemples de domaines sont fournis (`model/organisation.json` :
personnes, rôles, groupes, société, organigramme ; `model/reseau.json` :
adresses IP, VLAN, équipements réseau).

## 1.1 Catalogue des fonctionnalités livrées

Cette section recense, par thème, les fonctionnalités ajoutées au-delà du
cœur générique décrit ci-dessus (livrées par `plan-mark1.md`/`plan-mark2.md`/
`plan-mark3.md`). Chaque entrée reste volontairement courte (quoi/pourquoi/
exemple) : le détail technique (contrat API, schéma JSON, composants
frontend) reste dans [03-modele-donnees.md](03-modele-donnees.md)/
[04-api-backend.md](04-api-backend.md)/[05-frontend.md](05-frontend.md), ce
catalogue n'en est qu'une vue d'ensemble avec renvois précis.

### 1.1.1 Multi-tenant

Une notion de tenant permet de restreindre une classe (et donc les objets qui
en découlent) à un ou plusieurs tenants — portée directement par les
groupes/rôles Keycloak plutôt que par une table applicative dédiée. Une
classe sans tenant déclaré reste accessible depuis n'importe quel tenant.
Permet d'héberger plusieurs organisations/clients sur une même instance sans
dupliquer l'infrastructure : un tenant-admin ne voit et ne modifie que son
périmètre, un global-admin voit tout. Détail technique :
[02-architecture.md](02-architecture.md) §2bis (`backend/auth/rbac.py`),
RBAC décrit route par route dans
[04-api-backend.md](04-api-backend.md).

### 1.1.2 Authentification (Keycloak)

L'API, initialement entièrement ouverte, est protégée par un Bearer JWT
validé contre un realm Keycloak — couvrant à la fois des comptes de service
(automatisation, flux `client_credentials`) et une connexion humaine directe
par login/mot de passe. Certaines routes sensibles (purge, révélation d'un
secret) exigent un token valide même en lecture (`401` sinon), les routes de
lecture générique restant ouvertes par défaut (filtrage tenant appliqué
séparément). Détail technique :
[02-architecture.md](02-architecture.md) §2bis (`backend/auth/auth.py`).

### 1.1.3 Historisation et suppression différée (cycle de vie des objets)

Toute modification d'un attribut ouvre une nouvelle ligne versionnée
(`valid_from`/`valid_to`) au lieu d'écraser la valeur précédente — l'état
passé d'un objet reste reconstituable. Supprimer un objet est une opération
**logique** (`deleted_at`), avec fermeture en cascade des jointures entrantes
scopée au tenant de l'acteur ; une purge physique différée (période de grâce
configurable, 30 jours par défaut) retire ensuite définitivement les objets
soft-deleted. Évite la perte de donnée accidentelle immédiate tout en
gardant un mécanisme de nettoyage réel. Détail technique :
[04-api-backend.md](04-api-backend.md) §4.11,
[03-modele-donnees.md](03-modele-donnees.md) §3.4.

### 1.1.4 Stockage de fichiers

Une interface abstraite (`FileStorage`) découple le code applicatif du
backend de stockage réel ; l'implémentation fournie (`LocalFileStorage`)
écrit à plat sur disque avec un versionnement entier par
`(classe, objet, attribut)` — jamais d'écrasement, cohérent avec
l'historisation ci-dessus. Remplaçable par S3/MinIO plus tard sans modifier
les routes qui l'utilisent. Détail technique :
[04-api-backend.md](04-api-backend.md) §4.6.

### 1.1.5 Types d'attribut riches (fichier, image, csv, select, secret, datasource, boolean)

Le jeu de types d'un attribut est passé de 5 (`string`/`integer`/`float`/
`joint-1-1`/`joint-1-n`) à 12 : `file`/`image`/`csv` (pointeur vers le
stockage de fichiers), `select` (liste fermée de valeurs), `secret` (valeur
chiffrée, jamais renvoyée en clair par la lecture générique), `datasource`
(pointeur vers une connexion externe, ex. Prometheus) et `boolean` (case à
cocher). Couvre des besoins métier courants sans sortir du modèle dynamique
générique. Exemple : un attribut `statut` de type `select` sur un ticket
(`ouvert`/`en_cours`/`resolu`/`ferme`), ou un mot de passe de connexion
stocké chiffré et masqué (`"••••••••"`) à la lecture. Détail technique :
[03-modele-donnees.md](03-modele-donnees.md) §3.2bis/§3.2ter/§3.2quater,
[04-api-backend.md](04-api-backend.md) §4.6/§4.7/§4.8,
[05-frontend.md](05-frontend.md) §6.8/§6.9/§6.10.

### 1.1.6 Logo d'objet et icône de classe

Une classe peut définir une icône par défaut (jeu fixe d'icônes embarquées,
pas un upload libre) et chaque objet peut porter son propre logo (attribut
réservé de type `image`), avec possibilité de réutiliser par référence le
logo déjà uploadé d'un autre objet plutôt que de dupliquer les octets. Rend
la page Diagramme plus lisible sans ouvrir une porte d'upload non contrôlée.
Détail technique : [03-modele-donnees.md](03-modele-donnees.md) §3.2bis,
[04-api-backend.md](04-api-backend.md) §4.6,
[05-frontend.md](05-frontend.md) §6.8.

### 1.1.7 Framework de dashboard configurable

Une page Dashboard permet de créer des « tabs » affichant un sous-ensemble
d'objets d'une classe donnée, avec un filtre d'égalité optionnel —
entièrement porté par le modèle dynamique existant (aucune route ni table
backend dédiée). Offre des vues métier prêtes à l'emploi sans développement
spécifique par vue, ex. un tab « Serveurs en production » filtré sur
`environnement = prod`. Détail technique :
[03-modele-donnees.md](03-modele-donnees.md) §3.2ter,
[05-frontend.md](05-frontend.md) §6.11.

### 1.1.8 Extension du modèle CMDB embarqué

Le catalogue de classes fourni par défaut (`model/*.json`) a été fortement
enrichi : compute (serveurs physiques/VM, OS, baies), clusters (Kubernetes,
hyperviseurs, clusters applicatifs haute disponibilité), applicatif
(modules, conteneurs, interfaces, flux de données, versions d'application/
module), réseau (zones, équipements, entrées DNS), organisation (sociétés,
départements, contacts), localisation (bâtiments/étages/salles) et des
« besoins » métier reliant ces CI techniques. Fournit un jeu de données
représentatif d'une CMDB d'entreprise, utilisable tel quel ou comme base à
personnaliser — ex. un besoin « haute disponibilité du site web » référence
les serveurs/clusters applicatifs qui le couvrent. Détail technique :
[03-modele-donnees.md](03-modele-donnees.md) §3.3.

### 1.1.9 Layers — calques d'affichage statiques et dynamiques

Un tag `layers` posé sur une classe (filtre d'affichage pur, pas du RBAC)
permet de regrouper des classes transverses à plusieurs meta-classes
(`infra`/`applicatif`/`organisationnel`/`fonctionnel`/`metier`...) et de les
filtrer ensemble dans la Sidebar/Diagramme. Un complément (« layer
dynamique ») permet en plus à un attribut `select` de faire varier le layer
effectif d'un objet selon sa valeur courante — ex. un serveur de type `vm`
ne porte jamais le layer `physique`, contrairement à un serveur physique de
la même classe. Une liste de layers par défaut (configurable par
global-admin dans la page Configuration) est en plus toujours proposée
dans la Sidebar/Diagramme, même si aucune classe du modèle ne les
référence encore — évite qu'un layer attendu (ex. `metier`) disparaisse
simplement parce que le modèle chargé ne compte provisoirement aucune
classe taguée avec. Détail technique :
[03-modele-donnees.md](03-modele-donnees.md) §3.2ter/§3.2sexies,
[04-api-backend.md](04-api-backend.md) §4.11 (`GET`/`PUT
/api/config/default_layers`), [05-frontend.md](05-frontend.md) §6.12.

### 1.1.10 Liens transitifs du graphe (page Diagramme)

Quand un filtre de classe masque un nœud intermédiaire d'une chaîne de
jointures (A→B→C, B masqué), le lien logique entre A et C est reconstitué
(trait pointillé) plutôt que simplement perdu. Préserve la lisibilité des
relations métier malgré un filtrage actif — ex. masquer la classe `poste`
ne casse pas visuellement le lien entre une personne et son service. Détail
technique : [05-frontend.md](05-frontend.md) §6.4.

### 1.1.11 IHM de configuration : tous les types d'attribut

La page Configuration permet de créer/éditer un attribut de n'importe quel
type supporté par le modèle (plus seulement 5 des 11/12 existants), avec une
colonne « Options » adaptée par type (classes cibles, séparateur `csv`,
valeurs `select`...) et des validations bloquantes qui comblent des trous du
schéma JSON (ex. un tableau `values`/`classes` vide passerait la validation
JSON Schema mais échouerait plus tard de façon confuse). Détail technique :
[05-frontend.md](05-frontend.md) §6.10.

### 1.1.12 Autosuggest

Un attribut texte marqué `autosuggest` propose, à la saisie, les valeurs
déjà utilisées (actives seulement) les plus proches de la frappe en cours
(tri par distance d'édition), plutôt qu'une liste figée comme `select`.
Réduit les doublons/fautes de frappe sur des champs répétitifs (ville,
version logicielle...) sans imposer un ensemble fermé de valeurs — ex. taper
« Gen » sur la localisation d'un datacenter propose « Genève »/« Geneva »
déjà saisis ailleurs. Détail technique :
[03-modele-donnees.md](03-modele-donnees.md) §3.2quinquies,
[04-api-backend.md](04-api-backend.md) §4.9,
[05-frontend.md](05-frontend.md) §6.9.

### 1.1.13 Recherche globale

Un onglet Recherche interroge en un seul appel tous les objets/attributs
texte, toutes classes/meta-classes confondues, avec des facettes
(layers/classes/attributs) permettant d'affiner la liste affichée, et deux
options (`fuzzy`, recherche approchante ; `history`, inclut les valeurs
historisées). Permet de retrouver un objet sans connaître d'avance sa
classe. Détail technique : [04-api-backend.md](04-api-backend.md) §4.10,
[05-frontend.md](05-frontend.md) §6.14.

### 1.1.14 Validation à la création de classe

La meta-classe d'une nouvelle classe peut être déduite automatiquement de
son nom (cas non ambigu, une seule classe dans le formulaire) plutôt que de
bloquer la sauvegarde ; le nom de classe est garanti unique tous
meta-classes confondues, vérifié côté frontend ET backend. Évite une saisie
inutile et une collision silencieuse de nom de classe entre deux
meta-classes. Détail technique : [04-api-backend.md](04-api-backend.md) §4.4.

### 1.1.15 Durcissement sécurité : unicité attribut/classe et résolution deny-priority

Toute déclaration dupliquée d'un nom d'attribut au sein d'une classe, ou
d'un nom de classe au sein d'une même meta-classe, est bloquée à l'écriture
(`409`). Pour des données de schéma déjà existantes avant ce durcissement,
toute ambiguïté restante est résolue en priorité « deny » : une déclaration
`secret` l'emporte toujours sur une déclaration non-secrète du même nom, sur
tous les points de code qui résolvent un attribut par nom (chiffrement,
masquage en lecture, routes dédiées). Ferme une fuite potentielle de secret
en clair découverte en revue croisée. Détail technique :
[04-api-backend.md](04-api-backend.md) §4.4/§4.7/§4.9.

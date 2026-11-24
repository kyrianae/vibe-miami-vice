# Cas d'usage — revue face à l'état réel implémenté (2026-11-24)

> Revu contre le code réel (`model/*.json`, `plan-mark3.md` actions
> 1-22, dont l'action 17 — extension massive du modèle CMDB embarqué,
> commit `af2d544` — explicitement intégrée ici) le 2026-11-24, pas
> seulement contre les intentions d'origine. Les entrées dupliquées/
> éparses du brouillon initial ont été fusionnées, une par cas d'usage.
> Chaque cas d'usage ajouté ou enrichi décrit un parcours concret
> (quelles classes, quelles jointures `joint-1-1`/`joint-1-n`), pas
> seulement une liste de prérequis livrés par numéro d'action — le
> détail exhaustif des attributs reste dans `03-modele-donnees.md`.

## Cas d'usage accessibles ou implémentables (dès maintenant)

Tous les prérequis listés sont déjà livrés — ces cas d'usage sont
construisibles aujourd'hui avec le modèle dynamique existant, sans
développement supplémentaire (juste de la configuration/modélisation
via `ConfigurationPage.tsx`).

- **CMDB** (avec ou sans supervision intégrée) — `model/itil_cmdb.json`
  (meta-classe `cmdb` : `datacenter`, `baie_serveur`, `serveur`, `os`,
  `base_de_donnees`, `application`, `module`, `container`,
  `namespace_kubernetes`, `interface`, `flux_donnee`,
  `application_versionnee`, `module_versionne`, `materiel`,
  `service_metier`, `fournisseur`, `contrat_support` — 17 classes,
  contre 7 avant l'action 17). Supervision renforcée par : type
  `datasource` (action 9, démo réelle
  `datasource_prometheus`→`query`→`serveur.monitoring` en DB), icône de
  classe (action 4, `classIcons.tsx`), logo par objet (action 4,
  attribut `logo` réservé sur `serveur`).

- **Cartographie applicative détaillée** (modules, versions, contrats
  d'échange) — parcours : `application` →1-n→ `module` (ses briques
  fonctionnelles), `application` →1-1→ `base_de_donnees` (son stockage),
  `application` →1-n→ `interface` (ses contrats exposés, `type` select
  REST/SOAP/file/queue/db). Deux `interface` se relient via `flux_donnee`
  (`interface_source` →1-1, `interface_cible` →1-1) pour documenter un
  échange de données entre deux applications sans lien direct
  application↔application — utile pour cartographier les flux
  inter-applicatifs d'un SI (ex. flux de facturation entre CRM et ERP).
  Le versioning suit une chaîne dédiée : `application` →1-n→
  `application_versionnee` →1-n→ `module_versionne` →1-1→ `module` —
  une version d'application donne directement la liste des versions de
  modules qui la composent, utile pour un suivi de release ou un audit
  d'écart de version entre environnements. Les champs `version` de
  `application_versionnee`/`module_versionne` sont en `autosuggest`
  (action 20), donc les valeurs déjà saisies sont proposées à la
  ressaisie. Point de vigilance : `model/ansible_inventory.json` porte
  aussi `version_logicielle` (version/environnement/date_deploiement),
  chevauchement fonctionnel non résolu avec `application_versionnee` —
  à clarifier avant de bâtir un cas d'usage qui mélangerait les deux.

- **Infrastructure de virtualisation et conteneurs** (clusters
  Kubernetes, hyperviseurs, haute disponibilité applicative) —
  `model/cluster.json` (meta-classe `cluster`, dépend de `cmdb` et
  `element_avec_ip`) : `kube` (nom/version/namespace par défaut),
  `hyperviseur` (nom/type ex. vmware-proxmox/capacité CPU/capacité
  RAM), `cluster_applicatif` (regroupe plusieurs `serveur` derrière une
  IP virtuelle commune). Parcours concret VM : `serveur.type=vm` →1-1→
  `hyperviseur` (quel socle l'héberge) et `serveur` →1-1→ `os` (son
  système d'exploitation, classe dédiée nom/type linux-windows/
  architecture/version/`active` en booléen). Parcours concret
  conteneurs : un `kube` regroupe plusieurs `namespace_kubernetes`
  (chacun rattaché via `namespace_kubernetes.kube` →1-1→ `kube`), et
  chaque namespace regroupe plusieurs `container` (`nom`/`image`, via
  `container.namespace_kubernetes` →1-1→ `namespace_kubernetes`).
  Parcours HA : `cluster_applicatif` →1-1→ `application`
  (quelle appli est servie) + →1-n→ `serveur` (quels nœuds la portent)
  + →1-1→ `addresse_ip` en tant que VIP (réutilise la classe réseau
  existante plutôt qu'un champ IP brut) — permet une vue "cette
  application est servie en LB/HA par ces N serveurs derrière cette
  IP".

- **Inventaire et localisation physique multi-site** — deux niveaux de
  granularité coexistent, non reliés entre eux par une jointure directe
  (point vérifié dans le code, à ne pas supposer) :
  - `datacenter` (CMDB) porte un champ texte libre `localisation`
    (autosuggest) et reste le rattachement physique de `baie_serveur`
    (→1-1, + `position_rack`) et de `serveur` (→1-1) — niveau "quel
    site".
  - `model/localisation.json` (meta-classe `localisation`) détaille un
    niveau plus fin pour le patrimoine immobilier : un `batiment`
    (adresse complète : numéro/type de voie/nom de voie/pays/code
    postal/ville) regroupe des `etage` (`etage.batiment` →1-1→
    `batiment`), chacun regroupant des `salle` (`salle.etage` →1-1→
    `etage`). Seule `materiel` (ci-dessous) s'y rattache aujourd'hui via
    `materiel.salle` →1-1→ `salle`. Un cas
    d'usage "localiser précisément une baie dans un bâtiment/étage/
    salle" nécessiterait d'ajouter ce lien sur `baie_serveur`, pas
    construit à ce jour — à noter si le besoin se présente.

- **Inventaire matériel générique avec affectation** (postes,
  imprimantes, périphériques) — `materiel` (extension `itil_cmdb.json`,
  layers `infra`+`physique`) : `nom`, `type` (select
  poste/imprimante/peripherique), `numero_serie`, `personne_affectee`
  (→1-1 `personne_physique`, qui a reçu le matériel) et `salle` (→1-1
  `salle`, où il se trouve physiquement). Parcours concret : partir
  d'une `personne_physique` et lister tout le matériel qui lui est
  affecté, ou partir d'une `salle` et lister tout ce qui s'y trouve
  physiquement (le parc d'un étage/bâtiment). Combinable avec l'image
  (action 3) pour une fiche avec photo, et avec `ticketing.ci_concerne`
  (ci-dessous) pour rattacher un ticket de support à un poste précis.

- **Organisation d'entreprise unifiée** (sociétés, départements,
  organigramme, coordonnées) — `model/organisation.json` fusionne
  l'ancien organigramme (`service_organisation`, `poste`, `role`,
  `groupe`) avec une couche société/contact ajoutée à l'action 17 :
  `societe` (→1-1 `holding`, autoréférence pour un groupe de sociétés),
  `departement` (→1-1 `societe`), `contact` (type select tel/mail,
  `valeur`, →1-1 `cible` polymorphe vers `personne_physique`,
  `societe`, `service_organisation` ou `departement`). Parcours
  concret : depuis une `societe`, remonter sa `holding` (structure de
  groupe), descendre vers ses `departement`, et pour chaque entité
  (personne, société, service, département) retrouver tous ses
  `contact` via la jointure polymorphe — un seul modèle de contact pour
  toute l'organisation plutôt qu'un champ téléphone/email dupliqué par
  classe.

- **Gestion des besoins métier reliés à l'infrastructure** —
  `model/besoin.json` (meta-classe `besoin`, dépend de `cmdb` et
  `cluster`) : classe unique `besoin` (`nom`, `description`) avec deux
  jointures `joint-1-n` symétriques vers un large éventail de CI
  techniques (`serveur`, `application`, `cluster_applicatif`, `kube`,
  `hyperviseur`, `materiel`, `interface`, `module`) : `emerge_par` (quel
  besoin a motivé la création de ces CI) et `couvert_par` (quels CI
  répondent concrètement au besoin aujourd'hui). Parcours concret :
  tracer la justification métier d'une appli ou d'un cluster ("pourquoi
  ce `cluster_applicatif` existe") via `emerge_par`, ou à l'inverse,
  pour un `besoin` donné, vérifier d'un coup d'œil s'il est réellement
  couvert en listant les CI dans `couvert_par` (base d'un audit de
  couverture besoin/réalisation).

- **Coffre-fort documentaire / GED** (versions de fichiers par classe/
  id/attribut) — type attribut `file` + `FileStorage`/`LocalFileStorage`
  livrés (actions 2/3), versionnement incrémental, historique conservé.
  Applicable à n'importe laquelle des classes ci-dessus (ex. attacher
  un contrat PDF à `contrat_support`, un schéma réseau à `zone_reseau`).

- **Gestionnaire de secrets / vault de credentials** — type attribut
  `secret` livré (action 8), chiffrement Fernet, masquage strict en
  lecture générique, route reveal réservée global-admin.

- **Cartographie réseau et DNS** — `model/reseau.json` (meta-classe
  `element_avec_ip`) : `addresse_ip` →1-1→ `vlan` (et `vlan` →1-n→
  `membres` en retour, navigation dans les deux sens), `entree_dns`
  (type select A/CNAME/MX/TXT/NS, cible, zone DNS). Parcours concret :
  une `zone_reseau` (niveau de sécurité) regroupe plusieurs
  `equipement_reseau` (type select routeur/switch/firewall,
  `equipement_reseau.zone` →1-1→ `zone_reseau`) — retrouver d'un coup
  d'œil tous les firewalls d'une zone sensible ; depuis une
  `addresse_ip`, retrouver son `vlan` et son CIDR (`vlan.definition`)
  sans classe `subnet` séparée (le VLAN porte déjà le CIDR dans ce
  modèle). Point de vigilance : `cible` et `zone_dns` sur `entree_dns`
  sont de simples attributs `string` (texte libre, vérifié
  `model/reseau.json` lignes 110-119), sans `joint-1-1`/`joint-1-n` —
  `cible` ne pointe pas structurellement vers une `addresse_ip` du
  modèle, ni `zone_dns` vers une `zone_reseau` ; une recherche d'une
  entrée DNS pointant réellement vers une IP connue du modèle
  nécessiterait d'ajouter ces jointures, non construites à ce jour.

- **Recherche globale transverse** (un champ, toutes classes/
  meta-classes confondues) — route `GET /api/search?q=...&fuzzy=...
  &history=...` (action 21), page `frontend/src/pages/
  RecherchePage.tsx` : cherche dans les attributs de tous les objets,
  toutes classes/meta-classes confondues, sans devoir connaître à
  l'avance la classe ou le layer porteur de la donnée. Par défaut :
  attributs actifs seulement (`history=false`), correspondance
  substring directe (`fuzzy=false`). `history=true` étend la recherche
  à l'historique complet (y compris valeurs fermées) ; `fuzzy=true`
  propose des valeurs proches sélectionnables (réutilise `rapidfuzz`,
  action 20). Exclusion explicite du type `secret` (sécurité, pas une
  simple optimisation). Résultat : facettes layers (statique, action
  14)/classes/attributs qui filtrent la liste d'objets en dessous,
  filtrage en ET progressif par sélection de facette successive.
  Parcours concret : retrouver en un seul champ tous les objets portant
  une valeur donnée, quelle que soit la classe (ex. un numéro de série
  recherché aussi bien dans `materiel` que dans un futur inventaire
  hardware), sans naviguer classe par classe. Détail de conception
  complet : `specifications/07-roadmap.md` §10.18.

- **Outil de gestion de ticket avec CI large** — `model/ticketing.json`
  déjà livré avec `statut`/`priorite` en type `select` (action 7).
  `ticket.ci_concerne` (joint-1-n) couvre désormais 13 classes CMDB
  (`serveur`, `application`, `service_metier`, `baie_serveur`, `os`,
  `module`, `container`, `namespace_kubernetes`, `interface`,
  `flux_donnee`, `application_versionnee`, `module_versionne`,
  `materiel`) — un ticket peut viser aussi bien un serveur qu'un poste
  utilisateur (`materiel`) ou une version applicative précise
  (`application_versionnee`). Renforcé par fichier/pièces jointes
  (action 3) et icône de type de ticket (action 4).

- **Inventaire physique avec photos** (parc matériel, immobilier, flotte
  véhicules) — type attribut `image` livré (action 3). Le catalogue
  `materiel` dédié (action 17) couvre déjà le cas poste/imprimante/
  périphérique ; pour d'autres parcs (véhicules, mobilier), les classes
  restent à définir librement via `ConfigurationPage.tsx`.

- **Outil de bibliothèque / vinothèque** — image pour
  couverture/étiquette (action 3) et `csv` pour un tableau de données
  associé (action 3) tous deux livrés. Classes à modéliser librement.

- **Vue métier dédiée par rôle** (ex. vue ticketing lecture seule sur
  les serveurs, vue CMDB complète pour les admins) — framework
  dashboard/tab entièrement livré (actions 10a-10d : modèle, lecture
  seule, CRUD, sélection filtrée de sous-objets) + RBAC tenant déjà
  appliqué automatiquement à toute lecture d'objet (`_tenant_read_filter`,
  antérieur à mark3). Avec le modèle enrichi (action 17), un dashboard
  "vue infra" peut désormais agréger des tabs sur `cluster_applicatif`,
  `hyperviseur` et `materiel` côte à côte, sans développement
  supplémentaire. La distinction stricte "affichage partiel en lecture
  seule garanti par rôle" au niveau composant IHM n'est pas une brique
  dédiée, mais le filtrage tenant déjà en place couvre l'essentiel du
  besoin réel.

## Cas d'usage roadmap (prérequis manquants)

- **Dashboard de monitoring concret** (requêtes en direct, pas juste
  affichage de métadonnées) — `datasource`/`query` (action 9) ne
  *stockent* qu'une définition de connexion/requête, aucune route
  n'exécute réellement la requête contre Prometheus (noté
  explicitement hors scope à l'action 9 : « aucun câblage d'exécution
  de requête »). Reste à construire : exécution de requête à la
  demande, rendu résultat (valeur instantanée / série temporelle) dans
  un tab dashboard.

- **Inférence / machine learning sur le graphe d'objets** — en
  intégrant le projet lui-même comme datasource : apprentissage
  multi-dimensionnel sur les attributs, propagation des valeurs
  inférées via les jointures existantes (`joint-1-1`/`joint-1-n`).
  Le modèle enrichi (action 17) fournit davantage de dimensions
  exploitables (clusters, organisation, localisation, besoins), mais
  les prérequis techniques manquent toujours : une « datasource ML »
  dédiée, un outil d'import de données en masse (action 11), un type
  d'attribut « valeur inférée ». Aucun des trois construit.

- **Pipeline d'ingestion automatisé et récurrent** (binding champs
  source → attributs + planification) — action 11 (outil d'ingestion
  avec binding) volontairement non traitée (consigne utilisateur
  2026-11-24, reportée en action 25) ; la planification/scheduler reste
  explicitement hors scope même une fois l'action 11 livrée
  (`tocheck.md` #12, jamais engagé). Alimenterait aussi le cas
  d'inférence ML ci-dessus une fois fait, ainsi que le peuplement en
  masse du modèle CMDB étendu (ex. import d'un inventaire Kubernetes
  existant dans `kube`/`namespace_kubernetes`/`container`).

- **Migration / interconnexion en masse via import CSV** — nuance
  importante par rapport au brouillon d'origine : le type d'attribut
  `csv` (action 3) permet d'**afficher/attacher** un fichier CSV à un
  objet déjà existant (tableau lecture seule), il ne **crée pas en
  masse** des objets à partir d'un CSV uploadé. La vraie capacité de
  migration/import en masse dépend de l'outil d'ingestion avec binding
  (action 11), pas du type d'attribut seul.

- **Rattachement fin baie/salle/bâtiment** — `baie_serveur` ne porte
  aujourd'hui qu'un lien vers `datacenter` (pas vers `salle`), alors que
  `materiel` est la seule classe reliée à la chaîne
  `salle`→`etage`→`batiment`. Un cas d'usage "plan de salle avec
  position exacte d'une baie" demanderait d'ajouter ce lien, non fait à
  ce jour.

- **Déduplication du versioning applicatif** —
  `application_versionnee`/`module_versionne` (action 17) et
  `version_logicielle` (`ansible_inventory.json`, antérieur) se
  recoupent fonctionnellement (suivi de version d'une application par
  environnement/date de déploiement) sans être unifiés. Un cas d'usage
  de suivi de déploiement combinant les deux resterait incohérent tant
  que ce chevauchement n'est pas clarifié ou fusionné.

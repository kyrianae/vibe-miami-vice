# Cas d'usage — revue face à l'état réel implémenté (2026-11-23)

> Revu contre le code réel (`model/*.json`, `plan-mark3.md` actions 1-20)
> le 2026-11-23, pas seulement contre les intentions d'origine. Les
> entrées dupliquées/éparses du brouillon initial ont été fusionnées,
> une par cas d'usage.

## Cas d'usage accessibles ou implémentables (dès maintenant)

Tous les prérequis listés sont déjà livrés — ces cas d'usage sont
construisibles aujourd'hui avec le modèle dynamique existant, sans
développement supplémentaire (juste de la configuration/modélisation
via `ConfigurationPage.tsx`).

- **CMDB** (avec ou sans supervision intégrée) — `model/itil_cmdb.json`
  (7 classes : datacenter/serveur/base_de_donnees/application/
  service_metier/fournisseur/contrat_support) déjà livré. Supervision
  renforcée par : type `datasource` (action 9, démo réelle
  `datasource_prometheus`→`query`→`serveur.monitoring` en DB), icône de
  classe (action 4, `classIcons.tsx`), logo par objet (action 4,
  attribut `logo` réservé). Catalogue élargi (baies/clusters/réseau/
  organisation/localisation/hardware) prévu mais pas bloquant — voir
  action 17 en roadmap pour l'enrichir, le socle actuel suffit déjà à
  démarrer.

- **Coffre-fort documentaire / GED** (versions de fichiers par classe/
  id/attribut) — type attribut `file` + `FileStorage`/`LocalFileStorage`
  livrés (actions 2/3), versionnement incrémental, historique conservé.

- **Gestionnaire de secrets / vault de credentials** — type attribut
  `secret` livré (action 8), chiffrement Fernet, masquage strict en
  lecture générique, route reveal réservée global-admin.

- **Inventaire physique avec photos** (parc matériel, immobilier, flotte
  véhicules) — type attribut `image` livré (action 3), classes à définir
  librement via `ConfigurationPage.tsx` (le catalogue `materiel`
  dédié de l'action 17 l'enrichirait mais n'est pas un prérequis bloquant,
  le modèle dynamique générique suffit déjà).

- **Outil de gestion de ticket** — `model/ticketing.json` déjà livré
  avec `statut`/`priorite` en type `select` (action 7). Renforcé par
  fichier/pièces jointes (action 3) et icône de type de ticket (action
  4). Les 3 prérequis d'origine sont tous faits.

- **Outil de bibliothèque / vinothèque** — image pour
  couverture/étiquette (action 3) et `csv` pour un tableau de données
  associé (action 3) tous deux livrés. Classes à modéliser librement.

- **Vue métier dédiée par rôle** (ex. vue ticketing lecture seule sur
  les serveurs, vue CMDB complète pour les admins) — framework
  dashboard/tab entièrement livré (actions 10a-10d : modèle, lecture
  seule, CRUD, sélection filtrée de sous-objets) + RBAC tenant déjà
  appliqué automatiquement à toute lecture d'objet (`_tenant_read_filter`,
  antérieur à mark3). La distinction stricte "affichage partiel en
  lecture seule garanti par rôle" au niveau composant IHM n'est pas une
  brique dédiée, mais le filtrage tenant déjà en place couvre l'essentiel
  du besoin réel.

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
  Prérequis manquants : une « datasource ML » dédiée, un outil
  d'import de données en masse (action 11), un type d'attribut
  « valeur inférée ». Aucun des trois construit.

- **Pipeline d'ingestion automatisé et récurrent** (binding champs
  source → attributs + planification) — action 11 (outil d'ingestion
  avec binding) non faite ; la planification/scheduler reste
  explicitement hors scope même une fois l'action 11 livrée
  (`tocheck.md` #12, jamais engagé). Alimenterait aussi le cas
  d'inférence ML ci-dessus une fois fait.

- **Migration / interconnexion en masse via import CSV** — nuance
  importante par rapport au brouillon d'origine : le type d'attribut
  `csv` (action 3) permet d'**afficher/attacher** un fichier CSV à un
  objet déjà existant (tableau lecture seule), il ne **crée pas en
  masse** des objets à partir d'un CSV uploadé. La vraie capacité de
  migration/import en masse dépend de l'outil d'ingestion avec binding
  (action 11), pas du type d'attribut seul — reclassé en roadmap pour
  cette raison, contrairement à l'intention d'origine du brouillon.

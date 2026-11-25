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

Catalogue fonctionnel : §1.1.1 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §2bis de [02-architecture.md](02-architecture.md)
(`backend/auth/rbac.py`), RBAC documenté route par route dans
[04-api-backend.md](04-api-backend.md).

## 10.3 Authentification (fait — Keycloak, `plan-mark1.md` action 7b)

Catalogue fonctionnel : §1.1.2 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §2bis de [02-architecture.md](02-architecture.md)
(`backend/auth/auth.py`), comparatif des options : `doc/choix-authent.md`.

## 10.4 Historisation des objets et attributs (fait — `plan-mark2.md` actions 6.0-6.4)

Catalogue fonctionnel : §1.1.3 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique (suppression logique, cascade, purge différée,
`app_config`) : §4.11 de [04-api-backend.md](04-api-backend.md), §3.4 de
[03-modele-donnees.md](03-modele-donnees.md).

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

Catalogue fonctionnel : §1.1.10 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique (`resolveVisibleTargets`, garde-fous, construction en 2
passes) : §6.4 de [05-frontend.md](05-frontend.md).

## 10.7 Stockage de fichiers (fait — `plan-mark3.md` action 2)

Catalogue fonctionnel : §1.1.4 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique (`FileStorage`/`LocalFileStorage`, versionnement,
`FILE_STORAGE_ROOT`) : §4.6 de [04-api-backend.md](04-api-backend.md).

## 10.8 Types d'attribut fichier/image/csv, logo d'objet, icône de classe (fait — `plan-mark3.md` actions 3-4)

Catalogue fonctionnel : §1.1.5/§1.1.6 de
[01-fonctionnelle.md](01-fonctionnelle.md). Détail technique : §3.2bis de
[03-modele-donnees.md](03-modele-donnees.md), §4.6 de
[04-api-backend.md](04-api-backend.md), §6.8 de
[05-frontend.md](05-frontend.md).

## 10.9 Type d'attribut select/enum (`tocheck.md` #18, fait — `plan-mark3.md` action 7)

Catalogue fonctionnel : §1.1.5 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §3.2ter de [03-modele-donnees.md](03-modele-donnees.md),
§4.7 de [04-api-backend.md](04-api-backend.md), §6.9 de
[05-frontend.md](05-frontend.md).

## 10.10 Type d'attribut secret/password (`tocheck.md` #19, fait — `plan-mark3.md` action 8)

Catalogue fonctionnel : §1.1.5 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §3.2ter de [03-modele-donnees.md](03-modele-donnees.md),
§4.7 de [04-api-backend.md](04-api-backend.md), §6.9 de
[05-frontend.md](05-frontend.md).

## 10.11 Type d'attribut datasource (`tocheck.md` #1, fait — `plan-mark3.md` action 9)

Catalogue fonctionnel : §1.1.5 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §3.2ter de [03-modele-donnees.md](03-modele-donnees.md),
§4.7 de [04-api-backend.md](04-api-backend.md).

## 10.12 Framework de dashboard/affichage configurable (`tocheck.md` #9, actions 10a-10d fait, 10e hors scope — `plan-mark3.md` actions 10a-10d)

Catalogue fonctionnel : §1.1.7 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §3.2ter de [03-modele-donnees.md](03-modele-donnees.md),
§6.11 de [05-frontend.md](05-frontend.md).

## 10.12bis IHM de configuration : les 11 types d'attribut (`tocheck.md` #14-20, fait — `plan-mark3.md` action 13)

Catalogue fonctionnel : §1.1.11 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §6.10 de [05-frontend.md](05-frontend.md).

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

## 10.14 Extension du modèle CMDB embarqué (implémenté — `plan-mark3.md` action 17)

Catalogue fonctionnel : §1.1.8 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique (classes/attributs réels par fichier `model/*.json`) :
§3.3 de [03-modele-donnees.md](03-modele-donnees.md).

## 10.15 Layer dynamique piloté par un attribut `select` (implémenté — `plan-mark3.md` action 18)

Catalogue fonctionnel : §1.1.9 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique (champ `layer_map`) : §3.2sexies de
[03-modele-donnees.md](03-modele-donnees.md) ; `getObjectEffectiveLayers` :
§6.12 de [05-frontend.md](05-frontend.md) ; layers par défaut
(`GET`/`PUT /api/config/default_layers`, registre `app_config`) : §4.11 de
[04-api-backend.md](04-api-backend.md).

## 10.16 Type d'attribut `boolean` (fait — `plan-mark3.md` action 19)

Catalogue fonctionnel : §1.1.5 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §3.2quater de [03-modele-donnees.md](03-modele-donnees.md),
§4.8 de [04-api-backend.md](04-api-backend.md).

## 10.17 Autosuggest : suggestions de valeurs apprises sur un attribut texte (fait — `plan-mark3.md` action 20)

Catalogue fonctionnel : §1.1.12 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §3.2quinquies de
[03-modele-donnees.md](03-modele-donnees.md), §4.9 de
[04-api-backend.md](04-api-backend.md), §6.9 de [05-frontend.md](05-frontend.md).

## 10.18 Recherche globale (implémenté — `plan-mark3.md` action 21)

Catalogue fonctionnel : §1.1.13 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §4.10 de [04-api-backend.md](04-api-backend.md), §6.14 de
[05-frontend.md](05-frontend.md).

## 10.19 Validation création de classe : meta_class auto, nom de classe unique (implémenté — `plan-mark3.md` action 22)

Catalogue fonctionnel : §1.1.14 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §4.4 de [04-api-backend.md](04-api-backend.md).

## 10.19bis Durcissement sécurité : unicité attribut/classe + résolution deny-priority (implémenté — `plan-mark3.md` action 21bis)

Catalogue fonctionnel : §1.1.15 de [01-fonctionnelle.md](01-fonctionnelle.md).
Détail technique : §4.4/§4.7/§4.9 de [04-api-backend.md](04-api-backend.md).


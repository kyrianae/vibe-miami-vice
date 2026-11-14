# Idées à évaluer

Notes sur 5 (1 = faible, 5 = fort). Intérêt = valeur produit perçue. Difficulté = effort/risque technique estimé.

| # | Idée | Intérêt /5 | Difficulté /5 | Commentaire |
|---|------|:---:|:---:|---|
| 1 | Type d'attribut "datasource" via définition JSON + meta-class (Prometheus, PostgreSQL) | 4 | 3 | Prérequis des idées ML/ingestion ci-dessous (#2, #6, #7, #8) |
| 2 | Intégration du projet ML voisin comme nouveau type de datasource | 4 | 4 | Dépend de #1 + API du projet externe à spécifier |
| 3 | Apprentissage multi-dimensionnel (attributs de toutes classes comme dimensions d'entrée) | 3 | 5 | Gros morceau ML générique, risque de scope énorme |
| 4 | Propagation des valeurs inférées via le graphe de jointures (joint-1-1/joint-1-n) | 3 | 4 | S'appuie sur le moteur deref/depth existant (§10.1) |
| 5 | Attribut de type "valeur inférée" (distinct d'une saisie manuelle) | 3 | 2 | Mécanique si le schéma attribut est déjà extensible |
| 6 | Import de data depuis/vers le projet ML pour alimenter l'apprentissage | 3 | 3 | Lié à #1/#2, format d'échange à définir |
| 7 | Type d'attribut "query instant" | 3 | 2 | Proche d'un type datasource/query si #1 posé |
| 8 | Type d'attribut "query vector" (début/fin) | 3 | 3 | UI plus complexe que #7 (plage temporelle, rendu série) |
| 9 | Framework de dashboard/affichage configurable, tabs éditables dans l'IHM | 5 | 4 | Gros chantier frontend, à découper en sous-actions |
| 10 | Générer des displays différents à partir des tabs éditées (sous-objets sélectionnés, read-only partiel) | 4 | 4 | Dépend de #9, ajoute RBAC fin par vue |
| 11 | Outil d'ingestion avec binding (mapping champs source → attributs) | 4 | 4 | Fondation réutilisable (CSV, API, ...) |
| 12 | Workflow / scheduler des imports | 3 | 3 | Dépend de #11, besoin d'un worker/process séparé |
| 14 | Type d'attribut "fichier" | 4 | 2 | Dépend du stockage fichiers — voir `plan-mark3.md` action 2 |
| 15 | Type d'attribut "image" (jpg/svg/png) | 3 | 2 | Spécialisation de #14 + validation mime |
| 16 | Logo surchargeable par objet (sélection parmi logos existants ou import), utilisé dans les diagrammes | 3 | 3 | Dépend de #15, touche DiagramPage |
| 17 | Icône par défaut par classe (sélection quand actif) | 2 | 2 | Petite feature UI, indépendante. Complément (2026-11-14) : auto-récupération d'un SVG sur svgrepo.com à partir du nom de classe, passé par une homogénéisation configurable (couleur/trait/viewBox) ; fallback rond+nom si échec ou pas d'API de recherche dispo côté svgrepo (point à vérifier) |
| 18 | Type d'attribut select/enum (valeurs fixes : statut, priorité...) pour workflow type ticket | 4 | 2 | Manque identifié, gain rapide, peu coûteux |
| 19 | Type d'attribut secret/password (flag valeur masquée) | 3 | 2 | Implique un vrai chiffrement, pas juste masquage UI |
| 20 | Type d'attribut CSV (avec attribut séparateur) | 2 | 2 | Simple, utilité plus niche |
| 22 | Découpage microservices (ex: backend écriture / backend lecture séparés, backend storage dédié pour fichiers/autres côtés), pour scaler et intégrer des traitements type inférence/apprentissage, bascule Kubernetes | 5 | 4 | Fait d'abord : découpage interne de `app.py` en modules, `plan-mark3.md` action 1 ; prérequis d'infra pour #2/#3/#4 (ML) ; impacte RBAC/tenant partagé entre services et la cohérence read/write (réplication, latence). Bénéfice additionnel : une fois séparé, chaque modif ne demande d'analyser que le code du service concerné (contexte remonté plus petit à chaque passage, moins de risque de régression croisée) — baisse la difficulté perçue des évolutions futures, pas celle de la migration elle-même |

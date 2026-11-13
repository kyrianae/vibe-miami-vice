# Spécifications — Miami Vice

> Document généré par reverse engineering du code source présent dans le dépôt
> au 2026-11-07. Il décrit le fonctionnement **réel** du projet tel qu'implémenté
> (backend `backend/app.py`, frontend `frontend/src/`, modèle `model/*.json`,
> schéma SQL `sql/init.sql`, orchestration `docker-compose.yml`), y compris les
> écarts entre le comportement voulu (docstrings, README) et le comportement
> effectif du code. Les anomalies constatées sont signalées explicitement
> (⚠️) à l'endroit où elles s'appliquent, et résumées en fin de document.
>
> **2026-11-13** : ce document a été scindé en plusieurs fichiers par thème
> (fonctionnel / architecture / technique / anomalies / roadmap), repris
> intégralement depuis l'ancien `specifications.md` (racine du dépôt) — aucun
> contenu réécrit, seulement redécoupé. La numérotation `§N` des sections
> d'origine est conservée telle quelle dans chaque fichier ci-dessous, pour
> que toute référence externe existante (`plan-mark1.md`, `plan-mark2.md`,
> `doc/choix-authent.md`, ...) reste interprétable.

## Index

| Fichier | Sections | Contenu |
|---|---|---|
| [00-audit.md](00-audit.md) | §0 | Avertissement — état réel du code au moment de l'audit |
| [01-fonctionnelle.md](01-fonctionnelle.md) | §1 | Objectif du projet |
| [02-architecture.md](02-architecture.md) | §2, §5, §7 | Architecture générale, flux de démarrage, LDAP (désactivé) |
| [03-modele-donnees.md](03-modele-donnees.md) | §3 | Modèle de données (concepts, `schema.json`, tables PostgreSQL) |
| [04-api-backend.md](04-api-backend.md) | §4 | API Backend — contrat des endpoints |
| [05-frontend.md](05-frontend.md) | §6 | Frontend (pages, thèmes, client API, anomalies) |
| [06-dependances-anomalies.md](06-dependances-anomalies.md) | §8, §9 | Dépendances non exploitées, récapitulatif des anomalies (par gravité) |
| [07-roadmap.md](07-roadmap.md) | §10 | Pistes d'évolution et décisions (multi-tenant, authentification, historisation, partitionnement, liens transitifs) |

§0-§9 restent un **instantané figé** de l'audit du 2026-11-07 (bugs depuis
corrigés par `plan-mark1.md`/`plan-mark2.md`, non remis à jour dans ces
fichiers pour préserver la trace de l'état initial — le statut réel actuel
est dans [07-roadmap.md](07-roadmap.md) et les `plan-mark*.md`).

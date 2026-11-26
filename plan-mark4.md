# Plan d'action — Mark 4 — suite des corrections et évolutions de miami-vice

> **Mark 4** : fait suite à [`finished plan/plan-mark3.md`](finished%20plan/plan-mark3.md)
> (clos le 2026-11-25). Une seule action était reportée de Mark 3 — l'action
> 11 (outil d'ingestion avec binding), volontairement non traitée sur
> demande explicite de l'utilisateur. Reprise ci-dessous comme action 7.

> **Suivi d'avancement** : mêmes conventions que Mark 1/2/3 — chaque action
> porte un champ **Statut** (⬜ à faire / 🔄 en cours / ✅ fait / ⬜ démarche
> interactive requise) mis à jour au fur et à mesure, avec une date et un
> résumé de ce qu'ont confirmé `worker`/`testeur`/`pessimiste`/`candide`/
> `testeur-global`. Le tableau récapitulatif en fin de document doit rester
> synchronisé. Toute décision qui annule/remplace un contenu déjà écrit ici
> doit être annotée explicitement (pas supprimée silencieusement).

> **Démarche interactive** : quand une action porte ce statut, elle n'a
> volontairement pas été conçue dans ce document — avant de l'implémenter,
> poser des questions à l'utilisateur pour définir les points ouverts
> (plutôt que concevoir seul puis faire valider). C'est le cas des actions
> 4, 5 et 7 ci-dessous.

> **En attente** : ajouter ici chaque nouvelle demande (bug, feature,
> évolution) au même format (Problème / Correctif / Effort / Fichiers /
> Statut), avec un numéro d'action, dès qu'elle est formulée.

## 1. [Dette technique / outillage] Optimisation de la configuration des agents et de la verbosité docs/plan

> Demande utilisateur (2026-11-25), posée en brouillon pendant la clôture
> de Mark 3, avec les chiffres d'usage Claude Code suivants à l'appui :
> 100% de l'usage vient de sessions à forte charge de sous-agents ; 47% à
> plus de 150k de contexte ; 29% de sessions actives 8h+ ; 20% de
> sous-agents catégorisés "general-purpose". Répartition par agent : 20%
> general-purpose, 17% worker, 10% orchestrateur, 7% pessimiste, 4%
> testeur, 2% candide, 2% testeur-global.

- **Problème** : deux volets distincts posés par l'utilisateur.
  1. Configuration des agents (`.claude/agents/*.md`) : est-elle cohérente ?
     peut-elle être optimisée ? Chaque agent devrait être « top 0,1% » de
     son métier (prompts/outils bien ciblés pour son rôle précis, pas de
     sur-périmètre). Question explicite : peut-on configurer un modèle
     différent par agent (ex. un modèle moins cher pour les agents au
     rôle simple comme `testeur`/`candide`, un modèle plus capable pour
     `orchestrateur`/`pessimiste`) ?
  2. Documentation et plans (`specifications/*.md`, `plan-mark*.md`) :
     sont-ils trop verbeux, trop denses, ou parasités par de l'information
     historique qui alourdit inutilement la lecture par les agents à
     chaque cycle ?
- **Correctif** : à déterminer à l'implémentation — commence par un audit
  (lecture des 6 fichiers `.claude/agents/*.md` + un échantillon de
  `specifications/*.md`/`plan-mark*.md`) avant de proposer des
  changements concrets. Pistes déjà identifiées en cours de route (Mark 3,
  non closes ici, juste des précédents à connaître) : l'action 24 de
  Mark 3 a déjà extrait la majorité du détail historique de
  `specifications/07-roadmap.md` vers un catalogue fonctionnel plus
  compact — ce travail de « dé-verbosification » est donc déjà engagé sur
  un fichier, reste à évaluer les autres. Sur le `model`/modèle de coût
  par agent : vérifier le paramètre `model` disponible en frontmatter des
  définitions d'agent avant de choisir une répartition.
- **Effort** : faible à moyen pour l'audit, variable pour les correctifs
  selon ce qu'il révèle.
- **Fichiers** : `.claude/agents/*.md`, potentiellement
  `specifications/*.md`/`plan-mark4.md` lui-même si jugé trop dense à son
  tour.
- **Statut** : ✅ fait (2026-11-25).
  - **Configuration des agents** : audit fait — les 6 fichiers sont déjà
    compacts (260 lignes au total, style caveman déjà appliqué, pas de
    sur-périmètre détecté dans les outils déclarés). Le vrai levier de
    coût identifié n'est pas la verbosité du prompt mais le choix de
    modèle par rôle — confirmé disponible via le champ `model:` en
    frontmatter d'agent. Décision utilisateur après proposition : garder
    `sonnet` (défaut) pour `orchestrateur`/`worker`/`pessimiste`/`candide`
    (jugement fin requis pour leur rôle — `pessimiste` a trouvé 2 vraies
    failles de sécurité réelles pendant Mark 3, actions 21/21bis, un
    modèle plus faible aurait un risque réel de les manquer) ; passer
    `testeur`/`testeur-global` en `model: haiku` (rôle mécanique —
    exécuter des commandes, comparer une sortie à un attendu, remplir un
    tableau de résultats — pas de jugement de design à rendre). Appliqué
    dans `.claude/agents/testeur.md` et `.claude/agents/testeur-global.md`.
    **Non validé en conditions réelles à ce stade** (pas encore repassé
    par un cycle orchestrateur complet depuis le changement) — à
    surveiller sur les prochaines actions Mark 4 : si la qualité des
    rapports `testeur`/`testeur-global` se dégrade (faux PASS, tests
    superficiels), revenir à `sonnet` pour ces deux rôles.
  - **Les 20% "general-purpose"** : ce n'est pas un fichier `.claude/
    agents/` à éditer — c'est le type par défaut du SDK quand aucun
    `subagent_type` n'est précisé à l'appel `Agent(...)`. Correctif
    comportemental (pas de fichier modifié) : toujours nommer un
    `subagent_type` concret parmi les 6 rôles existants quand la tâche
    correspond, et sinon passer explicitement un `model` (souvent
    `haiku`) sur l'appel `Agent(...)` pour une investigation ponctuelle
    bornée plutôt que de laisser le modèle par défaut s'appliquer sans y
    penser.
  - **Verbosité documentation/plans** : déjà largement traitée par
    l'action 24 de Mark 3 (`specifications/07-roadmap.md` 1605→181
    lignes, catalogue fonctionnel compact dans `01-fonctionnelle.md`) et
    par la clôture de Mark 3 elle-même (`plan-mark3.md`, 2800+ lignes
    d'historique détaillé, déplacé en archive — les agents travaillant
    sur Mark 4 ne le lisent plus par défaut, seul `plan-mark4.md`,
    nettement plus court, et `resume.md`, juste le tableau). Pas de
    nouveau correctif jugé nécessaire sur `specifications/*.md` à ce
    stade — à réévaluer si la densité perçue revient une fois Mark 4
    suffisamment avancé.

## 1b. [Nouvelle fonctionnalité] Monitoring visuel de l'activité des agents Claude via Prometheus

> Demande utilisateur (2026-11-25), suite directe de l'action 1 :
> `claude_agent{agent="..."} 0|1` (exporter `tools/claude-agent-exporter/`,
> commit `892fc55`) existe et a été vérifié fonctionnel en requêtant
> Prometheus directement (`/api/v1/query`), mais reste un signal brut sans
> présentation visuelle. **Problème déjà observé par l'utilisateur** :
> la métrique reste à 0 la plupart du temps à l'œil nu.
- **Problème** : deux volets.
  1. Pas de tableau de bord visuel — la métrique n'existe qu'en requête
     brute Prometheus, aucun dashboard (Grafana ou autre) ne la présente.
  2. **Bug/limite déjà constatée** : en usage normal, la métrique affiche
     quasi tout le temps `0` à l'instant où on regarde. Cause probable
     (pas encore confirmée formellement) : chaque sous-agent ne reste
     « actif » que par rafales courtes (quelques secondes à quelques
     minutes), et la fenêtre de fraîcheur actuelle de l'exporter
     (`FRESH_SECONDS=20`, `tools/claude-agent-exporter/exporter.sh`)
     retombe à 0 dès que l'agent cesse d'écrire dans son transcript — un
     coup d'œil ponctuel sur la valeur **instantanée** tombe donc presque
     toujours entre deux rafales. Vérifié techniquement fonctionnel au
     moment du test (bascule 0→1→0 observée sur un agent `testeur` de
     test), donc pas un exporter cassé — plutôt un problème de
     présentation/lecture (valeur instantanée peu informative) qu'un bug
     de collecte.
- **Correctif** : à concevoir précisément à l'implémentation, pistes déjà
  identifiées :
  1. **Dashboard Grafana** (service `grafana` à ajouter à
     `docker-compose.yml`, pas encore présent — seuls `prometheus`/
     `node-exporter` existent) avec Prometheus en datasource, un panel en
     **graphe temporel** (pas une simple jauge/valeur instantanée) pour
     chaque type d'agent — un graphe sur une fenêtre de temps (ex. 1h)
     rend les rafales courtes visibles sous forme de pics, même si la
     valeur *actuelle* au moment de regarder est 0.
  2. Éventuellement compléter la jauge 0/1 par une métrique
     complémentaire moins binaire — ex. un compteur cumulatif
     `claude_agent_activations_total{agent="..."}` (incrémenté à chaque
     transition 0→1 détectée par l'exporter) pour voir « combien de fois
     cet agent a tourné récemment », pas seulement « tourne-t-il
     maintenant ».
  3. Revoir si `FRESH_SECONDS`/`INTERVAL` (actuellement 20s/15s) sont les
     bonnes valeurs une fois un vrai dashboard en place pour juger de la
     lisibilité réelle.
- **Effort** : moyen (nouveau service Grafana + dashboard JSON + éventuelle
  métrique complémentaire).
- **Fichiers** : `docker-compose.yml` (service `grafana` + volume
  provisioning), nouveau dossier de provisioning Grafana (datasource +
  dashboard), `tools/claude-agent-exporter/exporter.sh` (si la métrique
  complémentaire du point 2 est retenue).
- **Statut** : ✅ fait (2026-11-25). Service `grafana` ajouté
  (`docker-compose.yml`, image `grafana/grafana:11.3.1`, port `3002`
  côté hôte — `3001` déjà occupé par autre chose sur la machine, `3000`
  déjà pris par `frontend` ; accès anonyme Viewer activé, cohérent avec
  Prometheus déjà sans auth dans cette stack dev). Provisioning
  automatique : datasource Prometheus (`grafana/provisioning/
  datasources/prometheus.yml`, uid `prometheus`) + dashboard
  `grafana/dashboards/claude-agents.json` (« Claude Agents Activity »,
  `refresh: 10s` comme demandé) — 2 panels **state-timeline** (« multi
  state ») : un en vue temporelle sur les 15 dernières minutes (résout le
  point 2 du problème — les rafales d'activité restent visibles même
  quand la valeur instantanée repasse à 0), un en état instantané par
  agent. Vérifié en conditions réelles : dashboard accessible via l'API
  Grafana (`/api/search`, `/api/dashboards/uid/claude-agents`,
  2 panels confirmés, `refresh: "10s"` confirmé), datasource proxy
  fonctionnelle en anonyme (`/api/datasources/proxy/uid/prometheus/...`).
  **Cause du point 2 confirmée et résolue** : dispatch d'un agent
  `candide` de test (vrai sous-agent, pas une simulation) — la requête
  **instantanée** est bien retombée à `0` dès la fin du burst (confirmant
  le diagnostic initial), mais la même série en **range query** sur les
  90 dernières secondes montre bien le point `1` dans l'historique — donc
  la vue temporelle du dashboard (pas une simple jauge) résout bien le
  problème signalé. Pas de métrique complémentaire `_activations_total`
  ajoutée (point 2 du correctif, optionnel) — jugée non nécessaire une
  fois la vue temporelle en place, à reconsidérer seulement si la
  résolution 15s s'avère insuffisante en usage réel.

## 1c. [Nouvelle fonctionnalité] Métrique de tokens consommés par agent

> Demande utilisateur (2026-11-25), suite directe de l'action 1b : avoir
> une idée du nombre de tokens utilisés par les agents dans les
> métriques, éventuellement le nombre global, affiché via un `rate()`
> plutôt qu'une valeur brute instantanée.

- **Problème** : `claude_agent` (action 1b) donne un signal d'activité
  0/1, mais aucune métrique n'expose le volume de tokens réellement
  consommé par type d'agent.
- **Correctif** : `tools/claude-agent-exporter/exporter.sh` étendu —
  nouvelle métrique `claude_agent_tokens_total{agent="..."}` (compteur
  Prometheus), somme de `message.usage.output_tokens` sur l'ensemble des
  messages assistant de chaque transcript, agrégée par type d'agent
  (`jq`, installé une fois au démarrage du conteneur via `apk add`).
  Dashboard Grafana : panel `timeseries` sur
  `rate(claude_agent_tokens_total[5m])` (débit tokens/s par agent, vue
  graphe comme demandé) + panel `stat` sur `sum(claude_agent_tokens_total)`
  (total cumulé tous agents confondus).
- **Effort** : faible (extension du script existant + 2 panels
  supplémentaires sur le dashboard déjà en place).
- **Fichiers** : `tools/claude-agent-exporter/exporter.sh`,
  `grafana/dashboards/claude-agents.json`.
- **Statut** : ✅ fait (2026-11-25). Vérifié en conditions réelles :
  valeurs plausibles pour cette session marathon au moment du test
  (`worker` 2,8M, `orchestrateur` 1,3M, `pessimiste` ~1M, total global
  6,66M), dashboard rechargé automatiquement (4 panels confirmés via
  l'API Grafana), requête `rate()` et `sum()` toutes deux testées
  directement contre Prometheus. **Approximation documentée** (dans le
  `HELP` de la métrique elle-même) : somme des `output_tokens`
  uniquement — n'inclut pas les tokens d'entrée/cache, ne reproduit pas
  l'accounting interne exact du harnais (le chiffre `subagent_tokens`
  vu dans les rapports de fin de tâche d'un agent peut différer).

## 1d. [Raffinement] Dashboard personnalisé, suivi de la tâche en cours, suivi de la session principale

> Demande utilisateur (2026-11-25), suite directe des actions 1b/1c —
> plusieurs petits ajustements en continu pendant que la session
> travaillait en parallèle.

- **Problème/demandes** :
  1. L'utilisateur a créé son propre dashboard dans l'UI Grafana
     (« Claude Agents Activity Perso ») et a demandé de l'utiliser comme
     dashboard provisionné à la place de celui généré automatiquement.
  2. Avoir « quelque chose de visuel dès maintenant » plutôt que
     d'attendre une rafale d'activité — demande d'un label nommant la
     tâche de plan en cours.
  3. Constat : aucun agent ne « bouge » dans les métriques quand
     l'utilisateur pose une question en parallèle du worker — parce que
     la session principale (pas un sous-agent) n'était pas suivie du
     tout.
  4. Demande finale : afficher l'étape en cours, sinon « en attente »
     (pas « idle »).
- **Correctif** :
  1. Export du dashboard créé par l'utilisateur via l'API Grafana
     (`/api/dashboards/uid/ag5cdhxrs7ojkf`), écrit comme nouveau fichier
     de provisioning `grafana/dashboards/claude-agents-perso.json`
     (ancien `claude-agents.json` supprimé) — adoption confirmée après
     redémarrage de Grafana (`provisionedExternalId` correct), ancien
     doublon disparu proprement.
  2. Nouvelle métrique `claude_current_task{task="<description>"} 1`
     (`tools/claude-agent-exporter/exporter.sh`) : description brute de
     l'agent actif le plus pertinent (`orchestrateur` préféré s'il est
     frais, sinon l'agent frais le plus récent), `"en attente"` sinon.
     Nouveau panel `stat` (« Tâche en cours ») ajouté au dashboard.
  3. Nouvelle série `claude_agent{agent="main"}` : surveille aussi le
     transcript de la session principale elle-même (`*.jsonl` à la
     racine d'un répertoire de projet, pas dans `subagents/`) — comble
     le trou où la session principale travaille (répond, édite des
     fichiers) sans qu'aucun sous-agent ne tourne en parallèle.
  4. Libellé par défaut changé de `"idle"` à `"en attente"`.
- **Effort** : faible (extensions ciblées du script existant + 1 export
  de dashboard).
- **Fichiers** : `tools/claude-agent-exporter/exporter.sh`,
  `grafana/dashboards/claude-agents-perso.json` (remplace
  `claude-agents.json`).
- **Statut** : ✅ fait (2026-11-25). Toutes les métriques vérifiées en
  conditions réelles (requêtes Prometheus directes), dashboard rechargé
  et confirmé via l'API Grafana après chaque changement.

## 2. [Nouvelle fonctionnalité] Ajout de Selenium pour les tests IHM

> Demande utilisateur (2026-11-25) — marquée « à discuter » initialement,
> décisions tranchées par l'utilisateur depuis : outil **Playwright**
> (pas Selenium, alternative plus légère explicitement choisie — install
> npm seule, pas de driver binaire externe), portée de ce premier passage
> **smoke test large** (un test par page principale, charge sans erreur
> console + un élément clé visible, pas de scénario bout-en-bout profond).

- **Problème** : aucun test IHM automatisé/scripté dans le projet
  aujourd'hui (confirmé à plusieurs reprises pendant Mark 3 — les
  vérifications frontend se limitent à `tsc -b`/`vite build` et, quand
  l'environnement le permet, un rendu DOM statique via Chrome headless,
  jamais un scénario de clics réels scripté).
- **Correctif** : `@playwright/test` ajouté en devDependency
  (`frontend/package.json`, script `npm run test:e2e`). Nouveau dossier
  `frontend/tests/e2e/` : `global-setup.ts` (authentification — reproduit
  le pattern déjà utilisé par `tools/screenshot_demo.py`, password grant
  Keycloak direct `testuser`/`testuser123`, client `miami-vice-direct`,
  token injecté en `localStorage` puis capturé comme `storageState`
  Playwright réutilisable), `helpers.ts` (`collectConsoleErrors`/
  `gotoPage` — navigation via le menu `Navbar.tsx`, pas d'URL directe,
  app SPA sans routeur), 5 `*.spec.ts` (un par page : Navigation/
  Configuration/Diagramme/Dashboard/Recherche), `README.md` (commande
  d'exécution réelle détaillée). `playwright.config.ts` à la racine de
  `frontend/`.
- **Effort** : moyen (infra de test neuve + 2 problèmes d'environnement
  réels résolus en cours de route, voir ci-dessous).
- **Fichiers** : `frontend/package.json`, `frontend/playwright.config.ts`
  (nouveau), `frontend/tests/e2e/{global-setup.ts,helpers.ts,
  navigation.spec.ts,configuration.spec.ts,diagramme.spec.ts,
  dashboard.spec.ts,recherche.spec.ts,README.md}` (nouveaux), `.gitignore`
  (`frontend/test-results/`, `frontend/playwright-report/`,
  `frontend/tests/e2e/.auth/`), `specifications/05-frontend.md` (nouvelle
  section §6.15).
- **Statut** : ✅ fait (2026-11-26). Outil Playwright, 5 pages couvertes
  (Navigation/Configuration/Diagramme/Dashboard/Recherche), suite verte
  5/5. 1 itération de correction post-revue : sélecteur
  `navigation.spec.ts` rendu indépendant du contenu de la base (ne
  dépendait plus d'une donnée de dev précise) + note ajoutée dans
  `frontend/tests/e2e/README.md` sur la limite de couverture de
  `diagramme.spec.ts`. Revalidé OK, testeur-global au vert.
  - Historique détaillé de l'implémentation et des 2 bugs d'environnement
    résolus (`ERR_NETWORK_CHANGED`, flakiness workers) conservé ci-dessous.
  - **Exécution réelle, pas seulement compilation** : le conteneur
    `frontend` (`node:20-alpine`, musl) ne peut pas lancer les navigateurs
    Playwright (confirmé en pratique : `spawn ... ENOENT` au lancement de
    Chromium — limite connue, documentée, Playwright ne supporte pas
    Alpine). Exécution réelle via un conteneur Playwright officiel séparé
    (`mcr.microsoft.com/playwright:v1.65.1-noble`, version alignée sur
    `@playwright/test` installé), ponctuel, réseau host, montant
    `frontend/` — commande exacte dans `frontend/tests/e2e/README.md`.
  - **2 bugs d'environnement réels trouvés et corrigés en cours de route**
    (pas de simples sélecteurs fragiles) :
    1. `ERR_NETWORK_CHANGED` systématique (pas flaky, 3/3) sur le test
       Diagramme — cause confirmée par test isolé avant/après : résolution
       dual-stack de `localhost` (`::1`+`127.0.0.1`) combinée à la rafale
       de dizaines de `GET /api/read/object/<id>` en parallèle que
       `DiagramPage.tsx` envoie déjà (`Promise.all`, code applicatif non
       modifié). Corrigé en forçant `127.0.0.1` explicitement dans
       `playwright.config.ts`/`global-setup.ts` (`baseURL`, URLs Keycloak)
       — élimine le problème à 100 %, aucun changement côté application.
    2. Flakiness `dashboard.spec.ts` (timeout intermittent) sous 2
       workers Playwright — cause : le serveur de dev Vite (single
       process) ciblé devient contentieux sous 2 Chromium headless en
       parallèle. Corrigé par `workers: 1` dans `playwright.config.ts`
       (suite volontairement séquentielle, overhead de parallélisation
       non nécessaire pour 5 tests).
  - **Pollution pré-existante de la base de dev trouvée (pas causée par
    cette action)** : classe orpheline `testeur_dup_rt/compte_rt_dup`
    (attribut `pw` déclaré deux fois, types `secret` et `string`), absente
    de tout `model/*.json` versionné, déclenche un vrai avertissement
    React ("two children with the same key") dès le premier rendu de
    `NavigationPage` (page par défaut au chargement) — reproduit sur
    toutes les pages testées, pas seulement Navigation. Pas un bug
    applicatif (`write_class` valide normalement l'unicité des noms
    d'attribut, cf. action 3b) — origine non déterminée (écrite par un
    autre chemin ou directement en base, avant ce garde-fou). Suppression
    via l'API (`DELETE /api/delete/object/187` puis `.../class/
    testeur_dup_rt/compte_rt_dup` puis `.../metaclass/testeur_dup_rt`)
    **tentée pendant cette action et bloquée par le classifieur
    d'autorisation de l'environnement** (DELETE jugé destructif,
    confirmation utilisateur requise) — non appliquée. Filtrée
    explicitement et documentée dans `helpers.ts`
    (`isKnownPreexistingDuplicateKeyWarning`, matching ciblé sur le
    gabarit + le mot `pw` + la pile `NavigationPage`, pas un filtre
    générique qui masquerait un futur vrai doublon de clé) le temps du
    nettoyage manuel — commandes exactes dans `frontend/tests/e2e/
    README.md`. **Nécessite une décision utilisateur** : confirmer le
    nettoyage (3 appels DELETE ci-dessus) ou laisser le filtre en place.
  - `docker compose exec frontend npm run build` : toujours 3 erreurs
    `tsc` préexistantes dans `DiagramPage.tsx` (confirmées identiques
    avant/après cette action, dette déjà documentée ailleurs — action 6),
    aucune nouvelle erreur introduite par l'ajout de la dépendance
    Playwright.

## 3. [Documentation] Mode d'emploi illustré avec captures d'écran, basé sur des modèles de démonstration

> Demande utilisateur (2026-11-25). L'utilisateur suggérait lui-même que ce
> point pourrait être scindé en plusieurs morceaux une fois détaillé — ce
> découpage a été tranché à l'implémentation (même logique que l'action 10
> de `finished plan/plan-mark3.md`, scindée en 10a-10d).

> **Scission actée** (2026-11-25) : cette action 3 est scindée en **3a**
> (modèle de démo « bouteille de vin » + captures Configuration/
> Navigation/Diagramme), **3b** (modèle technique « architecture
> applicative / bus Kafka » + captures), **3c** (modèle organisationnel
> « holding/organigramme » + captures) et **3d** (assemblage final de la
> documentation : intro, conclusion, cohérence d'ensemble, sync specs si
> besoin). Voir les 4 sous-actions dédiées ci-dessous — cette action 3
> n'est plus directement actionnable telle quelle.

> **Incident de suivi (2026-11-26)** : l'orchestrateur dédié à cette
> action est resté sans notification de fin pendant ~1 jour (probablement
> une mise en veille de la machine hôte pendant son cycle) après avoir clos
> 3a. La session principale a repris la main directement pour 3b (review
> + correctif d'une collision de classe trouvée en revue, voir section 3b
> ci-dessous) sans attendre davantage. L'orchestrateur d'origine s'est
> réveillé pendant cette reprise, a correctement détecté via son garde-fou
> qu'un acteur non mandaté par lui avait touché `model/itil_cmdb.json`
> (hors de son périmètre connu), s'est arrêté sans rien modifier ni
> revert, et a demandé confirmation — comportement attendu, pas une
> anomalie de sa part. Confirmé qu'il s'agissait d'une reprise légitime, il
> a été explicitement mis en pause sur cette action. 3c et 3d restent donc
> à piloter directement par la session principale, pas par un nouvel
> orchestrateur, pour éviter une nouvelle collision de ce type tant que
> l'action 3 n'est pas intégralement close.

- **Problème** : pas de documentation « mode d'emploi » illustrée montrant
  concrètement comment modéliser et utiliser le produit de bout en bout.
- **Correctif** : renvoi à 3a/3b/3c/3d ci-dessous (pas de duplication du
  contenu ici).
- **Effort** : moyen à élevé (plusieurs modèles de démo complets + captures
  d'écran réelles pour chacun) — réparti sur les 4 sous-actions.
- **Fichiers** : voir chaque sous-action.
- **Statut** : 🔀 scindée (2026-11-25) — voir 3a-3d, **toutes closes**
  (2026-11-26). Un incident de suivi a eu lieu en cours de route (voir
  note en tête de section ci-dessus) : l'orchestrateur dédié bloqué ~1
  jour, reprise directe par la session principale pour 3b/3c/3d. Une
  collision de classe réelle trouvée et corrigée en 3b (voir cette
  section), un point de suivi séparé ouvert en action 8 suite à la revue
  de 3c.

## 3a. [Documentation] Mode d'emploi illustré — exemple 1 : bouteille de vin

> Sous-action issue de la scission de l'action 3 (2026-11-25).

- **Problème** : pas d'illustration de bout en bout, avec captures d'écran
  réelles, de la modélisation d'une classe simple grand public et de la
  création d'instances.
- **Correctif** : nouveau modèle de démo `model/demo_vin.json` (meta-classe
  `demo_vin`), 4 classes : `bouteille` (attributs `nom`, `cepage` en
  `joint-1-1` vers la classe `cepage`, `millesime`, `producteur`,
  `appellation`, `region` en `joint-1-1` vers la classe `region`,
  `prix_eur`, `notes` en `joint-1-n` vers la classe `note`), plus les 3
  classes de référence `cepage`/`region`/`note` (un seul attribut `nom`/
  `nom`/`descripteur`). Cépage/région/notes modélisés en jointures plutôt
  qu'en texte libre délibérément : seules les jointures produisent des
  arêtes dans la vue graphe de `DiagramPage.tsx` — un attribut string plat
  n'y produit aucun lien visuellement exploitable. Chargé réellement via
  `POST /api/init` sur la stack docker-compose vivante, authentifié
  `testuser`/global-admin (password grant Keycloak direct, client
  `miami-vice-direct`). 4 bouteilles créées via `POST /api/write/object`
  (Château Margaux 2015, Domaine Leflaive Puligny-Montrachet 2019, Domaine
  Zind-Humbrecht Riesling 2020, Chateauneuf-du-Pape Vieilles Vignes 2018),
  reliées à des objets `cepage`/`region`/`note` également créés réellement
  (Château Margaux 2015 porte 3 notes de dégustation, pour illustrer le
  `joint-1-n`). 3 captures d'écran réelles (PNG, via Chrome headless piloté
  en CDP — voir note technique `doc/mode-emploi.md`) : Configuration (classe
  `bouteille` + son attribut `cepage` en jointure), Navigation (table
  `bouteille` avec jointures résolues en displayname) et Diagramme (graphe
  des relations bouteille → cépage/région/notes). Documentation dans
  `doc/mode-emploi.md`, section « Exemple 1 : bouteille de vin ».
- **Effort** : faible/moyen (un modèle de démo + données + captures, pattern
  réutilisable tel quel pour 3b/3c).
- **Fichiers** : `model/demo_vin.json` (nouveau), `tools/screenshot_demo.py`
  (nouveau, script générique de capture CDP réutilisé par 3b/3c),
  `doc/mode-emploi.md` (nouveau), `doc/demo-vin/configuration.png`,
  `doc/demo-vin/navigation.png`, `doc/demo-vin/diagramme.png` (nouveaux). Le
  commit touche aussi une trentaine de fichiers
  `files/_class_icon_cache/*.svg` générés en effet de bord : mécanisme
  préexistant de génération déterministe d'une icône par nom de classe,
  déclenché par le rendu de la Sidebar/Configuration qui liste toutes les
  classes du système (pas seulement celles du modèle de démo) — sans
  impact, confirmé par l'analyse critique.
- **Statut** : ✅ fait — 2 itérations (1 correction : garde-fou
  `RuntimeError` sur sélecteurs DOM manquants dans
  `tools/screenshot_demo.py`, scope du sélecteur meta-classe, correction
  d'accents sur 2 objets + régénération de 2 PNG, traçabilité du cache
  d'icônes) ; testeur-global OK (299/299 tests backend, build frontend
  conforme à la dette préexistante documentée, stack vivante vérifiée).

## 3b. [Documentation] Mode d'emploi illustré — exemple 2 : architecture applicative / bus Kafka

> Sous-action issue de la scission de l'action 3 (2026-11-25).

- **Problème** : pas d'illustration de bout en bout d'un modèle technique/
  professionnel plus riche que l'exemple grand public de 3a.
- **Correctif** : nouveau modèle de démo `model/demo_kafka.json` (meta-classe
  `demo_kafka`), 6 classes : `vm` (`nom`, `ip`, classe de référence),
  `type_donnee` (`nom`, classe de référence, ex. `commande`/`paiement`),
  `base_donnees` (`nom`, `moteur`, `vm` en `joint-1-1`), `bus_kafka` (`nom`,
  `vm` en `joint-1-1`, `types_donnees` en `joint-1-n` vers `type_donnee`),
  `application` (`nom`, `role` en `select` frontend/backend/service, `vm`/
  `base_donnees`/`bus` en `joint-1-1`, `produit`/`consomme` en `joint-1-n`
  vers `type_donnee`), `reverse_proxy` (`nom`, `vm` en `joint-1-1`,
  `cibles` en `joint-1-n` vers `application`). Toutes les relations entre
  composants modélisées en jointures (même raisonnement qu'en 3a : seules
  les jointures produisent des arêtes dans le Diagramme). Chargé réellement
  via `POST /api/init` (aucun skip). 17 objets réels créés via
  `POST /api/write/object` : 7 `vm`, 2 `type_donnee` (`commande`,
  `paiement`), 2 `base_donnees` (mutualisées sur une VM commune
  `vm-db-1` - choix assumé, documenté), 1 `bus_kafka`, 4 `application`
  (`Portail Commandes` en 2 instances redondantes frontend sans base
  propre (stateless), `Service Commandes` backend qui **produit**
  `commande`, `Service Paiement` service qui **consomme** `commande` et
  **produit** `paiement` - illustre concrètement la relation producteur/
  consommateur), 1 `reverse_proxy` (`LB Portail Commandes`, ses `cibles`
  pointant vers les 2 instances du frontend - illustre redondance +
  load-balancing). 3 captures d'écran réelles (PNG 1280×900, confirmées
  via `file`) via `tools/screenshot_demo.py --meta-class demo_kafka`,
  **sans aucune adaptation de l'outil** (robustesse 3a suffisante même
  pour ce modèle à 6 classes/17 objets, plus riche que 3a). Documentation
  dans `doc/mode-emploi.md`, section « Exemple 2 : architecture
  applicative / bus Kafka » (renvoi à la note technique de l'Exemple 1
  plutôt que duplication, comme prévu).
- **Effort** : moyen (modèle plus riche que 3a, mêmes outils réutilisés).
- **Fichiers** : `model/demo_kafka.json` (nouveau), `doc/demo-kafka/configuration.png`,
  `doc/demo-kafka/navigation.png`, `doc/demo-kafka/diagramme.png`
  (nouveaux), `doc/mode-emploi.md` (section « Exemple 2 » ajoutée,
  section « Exemple 1 » non touchée). `tools/screenshot_demo.py` non
  modifié. Pas d'impact sur `specifications/*.md` (modèle de démo pur,
  aucun nouveau mécanisme backend/frontend - même constat qu'en 3a).
- **Statut** : 🔄 en cours (livré, en attente de vérification croisée de
  l'orchestrateur avant passage à ✅).

> **Révision post-revue croisée (2026-11-26)** : la revue a identifié que
> `model/demo_kafka.json` déclarait sa propre classe `application` (meta-
> classe `demo_kafka`), en collision de NOM avec la classe `application`
> déjà existante dans `model/itil_cmdb.json` (meta-classe `cmdb`, CMDB
> métier réelle). `POST /api/init` ne détecte pas ce doublon de nom de
> classe entre fichiers (contrairement à `write_class`/`write_metaclass` -
> gap pré-existant, resté hors scope de ce correctif, non traité ici) et ça
> causait un vrai bug visible : `frontend/src/components/Sidebar.tsx`
> compare la sélection active par `c.class` seul, pas `meta_class`+`class`,
> donc sélectionner `demo_kafka > application` surlignait aussi
> `cmdb > application` par erreur.
>
> Décision utilisateur, après présentation du compromis (renommer la
> classe de démo vs. réutiliser l'existante) : **réutiliser la classe
> `application` existante de `cmdb`** pour les objets de démo Kafka - plus
> aucune 2e classe `application` du tout.
>
> **Correctif appliqué** : `model/itil_cmdb.json`, classe `application` -
> attributs CMDB existants inchangés (`nom`, `version`, `serveurs`,
> `base_de_donnees`, `modules`), ajout de 6 attributs de démo dans un
> nouveau domaine `demo` (regroupement visuel distinct dans
> `ConfigurationPage.tsx`) : `demo_role` (select frontend/backend/service),
> `demo_vm` (joint-1-1 → `vm` de demo_kafka), `demo_base_donnees`
> (joint-1-1 → `base_donnees` de demo_kafka - **distinct** de l'attribut
> CMDB existant `base_de_donnees`, qui pointe vers une classe CMDB
> différente et n'a pas été touché), `demo_bus` (joint-1-1 → `bus_kafka`),
> `demo_produit`/`demo_consomme` (joint-1-n → `type_donnee`). `depends_on`
> de `itil_cmdb.json` complété avec `demo_kafka` (et réciproquement dans
> `demo_kafka.json` avec `cmdb`, dépendance circulaire assumée - précédent
> déjà existant entre `cluster.json`/`itil_cmdb.json`). `model/demo_kafka.json`
> : classe `application` retirée entièrement ; `reverse_proxy.cibles`
> (`classes: ["application"]`) cible désormais implicitement la classe
> `cmdb.application` (les classes sont référencées par nom global, sans
> qualification par meta-classe, dans tout ce modèle - confirmé par
> `model/schema.json` et le mécanisme déjà utilisé par `cluster.json` vers
> `cmdb.application`). Rechargé réellement via `POST /api/init` (aucun
> skip). Les 4 objets `application` de démo recréés sous
> `meta_class=cmdb, class=application` avec les attributs `demo_*` (nouveaux
> ids 284-287) ; les 4 anciens objets orphelins sous l'ex-`demo_kafka.
> application` (ids 279-282) soft-supprimés (`DELETE /api/delete/object`,
> cohérent avec les conventions déjà établies) ; `reverse_proxy.cibles`
> (id 283) remis à jour vers les 2 nouveaux ids `Portail Commandes`.
> Vérifié par `grep` qu'aucun autre `model/*.json` ne déclare de classe
> `application` ailleurs. `backend/tests/` reste vert (299 passed),
> `jsonschema` OK sur les 2 fichiers modifiés.
>
> Captures `doc/demo-kafka/{configuration,navigation,diagramme}.png`
> reprises : montrent désormais la classe `application` sous le groupe
> `cmdb` (plus de groupe `demo_kafka` séparé pour cette classe), un seul
> badge `application` dans le filtre du Diagramme (plus de doublon). Les 6
> classes de cette démo étant désormais réparties sur 2 meta-classes
> (`demo_kafka`/`cmdb`), `tools/screenshot_demo.py` a reçu 3 options
> supplémentaires pour ce besoin (documentées dans son usage) :
> `--only-classes` (page Diagramme, clique "Rien" puis ré-active
> uniquement les chips listées - utilisé pour `diagramme.png`), `--layer`
> (alternative additive par le filtre Layers, non utilisée au final pour
> ces captures - limite documentée dans l'outil : n'isole pas une classe
> sans layer, cf. `schema.json`), `--attr` (scroll sur un attribut
> spécifique de la classe sur la page Configuration, utilisé pour
> `configuration.png`). `--meta-class` est devenu optionnel (une des trois
> options `--meta-class`/`--layer`/`--only-classes` requise). `doc/
> mode-emploi.md` section « Exemple 2 » mise à jour en conséquence (classes
> par meta-classe, attributs `demo_*`, note de révision).
>
> **Fichiers (révision)** : `model/itil_cmdb.json`, `model/demo_kafka.json`,
> `tools/screenshot_demo.py`, `doc/demo-kafka/configuration.png`,
> `doc/demo-kafka/navigation.png`, `doc/demo-kafka/diagramme.png`,
> `doc/mode-emploi.md`, `specifications/03-modele-donnees.md` (description
> de `cmdb.application` complétée avec les 6 attributs `demo_*` — **correction
> sur la phrase « pas d'impact sur specifications/*.md » du rapport worker
> ci-dessus, inexacte**, vérifiée par `git diff --stat` avant clôture),
> `plan-mark4.md` (cette section).
> **Vérification finale (moi, 2026-11-26, orchestrateur d'origine resté
> bloqué ~1 jour puis explicitement mis en pause sur cette action)** :
> `backend/tests/` rejoué — 299/299 ; les 3 captures relues visuellement —
> confirment un seul badge `application` (sous `cmdb`, compte 6 = 2 objets
> CMDB réels préexistants + 4 objets de démo) dans le filtre Diagramme,
> plus de doublon visuel ; `configuration.png` montre bien les 3 attributs
> `demo_role`/`demo_vm`/`demo_base_donnees` groupés sous le domaine `demo` ;
> `navigation.png` montre les 6 objets `application` avec les 2 objets CMDB
> réels à champs `demo_*` vides (transparence assumée) et les 4 objets de
> démo correctement renseignés. Testeur-global (moi-même, vérification
> directe faute d'orchestrateur disponible) : stack inchangée depuis la
> dernière vérification globale de l'action 1b, aucune régression
> attendue ni trouvée (modèle pur + script d'outillage, aucun code
> applicatif touché).
> **Statut (révision)** : ✅ fait (2026-11-26, clôturé directement par la
> session principale après blocage de ~1 jour de l'orchestrateur dédié à
> l'action 3 — cf. note de suivi en tête de l'action 3 ci-dessus).

## 3c. [Documentation] Mode d'emploi illustré — exemple 3 : organigramme d'une holding

> Sous-action issue de la scission de l'action 3 (2026-11-25). Pilotée
> directement par la session principale (orchestrateur dédié à l'action 3
> explicitement mis en pause, cf. incident documenté en tête de l'action 3).

- **Problème** : pas d'illustration de bout en bout d'un modèle
  organisationnel (hiérarchie de personnes/sociétés).
- **Correctif** : **aucun nouveau fichier de modèle** - par précaution
  tirée directement de l'incident de collision de classe en 3b, vérifié
  par `grep` sur tous les `model/*.json` que `societe`/`departement`/
  `service_organisation`/`poste`/`personne_physique`/`role`/`groupe`/
  `contact` ne sont déclarées nulle part ailleurs que dans
  `model/organisation.json` (meta-classe `organisation`, livré Mark 3
  action 17) - ces classes couvrant déjà exactement le besoin, réutilisées
  telles quelles sans aucune modification de schéma. 71 objets réels créés
  via `POST /api/write/object` (aucun appel à `/api/init`, schéma déjà
  chargé) : 3 `societe` (Helveta Holding SA racine + 2 filiales Helveta
  Technologies SA / Helveta Conseil SA via `holding` joint-1-1), 4
  `departement` (1-2 par société), 26 `personne_physique` réparties sur 4
  départements en 3 niveaux hiérarchiques chacun (direction → managers
  d'équipe → collaborateurs, 5 à 8 personnes par département), 12
  `service_organisation` (1 service racine + 2 sous-services par
  département, chaîne `service_parent`), 26 `poste` (un par personne,
  chaîne `poste_parent` reproduisant exactement la hiérarchie de reporting,
  `service` reliant chaque poste à son service). 3 captures d'écran réelles
  (PNG 1280×900, confirmées via `file`) via `tools/screenshot_demo.py
  --meta-class organisation` : Configuration (classe `societe`, attribut
  `holding` auto-référence), Navigation (table `poste` avec ses 3
  jointures `titulaire`/`poste_parent`/`service` résolues - la hiérarchie
  de reporting s'y lit directement), Diagramme (disposition Force, 75
  objets/102 liens - la meta-classe `organisation` contenait déjà 4 objets
  réels préexistants avant cette démo, documentés avec transparence comme
  en 3b). Un seul ajustement à `tools/screenshot_demo.py` : nouvelle option
  `--expand-class` (page Navigation) pour forcer l'expansion d'un groupe de
  classe quand l'auto-expand de `NavigationPage.tsx` ne s'est pas appliqué
  de façon fiable sur une meta-classe à 75 objets/8 classes (fonctionnait
  pour 3a/3b, nettement plus petits). Documentation dans
  `doc/mode-emploi.md`, section « Exemple 3 : organigramme d'une holding »
  (renvoi à la note technique de l'Exemple 1, pas de duplication) - inclut
  une note expliquant pourquoi la disposition « 🌳 Organigramme » (tree) du
  Diagramme n'a pas été retenue : son algorithme désigne comme racine le(s)
  nœud(s) sans arête entrante, générique et sans connaissance de la
  sémantique des jointures de ce modèle - avec `poste_parent` orienté
  enfant→parent, ce sont les postes de plus bas niveau qui deviennent
  racines de l'arbre, pas la direction générale ; comportement générique de
  l'IHM, pas un bug introduit ici.
- **Effort** : moyen (volume d'objets plus important que 3a/3b : 71 objets
  contre 17, mais aucune création de modèle - gain de temps sur la partie
  schéma compensé par le volume de données et la construction de la
  hiérarchie).
- **Fichiers** : `doc/demo-organigramme/configuration.png`,
  `doc/demo-organigramme/navigation.png`,
  `doc/demo-organigramme/diagramme.png` (nouveaux),
  `tools/screenshot_demo.py` (option `--expand-class` ajoutée),
  `doc/mode-emploi.md` (section « Exemple 3 » ajoutée, sections
  précédentes non touchées). Aucun fichier `model/*.json` modifié ou créé.
  Pas d'impact sur `specifications/*.md` : `03-modele-donnees.md` §3.3
  documente déjà `model/organisation.json` au niveau schéma (classes et
  attributs, inchangés) - ces objets de démo sont des données d'instance,
  pas un nouveau mécanisme, vérifié par cohérence avec le constat déjà fait
  en 3a/3b.
- **Statut** : ✅ fait (2026-11-26). Revue croisée (testeur 7/7 + analyse
  combinée pessimiste/candide, pilotées directement) : **aucun point
  bloquant**. Les 5 points d'incertitude assumés par le worker ont tous été
  vérifiés réels et non trompeurs — en particulier, chiffres/liens
  annoncés (75 objets, 102 liens, comptage par classe) confirmés exacts en
  DB live, pixel pour pixel avec `diagramme.png` ; les 5 objets
  préexistants (pas 4 comme documenté à l'origine — léger écart de
  comptage sans conséquence, corrigé ici) confirmés intacts
  (`valid_from`/`valid_to` inchangés) ; le point 2 (département/service
  rattachés par convention de nommage, pas par jointure formelle) confirmé
  être une limite honnêtement documentée dans le texte narratif, pas une
  donnée trompeuse dans les captures elles-mêmes (la hiérarchie affichée,
  elle, repose sur de vraies jointures vérifiées exhaustivement) ; le
  choix Force vs Organigramme (point 3) confirmé techniquement justifié en
  lisant le code `DiagramPage.tsx` (l'algorithme tree inverserait la
  hiérarchie vu le sens enfant→parent de `poste_parent`), pas une
  esquive. `backend/tests/` 299/299, aucune régression, aucun fichier
  hors périmètre touché (vérifié `git diff`).
  **Point de suivi non résolu dans 3c, mérite un futur ticket séparé** :
  l'analyste a noté que l'auto-expand de `NavigationPage.tsx` (lignes
  ~475-496) peut ne pas s'appliquer de façon fiable sur une meta-classe à
  fort volume d'objets (75 ici) — contourné dans l'outil de capture par la
  nouvelle option `--expand-class`, mais la cause racine (possible bug
  réel affectant de vrais utilisateurs en prod sur une grosse
  meta-classe, pas juste un artefact de l'outil CDP) n'a pas été
  investiguée, volontairement hors du périmètre de cette action
  documentaire. **Ajouté au plan comme nouvelle action 8** (voir
  ci-dessous), pour ne pas perdre cette piste.
  **Point mineur noté, non bloquant** : la lecture du volume par société
  individuelle (ex. une filiale à 14 personnes cumulées sur ses 2
  départements) dépasse seule la fourchette « 5 à 10 personnes » lue au
  niveau société plutôt qu'au niveau département — le volume agrégé total
  (26 personnes sur 3 sociétés) reste dans l'esprit de la demande, écart
  jugé sans conséquence pour un exemple de documentation.

## 3d. [Documentation] Mode d'emploi illustré — assemblage final

> Sous-action issue de la scission de l'action 3 (2026-11-25), dépend de
> 3a/3b/3c (les 3 exemples doivent être livrés avant l'assemblage final).

- **Problème** : une fois les 3 exemples (3a/3b/3c) rédigés indépendamment,
  `doc/mode-emploi.md` a besoin d'une introduction cohérente, d'une
  conclusion, et d'une relecture de cohérence d'ensemble (terminologie,
  style, liens entre sections) — pas garanti automatiquement par 3 passages
  indépendants.
- **Correctif** : rédaction de l'introduction et de la conclusion de
  `doc/mode-emploi.md`, relecture de cohérence des 3 sections existantes,
  et synchronisation de `specifications/*.md` si les 3 exemples ont
  collectivement rendu une partie de la doc existante incohérente (sinon,
  le dire explicitement plutôt que de l'oublier).
- **Effort** : faible (relecture + rédaction, pas de nouveau modèle ni
  nouvelle capture).
- **Fichiers** : `doc/mode-emploi.md`, potentiellement
  `specifications/*.md`.
- **Statut** : ✅ fait (2026-11-26). Introduction et conclusion rédigées
  dans `doc/mode-emploi.md`, relues directement par la session principale
  (pilotage direct, sans orchestrateur, sans cycle testeur/analyste
  complet vu la nature purement éditoriale et le faible risque de cette
  action — relecture jugée suffisante). Introduction : objectif du
  document, annonce des 3 exemples par complexité croissante, renvoi
  unique vers la note technique headless. Conclusion : synthèse des 3
  contextes d'usage, principe transversal jointure > texte libre, principe
  de réutilisation illustré par l'évolution 3b→3c (`grep` avant de créer
  une classe). Relecture de cohérence confirmée : terminologie homogène
  entre les 3 sections (vérifié directement), ancre interne vers la note
  technique de l'Exemple 1 confirmée fonctionnelle (slugify vérifié
  caractère par caractère par le worker), tous les chemins d'image/modèle
  référencés existent sur disque. `specifications/*.md` : rien à
  synchroniser (déjà à jour depuis 3b). **Action 3 entière (3a-3d) close.**

## 4. [Nouvelle fonctionnalité] Champ conditionnel : affichage indexé sur une autre valeur ou un calcul

> Demande utilisateur (2026-11-25), née du constat qu'aucun mécanisme ne
> permet aujourd'hui de conditionner l'affichage d'un attribut à la valeur
> d'un autre attribut ou à un calcul.

- **Problème** : pas de mécanisme de champ conditionnel dans le modèle
  dynamique — tous les attributs déclarés sur une classe sont toujours
  affichés, jamais indexés sur la valeur d'un autre attribut de l'objet
  ni sur un calcul dérivé.
- **Correctif** : **non conçu ici** — l'utilisateur a explicitement demandé
  une démarche interactive pour définir ce point (voir note en tête de
  document). Avant toute conception : poser des questions sur, a minima —
  quelle syntaxe pour la condition (référence à un autre attribut de la
  même classe uniquement, ou aussi à des attributs joints ?), un calcul
  signifie quoi exactement ici (expression simple sur des attributs
  numériques, ou plus large ?), ce mécanisme s'applique-t-il au formulaire
  de saisie, à l'affichage en lecture, aux deux ?, interaction avec les
  mécanismes déjà existants qui conditionnent un affichage (`layer_map`
  de Mark 3 action 18, qui indexe déjà un *layer* — pas un *champ* — sur
  la valeur d'un attribut `select`).
- **Effort** : à évaluer après la démarche interactive.
- **Fichiers** : à déterminer.
- **Statut** : ⬜ démarche interactive requise (pas encore conçu).

## 5. [Nouvelle fonctionnalité] Révélation d'un secret dans l'IHM (bouton œil) + permissions de visibilité par classe

> Demande utilisateur (2026-11-25), qui note elle-même que ce point en
> amène un autre, plus large, à trancher aussi en démarche interactive.

- **Problème** : un attribut `secret` (Mark 3 action 8) est aujourd'hui
  masqué en lecture générique, avec une route *reveal* dédiée réservée
  strictement au global-admin (pas d'exposition dans l'IHM standard).
  L'utilisateur veut un bouton « œil » dans `NavigationPage.tsx` pour le
  révéler directement, ce qui soulève une question plus large : qui a le
  droit de voir quoi, et comment le définir finement (par classe, par
  attribut, par rôle) ?
- **Correctif** : **non conçu ici** — démarche interactive requise sur
  deux volets distincts signalés par l'utilisateur lui-même :
  1. Jusqu'où élargir le droit de reveal au-delà du global-admin actuel
     (Mark 3 action 8) — quels rôles, et comment l'exprimer dans le
     modèle RBAC existant (`backend/auth/rbac.py`) ?
  2. Ce que Keycloak permet concrètement de faire ici (rôles/scopes
     disponibles dans le royaume déjà configuré,
     `keycloak/miami-vice-realm.json`) — à explorer avant de s'engager sur
     un mécanisme précis.
  Question ouverte notée par l'utilisateur, « peut-être » : définir qui
  peut voir quoi directement dans la configuration de la classe
  (`ConfigurationPage.tsx`) plutôt que globalement.
- **Effort** : à évaluer après la démarche interactive — potentiellement
  élevé si un nouveau mécanisme de permission fine est retenu.
- **Fichiers** : à déterminer (probablement `backend/auth/rbac.py`,
  `backend/routes/routes_read.py` route reveal existante, `frontend/src/
  pages/NavigationPage.tsx`, `frontend/src/pages/ConfigurationPage.tsx`,
  potentiellement `keycloak/miami-vice-realm.json`).
- **Statut** : ⬜ démarche interactive requise (pas encore conçu).

## 6. [Nouvelle fonctionnalité] Sélection en cascade Salle → Bâtiment → Étage

> Demande utilisateur (2026-11-25), exemple concret donné : choix en
> cascade salle/bâtiment/étage dans un formulaire, avec vigilance sur la
> suppression d'un élément de la chaîne.

- **Problème** : les classes `salle`/`etage`/`batiment` (Mark 3 action 17,
  `model/localisation.json`) existent et sont chaînées par jointures
  (`salle.etage` → `etage.batiment`), mais aucun mécanisme d'IHM ne
  propose une sélection en cascade (choisir d'abord un bâtiment, puis un
  étage filtré sur ce bâtiment, puis une salle filtrée sur cet étage) —
  aujourd'hui chaque jointure se sélectionne indépendamment dans
  `NavigationPage.tsx`, sans narrowing successif.
- **Correctif** : à concevoir à l'implémentation — sélecteur en cascade
  générique ou spécifique à cette chaîne salle/bâtiment/étage (à trancher
  selon la réutilisabilité souhaitée pour d'autres chaînes similaires du
  modèle, ex. `baie_serveur`/`datacenter`). **Point de vigilance
  explicitement signalé par l'utilisateur** : attention au comportement à
  la suppression d'un élément de la chaîne (supprimer un bâtiment doit
  avoir un comportement défini et assumé sur ses étages/salles
  rattachés — cohérence à vérifier avec le mécanisme de suppression en
  cascade déjà existant par ailleurs dans le projet, ex.
  `test_delete_object_cascade_scoped_to_tenant_for_tenant_admin`).
- **Effort** : moyen (UI de sélection en cascade + vérification du
  comportement de suppression en chaîne).
- **Fichiers** : `frontend/src/pages/NavigationPage.tsx`, potentiellement
  `backend/routes/routes_write.py` (`delete_object`) si le comportement de
  suppression en cascade doit être adapté.
- **Statut** : ⬜ à faire.

## 7. [Nouvelle fonctionnalité] Outil d'ingestion avec binding

> Reportée de `plan-mark3.md` action 11 (volontairement jamais traitée
> dans Mark 3, consigne explicite de l'utilisateur : « continue le plan,
> sauf 11 »). L'utilisateur a demandé, à la clôture de Mark 3, une
> démarche interactive avant de la formaliser pour de bon — la conception
> d'origine ci-dessous est reprise **à titre de référence historique
> uniquement**, pas comme un correctif validé prêt à implémenter.

- **Problème** : pas d'outil générique de mapping champs source →
  attributs.
- **Conception antérieure (Mark 3, non validée, à revisiter)** :
  définition d'un mapping/binding (format probablement JSON) décrivant
  source → champ → attribut cible d'une classe ; réutilisation du type
  `csv` existant (Mark 3 actions 2-3) comme première source d'entrée
  possible, ou upload direct ; pas d'exécution ni de scheduler dans cette
  action (resterait une idée séparée, jamais engagée). Détail complet
  toujours disponible dans `specifications/07-roadmap.md` §10.13 (jamais
  supprimé). Point resté ouvert à l'époque, jamais tranché : où stocker
  la config de binding — nouvelle classe du modèle dynamique (cohérence à
  rechercher avec le framework dashboard de Mark 3, qui a le même besoin
  de stocker de la config applicative, pas des objets métier) ?
- **Correctif** : **non re-conçu ici** — démarche interactive requise
  avant de formaliser, comme demandé par l'utilisateur. La conception
  antérieure ci-dessus sert de point de départ à la discussion, pas de
  spécification figée.
- **Effort estimé à l'époque** : élevé (difficulté 4/4, fondation
  réutilisable) — à réévaluer après la démarche interactive.
- **Fichiers** : rien n'a jamais été codé pour cette action — tout reste à
  déterminer, y compris à la lumière de la démarche interactive à venir.
- **Statut** : ⬜ démarche interactive requise (pas encore conçu pour de
  bon).

## 8. [Dette technique / bug potentiel] Investiguer l'auto-expand de `NavigationPage.tsx` sur une meta-classe à fort volume

> Trouvée par l'analyste combiné (pessimiste/candide) en revue de l'action
> 3c (2026-11-26) — signalée comme point de suivi, volontairement non
> traitée dans 3c (documentaire, hors scope).

- **Problème** : l'auto-expand d'un groupe de classe dans
  `frontend/src/pages/NavigationPage.tsx` (lignes ~475-496) ne s'est pas
  appliqué de façon fiable lors de la capture d'écran de l'action 3c, sur
  une meta-classe comptant 75 objets (`organisation`, dépendance probable
  sur `filtered.map(id).join(',')`). Contourné dans
  `tools/screenshot_demo.py` par une nouvelle option `--expand-class`
  (clic explicite idempotent), mais la **cause racine n'a jamais été
  investiguée** — risque réel que ce soit un bug affectant aussi de vrais
  utilisateurs naviguant une meta-classe volumineuse en conditions
  normales, pas seulement un artefact du pilotage headless CDP de l'outil
  de capture.
- **Correctif** : à déterminer après investigation — commencer par
  reproduire manuellement (pas en headless) sur une meta-classe à fort
  volume d'objets réels déjà en base (ex. `organisation` après l'action
  3c, 75 objets ; ou `cmdb` après l'action 17 de Mark 3) pour confirmer
  si le défaut existe réellement en usage normal ou si c'est bien
  spécifique au contexte CDP/timing de l'outil de capture.
- **Effort** : faible pour l'investigation, variable pour le correctif
  selon ce qu'elle révèle.
- **Fichiers** : `frontend/src/pages/NavigationPage.tsx`.
- **Statut** : ⬜ à faire.

> **Tableau récapitulatif** : plus dupliqué ici — voir [`resume.md`](resume.md)
> à la racine du dépôt, tenu à jour en même temps que le champ **Statut**
> de chaque action ci-dessus.

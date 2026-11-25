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

## 2. [Nouvelle fonctionnalité] Ajout de Selenium pour les tests IHM

> Demande utilisateur (2026-11-25) — marquée « à discuter » par
> l'utilisateur lui-même : pas encore une décision ferme d'implémenter,
> à confirmer avant de lancer le cycle complet.

- **Problème** : aucun test IHM automatisé/scripté dans le projet
  aujourd'hui (confirmé à plusieurs reprises pendant Mark 3 — les
  vérifications frontend se limitent à `tsc -b`/`vite build` et, quand
  l'environnement le permet, un rendu DOM statique via Chrome headless,
  jamais un scénario de clics réels scripté).
- **Correctif** : à discuter avec l'utilisateur avant de concevoir quoi
  que ce soit — portée exacte (quels parcours couvrir en priorité),
  outil (Selenium nommément demandé, à confirmer vs. une alternative déjà
  plus légère comme Playwright si pertinent pour ce projet), intégration
  CI éventuelle.
- **Effort** : à évaluer après discussion.
- **Fichiers** : à déterminer.
- **Statut** : ⬜ à discuter (pas encore à faire).

## 3. [Documentation] Mode d'emploi illustré avec captures d'écran, basé sur des modèles de démonstration

> Demande utilisateur (2026-11-25). L'utilisateur suggère lui-même que ce
> point pourrait être scindé en plusieurs morceaux une fois détaillé —
> non tranché, à décider à l'implémentation plutôt qu'imposé ici.

- **Problème** : pas de documentation « mode d'emploi » illustrée montrant
  concrètement comment modéliser et utiliser le produit de bout en bout.
- **Correctif** : construire au moins 2 modèles de démonstration contrastés
  et illustrer leur usage par des captures d'écran réelles, montrant la
  création d'instances d'objets des deux côtés (modélisation en
  `ConfigurationPage.tsx` et saisie/consultation en `NavigationPage.tsx`) :
  1. **Exemple simple, grand public** : bouteille de vin — attributs
     cépage, année, cave/vigneron, AOC...
  2. **Exemple technique/professionnel** : architecture applicative —
     2-3 applications reliées par un bus Kafka central, avec des types de
     données (datatype1/datatype2), producteurs/consommateurs, base de
     données, frontend/backend, VMs, et éventuellement redondance +
     reverse proxy/load balancer. Ajouter 3-4 objets réels et montrer la
     création d'une instance de chaque côté.
  3. **Exemple organisationnel** : organigramme d'une holding avec 2-3
     sociétés et des structures de 5 à 10 personnes chacune, sur 2-3
     niveaux hiérarchiques.
- **Effort** : moyen à élevé (plusieurs modèles de démo complets + captures
  d'écran réelles pour chacun) — l'utilisateur suggère un découpage possible
  en plusieurs actions une fois le périmètre exact précisé.
- **Fichiers** : nouveaux modèles de démo (`model/*.json` dédiés, hors des
  modèles déjà livrés en Mark 3), nouveau contenu de documentation
  (emplacement à déterminer — probablement un nouveau fichier
  `specifications/` ou un dossier dédié `doc/`).
- **Statut** : ⬜ à faire.

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

> **Tableau récapitulatif** : plus dupliqué ici — voir [`resume.md`](resume.md)
> à la racine du dépôt, tenu à jour en même temps que le champ **Statut**
> de chaque action ci-dessus.

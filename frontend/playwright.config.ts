import { defineConfig, devices } from '@playwright/test';

// Smoke tests IHM (plan-mark4.md action 2) : un test par page principale
// (Navigation/Configuration/Diagramme/Dashboard/Recherche), chargement sans
// erreur console + un élément clé visible. Pas de scénario bout-en-bout
// profond pour ce premier passage.
//
// Exécution : cette config attend la stack docker-compose déjà up
// (frontend exposé sur http://127.0.0.1:3000, Keycloak sur
// http://127.0.0.1:8080 - mêmes services que tools/screenshot_demo.py et
// frontend/src/api.ts:apiLogin, 127.0.0.1 explicite plutôt que "localhost"
// - voir note ci-dessous). Le conteneur `frontend` est basé sur
// node:20-alpine (musl) : Playwright ne supporte pas d'installer/lancer ses
// navigateurs embarqués sur Alpine (pas de glibc) - voir note d'exécution
// dans tests/e2e/README.md pour la commande réelle utilisée (conteneur
// Playwright officiel séparé, réseau host, pointant sur 127.0.0.1:3000).
//
// Pourquoi 127.0.0.1 et pas "localhost" : reproduit et confirmé pendant
// l'implémentation de cette action - "localhost" résout en dual-stack
// (::1 et 127.0.0.1), et la page Diagramme déclenche une rafale de dizaines
// de GET /api/read/object/<id> en parallèle (DiagramPage.tsx,
// Promise.all(toLoad.map(...))) ; dans ce conteneur Playwright officiel
// (réseau host), cette rafale sur une résolution dual-stack fait basculer
// Chromium en ERR_NETWORK_CHANGED de façon systématique (pas flaky,
// reproduit 3/3). Forcer 127.0.0.1 (IPv4 seul) élimine le problème à 100% -
// confirmé par test isolé avant/après. Rien côté application n'a été
// modifié (DiagramPage.tsx inchangé) - correctif strictement côté config
// de test.
export default defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  fullyParallel: false,
  // 1 worker volontaire : le serveur de dev Vite (single-process) ciblé par
  // ces tests devient contentieux sous 2 Chromium headless en parallèle -
  // provoque un dépassement de timeout observé sur dashboard.spec.ts
  // (chargement > 5s), reproductible sous 2 workers, absent en isolé.
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3000',
    storageState: './tests/e2e/.auth/storageState.json',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});

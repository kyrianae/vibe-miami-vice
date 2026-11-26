import type { Page } from '@playwright/test';

// Collecte les erreurs console (type 'error', cf. page.on('console')) et les
// exceptions JS non interceptées (pageerror) à partir du moment de l'appel -
// à instancier avant page.goto() pour ne rater aucun message au chargement.
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    errors.push(msg.text());
  });
  page.on('pageerror', (err) => {
    errors.push(err.message);
  });
  return errors;
}

// Navigation via le menu Navbar.tsx (app SPA sans routeur dédié,
// frontend/src/App.tsx - pas d'URL directe par page).
export async function gotoPage(page: Page, label: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
}

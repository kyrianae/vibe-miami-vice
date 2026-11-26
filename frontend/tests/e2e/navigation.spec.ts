import { test, expect } from '@playwright/test';
import { collectConsoleErrors, gotoPage } from './helpers';

test('Navigation : charge sans erreur console et affiche l\'en-tête de navigation', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.goto('/');
  await gotoPage(page, 'Navigation');

  // Titre statique affiché quelle que soit la base de données (y compris
  // vide après une purge dev) - ne pas dépendre d'un badge de classe qui
  // n'apparaît que si des objets existent (NavigationPage.tsx:1877).
  await expect(page.getByRole('heading', { name: /Tous les objets/ })).toBeVisible();
  expect(errors).toEqual([]);
});

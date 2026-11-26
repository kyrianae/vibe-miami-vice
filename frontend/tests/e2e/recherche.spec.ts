import { test, expect } from '@playwright/test';
import { collectConsoleErrors, gotoPage } from './helpers';

test('Recherche : charge sans erreur console et affiche le champ de recherche', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.goto('/');
  await gotoPage(page, 'Recherche');

  await expect(page.getByPlaceholder('Rechercher dans les attributs de tous les objets…')).toBeVisible();
  expect(errors).toEqual([]);
});

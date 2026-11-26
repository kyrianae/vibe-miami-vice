import { test, expect } from '@playwright/test';
import { collectConsoleErrors, gotoPage } from './helpers';

test('Configuration : charge sans erreur console et affiche l\'en-tête de configuration', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.goto('/');
  await gotoPage(page, 'Configuration');

  await expect(page.getByRole('heading', { name: 'Configuration des définitions' })).toBeVisible();
  expect(errors).toEqual([]);
});

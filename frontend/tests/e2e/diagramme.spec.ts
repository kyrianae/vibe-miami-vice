import { test, expect } from '@playwright/test';
import { collectConsoleErrors, gotoPage } from './helpers';

test('Diagramme : charge sans erreur console et affiche le graphe', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.goto('/');
  await gotoPage(page, 'Diagramme');

  await expect(page.locator('.diagram-chart canvas').first()).toBeVisible({ timeout: 10000 });
  expect(errors).toEqual([]);
});

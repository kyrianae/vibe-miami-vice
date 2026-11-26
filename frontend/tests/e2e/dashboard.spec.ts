import { test, expect } from '@playwright/test';
import { collectConsoleErrors, gotoPage } from './helpers';

test('Dashboard : charge sans erreur console et affiche le titre Dashboard', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.goto('/');
  await gotoPage(page, 'Dashboard');

  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  expect(errors).toEqual([]);
});

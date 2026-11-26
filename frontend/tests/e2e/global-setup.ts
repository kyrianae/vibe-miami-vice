import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { chromium, type FullConfig } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Reproduit le pattern d'authentification de tools/screenshot_demo.py :
// password grant Keycloak direct (client public "miami-vice-direct", pas de
// secret), token injecté en localStorage sur l'origine du frontend avant
// tout chargement de page, capturé une fois comme storageState Playwright
// réutilisable par tous les tests (évite de refaire un login par test).
// 127.0.0.1 plutôt que "localhost" : cf. note dans playwright.config.ts
// (résolution dual-stack source d'ERR_NETWORK_CHANGED sous rafale de
// requêtes, observé sur la page Diagramme).
const KEYCLOAK_TOKEN_URL =
  process.env.KEYCLOAK_TOKEN_URL || 'http://127.0.0.1:8080/realms/miami-vice/protocol/openid-connect/token';
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:3000';
const AUTH_TOKEN_STORAGE_KEY = 'miami-vice-auth-token';
const STORAGE_STATE_PATH = path.join(__dirname, '.auth', 'storageState.json');

export default async function globalSetup(_config: FullConfig) {
  const res = await fetch(KEYCLOAK_TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'password',
      client_id: 'miami-vice-direct',
      username: 'testuser',
      password: 'testuser123',
    }),
  });
  if (!res.ok) {
    throw new Error(`Keycloak login failed (${res.status}): ${await res.text()}`);
  }
  const { access_token: accessToken } = (await res.json()) as { access_token: string };

  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(FRONTEND_URL);
  await page.evaluate(
    ({ key, token }) => localStorage.setItem(key, token),
    { key: AUTH_TOKEN_STORAGE_KEY, token: accessToken },
  );

  fs.mkdirSync(path.dirname(STORAGE_STATE_PATH), { recursive: true });
  await page.context().storageState({ path: STORAGE_STATE_PATH });
  await browser.close();
}

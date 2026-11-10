import type {
  MetaClassInfo,
  ClassInfo,
  MetaClassDefinition,
  ObjectSummary,
  ObjectDetail,
} from './types';

const BASE = '/api';

const AUTH_TOKEN_STORAGE_KEY = 'miami-vice-auth-token';

export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
}

export function setAuthToken(token: string | null): void {
  if (token) {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  }
}

// Attache systématiquement l'en-tête Authorization: Bearer <token> (depuis
// le localStorage) quand un token est présent, y compris pour les routes de
// lecture : action 7 ne l'exigeait que pour les écritures (protégées côté
// backend), mais action 11 (RBAC multi-tenant) en a besoin aussi en lecture
// pour que le backend puisse filtrer les objets par tenant quand l'identité
// de l'appelant est connue. Les routes /api/read/* restent ouvertes côté
// backend (pas de 401 si le token est absent) : attacher ce header ne
// change donc rien pour un visiteur non connecté.
async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

// Alias historique : les routes d'écriture utilisaient un helper dédié pour
// attacher le Bearer ; fetchJson le fait désormais pour toutes les requêtes
// (voir commentaire ci-dessus), donc fetchJsonAuth n'est plus qu'un simple
// alias, conservé pour ne pas renommer tous les appels existants et garder
// la distinction sémantique "cet appel nécessite d'être authentifié".
const fetchJsonAuth = fetchJson;

// READ - Definitions
export const apiReadMetaClasses = () =>
  fetchJson<MetaClassInfo[]>(`${BASE}/read/meta_class`);

export const apiReadClasses = () =>
  fetchJson<ClassInfo[]>(`${BASE}/read/class`);

export const apiReadClassById = (id: number) =>
  fetchJson<ClassInfo>(`${BASE}/read/class/${id}`);

export const apiReadMetaClass = (metaClass: string) =>
  fetchJson<MetaClassDefinition>(`${BASE}/read/${metaClass}`);

// READ - Objects
export const apiReadObjects = () =>
  fetchJson<ObjectSummary[]>(`${BASE}/read/objects`);

export const apiReadObject = (id: number) =>
  fetchJson<ObjectDetail>(`${BASE}/read/object/${id}`);

// WRITE - Definitions
export const apiWriteMetaClass = (data: MetaClassDefinition) =>
  fetchJsonAuth<{ status: string; action: string; meta_class: string }>(
    `${BASE}/write/metaclass`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }
  );

export const apiWriteClass = (metaClass: string, cls: { class: string; attributes: unknown[] }) =>
  fetchJsonAuth<{ status: string; action: string; class: string }>(
    `${BASE}/write/class`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ meta_class: metaClass, class: cls }),
    }
  );

// WRITE - Objects
export const apiWriteObject = (data: { id?: number; meta_class: string; class: string; attributes: Record<string, unknown>; tenants?: string[] | null }) =>
  fetchJsonAuth<{ status: string; id: number; tenants?: string[] }>(
    `${BASE}/write/object`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }
  );

export const apiWriteAttribute = (cls: string, id: number, attribute: string, value: string) =>
  fetchJsonAuth<{ status: string }>(
    `${BASE}/write/attribute/${cls}/${id}/${attribute}/${encodeURIComponent(value)}`,
    { method: 'PUT' }
  );

// Init
export const apiInit = () =>
  fetchJsonAuth<{ status: string; loaded: string[] }>(`${BASE}/init`, { method: 'POST' });

// Auth - login direct Keycloak (Resource Owner Password Credentials)
// Appel direct au navigateur vers Keycloak (port 8080 publié sur l'hôte),
// pas via le proxy Vite /api : ce n'est pas une route de ce backend, et
// passer par le proxy n'apporterait rien ici (pas de cookie à protéger,
// pas de secret à cacher pour un client public "miami-vice-direct").
const KEYCLOAK_TOKEN_URL =
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_KEYCLOAK_TOKEN_URL ||
  'http://localhost:8080/realms/miami-vice/protocol/openid-connect/token';

export async function apiLogin(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({
    grant_type: 'password',
    client_id: 'miami-vice-direct',
    username,
    password,
  });
  const res = await fetch(KEYCLOAK_TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Échec de connexion (${res.status}): ${text}`);
  }
  const data = (await res.json()) as { access_token: string };
  setAuthToken(data.access_token);
  return data.access_token;
}

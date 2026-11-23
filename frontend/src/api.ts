import type {
  MetaClassInfo,
  ClassInfo,
  MetaClassDefinition,
  ObjectSummary,
  ObjectDetail,
  LogoEntry,
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

// WRITE - Création d'objet + fichier(s) en une seule requête multipart
// (plan-mark3.md action 3, point A de la revue croisée) : évite la fenêtre
// "objet créé sans fichier" du flux JSON + upload séparé (si un upload
// échoue après une création JSON déjà commitée, un retry recrée un
// doublon). Réservé à la CRÉATION (pas d'édition par ce chemin, voir
// NavigationPage.tsx) - un champ multipart 'metadata' (JSON) porte les
// métadonnées/attributs non-fichier, un champ multipart par attribut
// file/image/csv porte le fichier correspondant.
export const apiWriteObjectCreateMultipart = async (
  metadata: { meta_class: string; class: string; attributes: Record<string, unknown>; tenants?: string[] | null },
  files: Record<string, File>
) => {
  const token = getAuthToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const formData = new FormData();
  formData.append('metadata', JSON.stringify(metadata));
  for (const [attrName, file] of Object.entries(files)) {
    formData.append(attrName, file);
  }
  const res = await fetch(`${BASE}/write/object`, {
    method: 'POST',
    headers,
    body: formData,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json() as Promise<{ status: string; id: number; action: string; tenants?: string[] }>;
};

// WRITE - Fichiers (plan-mark3.md action 3) : multipart/form-data, champ
// 'file'. Utilisé pour l'édition d'un objet existant (appelé séparément de
// apiWriteObject JSON, cf. NavigationPage.tsx) - la création avec
// fichier(s) passe par apiWriteObjectCreateMultipart ci-dessus.
export const apiWriteObjectFile = async (objectId: number, attribute: string, file: File) => {
  const token = getAuthToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/write/object/${objectId}/file/${attribute}`, {
    method: 'POST',
    headers,
    body: formData,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json() as Promise<{ status: string; object_id: number; attribute: string; version: number; filename: string; value: string }>;
};

// READ - Fichiers : routes /api/read/object/*/file/* non protégées côté
// backend (pas de 401 sans token), mais le filtrage tenant dépend du Bearer
// identique à fetchJson - un <img src=...>/<a href=...> direct ne porterait
// pas ce header, d'où un fetch explicite + Blob (URL.createObjectURL côté
// appelant) plutôt qu'une simple URL statique.
export const apiReadObjectFileBlob = async (objectId: number, attribute: string, version?: number) => {
  const token = getAuthToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const url = `${BASE}/read/object/${objectId}/file/${attribute}${version != null ? `?version=${version}` : ''}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const filename = match ? match[1] : `${attribute}`;
  const blob = await res.blob();
  return { blob, filename };
};

// Logo par référence (plan-mark3.md action 4, point 2/3) : URL brute de
// lecture d'un fichier d'objet, pour un usage <img>/ECharts `image://` qui
// ne peut pas attacher l'en-tête Authorization (cf. apiReadObjectFileBlob
// ci-dessus) - acceptable ici (DiagramPage.tsx), la spec tolère
// explicitement une icône cassée le temps d'un rendu si le tenant de
// l'appelant anonyme ne couvre pas l'objet.
export const apiObjectFileUrl = (objectId: number, attribute: string) =>
  `${BASE}/read/object/${objectId}/file/${attribute}`;

// Icône de secours auto-générée par classe (plan-mark3.md action 4, point
// 1bis) : dernier recours avant la couleur de palette, jamais appelée si
// une icône du jeu fixe (classIcons.tsx) est choisie manuellement.
export const apiClassIconUrl = (metaClass: string, cls: string) =>
  `${BASE}/class_icon/${metaClass}/${cls}`;

// Liste des logos actifs réutilisables (plan-mark3.md action 4, point 2) :
// alimente le sélecteur "réutiliser un logo existant" de NavigationPage.tsx.
export const apiListLogos = () => fetchJson<LogoEntry[]>(`${BASE}/logos`);

// Référence croisée (plan-mark3.md action 4, point 3) : pointe l'attribut
// file/image/csv d'un objet vers le fichier déjà stocké d'un AUTRE objet,
// sans dupliquer les octets. `source` désigne l'emplacement (classe,
// object_id, attribut, version) déjà connu (ex. une entrée de apiListLogos).
export const apiSetObjectFileReference = (
  objectId: number,
  attribute: string,
  source: { class: string; object_id: number; attribute: string; version: number }
) =>
  fetchJsonAuth<{ status: string; object_id: number; attribute: string; value: string }>(
    `${BASE}/write/object/${objectId}/file/${attribute}/reference`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(source),
    }
  );

// DELETE - Objects (suppression logique, plan-mark2.md action 6.1)
export const apiDeleteObject = (id: number) =>
  fetchJsonAuth<{ status: string; id: number; deleted_at: string }>(
    `${BASE}/delete/object/${id}`,
    { method: 'DELETE' }
  );

// Init
export const apiInit = () =>
  fetchJsonAuth<{ status: string; loaded: string[] }>(`${BASE}/init`, { method: 'POST' });

// Config - purge physique différée (plan-mark2.md action 6.2, global-admin uniquement)
export const apiGetPurgeGracePeriod = () =>
  fetchJsonAuth<{ value: number }>(`${BASE}/config/purge_grace_period_days`);

export const apiSetPurgeGracePeriod = (value: number) =>
  fetchJsonAuth<{ status: string; value: number }>(
    `${BASE}/config/purge_grace_period_days`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    }
  );

// Config - layers par défaut (plan-mark3.md action 18). GET ouvert (pure
// métadonnée d'affichage UI, pas un mécanisme RBAC/sécurité - cf.
// types.ts, commentaire sur ClassDef.layers) : fetchJson suffit, pas
// besoin de fetchJsonAuth. PUT réservé global-admin côté backend.
export const apiGetDefaultLayers = () =>
  fetchJson<{ value: string[] }>(`${BASE}/config/default_layers`);

export const apiSetDefaultLayers = (layers: string[]) =>
  fetchJsonAuth<{ status: string; value: string[] }>(
    `${BASE}/config/default_layers`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: layers }),
    }
  );

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

import type {
  MetaClassInfo,
  ClassInfo,
  MetaClassDefinition,
  ObjectSummary,
  ObjectDetail,
} from './types';

const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

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
  fetchJson<{ status: string; action: string; meta_class: string }>(
    `${BASE}/write/metaclass`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }
  );

export const apiWriteClass = (metaClass: string, cls: { class: string; attributes: unknown[] }) =>
  fetchJson<{ status: string; action: string; class: string }>(
    `${BASE}/write/class`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ meta_class: metaClass, class: cls }),
    }
  );

// WRITE - Objects
export const apiWriteObject = (data: { id?: number; meta_class: string; class: string; attributes: Record<string, unknown> }) =>
  fetchJson<{ status: string; id: number }>(
    `${BASE}/write/object`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }
  );

export const apiWriteAttribute = (cls: string, id: number, attribute: string, value: string) =>
  fetchJson<{ status: string }>(
    `${BASE}/write/attribute/${cls}/${id}/${attribute}/${encodeURIComponent(value)}`,
    { method: 'PUT' }
  );

// Init
export const apiInit = () =>
  fetchJson<{ status: string; loaded: string[] }>(`${BASE}/init`, { method: 'POST' });

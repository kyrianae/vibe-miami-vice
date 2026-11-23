import { useEffect, useState, useCallback, useRef, useMemo, type MouseEvent } from 'react';
import { apiReadObjects, apiReadObject, apiWriteObject, apiWriteObjectCreateMultipart, apiWriteAttribute, apiDeleteObject, apiReadClasses, apiWriteObjectFile, apiReadObjectFileBlob, apiListLogos, apiSetObjectFileReference } from '../api';
import type { ObjectSummary, ObjectDetail, ClassInfo, AttributeDefinition, LogoEntry } from '../types';
import type { AuthInfo } from '../auth';

// --- Types file/image/csv (plan-mark3.md action 3) ---
//
// Pointeur stocké côté backend : "<version>:<nom_fichier>" (value_string).
// parseFilePointer en extrait (version, filename) côté client, pour
// affichage et pour cibler une version précise en lecture.
//
// Format référence croisée (plan-mark3.md action 4, point 3 ; voir docstring
// de module backend/routes_files.py) :
// "ref:<classe>:<object_id>:<attribut>:<version>:<nom_fichier>". Seuls
// (version, filename) sont nécessaires côté client (aperçu/URL de lecture) :
// la résolution classe/object_id/attribut de la source est déjà faite côté
// backend, de façon transparente, quelle que soit la version demandée. Le
// nom de fichier peut lui-même contenir ':' (même règle que le format court),
// donc on ne fait jamais un split naïf sur tout le pointeur : on saute
// exactement les 5 premiers ':' (après ref, classe, object_id, attribut,
// version) et on garde tout le reste tel quel comme filename.
function parseFilePointer(value: string | number | { joint_id: number } | undefined): { version: number; filename: string } | null {
  if (typeof value !== 'string') return null;
  if (value.startsWith('ref:')) {
    const colonIndexes: number[] = [];
    let searchFrom = 0;
    for (let i = 0; i < 5; i++) {
      const idx = value.indexOf(':', searchFrom);
      if (idx === -1) return null;
      colonIndexes.push(idx);
      searchFrom = idx + 1;
    }
    const versionStr = value.slice(colonIndexes[3] + 1, colonIndexes[4]);
    const filename = value.slice(colonIndexes[4] + 1);
    const version = Number(versionStr);
    if (!Number.isInteger(version)) return null;
    return { version, filename };
  }
  if (!value.includes(':')) return null;
  const idx = value.indexOf(':');
  const versionStr = value.slice(0, idx);
  const filename = value.slice(idx + 1);
  const version = Number(versionStr);
  if (!Number.isInteger(version)) return null;
  return { version, filename };
}

function fileExtensionOf(filename: string): string {
  return filename.includes('.') ? filename.split('.').pop()!.toLowerCase() : '';
}

function FileDownloadButton({ objectId, attribute, version, filename }: { objectId: number; attribute: string; version: number; filename: string }) {
  const [busy, setBusy] = useState(false);
  const handleDownload = async (e: MouseEvent) => {
    e.stopPropagation();
    setBusy(true);
    try {
      const { blob, filename: serverFilename } = await apiReadObjectFileBlob(objectId, attribute, version);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = serverFilename || filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      // Pas de toast ici : ce composant n'a pas accès à addToast (défini
      // dans NavigationPage) - un échec de téléchargement reste silencieux
      // côté UI, acceptable pour ce premier passage.
    } finally {
      setBusy(false);
    }
  };
  return (
    <button onClick={handleDownload} disabled={busy}
      style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: 12, padding: 0, textDecoration: 'underline' }}
    >{busy ? '...' : '↓ télécharger'}</button>
  );
}

// Cache des blobs fichier (plan-mark3.md action 3, correction post-revue
// point D6) : ImagePreview/CsvPreviewTable refetchaient le même blob à
// chaque render de cellule (un re-render du tableau parent, ex. après
// loadObjects, recrée ces composants) - une version de fichier est
// immuable une fois écrite (jamais mutée en place), donc une Promise par
// clé "<objectId>:<attribute>:<version>" peut être partagée indéfiniment
// entre toutes les instances, sans invalidation nécessaire. Map module-level
// (pas de contexte React) : volontairement non bornée pour ce premier
// passage - limite connue assumée (pas de LRU/éviction), acceptable vu le
// volume attendu d'un back-office.
const fileBlobCache = new Map<string, Promise<{ blob: Blob; filename: string }>>();
function getCachedFileBlob(objectId: number, attribute: string, version: number) {
  const key = `${objectId}:${attribute}:${version}`;
  let entry = fileBlobCache.get(key);
  if (!entry) {
    entry = apiReadObjectFileBlob(objectId, attribute, version);
    entry.catch(() => { fileBlobCache.delete(key); }); // n'y laisse pas un échec en cache
    fileBlobCache.set(key, entry);
  }
  return entry;
}

// Aperçu inline jpg/png uniquement (plan-mark3.md action 3, décision
// sécurité SVG : jamais d'<img> direct pour un SVG, cf. routes_files.py).
function ImagePreview({ objectId, attribute, version }: { objectId: number; attribute: string; version: number }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let revoked = false;
    let objectUrl: string | null = null;
    getCachedFileBlob(objectId, attribute, version).then(({ blob }) => {
      if (revoked) return;
      objectUrl = URL.createObjectURL(blob);
      setSrc(objectUrl);
    }).catch(() => {});
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [objectId, attribute, version]);
  if (!src) return <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>chargement…</span>;
  return <img src={src} alt={attribute} style={{ maxWidth: 80, maxHeight: 80, borderRadius: 4, display: 'block' }} />;
}

// Tableau lecture seule (pas d'édition de cellule, cf. §10.8) : parsing
// client avec le separator défini sur l'attribut (défaut ',' si absent).
function CsvPreviewTable({ objectId, attribute, version, separator }: { objectId: number; attribute: string; version: number; separator: string }) {
  const [rows, setRows] = useState<string[][] | null>(null);
  useEffect(() => {
    let cancelled = false;
    getCachedFileBlob(objectId, attribute, version).then(async ({ blob }) => {
      const text = await blob.text();
      if (cancelled) return;
      const parsed = text.split(/\r?\n/).filter((l) => l.length > 0).map((line) => line.split(separator));
      setRows(parsed);
    }).catch(() => { if (!cancelled) setRows([]); });
    return () => { cancelled = true; };
  }, [objectId, attribute, version, separator]);

  if (rows === null) return <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>chargement…</span>;
  if (rows.length === 0) return <span style={{ color: 'var(--color-text-muted)' }}>—</span>;
  return (
    <table style={{ fontSize: 11, borderCollapse: 'collapse' }}>
      <tbody>
        {rows.map((cols, i) => (
          <tr key={i}>
            {cols.map((cell, j) => <td key={j} style={{ border: '1px solid var(--color-border)', padding: '2px 6px' }}>{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FileAttributeValueDisplay({ objectId, attrDef, value }: { objectId: number; attrDef: AttributeDefinition; value: string }) {
  const pointer = parseFilePointer(value);
  if (!pointer) return <span>{value}</span>;
  const { version, filename } = pointer;
  const ext = fileExtensionOf(filename);

  if (attrDef.type === 'image' && (ext === 'jpg' || ext === 'jpeg' || ext === 'png')) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <ImagePreview objectId={objectId} attribute={attrDef.name} version={version} />
        <FileDownloadButton objectId={objectId} attribute={attrDef.name} version={version} filename={filename} />
      </div>
    );
  }
  if (attrDef.type === 'csv') {
    return (
      <div>
        <CsvPreviewTable objectId={objectId} attribute={attrDef.name} version={version} separator={attrDef.separator || ','} />
        <div style={{ marginTop: 4 }}>
          <FileDownloadButton objectId={objectId} attribute={attrDef.name} version={version} filename={filename} />
        </div>
      </div>
    );
  }
  // 'file' générique, et 'image' svg (pas d'aperçu inline - décision
  // sécurité backend, routes_files.py) : nom + téléchargement seul.
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span>{filename}</span>
      <FileDownloadButton objectId={objectId} attribute={attrDef.name} version={version} filename={filename} />
    </div>
  );
}

interface NavigationPageProps {
  selectedMetaClass: string | null;
  selectedClass: string | null;
  readOnly: boolean;
  authInfo: AuthInfo;
  // Filtre layers (plan-mark3.md action 14, point 6) : multi-sélection,
  // orthogonal au filtre meta_class/class ci-dessus. Vide = pas de filtre
  // actif (tout visible).
  selectedLayers: Set<string>;
}

// Classe visible pour le filtre layer actif (plan-mark3.md action 14,
// point 1) : `layers` absent/vide = toujours visible, quel que soit le
// filtre (même convention que `tenants`, cf. isClassVisibleForTenant dans
// ConfigurationPage.tsx). selectedLayers vide = pas de filtre actif (tout
// visible), défaut non régressif.
function isClassVisibleForLayers(def: { layers?: string[] } | undefined, selectedLayers: Set<string>): boolean {
  if (selectedLayers.size === 0) return true;
  const layers = def?.layers || [];
  if (layers.length === 0) return true;
  return layers.some((l) => selectedLayers.has(l));
}

// Layer effectif d'un objet (plan-mark3.md action 18, specifications/
// 07-roadmap.md §10.15) : union du `layers` statique de sa classe et, pour
// chaque attribut 'select' de la classe portant un `layer_map`, des layers
// mappés à la valeur courante de l'objet sur cet attribut (si connue).
// Repli sur `classDef.layers` statique seul si le détail de l'objet n'est
// pas encore chargé (chargement lazy par groupe, cf. toggleGroup/auto-load
// ci-dessous) - point ouvert tranché par l'utilisateur (§10.15) : pas de
// blocage/attente du détail pour filtrer.
function getObjectEffectiveLayers(
  classDef: { layers?: string[]; attributes: AttributeDefinition[] } | undefined,
  detail: ObjectDetail | undefined,
): string[] {
  const base = classDef?.layers || [];
  if (!classDef || !detail) return base;
  const extra: string[] = [];
  for (const attrDef of classDef.attributes) {
    if (attrDef.type !== 'select' || !attrDef.layer_map) continue;
    const attrVal = detail.attributes.find((a) => a.name === attrDef.name);
    if (!attrVal || attrVal.values.length === 0) continue;
    const current = attrVal.values[0];
    if (typeof current !== 'string') continue;
    const mapped = attrDef.layer_map[current];
    if (mapped) extra.push(...mapped);
  }
  return extra.length > 0 ? [...new Set([...base, ...extra])] : base;
}

// État d'édition inline d'une cellule
interface InlineEdit {
  objectId: number;
  attrName: string;
  value: string;
}

// État d'édition joint (modale)
interface JointEdit {
  objectId: number;
  attrName: string;
  attrDef: AttributeDefinition;
  selected: number[];
}

export default function NavigationPage({ selectedMetaClass, selectedClass, readOnly, authInfo, selectedLayers }: NavigationPageProps) {
  const [objects, setObjects] = useState<ObjectSummary[]>([]);
  const [detailCache, setDetailCache] = useState<Record<number, ObjectDetail>>({});
  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  // Filtre texte par groupe de classe (plan-mark3.md action 15, point 4) :
  // une case par card, filtre d'affichage pur sur les lignes déjà chargées -
  // ne touche jamais `objects`/`detailCache`.
  const [groupFilters, setGroupFilters] = useState<Record<string, string>>({});
  const [showCreate, setShowCreate] = useState(false);
  const [editingObjectId, setEditingObjectId] = useState<number | null>(null);
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [toasts, setToasts] = useState<{ id: number; type: 'success' | 'error'; text: string; fading: boolean }[]>([]);
  const toastIdRef = useRef(0);

  const addToast = useCallback((type: 'success' | 'error', text: string) => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, type, text, fading: false }]);
    setTimeout(() => {
      setToasts((prev) => prev.map((t) => t.id === id ? { ...t, fading: true } : t));
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 400);
    }, 5000);
  }, []);

  // Filtres par classe (toggle buttons)
  const [visibleClasses, setVisibleClasses] = useState<Set<string>>(new Set());

  // Form state (create + edit modal)
  const [newMetaClass, setNewMetaClass] = useState('');
  const [newClass, setNewClass] = useState('');
  const [newAttrs, setNewAttrs] = useState<Record<string, string>>({});
  // Types file/image/csv (plan-mark3.md action 3) : fichier sélectionné par
  // l'utilisateur dans le formulaire, séparé de newAttrs (pas une valeur
  // texte) - uploadé via une route multipart dédiée au moment du save,
  // jamais inclus dans le JSON envoyé à apiWriteObject.
  const [newFileUploads, setNewFileUploads] = useState<Record<string, File | null>>({});
  // Réutilisation d'un logo existant par référence (plan-mark3.md action 4,
  // point 2/3) : sélection distincte d'un upload (newFileUploads) - au plus
  // l'un des deux par attribut, le dernier choisi par l'utilisateur gagne
  // (voir les onChange ci-dessous, qui remettent l'autre à null).
  const [newFileReferences, setNewFileReferences] = useState<Record<string, LogoEntry | null>>({});
  const [availableLogos, setAvailableLogos] = useState<LogoEntry[]>([]);
  // Refs du <input type="file"> caché de chaque attribut "logo" - cliquer
  // sur l'aperçu déclenche directement le sélecteur de fichier natif (pas
  // de bouton séparé, plan-mark3.md action 4, point 2).
  const logoInputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  // RBAC multi-tenant (plan.md action 11) : tenant explicite à poser sur un
  // objet en cours de création, utile uniquement pour un tenant-admin
  // multi-tenant (cas secondaire - un tenant-admin à un seul tenant est
  // auto-tagué côté backend sans action requise ici). Non géré en édition
  // (choix simple assumé pour ce premier passage, cf. rapport worker).
  const [objectTenant, setObjectTenant] = useState('');
  const [jointValues, setJointValues] = useState<Record<string, number[]>>({});
  const [candidateLabels, setCandidateLabels] = useState<Record<number, string>>({});

  // Inline cell editing
  const [inlineEdit, setInlineEdit] = useState<InlineEdit | null>(null);

  // Joint editing modal (from cell click)
  const [jointEdit, setJointEdit] = useState<JointEdit | null>(null);

  // Quick-create inline dans un champ joint
  const [quickCreate, setQuickCreate] = useState<{
    attrName: string; // nom de l'attribut joint parent
    targetClass: string;
    targetMetaClass: string;
    attrs: Record<string, string>;
    context: 'modal' | 'jointEdit'; // dans quelle modale
  } | null>(null);

  const loadObjects = useCallback(() => {
    apiReadObjects().then(setObjects).catch(() => {});
  }, []);

  useEffect(() => {
    loadObjects();
    apiReadClasses().then(setClasses).catch(() => {});
  }, [loadObjects]);

  // Quand la sélection sidebar change
  useEffect(() => {
    if (selectedMetaClass) {
      const classesOfMeta = classes
        .filter((c) => c.meta_class === selectedMetaClass)
        .map((c) => c.class);
      if (selectedClass) {
        setVisibleClasses(new Set([selectedClass]));
      } else {
        setVisibleClasses(new Set(classesOfMeta));
      }
      setNewMetaClass(selectedMetaClass);
      setNewClass(selectedClass || '');
    } else {
      setVisibleClasses(new Set());
      setNewMetaClass('');
      setNewClass('');
    }
    setShowCreate(false);
    setEditingObjectId(null);
    setNewAttrs({});
    setExpandedGroups(new Set());
    setInlineEdit(null);
    setJointEdit(null);
    setGroupFilters({});
  }, [selectedMetaClass, selectedClass, classes]);

  const availableClasses = selectedMetaClass
    ? classes.filter((c) => c.meta_class === selectedMetaClass)
    : [];

  const filtered = useMemo(
    () =>
      objects.filter((o) => {
        if (selectedMetaClass && o.meta_class !== selectedMetaClass) return false;
        if (selectedMetaClass && visibleClasses.size > 0 && !visibleClasses.has(o.class)) return false;
        if (!selectedMetaClass && selectedClass && o.class !== selectedClass) return false;
        const def = classes.find((c) => c.meta_class === o.meta_class && c.class === o.class);
        // Layer effectif par objet (action 18) : remplace classDef.layers
        // statique seul par le calcul union, repli automatique si le détail
        // n'est pas encore en cache (voir getObjectEffectiveLayers).
        const effectiveLayers = getObjectEffectiveLayers(def, detailCache[o.id]);
        if (!isClassVisibleForLayers({ layers: effectiveLayers }, selectedLayers)) return false;
        return true;
      }),
    [objects, selectedMetaClass, selectedClass, visibleClasses, classes, selectedLayers, detailCache],
  );

  const grouped: Record<string, { meta_class: string; class: string; objects: ObjectSummary[] }> = {};
  // Ajouter les groupes vides pour les classes visibles (pour pouvoir créer des objets)
  if (selectedMetaClass) {
    const classesToShow = selectedClass ? [selectedClass] : [...visibleClasses];
    for (const cls of classesToShow) {
      const def = classes.find((c) => c.meta_class === selectedMetaClass && c.class === cls);
      if (def) {
        const key = `${selectedMetaClass}::${cls}`;
        grouped[key] = { meta_class: selectedMetaClass, class: cls, objects: [] };
      }
    }
  }
  for (const obj of filtered) {
    const key = `${obj.meta_class}::${obj.class}`;
    if (!grouped[key]) {
      grouped[key] = { meta_class: obj.meta_class, class: obj.class, objects: [] };
    }
    grouped[key].objects.push(obj);
  }

  const getClassDef = (mc: string, cls: string) =>
    classes.find((c) => c.meta_class === mc && c.class === cls);

  // Auto-expand + auto-load
  useEffect(() => {
    const keys = Object.keys(grouped);
    if (keys.length === 0) return;
    setExpandedGroups(new Set(keys));
    const toLoad = filtered.filter((o) => !detailCache[o.id]);
    if (toLoad.length === 0) return;
    const ids = new Set(toLoad.map((o) => o.id));
    setLoadingIds((prev) => new Set([...prev, ...ids]));
    Promise.allSettled(toLoad.map((o) => apiReadObject(o.id))).then((results) => {
      const newCache: Record<number, ObjectDetail> = {};
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') newCache[toLoad[i].id] = r.value;
      });
      setDetailCache((prev) => ({ ...prev, ...newCache }));
      setLoadingIds((prev) => {
        const n = new Set(prev);
        ids.forEach((id) => n.delete(id));
        return n;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered.map((o) => o.id).join(',')]);

  const toggleClassFilter = (cls: string) => {
    setVisibleClasses((prev) => {
      const next = new Set(prev);
      next.has(cls) ? next.delete(cls) : next.add(cls);
      return next;
    });
  };

  const toggleGroup = async (groupKey: string) => {
    const next = new Set(expandedGroups);
    if (next.has(groupKey)) { next.delete(groupKey); setExpandedGroups(next); return; }
    next.add(groupKey);
    setExpandedGroups(next);
    const group = grouped[groupKey];
    if (!group) return;
    const toLoad = group.objects.filter((o) => !detailCache[o.id]);
    if (toLoad.length === 0) return;
    const ids = new Set(toLoad.map((o) => o.id));
    setLoadingIds((prev) => new Set([...prev, ...ids]));
    const results = await Promise.allSettled(toLoad.map((o) => apiReadObject(o.id)));
    const newCache: Record<number, ObjectDetail> = {};
    results.forEach((r, i) => { if (r.status === 'fulfilled') newCache[toLoad[i].id] = r.value; });
    setDetailCache((prev) => ({ ...prev, ...newCache }));
    setLoadingIds((prev) => { const n = new Set(prev); ids.forEach((id) => n.delete(id)); return n; });
  };

  // --- Display helpers ---
  const resolveDisplayName = (detail: ObjectDetail): string => {
    const classDef = classes.find((c) => c.meta_class === detail.meta_class && c.class === detail.class);
    const template = classDef?.displayname;
    if (template) {
      return template.replace(/\{\{(\w+)\}\}/g, (_m, name) => {
        const a = detail.attributes.find((x) => x.name === name);
        if (!a || a.values.length === 0) return '';
        const v = a.values[0];
        return typeof v === 'object' && 'joint_id' in v ? `#${v.joint_id}` : String(v);
      });
    }
    const parts = detail.attributes
      .filter((a) => a.domain === 'details' && a.values.length > 0 && typeof a.values[0] !== 'object')
      .map((a) => String(a.values[0]));
    return parts.length > 0 ? parts.join(' ') : `${detail.class} #${detail.id}`;
  };

  const formatValue = (v: string | number | { joint_id: number }) => {
    if (typeof v === 'object' && v && 'joint_id' in v) {
      const ref = detailCache[v.joint_id];
      return ref ? `→ ${resolveDisplayName(ref)}` : `→ #${v.joint_id}`;
    }
    return String(v);
  };

  // Filtre texte par groupe (plan-mark3.md action 15, point 4) : construit
  // un texte plat par ligne à partir des mêmes données que le rendu réel des
  // cellules (formatValue, nom de fichier pour file/image/csv) - inclut l'ID
  // (choix retenu : filtre sur toutes les cellules rendues, ID compris).
  const rowMatchesFilter = (obj: ObjectSummary, attrNames: string[], attrDefs: AttributeDefinition[], needle: string): boolean => {
    if (!needle) return true;
    const parts: string[] = [String(obj.id)];
    const detail = detailCache[obj.id];
    if (detail) {
      for (const name of attrNames) {
        const attrDef = attrDefs.find((a) => a.name === name);
        const attr = detail.attributes.find((a) => a.name === name);
        if (!attr || attr.values.length === 0) continue;
        if (attrDef?.type === 'file' || attrDef?.type === 'image' || attrDef?.type === 'csv') {
          const pointer = parseFilePointer(attr.values[0]);
          if (pointer) parts.push(pointer.filename);
          continue;
        }
        if (attrDef?.type === 'datasource') {
          attr.values.forEach((v) => parts.push(formatValue({ joint_id: Number(v) })));
          continue;
        }
        attr.values.forEach((v) => parts.push(formatValue(v)));
      }
    }
    return parts.join(' ').toLowerCase().includes(needle);
  };

  const getCandidateLabel = (obj: ObjectSummary) => {
    const detail = detailCache[obj.id];
    if (detail) return `${resolveDisplayName(detail)} (#${obj.id})`;
    if (candidateLabels[obj.id]) return candidateLabels[obj.id];
    return `${obj.class} #${obj.id}`;
  };

  // Trouver les parents d'un objet sur un attribut donné (objets qui référencent objectId via attrName)
  const getParentIds = (objectId: number, attrName: string): Set<number> => {
    const parents = new Set<number>();
    for (const [id, detail] of Object.entries(detailCache)) {
      const numId = Number(id);
      if (numId === objectId) continue;
      const attr = detail.attributes.find((a) => a.name === attrName);
      if (attr) {
        for (const v of attr.values) {
          if (typeof v === 'object' && 'joint_id' in v && v.joint_id === objectId) {
            parents.add(numId);
            break;
          }
        }
      }
    }
    return parents;
  };

  const getCandidates = (attr: { classes?: string[]; name?: string }, excludeObjectId?: number | null) => {
    let candidates = objects.filter((o) => (attr.classes || []).includes(o.class));
    if (excludeObjectId != null && attr.name) {
      const parentIds = getParentIds(excludeObjectId, attr.name);
      candidates = candidates.filter((o) => o.id !== excludeObjectId && !parentIds.has(o.id));
    }
    return candidates;
  };

  // --- Form helpers (create/edit modal) ---
  const selectedClassDef = classes.find((c) => c.meta_class === newMetaClass && c.class === newClass);

  // Logos réutilisables (plan-mark3.md action 4, point 2) : chargés
  // seulement si la classe sélectionnée porte l'attribut réservé "logo" -
  // évite un appel réseau superflu pour les classes sans logo.
  useEffect(() => {
    if (!showCreate) { setAvailableLogos([]); return; }
    const hasLogoAttr = selectedClassDef?.attributes.some((a) => a.name === 'logo' && a.type === 'image');
    if (!hasLogoAttr) { setAvailableLogos([]); return; }
    apiListLogos().then(setAvailableLogos).catch(() => setAvailableLogos([]));
  }, [showCreate, selectedClassDef]);

  const loadCandidatesForDef = (def: ClassInfo) => {
    // datasource (plan-mark3.md action 9) inclus ici : même préchargement de
    // label d'objet cible que joint-1-1/joint-1-n, réutilisé tel quel.
    const jointAttrs = def.attributes.filter((a) => a.type === 'joint-1-1' || a.type === 'joint-1-n' || a.type === 'datasource');
    if (jointAttrs.length === 0) return;
    const targetClasses = new Set(jointAttrs.flatMap((a) => a.classes || []));
    const candidates = objects.filter((o) => targetClasses.has(o.class));
    const toLoad = candidates.filter((o) => !detailCache[o.id]);
    if (toLoad.length > 0) {
      Promise.allSettled(toLoad.map((o) => apiReadObject(o.id))).then((results) => {
        const labels: Record<number, string> = {};
        results.forEach((r, i) => {
          if (r.status === 'fulfilled') {
            const d = r.value;
            setDetailCache((prev) => ({ ...prev, [d.id]: d }));
            labels[d.id] = `${resolveDisplayName(d)} (#${d.id})`;
          }
        });
        setCandidateLabels((prev) => ({ ...prev, ...labels }));
      });
    }
  };

  const handleSelectNewClass = (mc: string, cls: string) => {
    setNewMetaClass(mc);
    setNewClass(cls);
    const def = classes.find((c) => c.meta_class === mc && c.class === cls);
    if (def) {
      const attrs: Record<string, string> = {};
      const joints: Record<string, number[]> = {};
      for (const a of def.attributes) {
        if (a.type === 'joint-1-1' || a.type === 'joint-1-n') joints[a.name] = [];
        else if (a.type === 'file' || a.type === 'image' || a.type === 'csv') continue; // géré par newFileUploads
        else attrs[a.name] = '';
      }
      setNewAttrs(attrs);
      setJointValues(joints);
      setNewFileUploads({});
      setNewFileReferences({});
      loadCandidatesForDef(def);
    } else {
      setNewAttrs({});
      setJointValues({});
      setNewFileUploads({});
      setNewFileReferences({});
    }
  };

  // --- Open edit modal (double-click) ---
  const handleEditObject = (obj: ObjectSummary) => {
    const detail = detailCache[obj.id];
    const def = getClassDef(obj.meta_class, obj.class);
    if (!detail || !def) return;

    setEditingObjectId(obj.id);
    setNewMetaClass(obj.meta_class);
    setNewClass(obj.class);

    const attrs: Record<string, string> = {};
    const joints: Record<string, number[]> = {};
    for (const attrDef of def.attributes) {
      const attrVal = detail.attributes.find((a) => a.name === attrDef.name);
      if (attrDef.type === 'joint-1-1' || attrDef.type === 'joint-1-n') {
        joints[attrDef.name] = attrVal
          ? attrVal.values
              .filter((v): v is { joint_id: number } => typeof v === 'object' && 'joint_id' in v)
              .map((v) => v.joint_id)
          : [];
      } else if (attrDef.type === 'file' || attrDef.type === 'image' || attrDef.type === 'csv') {
        // Géré par newFileUploads : la valeur actuelle (pointeur) reste
        // lisible via detailCache dans le rendu du formulaire, jamais
        // recopiée dans newAttrs (pas éditable en texte).
        continue;
      } else if (attrDef.type === 'secret') {
        // Jamais pré-rempli (plan-mark3.md action 8) : la lecture générique
        // ne renvoie qu'un placeholder masqué, jamais la vraie valeur - le
        // recopier dans newAttrs permettrait de resoumettre ce placeholder
        // littéral comme nouveau texte en clair si le champ n'est pas
        // retouché. Champ vide à l'ouverture, dans tous les cas.
        attrs[attrDef.name] = '';
      } else {
        attrs[attrDef.name] = attrVal && attrVal.values.length > 0
          ? String(attrVal.values[0])
          : '';
      }
    }
    setNewAttrs(attrs);
    setJointValues(joints);
    setNewFileUploads({});
    setNewFileReferences({});
    loadCandidatesForDef(def);
    setShowCreate(true);
  };

  // --- Delete (suppression logique, action 6.1) ---
  const handleDeleteObject = async (obj: ObjectSummary) => {
    if (!window.confirm(`Supprimer l'objet #${obj.id} (${obj.class}) ?`)) return;
    try {
      await apiDeleteObject(obj.id);
      addToast('success', `Objet #${obj.id} supprimé`);
      loadObjects();
      setDetailCache((prev) => {
        const next = { ...prev };
        delete next[obj.id];
        return next;
      });
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    }
  };

  // --- Save (create or update) ---
  const handleSave = async () => {
    if (!newMetaClass || !newClass) {
      addToast('error', 'Sélectionnez une meta-classe et une classe');
      return;
    }
    try {
      const attributes: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(newAttrs)) {
        if (v !== '') attributes[k] = v;
      }
      const def = classes.find((c) => c.meta_class === newMetaClass && c.class === newClass);
      if (def) {
        for (const attr of def.attributes) {
          // boolean (plan-mark3.md action 19) : newAttrs ne porte jamais
          // qu'une chaîne "true"/"false" (comme tout autre type scalaire,
          // cf. handleEditObject/handleSelectNewClass) - reconverti ici en
          // booléen JSON natif juste avant l'envoi, seul format accepté par
          // _coerce_typed_value côté backend pour ce chemin JSON (write_object).
          if (attr.type === 'boolean' && attributes[attr.name] !== undefined) {
            attributes[attr.name] = attributes[attr.name] === 'true';
          }
          const ids = jointValues[attr.name];
          if (!ids || ids.length === 0) continue;
          if (attr.type === 'joint-1-1') attributes[attr.name] = { joint_id: ids[0] };
          else if (attr.type === 'joint-1-n') attributes[attr.name] = ids.map((id) => ({ joint_id: id }));
        }
      }
      const fileEntries = Object.entries(newFileUploads).filter(
        (entry): entry is [string, File] => entry[1] != null
      );

      let objectId: number;
      let resultId: number;

      if (!editingObjectId && fileEntries.length > 0) {
        // Création avec fichier(s) : une seule requête multipart
        // (plan-mark3.md action 3, point A de la revue croisée) - évite la
        // fenêtre "objet créé sans fichier" du flux JSON + upload séparé
        // (un retry après échec d'upload recréait un second objet,
        // doublon). Réservé à la création : l'édition d'un objet existant
        // n'a pas ce risque (un retry réutilise le même object_id), elle
        // garde le flux JSON + upload(s) séparé(s) ci-dessous.
        const metadata: { meta_class: string; class: string; attributes: Record<string, unknown>; tenants?: string[] } = {
          meta_class: newMetaClass,
          class: newClass,
          attributes,
        };
        if (authInfo.isTenantAdmin && authInfo.tenants.length > 1 && objectTenant) metadata.tenants = [objectTenant];
        const files: Record<string, File> = {};
        for (const [attrName, file] of fileEntries) files[attrName] = file;
        const res = await apiWriteObjectCreateMultipart(metadata, files);
        objectId = res.id;
        resultId = res.id;
      } else {
        const payload: Record<string, unknown> = {
          meta_class: newMetaClass,
          class: newClass,
          attributes,
        };
        if (editingObjectId) payload.id = editingObjectId;
        else if (authInfo.isTenantAdmin && authInfo.tenants.length > 1 && objectTenant) payload.tenants = [objectTenant];

        const res = await apiWriteObject(payload as { meta_class: string; class: string; attributes: Record<string, unknown> });
        objectId = editingObjectId || res.id;
        resultId = res.id;

        // Édition : upload(s) séparé(s) comme avant, pas de risque de
        // doublon (object_id déjà fixé, un retry le réutilise).
        for (const [attrName, file] of fileEntries) {
          await apiWriteObjectFile(objectId, attrName, file);
        }
      }

      // Réutilisation d'un logo existant par référence (plan-mark3.md
      // action 4, point 2/3) : toujours une requête séparée APRÈS la
      // création/édition de l'objet (objectId connu dans les deux branches
      // ci-dessus, multipart ou JSON) - pas de risque de doublon d'objet,
      // seul un retry de cette seule requête serait à refaire en cas
      // d'échec, inchangé par ailleurs (idempotent côté backend : pointe à
      // nouveau le même attribut vers la même source).
      const referenceEntries = Object.entries(newFileReferences).filter(
        (entry): entry is [string, LogoEntry] => entry[1] != null
      );
      for (const [attrName, ref] of referenceEntries) {
        await apiSetObjectFileReference(objectId, attrName, {
          class: ref.class, object_id: ref.object_id, attribute: ref.attribute, version: ref.version,
        });
      }

      const action = editingObjectId ? 'mis à jour' : 'créé';
      addToast('success', `Objet ${action} (id: ${resultId})`);
      closeModal();
      // Refresh
      loadObjects();
      // Invalidate detail cache for this object
      if (editingObjectId || fileEntries.length > 0 || referenceEntries.length > 0) {
        const refreshed = await apiReadObject(objectId);
        setDetailCache((prev) => ({ ...prev, [objectId]: refreshed }));
      }
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    }
  };

  const closeModal = () => {
    setShowCreate(false);
    setEditingObjectId(null);
    setNewAttrs({});
    setJointValues({});
    setObjectTenant('');
    setNewFileUploads({});
    setNewFileReferences({});
  };

  // --- Inline cell click ---
  const handleCellClick = (obj: ObjectSummary, attrName: string) => {
    const def = getClassDef(obj.meta_class, obj.class);
    if (!def) return;
    const attrDef = def.attributes.find((a) => a.name === attrName);
    if (!attrDef) return;
    // file/image/csv (plan-mark3.md action 3) : pas d'édition inline de
    // cellule, uniquement via le formulaire (<input type="file">) - un clic
    // ne doit jamais ouvrir l'édition texte générique sur un pointeur
    // "<version>:<nom>" (le JSON write le rejetterait de toute façon, cf.
    // garde-fou routes_write.py).
    // secret (plan-mark3.md action 8) : même exclusion - la cellule n'affiche
    // que le placeholder masqué renvoyé par la lecture générique, jamais la
    // vraie valeur ; pré-remplir une édition inline avec ce placeholder
    // écraserait le secret réel par ce texte littéral à la sauvegarde.
    if (attrDef.type === 'file' || attrDef.type === 'image' || attrDef.type === 'csv' || attrDef.type === 'secret') return;
    const detail = detailCache[obj.id];

    if (attrDef.type === 'joint-1-n') {
      // Open joint editing modal for 1:N only
      const currentIds = detail
        ? detail.attributes
            .find((a) => a.name === attrName)
            ?.values.filter((v): v is { joint_id: number } => typeof v === 'object' && 'joint_id' in v)
            .map((v) => v.joint_id) || []
        : [];
      setJointEdit({ objectId: obj.id, attrName, attrDef, selected: currentIds });
      // Load candidates
      const targetClasses = new Set(attrDef.classes || []);
      const candidates = objects.filter((o) => targetClasses.has(o.class));
      const toLoad = candidates.filter((o) => !detailCache[o.id]);
      if (toLoad.length > 0) {
        Promise.allSettled(toLoad.map((o) => apiReadObject(o.id))).then((results) => {
          const labels: Record<number, string> = {};
          results.forEach((r, i) => {
            if (r.status === 'fulfilled') {
              const d = r.value;
              setDetailCache((prev) => ({ ...prev, [d.id]: d }));
              labels[d.id] = `${resolveDisplayName(d)} (#${d.id})`;
            }
          });
          setCandidateLabels((prev) => ({ ...prev, ...labels }));
        });
      }
    } else if (attrDef.type === 'joint-1-1') {
      // Inline select for 1:1
      const currentIds = detail
        ? detail.attributes
            .find((a) => a.name === attrName)
            ?.values.filter((v): v is { joint_id: number } => typeof v === 'object' && 'joint_id' in v)
            .map((v) => v.joint_id) || []
        : [];
      setInlineEdit({ objectId: obj.id, attrName, value: currentIds.length > 0 ? String(currentIds[0]) : '' });
      // Load candidates
      const targetClasses = new Set(attrDef.classes || []);
      const candidates = objects.filter((o) => targetClasses.has(o.class));
      const toLoad = candidates.filter((o) => !detailCache[o.id]);
      if (toLoad.length > 0) {
        Promise.allSettled(toLoad.map((o) => apiReadObject(o.id))).then((results) => {
          const labels: Record<number, string> = {};
          results.forEach((r, i) => {
            if (r.status === 'fulfilled') {
              const d = r.value;
              setDetailCache((prev) => ({ ...prev, [d.id]: d }));
              labels[d.id] = `${resolveDisplayName(d)} (#${d.id})`;
            }
          });
          setCandidateLabels((prev) => ({ ...prev, ...labels }));
        });
      }
    } else if (attrDef.type === 'datasource') {
      // Inline select pour datasource (plan-mark3.md action 9) : même
      // préchargement de labels que joint-1-1 ci-dessus - l'édition inline
      // de cellule avait été oubliée à l'action 7 (select), pas reproduit
      // ici.
      const currentVal = detail?.attributes.find((a) => a.name === attrName);
      const val = currentVal && currentVal.values.length > 0 ? String(currentVal.values[0]) : '';
      setInlineEdit({ objectId: obj.id, attrName, value: val });
      const targetClasses = new Set(attrDef.classes || []);
      const candidates = objects.filter((o) => targetClasses.has(o.class));
      const toLoad = candidates.filter((o) => !detailCache[o.id]);
      if (toLoad.length > 0) {
        Promise.allSettled(toLoad.map((o) => apiReadObject(o.id))).then((results) => {
          const labels: Record<number, string> = {};
          results.forEach((r, i) => {
            if (r.status === 'fulfilled') {
              const d = r.value;
              setDetailCache((prev) => ({ ...prev, [d.id]: d }));
              labels[d.id] = `${resolveDisplayName(d)} (#${d.id})`;
            }
          });
          setCandidateLabels((prev) => ({ ...prev, ...labels }));
        });
      }
    } else if (attrDef.type === 'boolean') {
      // Case à cocher (plan-mark3.md action 19) : valeur par défaut 'false'
      // (jamais '' comme le texte libre) - une cellule vide pour un booléen
      // n'a pas de sens, le checkbox doit toujours démarrer dans un état
      // déterminé coché/décoché.
      const currentVal = detail?.attributes.find((a) => a.name === attrName);
      const val = currentVal && currentVal.values.length > 0 ? String(currentVal.values[0]) : 'false';
      setInlineEdit({ objectId: obj.id, attrName, value: val });
    } else {
      // Inline text/number edit
      const currentVal = detail?.attributes.find((a) => a.name === attrName);
      const val = currentVal && currentVal.values.length > 0 ? String(currentVal.values[0]) : '';
      setInlineEdit({ objectId: obj.id, attrName, value: val });
    }
  };

  // --- Save inline edit ---
  const saveInlineEdit = async () => {
    if (!inlineEdit) return
    const { objectId, attrName, value } = inlineEdit
    const obj = objects.find((o) => o.id === objectId)
    if (!obj) return

    const def = getClassDef(obj.meta_class, obj.class)
    const attrDef = def?.attributes.find((a) => a.name === attrName)

    try {
      if (attrDef?.type === 'joint-1-1') {
        const detail = detailCache[obj.id]
        if (!def || !detail) {
          addToast('error', 'Impossible de sauvegarder : détail de l\'objet non chargé');
          setInlineEdit(null);
          return;
        }
        const attributes: Record<string, unknown> = {}
        for (const ad of def.attributes) {
          const attrVal = detail.attributes.find((a) => a.name === ad.name)
          if (ad.name === attrName) {
            if (value !== '') {
              attributes[ad.name] = { joint_id: Number(value) }
            }
          } else if (ad.type === 'joint-1-1' || ad.type === 'joint-1-n') {
            if (attrVal) {
              const jointIds = attrVal.values.filter((v): v is { joint_id: number } => typeof v === 'object' && 'joint_id' in v)
              if (jointIds.length > 0) attributes[ad.name] = jointIds.length === 1 ? jointIds[0] : jointIds
            }
          } else if (attrVal && attrVal.values.length > 0) {
            attributes[ad.name] = String(attrVal.values[0])
          }
        }
        await apiWriteObject({
          meta_class: obj.meta_class,
          class: obj.class,
          attributes,
          id: obj.id,
        } as unknown as { meta_class: string; class: string; attributes: Record<string, unknown> });
      } else {
        await apiWriteAttribute(obj.class, obj.id, attrName, value);
      }
      const refreshed = await apiReadObject(obj.id);
      setDetailCache((prev) => ({ ...prev, [obj.id]: refreshed }));
      addToast('success', `Attribut "${attrName}" mis à jour`);
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    }
    setInlineEdit(null);
  };

  // --- Save joint edit ---
  const saveJointEdit = async () => {
    if (!jointEdit) return;
    const obj = objects.find((o) => o.id === jointEdit.objectId);
    if (!obj) return;
    const detail = detailCache[obj.id];
    if (!detail) return;

    const def = getClassDef(obj.meta_class, obj.class);
    const attributes: Record<string, unknown> = {};
    if (def) {
      for (const attrDef of def.attributes) {
        const attrVal = detail.attributes.find((a) => a.name === attrDef.name);
        if (attrDef.name === jointEdit.attrName) {
          if (jointEdit.attrDef.type === 'joint-1-1' && jointEdit.selected.length > 0) {
            attributes[attrDef.name] = { joint_id: jointEdit.selected[0] };
          } else if (jointEdit.attrDef.type === 'joint-1-n' && jointEdit.selected.length > 0) {
            attributes[attrDef.name] = jointEdit.selected.map((id) => ({ joint_id: id }));
          }
        } else if (attrDef.type === 'joint-1-1' || attrDef.type === 'joint-1-n') {
          if (attrVal) {
            const jointIds = attrVal.values.filter((v): v is { joint_id: number } => typeof v === 'object' && 'joint_id' in v);
            if (jointIds.length > 0) attributes[attrDef.name] = jointIds.length === 1 ? jointIds[0] : jointIds;
          }
        } else {
          if (attrVal && attrVal.values.length > 0) attributes[attrDef.name] = String(attrVal.values[0]);
        }
      }
    }

    try {
      await apiWriteObject({
        meta_class: obj.meta_class,
        class: obj.class,
        attributes,
        id: obj.id,
      } as unknown as { meta_class: string; class: string; attributes: Record<string, unknown> });
      const refreshed = await apiReadObject(obj.id);
      setDetailCache((prev) => ({ ...prev, [obj.id]: refreshed }));
      addToast('success', `Jointure "${jointEdit.attrName}" mise à jour`);
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    }
    setJointEdit(null);
  };

  // --- Quick-create dans un champ joint ---
  const startQuickCreate = (attrName: string, targetClass: string, context: 'modal' | 'jointEdit') => {
    const def = classes.find((c) => c.class === targetClass);
    if (!def) return;
    const attrs: Record<string, string> = {};
    for (const a of def.attributes) {
      if (a.type !== 'joint-1-1' && a.type !== 'joint-1-n') attrs[a.name] = '';
    }
    setQuickCreate({ attrName, targetClass, targetMetaClass: def.meta_class, attrs, context });
  };

  const handleQuickCreateSave = async () => {
    if (!quickCreate) return;
    const def = classes.find((c) => c.class === quickCreate.targetClass);
    if (!def) return;
    const attributes: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(quickCreate.attrs)) {
      if (v !== '') attributes[k] = v;
    }
    try {
      const res = await apiWriteObject({
        meta_class: quickCreate.targetMetaClass,
        class: quickCreate.targetClass,
        attributes,
      });
      addToast('success', `${quickCreate.targetClass} créé (id: ${res.id})`);
      // Refresh objects list
      const newObjects = await apiReadObjects();
      setObjects(newObjects);
      // Load detail for new object
      const detail = await apiReadObject(res.id);
      setDetailCache((prev) => ({ ...prev, [res.id]: detail }));
      setCandidateLabels((prev) => ({ ...prev, [res.id]: `${resolveDisplayName(detail)} (#${res.id})` }));
      // Auto-select the new object in the joint
      if (quickCreate.context === 'modal') {
        setJointValues((prev) => ({
          ...prev,
          [quickCreate.attrName]: [...(prev[quickCreate.attrName] || []), res.id],
        }));
      } else if (quickCreate.context === 'jointEdit' && jointEdit) {
        setJointEdit({ ...jointEdit, selected: [...jointEdit.selected, res.id] });
      }
      setQuickCreate(null);
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur création');
    }
  };

  const renderQuickCreateForm = () => {
    if (!quickCreate) return null;
    const def = classes.find((c) => c.class === quickCreate.targetClass);
    if (!def) return null;
    const scalarAttrs = def.attributes.filter((a) => a.type !== 'joint-1-1' && a.type !== 'joint-1-n');
    return (
      <div style={{ marginTop: 8, padding: '10px 12px', border: '1px dashed var(--color-accent)', borderRadius: 6, background: 'rgba(233,69,96,0.05)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-accent)' }}>Créer un {quickCreate.targetClass}</span>
          <button onClick={() => setQuickCreate(null)} style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', fontSize: 14 }}>✕</button>
        </div>
        {scalarAttrs.map((a) => (
          <div key={a.name} style={{ marginBottom: 6 }}>
            <input
              type={a.type === 'integer' || a.type === 'float' ? 'number' : 'text'}
              step={a.type === 'float' ? '0.01' : undefined}
              placeholder={a.name + (a.constraint ? ` (${a.constraint})` : '')}
              value={quickCreate.attrs[a.name] || ''}
              onChange={(e) => setQuickCreate({ ...quickCreate, attrs: { ...quickCreate.attrs, [a.name]: e.target.value } })}
              style={{ width: '100%', padding: '5px 8px', fontSize: 12, background: 'var(--color-bg)', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: 4, boxSizing: 'border-box' }}
            />
          </div>
        ))}
        <button className="btn btn-primary" style={{ fontSize: 11, padding: '4px 12px', marginTop: 2 }} onClick={handleQuickCreateSave}>Créer</button>
      </div>
    );
  };

  const renderQuickCreateButton = (attr: AttributeDefinition, context: 'modal' | 'jointEdit') => {
    const targetClasses = attr.classes || [];
    if (targetClasses.length === 0) return null;
    if (quickCreate && quickCreate.attrName === attr.name && quickCreate.context === context) {
      return renderQuickCreateForm();
    }
    if (targetClasses.length === 1) {
      return (
        <div style={{ marginTop: 6 }}>
          <button onClick={() => startQuickCreate(attr.name, targetClasses[0], context)}
            style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: 12, padding: 0, textDecoration: 'underline' }}
          >+ Créer un {targetClasses[0]}</button>
        </div>
      );
    }
    return (
      <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {targetClasses.map((cls) => (
          <button key={cls} onClick={() => startQuickCreate(attr.name, cls, context)}
            style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: 12, padding: 0, textDecoration: 'underline' }}
          >+ Créer un {cls}</button>
        ))}
      </div>
    );
  };

  const metaClassOptions = [...new Set(classes.map((c) => c.meta_class))];
  const classOptions = classes.filter((c) => c.meta_class === newMetaClass);

  // --- Render ---
  return (
    <div>
      {/* Header + filtres */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>
            {selectedMetaClass ? (
              <span className="badge badge-meta">{selectedMetaClass}</span>
            ) : (
              'Tous les objets'
            )}
            {' '}<span style={{ fontSize: 13, color: 'var(--color-text-muted)', fontWeight: 400 }}>
              — {filtered.length} résultat(s)
            </span>
          </h2>
        </div>

        {selectedMetaClass && availableClasses.length > 0 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
            {availableClasses.map((c) => (
              <button
                key={c.class}
                className={`btn ${visibleClasses.has(c.class) ? 'btn-primary' : 'btn-secondary'}`}
                style={{ fontSize: 12, padding: '4px 14px' }}
                onClick={() => toggleClassFilter(c.class)}
              >
                {c.class}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Modal création / édition */}
      {showCreate && (
        <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) closeModal(); }}>
          <div className="modal">
            <div className="modal-header">
              <h3>{editingObjectId
                ? `Modifier « ${detailCache[editingObjectId] ? resolveDisplayName(detailCache[editingObjectId]) : ''} » (#${editingObjectId})`
                : 'Créer un objet'}</h3>
              <button className="modal-close" onClick={closeModal}>✕</button>
            </div>

            {!editingObjectId && !selectedMetaClass && (
              <div className="form-group">
                <label>Meta-classe</label>
                <select value={newMetaClass} onChange={(e) => handleSelectNewClass(e.target.value, '')}>
                  <option value="">-- Sélectionner --</option>
                  {metaClassOptions.map((mc) => <option key={mc} value={mc}>{mc}</option>)}
                </select>
              </div>
            )}

            {!editingObjectId && (selectedMetaClass && !selectedClass) && (
              <div className="form-group">
                <label>Classe</label>
                <select value={newClass} onChange={(e) => handleSelectNewClass(newMetaClass, e.target.value)}>
                  <option value="">-- Sélectionner --</option>
                  {classOptions.map((c) => <option key={c.class} value={c.class}>{c.class}</option>)}
                </select>
              </div>
            )}

            {(editingObjectId || selectedClass) && (
              <div className="form-group">
                <label>Classe</label>
                <input type="text" value={newClass} disabled />
              </div>
            )}

            {selectedClassDef && selectedClassDef.attributes.map((attr) => {
              if (attr.type === 'joint-1-1') {
                const candidates = getCandidates(attr, editingObjectId);
                const selected = jointValues[attr.name] || [];
                return (
                  <div className="form-group" key={attr.name}>
                    <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>(joint 1:1 — {attr.domain})</span></label>
                    <select
                      value={selected[0] ?? ''}
                      onChange={(e) => setJointValues({ ...jointValues, [attr.name]: e.target.value ? [Number(e.target.value)] : [] })}
                    >
                      <option value="">-- Aucun --</option>
                      {candidates.map((c) => <option key={c.id} value={c.id}>{getCandidateLabel(c)}</option>)}
                    </select>
                    {renderQuickCreateButton(attr, 'modal')}
                  </div>
                );
              }
              if (attr.type === 'joint-1-n') {
                const candidates = getCandidates(attr, editingObjectId);
                const selected = jointValues[attr.name] || [];
                const available = candidates.filter((c) => !selected.includes(c.id));
                const selectedObjs = candidates.filter((c) => selected.includes(c.id));
                return (
                  <div className="form-group" key={attr.name}>
                    <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>(joint 1:N — {attr.domain})</span></label>
                    <div style={{ display: 'flex', gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--color-text-muted)' }}>Disponibles ({available.length})</div>
                        <div style={{ border: '1px solid var(--color-border)', borderRadius: 6, maxHeight: 160, overflowY: 'auto', background: 'var(--color-bg-card)' }}>
                          {available.length === 0 && <div style={{ padding: 8, fontSize: 12, color: 'var(--color-text-muted)', textAlign: 'center' }}>Aucun disponible</div>}
                          {available.map((c) => (
                            <div key={c.id} onClick={() => setJointValues({ ...jointValues, [attr.name]: [...selected, c.id] })}
                              style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid var(--color-border)', transition: 'background 0.15s' }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(99,102,241,0.1)')}
                              onMouseLeave={(e) => (e.currentTarget.style.background = '')}
                            >{getCandidateLabel(c)} <span style={{ float: 'right', color: 'var(--color-primary)' }}>→</span></div>
                          ))}
                        </div>
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--color-text-muted)' }}>Sélectionnés ({selectedObjs.length})</div>
                        <div style={{ border: '1px solid var(--color-border)', borderRadius: 6, maxHeight: 160, overflowY: 'auto', background: 'var(--color-bg-card)' }}>
                          {selectedObjs.length === 0 && <div style={{ padding: 8, fontSize: 12, color: 'var(--color-text-muted)', textAlign: 'center' }}>Aucun sélectionné</div>}
                          {selectedObjs.map((c) => (
                            <div key={c.id} onClick={() => setJointValues({ ...jointValues, [attr.name]: selected.filter((id) => id !== c.id) })}
                              style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid var(--color-border)', transition: 'background 0.15s' }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(239,68,68,0.1)')}
                              onMouseLeave={(e) => (e.currentTarget.style.background = '')}
                            ><span style={{ float: 'left', color: '#ef4444', marginRight: 6 }}>←</span> {getCandidateLabel(c)}</div>
                          ))}
                        </div>
                      </div>
                    </div>
                    {renderQuickCreateButton(attr, 'modal')}
                  </div>
                );
              }
              if (attr.type === 'file' || attr.type === 'image' || attr.type === 'csv') {
                const currentDetail = editingObjectId ? detailCache[editingObjectId] : undefined;
                const currentAttrVal = currentDetail?.attributes.find((a) => a.name === attr.name);
                const currentPointer = currentAttrVal && currentAttrVal.values.length > 0
                  ? parseFilePointer(currentAttrVal.values[0])
                  : null;
                const picked = newFileUploads[attr.name];
                const pickedRef = newFileReferences[attr.name];

                // Logo d'objet (plan-mark3.md action 4, point 2) : aperçu
                // cliquable (ouvre directement le sélecteur de fichier,
                // pas de bouton séparé) + sélecteur de réutilisation d'un
                // logo existant par référence - comportement réservé à
                // l'attribut réservé "logo" (convention de modèle), les
                // autres attributs file/image/csv gardent le rendu
                // générique ci-dessous.
                if (attr.name === 'logo' && attr.type === 'image') {
                  const ext = currentPointer ? fileExtensionOf(currentPointer.filename) : '';
                  const hasInlinePreview = !!(editingObjectId && currentPointer && !picked && !pickedRef
                    && (ext === 'jpg' || ext === 'jpeg' || ext === 'png'));
                  const refKey = (r: LogoEntry) => `${r.class}:${r.object_id}:${r.attribute}:${r.version}`;
                  return (
                    <div className="form-group" key={attr.name}>
                      <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>(logo — {attr.domain})</span></label>
                      <div
                        onClick={() => logoInputRefs.current[attr.name]?.click()}
                        title="Cliquer pour changer le logo"
                        style={{
                          width: 80, height: 80, borderRadius: 8, cursor: 'pointer',
                          border: '1px dashed var(--color-border)', display: 'flex',
                          alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
                          background: 'var(--color-bg)', textAlign: 'center',
                        }}
                      >
                        {hasInlinePreview ? (
                          <ImagePreview objectId={editingObjectId as number} attribute={attr.name} version={currentPointer!.version} />
                        ) : picked ? (
                          <span style={{ fontSize: 11, color: 'var(--color-accent)', padding: 4 }}>{picked.name}</span>
                        ) : pickedRef ? (
                          <span style={{ fontSize: 11, color: 'var(--color-accent)', padding: 4 }}>{pickedRef.filename}</span>
                        ) : currentPointer ? (
                          <span style={{ fontSize: 11, color: 'var(--color-text-muted)', padding: 4 }}>{currentPointer.filename}</span>
                        ) : (
                          <span style={{ fontSize: 24, color: 'var(--color-text-muted)' }}>+</span>
                        )}
                      </div>
                      <input
                        ref={(el) => { logoInputRefs.current[attr.name] = el; }}
                        type="file"
                        accept=".jpg,.jpeg,.png,.svg"
                        style={{ display: 'none' }}
                        onChange={(e) => {
                          const file = e.target.files?.[0] || null;
                          setNewFileUploads({ ...newFileUploads, [attr.name]: file });
                          if (file) setNewFileReferences({ ...newFileReferences, [attr.name]: null });
                        }}
                      />
                      {availableLogos.length > 0 && (
                        <div style={{ marginTop: 6 }}>
                          <label style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>…ou réutiliser un logo existant :</label>
                          <select
                            value={pickedRef ? refKey(pickedRef) : ''}
                            onChange={(e) => {
                              const val = e.target.value;
                              if (!val) { setNewFileReferences({ ...newFileReferences, [attr.name]: null }); return; }
                              const entry = availableLogos.find((l) => refKey(l) === val) || null;
                              setNewFileReferences({ ...newFileReferences, [attr.name]: entry });
                              if (entry) setNewFileUploads({ ...newFileUploads, [attr.name]: null });
                            }}
                            style={{ fontSize: 12, marginTop: 2, width: '100%' }}
                          >
                            <option value="">-- Aucun --</option>
                            {availableLogos.map((l) => (
                              <option key={refKey(l)} value={refKey(l)}>{l.display_name} — {l.filename}</option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>
                  );
                }

                return (
                  <div className="form-group" key={attr.name}>
                    <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>({attr.type} — {attr.domain})</span></label>
                    {currentPointer && !picked && (
                      <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
                        Fichier actuel : {currentPointer.filename}
                      </div>
                    )}
                    <input
                      type="file"
                      accept={attr.type === 'image' ? '.jpg,.jpeg,.png,.svg' : attr.type === 'csv' ? '.csv' : undefined}
                      onChange={(e) => setNewFileUploads({ ...newFileUploads, [attr.name]: e.target.files?.[0] || null })}
                    />
                    {picked && (
                      <div style={{ fontSize: 12, color: 'var(--color-accent)', marginTop: 4 }}>
                        Nouveau fichier sélectionné : {picked.name} (remplacera la version actuelle à l'enregistrement)
                      </div>
                    )}
                  </div>
                );
              }
              if (attr.type === 'datasource') {
                // Pointeur vers un objet d'une meta-classe datasource_*
                // dédiée (plan-mark3.md action 9) : sélecteur d'objet
                // cible, même mécanisme que joint-1-1 (getCandidates/
                // getCandidateLabel), mais stocké dans newAttrs (string)
                // comme un attribut scalaire ordinaire - pas dans
                // jointValues, la valeur backend est value_string (un id),
                // jamais la colonne physique joint_id.
                const candidates = getCandidates(attr, editingObjectId);
                const current = newAttrs[attr.name] || '';
                return (
                  <div className="form-group" key={attr.name}>
                    <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>(datasource — {attr.domain})</span></label>
                    <select
                      value={current}
                      onChange={(e) => setNewAttrs({ ...newAttrs, [attr.name]: e.target.value })}
                    >
                      <option value="">-- Aucun --</option>
                      {candidates.map((c) => <option key={c.id} value={c.id}>{getCandidateLabel(c)}</option>)}
                    </select>
                  </div>
                );
              }
              if (attr.type === 'select') {
                // Liste fixe de valeurs (plan-mark3.md action 7) : dropdown
                // au lieu du champ texte générique, option vide ajoutée si
                // aucune valeur courante n'est sélectionnée.
                const options = attr.values || [];
                const current = newAttrs[attr.name] || '';
                return (
                  <div className="form-group" key={attr.name}>
                    <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>({attr.type} — {attr.domain})</span></label>
                    <select
                      value={current}
                      onChange={(e) => setNewAttrs({ ...newAttrs, [attr.name]: e.target.value })}
                    >
                      {!current && <option value="">-- Choisir --</option>}
                      {options.map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  </div>
                );
              }
              if (attr.type === 'secret') {
                // Valeur sensible (plan-mark3.md action 8) : saisie masquée,
                // jamais pré-remplie avec la vraie valeur (newAttrs déjà
                // forcé à '' à l'ouverture du formulaire d'édition, voir
                // handleEditObject) - comportement d'un formulaire classique
                // de changement de mot de passe. Pas de bouton reveal ici
                // (seulement via l'API, réservée global-admin).
                return (
                  <div className="form-group" key={attr.name}>
                    <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>({attr.type} — {attr.domain})</span></label>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={newAttrs[attr.name] || ''}
                      onChange={(e) => setNewAttrs({ ...newAttrs, [attr.name]: e.target.value })}
                      placeholder={editingObjectId ? 'Laisser vide pour ne pas modifier' : ''}
                    />
                  </div>
                );
              }
              if (attr.type === 'boolean') {
                // Case à cocher (plan-mark3.md action 19) : état local
                // newAttrs toujours une chaîne "true"/"false" comme les
                // autres types scalaires (newAttrs: Record<string, string>,
                // cohérent avec handleEditObject/handleSelectNewClass) -
                // reconverti en booléen JSON natif uniquement à l'envoi
                // (handleSave), jamais stocké comme bool dans ce state local.
                const checked = newAttrs[attr.name] === 'true';
                return (
                  <div className="form-group" key={attr.name}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => setNewAttrs({ ...newAttrs, [attr.name]: e.target.checked ? 'true' : 'false' })}
                      />
                      {attr.name} <span style={{ color: 'var(--color-text-muted)' }}>({attr.type} — {attr.domain})</span>
                    </label>
                  </div>
                );
              }
              return (
                <div className="form-group" key={attr.name}>
                  <label>{attr.name} <span style={{ color: 'var(--color-text-muted)' }}>({attr.type} — {attr.domain})</span></label>
                  <input
                    type={attr.type === 'integer' || attr.type === 'float' ? 'number' : 'text'}
                    step={attr.type === 'float' ? '0.01' : undefined}
                    value={newAttrs[attr.name] || ''}
                    onChange={(e) => setNewAttrs({ ...newAttrs, [attr.name]: e.target.value })}
                    placeholder={attr.constraint ? `Format: ${attr.constraint}` : ''}
                  />
                </div>
              );
            })}

            {/* RBAC multi-tenant (action 11) : un tenant-admin à un seul
                tenant est auto-tagué côté backend sans rien à faire ici
                (cas simple visé par la conception) ; ce sélecteur ne
                s'affiche que pour le cas secondaire multi-tenant, en
                création uniquement. */}
            {!editingObjectId && authInfo.isTenantAdmin && authInfo.tenants.length > 1 && (
              <div className="form-group">
                <label>Tenant</label>
                <select value={objectTenant} onChange={(e) => setObjectTenant(e.target.value)}>
                  <option value="">-- Sélectionner --</option>
                  {authInfo.tenants.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            )}

            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeModal}>Annuler</button>
              <button className="btn btn-primary" onClick={handleSave}>
                {editingObjectId ? 'Enregistrer' : 'Créer'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal édition jointure (depuis clic cellule) */}
      {jointEdit && (
        <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setJointEdit(null); }}>
          <div className="modal">
            <div className="modal-header">
              <h3>Modifier « {jointEdit.attrName} » — {detailCache[jointEdit.objectId] ? resolveDisplayName(detailCache[jointEdit.objectId]) : `#${jointEdit.objectId}`}</h3>
              <button className="modal-close" onClick={() => setJointEdit(null)}>✕</button>
            </div>

            {jointEdit.attrDef.type === 'joint-1-1' ? (
              <div className="form-group">
                <label>{jointEdit.attrName} <span style={{ color: 'var(--color-text-muted)' }}>(joint 1:1)</span></label>
                <select
                  value={jointEdit.selected[0] ?? ''}
                  onChange={(e) => setJointEdit({ ...jointEdit, selected: e.target.value ? [Number(e.target.value)] : [] })}
                >
                  <option value="">-- Aucun --</option>
                  {getCandidates(jointEdit.attrDef, jointEdit.objectId).map((c) => (
                    <option key={c.id} value={c.id}>{getCandidateLabel(c)}</option>
                  ))}
                </select>
                {renderQuickCreateButton(jointEdit.attrDef, 'jointEdit')}
              </div>
            ) : (
              <div className="form-group">
                <label>{jointEdit.attrName} <span style={{ color: 'var(--color-text-muted)' }}>(joint 1:N)</span></label>
                <div style={{ display: 'flex', gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--color-text-muted)' }}>
                      Disponibles ({getCandidates(jointEdit.attrDef, jointEdit.objectId).filter((c) => !jointEdit.selected.includes(c.id)).length})
                    </div>
                    <div style={{ border: '1px solid var(--color-border)', borderRadius: 6, maxHeight: 200, overflowY: 'auto', background: 'var(--color-bg-card)' }}>
                      {getCandidates(jointEdit.attrDef, jointEdit.objectId).filter((c) => !jointEdit.selected.includes(c.id)).map((c) => (
                        <div key={c.id}
                          onClick={() => setJointEdit({ ...jointEdit, selected: [...jointEdit.selected, c.id] })}
                          style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid var(--color-border)', transition: 'background 0.15s' }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(99,102,241,0.1)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = '')}
                        >{getCandidateLabel(c)} <span style={{ float: 'right', color: 'var(--color-primary)' }}>→</span></div>
                      ))}
                    </div>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--color-text-muted)' }}>
                      Sélectionnés ({jointEdit.selected.length})
                    </div>
                    <div style={{ border: '1px solid var(--color-border)', borderRadius: 6, maxHeight: 200, overflowY: 'auto', background: 'var(--color-bg-card)' }}>
                      {jointEdit.selected.length === 0 && <div style={{ padding: 8, fontSize: 12, color: 'var(--color-text-muted)', textAlign: 'center' }}>Aucun sélectionné</div>}
                      {getCandidates(jointEdit.attrDef, jointEdit.objectId).filter((c) => jointEdit.selected.includes(c.id)).map((c) => (
                        <div key={c.id}
                          onClick={() => setJointEdit({ ...jointEdit, selected: jointEdit.selected.filter((id) => id !== c.id) })}
                          style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid var(--color-border)', transition: 'background 0.15s' }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(239,68,68,0.1)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = '')}
                        ><span style={{ float: 'left', color: '#ef4444', marginRight: 6 }}>←</span> {getCandidateLabel(c)}</div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {jointEdit.attrDef.type === 'joint-1-n' && renderQuickCreateButton(jointEdit.attrDef, 'jointEdit')}

            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setJointEdit(null)}>Annuler</button>
              <button className="btn btn-primary" onClick={saveJointEdit}>Enregistrer</button>
            </div>
          </div>
        </div>
      )}

      {/* Tableaux groupés par classe */}
      {Object.entries(grouped).map(([groupKey, group]) => {
        const classDef = getClassDef(group.meta_class, group.class);
        const attrDefs = classDef ? classDef.attributes : [];
        const attrNames = attrDefs.map((a) => a.name);
        const isExpanded = expandedGroups.has(groupKey);
        const isLoading = group.objects.some((o) => loadingIds.has(o.id));
        const groupFilter = (groupFilters[groupKey] || '').trim().toLowerCase();
        const visibleObjects = groupFilter
          ? group.objects.filter((obj) => rowMatchesFilter(obj, attrNames, attrDefs, groupFilter))
          : group.objects;

        return (
          <div className="card" key={groupKey}>
            <div
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
              onClick={() => toggleGroup(groupKey)}
            >
              <h2 style={{ margin: 0 }}>
                {!selectedMetaClass && <span className="badge badge-meta" style={{ marginRight: 8 }}>{group.meta_class}</span>}
                <span className="badge badge-class">{group.class}</span>
                <span style={{ fontSize: 13, color: 'var(--color-text-muted)', fontWeight: 400, marginLeft: 12 }}>({group.objects.length})</span>
              </h2>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {!readOnly && <button
                  className="btn btn-primary"
                  style={{ fontSize: 12, padding: '3px 10px', lineHeight: '1.4' }}
                  onClick={(e) => { e.stopPropagation(); handleSelectNewClass(group.meta_class, group.class); setEditingObjectId(null); setShowCreate(true); }}
                  title={`Ajouter un ${group.class}`}
                >+</button>}
                <span style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>{isExpanded ? '▲' : '▼'}</span>
              </div>
            </div>

            {isExpanded && (
              <div className="table-container" style={{ marginTop: 12 }}>
                {isLoading && <p style={{ fontSize: 13, color: 'var(--color-text-muted)', padding: 8 }}>Chargement des attributs...</p>}
                <input
                  type="text"
                  placeholder="Filtrer les lignes..."
                  value={groupFilters[groupKey] || ''}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setGroupFilters((prev) => ({ ...prev, [groupKey]: e.target.value }))}
                  style={{ width: '100%', marginBottom: 8, padding: '4px 8px', fontSize: 13, background: 'var(--color-bg)', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: 4 }}
                />
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      {attrNames.map((name) => <th key={name}>{name}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleObjects.map((obj) => {
                      const detail = detailCache[obj.id];
                      return (
                        <tr key={obj.id}
                          onDoubleClick={() => { if (!readOnly) handleEditObject(obj); }}
                          style={{ cursor: readOnly ? 'default' : 'pointer' }}
                          title={readOnly ? '' : 'Double-clic pour modifier l\'objet'}
                        >
                          <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                            {obj.id}
                            {obj.tenants && obj.tenants.length > 0 && (
                              <span className="badge" style={{ marginLeft: 6, fontSize: 10 }} title="Tenants">{obj.tenants.join(', ')}</span>
                            )}
                            {!readOnly && (
                              <button
                                onClick={(e) => { e.stopPropagation(); handleDeleteObject(obj); }}
                                title="Supprimer cet objet"
                                style={{ marginLeft: 6, background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', fontSize: 11, padding: 0, textDecoration: 'underline' }}
                              >suppr.</button>
                            )}
                          </td>
                          {attrNames.map((name) => {
                            const isInlineEditing = inlineEdit?.objectId === obj.id && inlineEdit?.attrName === name;
                            const attrDef = attrDefs.find((a) => a.name === name);
                            const isJoint11 = attrDef?.type === 'joint-1-1';
                            const isJoint1N = attrDef?.type === 'joint-1-n';
                            const isSelect = attrDef?.type === 'select';
                            const isDatasource = attrDef?.type === 'datasource';
                            const isBoolean = attrDef?.type === 'boolean';

                            if (isInlineEditing && isDatasource) {
                              const candidates = getCandidates({ classes: attrDef?.classes, name: attrDef?.name }, obj.id);
                              return (
                                <td key={name} style={{ padding: 2 }}>
                                  <select
                                    autoFocus
                                    value={inlineEdit.value}
                                    onChange={(e) => {
                                      setInlineEdit({ ...inlineEdit, value: e.target.value });
                                    }}
                                    onBlur={saveInlineEdit}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Escape') setInlineEdit(null);
                                    }}
                                    style={{ width: '100%', padding: '4px 6px', fontSize: 13, background: 'var(--color-bg)', color: 'var(--color-text)', border: '2px solid var(--color-accent)', borderRadius: 4, outline: 'none' }}
                                  >
                                    <option value="">-- Aucun --</option>
                                    {candidates.map((c) => <option key={c.id} value={c.id}>{getCandidateLabel(c)}</option>)}
                                  </select>
                                </td>
                              );
                            }

                            if (isInlineEditing && isSelect) {
                              return (
                                <td key={name} style={{ padding: 2 }}>
                                  <select
                                    autoFocus
                                    value={inlineEdit.value}
                                    onChange={(e) => {
                                      setInlineEdit({ ...inlineEdit, value: e.target.value });
                                    }}
                                    onBlur={saveInlineEdit}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Escape') setInlineEdit(null);
                                    }}
                                    style={{ width: '100%', padding: '4px 6px', fontSize: 13, background: 'var(--color-bg)', color: 'var(--color-text)', border: '2px solid var(--color-accent)', borderRadius: 4, outline: 'none' }}
                                  >
                                    <option value="">-- Aucun --</option>
                                    {(attrDef?.values || []).map((v: string) => <option key={v} value={v}>{v}</option>)}
                                  </select>
                                </td>
                              );
                            }

                            if (isInlineEditing && isJoint11) {
                              const candidates = getCandidates({ classes: attrDef?.classes, name: attrDef?.name }, obj.id);
                              return (
                                <td key={name} style={{ padding: 2 }}>
                                  <select
                                    autoFocus
                                    value={inlineEdit.value}
                                    onChange={(e) => {
                                      setInlineEdit({ ...inlineEdit, value: e.target.value });
                                    }}
                                    onBlur={saveInlineEdit}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Escape') setInlineEdit(null);
                                    }}
                                    style={{ width: '100%', padding: '4px 6px', fontSize: 13, background: 'var(--color-bg)', color: 'var(--color-text)', border: '2px solid var(--color-accent)', borderRadius: 4, outline: 'none' }}
                                  >
                                    <option value="">-- Aucun --</option>
                                    {candidates.map((c) => <option key={c.id} value={c.id}>{getCandidateLabel(c)}</option>)}
                                  </select>
                                </td>
                              );
                            }

                            if (isInlineEditing && isBoolean) {
                              // Case à cocher (plan-mark3.md action 19) : édition
                              // inline de cellule - rappel explicite de la
                              // conception, oubliée une première fois à l'action 7
                              // (select) sur ce même emplacement, corrigée en
                              // itération 2. onChange met juste à jour inlineEdit
                              // (comme select/joint-1-1 ci-dessus), onBlur commet
                              // via saveInlineEdit -> apiWriteAttribute (chemin
                              // URL, valeur "true"/"false" en texte, acceptée par
                              // _coerce_typed_value au même titre qu'un bool JSON
                              // natif - backend/routes/routes_write.py).
                              return (
                                <td key={name} style={{ padding: 2 }}>
                                  <input
                                    type="checkbox"
                                    autoFocus
                                    checked={inlineEdit.value === 'true'}
                                    onChange={(e) => setInlineEdit({ ...inlineEdit, value: e.target.checked ? 'true' : 'false' })}
                                    onBlur={saveInlineEdit}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Escape') setInlineEdit(null);
                                      if (e.key === 'Enter') saveInlineEdit();
                                    }}
                                  />
                                </td>
                              );
                            }

                            if (isInlineEditing && !isJoint11 && !isJoint1N && !isSelect && !isDatasource && !isBoolean) {
                              return (
                                <td key={name} style={{ padding: 2 }}>
                                  <input
                                    autoFocus
                                    type={attrDef?.type === 'integer' || attrDef?.type === 'float' ? 'number' : 'text'}
                                    step={attrDef?.type === 'float' ? '0.01' : undefined}
                                    value={inlineEdit.value}
                                    onChange={(e) => setInlineEdit({ ...inlineEdit, value: e.target.value })}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') saveInlineEdit();
                                      if (e.key === 'Escape') setInlineEdit(null);
                                    }}
                                    onBlur={saveInlineEdit}
                                    style={{ width: '100%', padding: '4px 6px', fontSize: 13, background: 'var(--color-bg)', color: 'var(--color-text)', border: '2px solid var(--color-accent)', borderRadius: 4, outline: 'none' }}
                                  />
                                </td>
                              );
                            }

                            if (!detail) {
                              return <td key={name} style={{ color: 'var(--color-text-muted)' }}>…</td>;
                            }
                            const attr = detail.attributes.find((a) => a.name === name);
                            const isEmpty = !attr || attr.values.length === 0;
                            // file/image/csv (plan-mark3.md action 3) et
                            // secret (plan-mark3.md action 8) : pas d'édition
                            // inline de cellule (cf. handleCellClick).
                            const isFileType = attrDef?.type === 'file' || attrDef?.type === 'image' || attrDef?.type === 'csv';
                            const isSecretType = attrDef?.type === 'secret';
                            const isNonInlineEditable = isFileType || isSecretType;
                            return (
                              <td key={name}
                                onClick={(e) => { if (!readOnly && !isNonInlineEditable) { e.stopPropagation(); handleCellClick(obj, name); } }}
                                style={{ cursor: readOnly || isNonInlineEditable ? 'default' : 'pointer', transition: 'background 0.15s' }}
                                onMouseEnter={(e) => { if (!readOnly && !isNonInlineEditable) e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = ''; }}
                                title={readOnly || isNonInlineEditable ? '' : (isJoint1N ? 'Clic pour modifier la jointure' : 'Clic pour modifier')}
                              >
                                {isEmpty ? (
                                  <span style={{ color: 'var(--color-text-muted)' }}>—</span>
                                ) : isFileType && attrDef ? (
                                  <FileAttributeValueDisplay objectId={obj.id} attrDef={attrDef} value={String(attr!.values[0])} />
                                ) : isDatasource ? (
                                  // Stocké en value_string (un id, jamais la colonne
                                  // physique joint_id - plan-mark3.md action 9) :
                                  // ré-enveloppé en {joint_id} pour réutiliser tel
                                  // quel la résolution de label existante de formatValue.
                                  attr!.values.map((v, j) => <span key={j} style={{ marginRight: 6 }}>{formatValue({ joint_id: Number(v) })}</span>)
                                ) : isBoolean ? (
                                  // Rendu lecture (plan-mark3.md action 19) : case à
                                  // cocher désactivée plutôt que le texte brut
                                  // "true"/"false" - cohérent avec le rendu édition
                                  // (modal et inline) du même type juste au-dessus.
                                  <input type="checkbox" checked={attr!.values[0] === 'true'} disabled />
                                ) : (
                                  attr!.values.map((v, j) => <span key={j} style={{ marginRight: 6 }}>{formatValue(v)}</span>)
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}

      {filtered.length === 0 && Object.keys(grouped).length === 0 && (
        <div className="card">
          <p style={{ textAlign: 'center', color: 'var(--color-text-muted)', margin: 0 }}>Aucun objet trouvé</p>
        </div>
      )}

      {/* Toast stack */}
      {toasts.length > 0 && (
        <div className="toast-container">
          {toasts.map((t) => (
            <div key={t.id} className={`toast toast-${t.type}${t.fading ? ' toast-exit' : ''}`}>
              {t.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

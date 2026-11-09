import { useEffect, useState, useCallback, useRef } from 'react';
import { apiReadObjects, apiReadObject, apiWriteObject, apiWriteAttribute, apiReadClasses } from '../api';
import type { ObjectSummary, ObjectDetail, ClassInfo, AttributeDefinition } from '../types';

interface NavigationPageProps {
  selectedMetaClass: string | null;
  selectedClass: string | null;
  readOnly: boolean;
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

export default function NavigationPage({ selectedMetaClass, selectedClass, readOnly }: NavigationPageProps) {
  const [objects, setObjects] = useState<ObjectSummary[]>([]);
  const [detailCache, setDetailCache] = useState<Record<number, ObjectDetail>>({});
  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
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
  }, [selectedMetaClass, selectedClass, classes]);

  const availableClasses = selectedMetaClass
    ? classes.filter((c) => c.meta_class === selectedMetaClass)
    : [];

  const filtered = objects.filter((o) => {
    if (selectedMetaClass && o.meta_class !== selectedMetaClass) return false;
    if (selectedMetaClass && visibleClasses.size > 0 && !visibleClasses.has(o.class)) return false;
    if (!selectedMetaClass && selectedClass && o.class !== selectedClass) return false;
    return true;
  });

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

  const loadCandidatesForDef = (def: ClassInfo) => {
    const jointAttrs = def.attributes.filter((a) => a.type === 'joint-1-1' || a.type === 'joint-1-n');
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
        else attrs[a.name] = '';
      }
      setNewAttrs(attrs);
      setJointValues(joints);
      loadCandidatesForDef(def);
    } else {
      setNewAttrs({});
      setJointValues({});
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
      } else {
        attrs[attrDef.name] = attrVal && attrVal.values.length > 0
          ? String(attrVal.values[0])
          : '';
      }
    }
    setNewAttrs(attrs);
    setJointValues(joints);
    loadCandidatesForDef(def);
    setShowCreate(true);
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
          const ids = jointValues[attr.name];
          if (!ids || ids.length === 0) continue;
          if (attr.type === 'joint-1-1') attributes[attr.name] = { joint_id: ids[0] };
          else if (attr.type === 'joint-1-n') attributes[attr.name] = ids.map((id) => ({ joint_id: id }));
        }
      }
      const payload: Record<string, unknown> = {
        meta_class: newMetaClass,
        class: newClass,
        attributes,
      };
      if (editingObjectId) payload.id = editingObjectId;

      const res = await apiWriteObject(payload as { meta_class: string; class: string; attributes: Record<string, unknown> });
      const action = editingObjectId ? 'mis à jour' : 'créé';
      addToast('success', `Objet ${action} (id: ${res.id})`);
      closeModal();
      // Refresh
      loadObjects();
      // Invalidate detail cache for this object
      if (editingObjectId) {
        const refreshed = await apiReadObject(editingObjectId);
        setDetailCache((prev) => ({ ...prev, [editingObjectId]: refreshed }));
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
  };

  // --- Inline cell click ---
  const handleCellClick = (obj: ObjectSummary, attrName: string) => {
    const def = getClassDef(obj.meta_class, obj.class);
    if (!def) return;
    const attrDef = def.attributes.find((a) => a.name === attrName);
    if (!attrDef) return;
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
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      {attrNames.map((name) => <th key={name}>{name}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {group.objects.map((obj) => {
                      const detail = detailCache[obj.id];
                      return (
                        <tr key={obj.id}
                          onDoubleClick={() => { if (!readOnly) handleEditObject(obj); }}
                          style={{ cursor: readOnly ? 'default' : 'pointer' }}
                          title={readOnly ? '' : 'Double-clic pour modifier l\'objet'}
                        >
                          <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{obj.id}</td>
                          {attrNames.map((name) => {
                            const isInlineEditing = inlineEdit?.objectId === obj.id && inlineEdit?.attrName === name;
                            const attrDef = attrDefs.find((a) => a.name === name);
                            const isJoint11 = attrDef?.type === 'joint-1-1';
                            const isJoint1N = attrDef?.type === 'joint-1-n';

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

                            if (isInlineEditing && !isJoint11 && !isJoint1N) {
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
                            return (
                              <td key={name}
                                onClick={(e) => { if (!readOnly) { e.stopPropagation(); handleCellClick(obj, name); } }}
                                style={{ cursor: readOnly ? 'default' : 'pointer', transition: 'background 0.15s' }}
                                onMouseEnter={(e) => { if (!readOnly) e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = ''; }}
                                title={readOnly ? '' : (isJoint1N ? 'Clic pour modifier la jointure' : 'Clic pour modifier')}
                              >
                                {isEmpty ? (
                                  <span style={{ color: 'var(--color-text-muted)' }}>—</span>
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

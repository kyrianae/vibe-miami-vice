import { useEffect, useState, useCallback, useRef } from 'react';
import {
  apiReadMetaClass, apiWriteMetaClass, apiInit, apiReadClasses,
  apiGetPurgeGracePeriod, apiSetPurgeGracePeriod,
  apiGetDefaultLayers, apiSetDefaultLayers,
} from '../api';
import type { MetaClassDefinition, ClassDefinition, AttributeDefinition, ClassInfo } from '../types';
import type { AuthInfo } from '../auth';
import { CLASS_ICONS, classIconDataUri } from '../classIcons';

interface ConfigurationPageProps {
  selectedMetaClass: string | null;
  authInfo: AuthInfo;
}

// RBAC multi-tenant (plan.md action 11) : une classe est visible/éditable
// par un tenant-admin si elle n'a aucun tenant déclaré (classe globale) ou
// si l'un de ses tenants correspond à l'un des siens. Pas de filtrage pour
// global-admin (ni pour la compat ascendante sans rôle RBAC reconnu, cf.
// auth.ts) : authInfo.isTenantAdmin est alors false, donc tout reste visible.
function isClassVisibleForTenant(cls: { tenants?: string[] }, authInfo: AuthInfo): boolean {
  if (!authInfo.isTenantAdmin) return true;
  const tenants = cls.tenants || [];
  return tenants.length === 0 || tenants.some((t) => authInfo.tenants.includes(t));
}

const ATTR_TYPES: AttributeDefinition['type'][] = [
  'string', 'integer', 'float', 'joint-1-1', 'joint-1-n',
  'file', 'image', 'csv', 'select', 'secret', 'datasource', 'boolean',
];

function emptyAttribute(): AttributeDefinition {
  return { domain: 'details', name: '', type: 'string' };
}

function emptyClass(): ClassDefinition {
  return { class: '', displayname: '', attributes: [emptyAttribute()] };
}

export default function ConfigurationPage({ selectedMetaClass, authInfo }: ConfigurationPageProps) {
  const [metaClassName, setMetaClassName] = useState('');
  const [classDefs, setClassDefs] = useState<ClassDefinition[]>([emptyClass()]);
  const [toasts, setToasts] = useState<{ id: number; type: 'success' | 'error'; text: string; fading: boolean }[]>([]);
  const toastIdRef = useRef(0);
  const [loading, setLoading] = useState(false);
  const [allClasses, setAllClasses] = useState<ClassInfo[]>([]);
  const [expandedClasses, setExpandedClasses] = useState<Set<number>>(new Set());
  const [purgeGraceDays, setPurgeGraceDays] = useState<string>('');
  const [purgeGraceSaving, setPurgeGraceSaving] = useState(false);
  // Layers par défaut (plan-mark3.md action 18) : fetch ouvert (pas de
  // gating admin sur le GET, cf. routes_admin.py), utilisé à la fois pour
  // l'union dans knownLayers ci-dessous et comme valeur initiale du champ
  // d'édition réservé global-admin plus bas.
  const [defaultLayersStored, setDefaultLayersStored] = useState<string[]>([]);
  const [defaultLayersDraft, setDefaultLayersDraft] = useState<string>('');
  const [defaultLayersSaving, setDefaultLayersSaving] = useState(false);

  const addToast = useCallback((type: 'success' | 'error', text: string) => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, type, text, fading: false }]);
    setTimeout(() => {
      setToasts((prev) => prev.map((t) => t.id === id ? { ...t, fading: true } : t));
      setTimeout(() => { setToasts((prev) => prev.filter((t) => t.id !== id)); }, 400);
    }, 5000);
  }, []);

  // Load all classes for joint target suggestions (filtrées par tenant pour
  // un tenant-admin, cf. isClassVisibleForTenant)
  useEffect(() => {
    apiReadClasses()
      .then((cls) => setAllClasses(cls.filter((c) => isClassVisibleForTenant(c, authInfo))))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authInfo]);

  // Purge physique différée (plan-mark2.md action 6.2) : champ réservé
  // global-admin, cf. frontend/src/auth.ts (isGlobalAdmin).
  useEffect(() => {
    if (!authInfo.isGlobalAdmin) return;
    apiGetPurgeGracePeriod()
      .then((res) => setPurgeGraceDays(String(res.value)))
      .catch(() => {});
  }, [authInfo.isGlobalAdmin]);

  const handleSavePurgeGraceDays = async () => {
    const parsed = Number(purgeGraceDays);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      addToast('error', 'La période de grâce doit être un entier strictement positif');
      return;
    }
    setPurgeGraceSaving(true);
    try {
      const res = await apiSetPurgeGracePeriod(parsed);
      setPurgeGraceDays(String(res.value));
      addToast('success', `Période de grâce de purge mise à jour : ${res.value} jour(s)`);
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    } finally {
      setPurgeGraceSaving(false);
    }
  };

  // Layers par défaut (plan-mark3.md action 18) : lecture ouverte, aucune
  // condition authInfo.isGlobalAdmin ici (contrairement à purgeGraceDays
  // ci-dessus) - cf. commentaire de apiGetDefaultLayers, nécessaire pour que
  // knownLayers (lecture seule, tous utilisateurs) voie l'union aussi.
  useEffect(() => {
    apiGetDefaultLayers()
      .then((res) => {
        setDefaultLayersStored(res.value);
        setDefaultLayersDraft(res.value.join(', '));
      })
      .catch(() => {});
  }, []);

  const handleSaveDefaultLayers = async () => {
    const deduped = [...new Set(
      defaultLayersDraft.split(',').map((t) => t.trim()).filter(Boolean)
    )];
    if (deduped.length === 0) {
      addToast('error', 'La liste des layers par défaut ne peut pas être vide');
      return;
    }
    setDefaultLayersSaving(true);
    try {
      const res = await apiSetDefaultLayers(deduped);
      setDefaultLayersStored(res.value);
      setDefaultLayersDraft(res.value.join(', '));
      addToast('success', `Layers par défaut mis à jour : ${res.value.join(', ')}`);
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    } finally {
      setDefaultLayersSaving(false);
    }
  };

  const allClassNames = [...new Set([
    ...allClasses.map((c) => c.class),
    ...classDefs.map((c) => c.class).filter(Boolean),
  ])];

  // Registre des layers (plan-mark3.md action 14, point 3 ; union avec
  // default_layers ajoutée action 18) : pas de meta-classe dédiée - union
  // dédupliquée (trim) des `layers` de toutes les classes du modèle chargé
  // (allClasses, déjà filtré par tenant) ET des layers par défaut persistés
  // en base (defaultLayersStored, toujours proposés même sans classe),
  // affichée en lecture pour que l'utilisateur réutilise un nom de layer
  // existant au lieu de le retaper/fauter dans le champ texte libre.
  const knownLayers = [...new Set([
    ...allClasses.flatMap((c) => (c.layers || []).map((l) => l.trim()).filter(Boolean)),
    ...defaultLayersStored,
  ])].sort();

  // Load definition when selecting a meta_class
  useEffect(() => {
    if (!selectedMetaClass) {
      setMetaClassName('');
      setClassDefs([emptyClass()]);
      setExpandedClasses(new Set([0]));
      return;
    }
    setLoading(true);
    apiReadMetaClass(selectedMetaClass)
      .then((data) => {
        // RBAC multi-tenant (action 11) : un tenant-admin ne voit/n'édite
        // que les classes dans son périmètre - voir isClassVisibleForTenant.
        // Limitation connue (documentée dans le rapport worker) : si la
        // meta-classe contient aussi des classes hors périmètre, elles
        // disparaissent de cette vue d'édition ; le backend refuse alors la
        // sauvegarde complète (write_metaclass vérifie que les classes
        // existantes restent dans le périmètre avant tout remplacement),
        // donc aucune perte de données silencieuse, mais l'édition de ce
        // type de meta-classe mixte n'est pas possible depuis cette UI.
        const visibleClasses = data.classes.filter((c) => isClassVisibleForTenant(c, authInfo));
        setMetaClassName(data.meta_class);
        setClassDefs(visibleClasses.length > 0 ? visibleClasses : [emptyClass()]);
        setExpandedClasses(new Set(visibleClasses.map((_, i) => i)));
      })
      .catch(() => {
        setMetaClassName(selectedMetaClass);
        setClassDefs([emptyClass()]);
        setExpandedClasses(new Set([0]));
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMetaClass, authInfo]);

  // --- Class operations ---
  const updateClass = (idx: number, patch: Partial<ClassDefinition>) => {
    setClassDefs((prev) => prev.map((c, i) => i === idx ? { ...c, ...patch } : c));
  };

  const addClass = () => {
    setClassDefs((prev) => [...prev, emptyClass()]);
    setExpandedClasses((prev) => new Set([...prev, classDefs.length]));
  };

  const removeClass = (idx: number) => {
    if (classDefs.length <= 1) return;
    setClassDefs((prev) => prev.filter((_, i) => i !== idx));
    setExpandedClasses((prev) => {
      const n = new Set<number>();
      prev.forEach((v) => { if (v < idx) n.add(v); else if (v > idx) n.add(v - 1); });
      return n;
    });
    // Indices classes/attributs décalés : purge brouillons select pour éviter désync.
    setSelectValueDrafts({});
  };

  const toggleClass = (idx: number) => {
    setExpandedClasses((prev) => {
      const n = new Set(prev);
      n.has(idx) ? n.delete(idx) : n.add(idx);
      return n;
    });
  };

  // --- Attribute operations ---
  const updateAttribute = (classIdx: number, attrIdx: number, patch: Partial<AttributeDefinition>) => {
    setClassDefs((prev) => prev.map((c, ci) => {
      if (ci !== classIdx) return c;
      const attrs = c.attributes.map((a, ai) => ai === attrIdx ? { ...a, ...patch } : a);
      return { ...c, attributes: attrs };
    }));
  };

  const addAttribute = (classIdx: number) => {
    setClassDefs((prev) => prev.map((c, ci) =>
      ci === classIdx ? { ...c, attributes: [...c.attributes, emptyAttribute()] } : c
    ));
  };

  const removeAttribute = (classIdx: number, attrIdx: number) => {
    setClassDefs((prev) => prev.map((c, ci) => {
      if (ci !== classIdx) return c;
      if (c.attributes.length <= 1) return c;
      return { ...c, attributes: c.attributes.filter((_, ai) => ai !== attrIdx) };
    }));
    // Indices attributs décalés : purge brouillons select pour éviter désync.
    setSelectValueDrafts({});
  };

  const moveAttribute = (classIdx: number, attrIdx: number, dir: -1 | 1) => {
    setClassDefs((prev) => prev.map((c, ci) => {
      if (ci !== classIdx) return c;
      const newIdx = attrIdx + dir;
      if (newIdx < 0 || newIdx >= c.attributes.length) return c;
      const attrs = [...c.attributes];
      [attrs[attrIdx], attrs[newIdx]] = [attrs[newIdx], attrs[attrIdx]];
      return { ...c, attributes: attrs };
    }));
    // Indices attributs permutés : purge brouillons select pour éviter désync.
    setSelectValueDrafts({});
  };

  // --- Joint classes management (aussi utilisé par 'datasource', même
  // mécanisme de ciblage de classes, cf. AttributeDefinition.classes) ---
  const toggleJointClass = (classIdx: number, attrIdx: number, cls: string) => {
    setClassDefs((prev) => prev.map((c, ci) => {
      if (ci !== classIdx) return c;
      const attrs = c.attributes.map((a, ai) => {
        if (ai !== attrIdx) return a;
        const current = a.classes || [];
        const next = current.includes(cls) ? current.filter((x) => x !== cls) : [...current, cls];
        return { ...a, classes: next };
      });
      return { ...c, attributes: attrs };
    }));
  };

  // --- Select values management (type 'select') ---
  // Saisie en cours par ligne d'attribut, tant que non validée par "Ajouter"
  // (clé "classIdx-attrIdx" -> texte du champ, purement local à l'IHM).
  const [selectValueDrafts, setSelectValueDrafts] = useState<Record<string, string>>({});
  const selectDraftKey = (classIdx: number, attrIdx: number) => `${classIdx}-${attrIdx}`;

  const addSelectValue = (classIdx: number, attrIdx: number, attr: AttributeDefinition) => {
    const key = selectDraftKey(classIdx, attrIdx);
    const val = (selectValueDrafts[key] || '').trim();
    setSelectValueDrafts((prev) => ({ ...prev, [key]: '' }));
    if (!val) return;
    const current = attr.values || [];
    if (current.includes(val)) { addToast('error', `Valeur "${val}" déjà présente`); return; }
    updateAttribute(classIdx, attrIdx, { values: [...current, val] });
  };

  // Limite connue assumée : re-saisir ensuite la même valeur à l'identique (avant
  // sauvegarde) ne restaure pas son layer_map purgé ci-dessous - edge case rare, pas
  // traité pour éviter de complexifier le state tracking.
  const removeSelectValue = (classIdx: number, attrIdx: number, attr: AttributeDefinition, val: string) => {
    const patch: Partial<AttributeDefinition> = { values: (attr.values || []).filter((v) => v !== val) };
    // Purge la clé layer_map correspondante (plan-mark3.md action 18) : une
    // valeur retirée de `values` ne doit pas laisser un layer_map[val]
    // orphelin (censé rester un sous-ensemble de `values`).
    if (attr.layer_map && val in attr.layer_map) {
      const nextMap = { ...attr.layer_map };
      delete nextMap[val];
      patch.layer_map = Object.keys(nextMap).length > 0 ? nextMap : undefined;
    }
    updateAttribute(classIdx, attrIdx, patch);
  };

  // --- Layer map management (plan-mark3.md action 18, specifications/
  // 07-roadmap.md §10.15) : un sélecteur de layers par valeur de `values`,
  // réutilisation telle quelle du pattern déjà en place pour `cls.layers`
  // (action 14) - texte libre comma-séparé, pas de nouveau composant de
  // sélection de layers. Liste vide (layersText vide) = pas de layer pour
  // cette valeur, retire la clé plutôt que de garder un tableau vide.
  const updateValueLayerMap = (classIdx: number, attrIdx: number, attr: AttributeDefinition, value: string, layersText: string) => {
    const layers = layersText.split(',').map((t) => t.trim()).filter(Boolean);
    const nextMap = { ...(attr.layer_map || {}) };
    if (layers.length > 0) nextMap[value] = layers;
    else delete nextMap[value];
    updateAttribute(classIdx, attrIdx, { layer_map: Object.keys(nextMap).length > 0 ? nextMap : undefined });
  };

  // --- Save ---
  const handleSave = async () => {
    // Clean up: remove empty classes array items, clean attributes. Déplacé
    // avant le test de `metaClassName` vide (plan-mark3.md action 22,
    // specifications/07-roadmap.md §10.19) : il faut connaître le nombre de
    // classes réelles du formulaire pour décider du défaut auto ci-dessous.
    const cleanClasses: ClassDefinition[] = classDefs
      .filter((c) => c.class.trim())
      .map((c) => {
        const cleanAttrs: AttributeDefinition[] = c.attributes
          .filter((a) => a.name.trim())
          .map((a) => {
            const clean: AttributeDefinition = { domain: a.domain, name: a.name, type: a.type };
            if (a.type === 'joint-1-1' || a.type === 'joint-1-n' || a.type === 'datasource') {
              clean.classes = a.classes || [];
            }
            if (a.type === 'select') {
              const cleanValues = a.values || [];
              clean.values = cleanValues;
              // layer_map (plan-mark3.md action 18) : persiste uniquement les
              // clés encore présentes dans `values` au moment de la sauvegarde
              // (garde-fou front, le schéma ne l'impose pas strictement -
              // cf. model/schema.json) et seulement si non vide.
              if (a.layer_map) {
                const filteredMap = Object.fromEntries(
                  Object.entries(a.layer_map).filter(([k]) => cleanValues.includes(k))
                );
                if (Object.keys(filteredMap).length > 0) clean.layer_map = filteredMap;
              }
            }
            if (a.type === 'csv' && a.separator) {
              clean.separator = a.separator;
            }
            if (a.constraint) clean.constraint = a.constraint;
            if (a.sql_constraint) clean.sql_constraint = a.sql_constraint;
            return clean;
          });
        const def: ClassDefinition = { class: c.class, attributes: cleanAttrs };
        if (c.displayname) def.displayname = c.displayname;
        if (c.tenants && c.tenants.length > 0) def.tenants = c.tenants;
        if (c.layers && c.layers.length > 0) def.layers = c.layers;
        if (c.icon) def.icon = c.icon;
        return def;
      });

    // meta_class auto-déduite (plan-mark3.md action 22, specifications/
    // 07-roadmap.md §10.19) : si le nom de meta-classe est vide, on le
    // déduit du nom de la classe UNIQUEMENT si le formulaire ne porte
    // qu'une seule classe réelle (cleanClasses) - sinon ambiguïté (0 ou 2+
    // classes), on garde le blocage explicite déjà en place.
    let effectiveMetaClassName = metaClassName.trim();
    if (!effectiveMetaClassName) {
      if (cleanClasses.length === 1) {
        effectiveMetaClassName = cleanClasses[0].class;
        setMetaClassName(effectiveMetaClassName);
      } else {
        addToast('error', 'Le nom de la meta-classe est requis');
        return;
      }
    }

    // Validation front légère : le schéma JSON backend exige juste la
    // présence des clés 'classes'/'values' (required), pas qu'elles soient
    // non vides - un tableau vide passerait donc la validation silencieusement
    // et ne casserait qu'au moment, bien plus tard et bien moins clair, d'une
    // tentative de saisie de valeur sur l'objet (cf. backend/routes/
    // routes_write.py, _coerce_typed_value / _apply_attribute_diff). On
    // bloque donc ici, tant que l'utilisateur n'a pas renseigné de cible.
    for (const c of cleanClasses) {
      for (const a of c.attributes) {
        if ((a.type === 'joint-1-1' || a.type === 'joint-1-n' || a.type === 'datasource')
          && (!a.classes || a.classes.length === 0)) {
          addToast('error', `Attribut "${a.name}" de la classe "${c.class}" : au moins une classe cible requise (type ${a.type})`);
          return;
        }
        if (a.type === 'select' && (!a.values || a.values.length === 0)) {
          addToast('error', `Attribut "${a.name}" de la classe "${c.class}" : au moins une valeur requise (type select)`);
          return;
        }
      }
    }

    // Unicité du nom de classe (plan-mark3.md action 22, specifications/
    // 07-roadmap.md §10.19) : une classe de cleanClasses ne doit pas déjà
    // exister dans une AUTRE meta-classe que celle en cours d'édition. Set
    // scopé construit ici (allClassNames, ligne ~137, ne convient pas : il
    // fusionne aussi classDefs courant, donc une classe du formulaire s'y
    // retrouverait toujours - faux conflit garanti). Quand selectedMetaClass
    // est null (création), aucune exclusion n'a lieu. Garde-fou UX - le
    // contrôle réel (contournement direct de l'API) est fait côté backend,
    // voir _check_class_name_unique dans routes_write.py.
    const otherClassNames = new Set(
      allClasses
        .filter((c) => c.meta_class !== selectedMetaClass)
        .map((c) => c.class)
    );
    for (const c of cleanClasses) {
      if (otherClassNames.has(c.class)) {
        addToast('error', `La classe "${c.class}" existe déjà dans une autre meta-classe`);
        return;
      }
    }

    const data: MetaClassDefinition = { meta_class: effectiveMetaClassName, classes: cleanClasses };

    try {
      const res = await apiWriteMetaClass(data);
      addToast('success', `Meta-classe "${res.meta_class}" ${res.action === 'created' ? 'créée' : 'mise à jour'}`);
      apiReadClasses().then(setAllClasses).catch(() => {});
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    }
  };

  const handleInit = async () => {
    try {
      const res = await apiInit();
      addToast('success', `Initialisé : ${res.loaded.join(', ')}`);
      apiReadClasses().then(setAllClasses).catch(() => {});
    } catch (e: unknown) {
      addToast('error', e instanceof Error ? e.message : 'Erreur');
    }
  };

  // Styles inline
  const attrRowStyle: React.CSSProperties = {
    display: 'grid',
    gridTemplateColumns: '120px 1fr 130px 1fr auto',
    gap: 8,
    alignItems: 'start',
    padding: '8px 0',
    borderBottom: '1px solid var(--color-border)',
  };

  const smallInput: React.CSSProperties = {
    width: '100%',
    padding: '5px 8px',
    fontSize: 12,
    background: 'var(--color-bg)',
    color: 'var(--color-text)',
    border: '1px solid var(--color-border)',
    borderRadius: 4,
    boxSizing: 'border-box',
  };

  const smallSelect: React.CSSProperties = {
    ...smallInput,
    cursor: 'pointer',
  };

  const iconBtn: React.CSSProperties = {
    background: 'none',
    border: 'none',
    color: 'var(--color-text-muted)',
    cursor: 'pointer',
    fontSize: 14,
    padding: '2px 4px',
    transition: 'color 0.15s',
  };

  return (
    <div>
      {/* Header */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>Configuration des définitions</h2>
          <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={handleInit}>
            Charger depuis model/
          </button>
        </div>
      </div>

      {/* Purge physique différée (plan-mark2.md action 6.2) - global-admin uniquement */}
      {authInfo.isGlobalAdmin && (
        <div className="card">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Période de grâce avant purge physique (jours)</label>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="number"
                min={1}
                step={1}
                value={purgeGraceDays}
                onChange={(e) => setPurgeGraceDays(e.target.value)}
                style={{ maxWidth: 120 }}
              />
              <button className="btn btn-secondary" style={{ fontSize: 12 }}
                onClick={handleSavePurgeGraceDays} disabled={purgeGraceSaving}
              >
                Enregistrer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Layers par défaut (plan-mark3.md action 18) - global-admin
          uniquement, même structure que le bloc purge grace period
          ci-dessus. Champ texte comma-separated : réutilise tel quel le
          pattern déjà en place pour éditer le champ "Layers" d'une classe
          (ligne ~519 plus bas, action 14) - pas de nouveau composant. */}
      {authInfo.isGlobalAdmin && (
        <div className="card">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Layers par défaut <span style={{ color: 'var(--color-text-muted)' }}>(toujours sélectionnables, même sans classe qui les utilise)</span></label>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="text"
                value={defaultLayersDraft}
                onChange={(e) => setDefaultLayersDraft(e.target.value)}
                placeholder="ex: applicatif, infra, organisationnel"
                style={{ flex: 1 }}
              />
              <button className="btn btn-secondary" style={{ fontSize: 12 }}
                onClick={handleSaveDefaultLayers} disabled={defaultLayersSaving}
              >
                Enregistrer
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="card"><p>Chargement...</p></div>
      ) : (
        <>
          {/* Meta-class name */}
          <div className="card">
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Meta-classe</label>
              <input
                type="text"
                value={metaClassName}
                onChange={(e) => setMetaClassName(e.target.value)}
                placeholder="Nom de la meta-classe"
                disabled={!!selectedMetaClass}
              />
            </div>
          </div>

          {/* Layers connus (plan-mark3.md action 14, point 3) : union
              dédupliquée de tous les layers du modèle chargé, lecture seule
              - sert de référentiel visuel pour le champ "Layers" ci-dessous,
              aucune édition inline de cette liste (le layer se retape/se
              retire via le champ texte de la classe concernée). */}
          {knownLayers.length > 0 && (
            <div className="card">
              <label style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                Layers connus <span style={{ color: 'var(--color-text-muted)' }}>(toutes classes confondues)</span>
              </label>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {knownLayers.map((l) => (
                  <span key={l} className="badge" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                    {l}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Classes */}
          {classDefs.map((cls, classIdx) => {
            const isExpanded = expandedClasses.has(classIdx);
            return (
              <div className="card" key={classIdx}>
                {/* Class header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                  onClick={() => toggleClass(classIdx)}
                >
                  <h3 style={{ margin: 0, fontSize: 15 }}>
                    <span className="badge badge-class" style={{ marginRight: 8 }}>{cls.class || '(nouvelle classe)'}</span>
                    <span style={{ fontSize: 12, color: 'var(--color-text-muted)', fontWeight: 400 }}>
                      {cls.attributes.filter((a) => a.name).length} attribut(s)
                    </span>
                  </h3>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {classDefs.length > 1 && (
                      <button style={{ ...iconBtn, color: '#ef4444' }}
                        onClick={(e) => { e.stopPropagation(); removeClass(classIdx); }}
                        title="Supprimer cette classe"
                      >✕</button>
                    )}
                    <span style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>{isExpanded ? '▲' : '▼'}</span>
                  </div>
                </div>

                {isExpanded && (
                  <div style={{ marginTop: 12 }}>
                    {/* Class name + displayname + tenants + layers */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
                      <div className="form-group" style={{ marginBottom: 0 }}>
                        <label style={{ fontSize: 12 }}>Nom de la classe</label>
                        <input type="text" value={cls.class}
                          onChange={(e) => updateClass(classIdx, { class: e.target.value })}
                          placeholder="ex: personne_physique" style={smallInput} />
                      </div>
                      <div className="form-group" style={{ marginBottom: 0 }}>
                        <label style={{ fontSize: 12 }}>Displayname <span style={{ color: 'var(--color-text-muted)' }}>(template)</span></label>
                        <input type="text" value={cls.displayname || ''}
                          onChange={(e) => updateClass(classIdx, { displayname: e.target.value })}
                          placeholder="ex: {{prenom}} {{nom}}" style={smallInput} />
                      </div>
                      <div className="form-group" style={{ marginBottom: 0 }}>
                        <label style={{ fontSize: 12 }}>Tenants <span style={{ color: 'var(--color-text-muted)' }}>(vide = tous)</span></label>
                        <input type="text" value={(cls.tenants || []).join(', ')}
                          onChange={(e) => updateClass(classIdx, {
                            tenants: e.target.value.split(',').map((t) => t.trim()).filter(Boolean),
                          })}
                          placeholder="ex: tenant1, tenant2" style={smallInput} />
                      </div>
                      <div className="form-group" style={{ marginBottom: 0 }}>
                        <label style={{ fontSize: 12 }}>Layers <span style={{ color: 'var(--color-text-muted)' }}>(vide = toujours visible)</span></label>
                        <input type="text" value={(cls.layers || []).join(', ')}
                          onChange={(e) => updateClass(classIdx, {
                            layers: e.target.value.split(',').map((t) => t.trim()).filter(Boolean),
                          })}
                          placeholder="ex: physique, reseau" style={smallInput} />
                      </div>
                    </div>

                    {/* Icône de classe (plan-mark3.md action 4, point 1) :
                        jeu fixe embarqué (classIcons.tsx), pas d'upload
                        libre - utilisée en dernier recours (après un
                        éventuel logo d'objet) dans DiagramPage/
                        NavigationPage. */}
                    <div className="form-group">
                      <label style={{ fontSize: 12 }}>
                        Icône par défaut <span style={{ color: 'var(--color-text-muted)' }}>(jeu fixe, optionnel)</span>
                      </label>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          onClick={() => updateClass(classIdx, { icon: undefined })}
                          title="Aucune icône"
                          style={{
                            width: 36, height: 36, borderRadius: 6, cursor: 'pointer',
                            border: !cls.icon ? '2px solid var(--color-accent)' : '1px solid var(--color-border)',
                            background: 'var(--color-bg)', color: 'var(--color-text-muted)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11,
                          }}
                        >✕</button>
                        {CLASS_ICONS.map((ic) => (
                          <button
                            type="button"
                            key={ic.id}
                            onClick={() => updateClass(classIdx, { icon: ic.id })}
                            title={ic.label}
                            style={{
                              width: 36, height: 36, borderRadius: 6, cursor: 'pointer', padding: 4,
                              border: cls.icon === ic.id ? '2px solid var(--color-accent)' : '1px solid var(--color-border)',
                              background: cls.icon === ic.id ? 'rgba(233,69,96,0.12)' : 'var(--color-bg)',
                            }}
                          >
                            <img src={classIconDataUri(ic.svg)} alt={ic.label} style={{ width: '100%', height: '100%' }} />
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Attributes header */}
                    <div style={{ ...attrRowStyle, borderBottom: '2px solid var(--color-border)', fontWeight: 600, fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, padding: '4px 0' }}>
                      <span>Domaine</span>
                      <span>Nom</span>
                      <span>Type</span>
                      <span>Options</span>
                      <span></span>
                    </div>

                    {/* Attribute rows */}
                    {cls.attributes.map((attr, attrIdx) => (
                      <div key={attrIdx} style={attrRowStyle}>
                        <input type="text" value={attr.domain}
                          onChange={(e) => updateAttribute(classIdx, attrIdx, { domain: e.target.value })}
                          placeholder="details" style={smallInput} />
                        <input type="text" value={attr.name}
                          onChange={(e) => updateAttribute(classIdx, attrIdx, { name: e.target.value })}
                          placeholder="nom_attribut" style={smallInput} />
                        <select value={attr.type}
                          onChange={(e) => {
                            const newType = e.target.value as AttributeDefinition['type'];
                            const patch: Partial<AttributeDefinition> = { type: newType };
                            if (newType === 'joint-1-1' || newType === 'joint-1-n' || newType === 'datasource') {
                              patch.classes = attr.classes || [];
                            } else if (newType === 'select') {
                              patch.values = attr.values || [];
                            }
                            updateAttribute(classIdx, attrIdx, patch);
                          }}
                          style={smallSelect}
                        >
                          {ATTR_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                        <div>
                          {(attr.type === 'joint-1-1' || attr.type === 'joint-1-n' || attr.type === 'datasource') ? (
                            // Classes cibles : bloc partagé par joint-1-1/joint-1-n/datasource
                            // (même champ attr.classes, même toggle - cf. types.ts).
                            <div>
                              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>Classes cibles :</div>
                              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                {allClassNames.map((cn) => (
                                  <button key={cn}
                                    onClick={() => toggleJointClass(classIdx, attrIdx, cn)}
                                    style={{
                                      fontSize: 11, padding: '2px 8px', borderRadius: 4, cursor: 'pointer',
                                      border: '1px solid var(--color-border)',
                                      background: (attr.classes || []).includes(cn) ? 'var(--color-accent)' : 'var(--color-bg)',
                                      color: (attr.classes || []).includes(cn) ? '#fff' : 'var(--color-text)',
                                      transition: 'all 0.15s',
                                    }}
                                  >{cn}</button>
                                ))}
                              </div>
                            </div>
                          ) : attr.type === 'select' ? (
                            // Liste fixe de valeurs autorisées (attr.values).
                            <div>
                              <div style={{ display: 'flex', gap: 4 }}>
                                <input type="text"
                                  value={selectValueDrafts[selectDraftKey(classIdx, attrIdx)] || ''}
                                  onChange={(e) => {
                                    const key = selectDraftKey(classIdx, attrIdx);
                                    const val = e.target.value;
                                    setSelectValueDrafts((prev) => ({ ...prev, [key]: val }));
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') { e.preventDefault(); addSelectValue(classIdx, attrIdx, attr); }
                                  }}
                                  placeholder="Nouvelle valeur" style={{ ...smallInput, fontSize: 11 }} />
                                <button type="button" onClick={() => addSelectValue(classIdx, attrIdx, attr)}
                                  style={{
                                    ...iconBtn, fontSize: 11, padding: '4px 8px',
                                    border: '1px solid var(--color-border)', borderRadius: 4, whiteSpace: 'nowrap',
                                  }}
                                >Ajouter</button>
                              </div>
                              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                                {(attr.values || []).map((v, i: number) => (
                                  <span key={`${v}-${i}`}
                                    style={{
                                      display: 'inline-flex', alignItems: 'center', gap: 4,
                                      fontSize: 11, padding: '2px 6px', borderRadius: 4,
                                      border: '1px solid var(--color-border)', background: 'var(--color-bg)',
                                    }}
                                  >
                                    {v}
                                    <button type="button" onClick={() => removeSelectValue(classIdx, attrIdx, attr, v)}
                                      style={{ ...iconBtn, fontSize: 10, padding: 0 }} title="Retirer"
                                    >✕</button>
                                  </span>
                                ))}
                              </div>
                              {/* Layer dynamique par valeur (plan-mark3.md action 18,
                                  specifications/07-roadmap.md §10.15) : même pattern
                                  texte comma-séparé que "Layers" de classe (action 14,
                                  ci-dessus) - un champ par valeur de `values`. Présence
                                  de layer_map (même vide côté UI tant qu'aucune ligne
                                  n'est remplie) marque l'attribut comme pilotant le
                                  layer effectif, pas de case à cocher séparée. */}
                              {(attr.values || []).length > 0 && (
                                <div style={{ marginTop: 8 }}>
                                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
                                    Layer(s) par valeur <span>(optionnel - vide = pas de layer dynamique pour cette valeur)</span> :
                                  </div>
                                  {(attr.values || []).map((v, i: number) => (
                                    <div key={`lm-${v}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                                      <span style={{ fontSize: 11, minWidth: 70, color: 'var(--color-text-muted)' }}>{v}</span>
                                      <input type="text"
                                        value={(attr.layer_map?.[v] || []).join(', ')}
                                        onChange={(e) => updateValueLayerMap(classIdx, attrIdx, attr, v, e.target.value)}
                                        placeholder="ex: physique" style={{ ...smallInput, fontSize: 11 }} />
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ) : attr.type === 'csv' ? (
                            // Séparateur optionnel (défaut ',' affiché en placeholder, pas forcé en state).
                            <input type="text" value={attr.separator || ''}
                              onChange={(e) => updateAttribute(classIdx, attrIdx, { separator: e.target.value || undefined })}
                              placeholder="," style={{ ...smallInput, fontSize: 11 }} />
                          ) : (attr.type === 'file' || attr.type === 'image' || attr.type === 'secret' || attr.type === 'boolean') ? (
                            // boolean (plan-mark3.md action 19) : type le plus simple du jeu,
                            // aucun champ requis supplémentaire (pas de values/classes/separator) -
                            // même traitement "Aucune option" que file/image/secret.
                            <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Aucune option</span>
                          ) : (
                            // Fallback string/integer/float.
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                              <input type="text" value={attr.constraint || ''}
                                onChange={(e) => updateAttribute(classIdx, attrIdx, { constraint: e.target.value || undefined })}
                                placeholder="Regexp" style={{ ...smallInput, fontSize: 11 }} />
                              <input type="text" value={attr.sql_constraint || ''}
                                onChange={(e) => updateAttribute(classIdx, attrIdx, { sql_constraint: e.target.value || undefined })}
                                placeholder="SQL constraint" style={{ ...smallInput, fontSize: 11 }} />
                              {attr.type === 'string' && (
                                // Autosuggest (plan-mark3.md action 20,
                                // specifications/07-roadmap.md §10.17) :
                                // réservé au type 'string', même convention
                                // que values/layer_map/separator ci-dessus.
                                <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--color-text-muted)' }}>
                                  <input type="checkbox" checked={!!attr.autosuggest}
                                    onChange={(e) => updateAttribute(classIdx, attrIdx, { autosuggest: e.target.checked || undefined })}
                                  />
                                  Suggestion auto (valeurs déjà saisies)
                                </label>
                              )}
                            </div>
                          )}
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center' }}>
                          <button style={iconBtn} onClick={() => moveAttribute(classIdx, attrIdx, -1)}
                            disabled={attrIdx === 0} title="Monter">▲</button>
                          <button style={iconBtn} onClick={() => moveAttribute(classIdx, attrIdx, 1)}
                            disabled={attrIdx === cls.attributes.length - 1} title="Descendre">▼</button>
                          {cls.attributes.length > 1 && (
                            <button style={{ ...iconBtn, color: '#ef4444' }}
                              onClick={() => removeAttribute(classIdx, attrIdx)}
                              title="Supprimer">✕</button>
                          )}
                        </div>
                      </div>
                    ))}

                    {/* Add attribute button */}
                    <button onClick={() => addAttribute(classIdx)}
                      style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: 12, padding: '8px 0', textDecoration: 'underline' }}
                    >+ Ajouter un attribut</button>
                  </div>
                )}
              </div>
            );
          })}

          {/* Add class + Save */}
          <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button onClick={addClass}
              style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: 13, textDecoration: 'underline' }}
            >+ Ajouter une classe</button>
            <button className="btn btn-primary" onClick={handleSave}>Sauvegarder</button>
          </div>
        </>
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

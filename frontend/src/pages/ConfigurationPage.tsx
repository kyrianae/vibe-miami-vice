import { useEffect, useState, useCallback, useRef } from 'react';
import {
  apiReadMetaClass, apiWriteMetaClass, apiInit, apiReadClasses,
  apiGetPurgeGracePeriod, apiSetPurgeGracePeriod,
} from '../api';
import type { MetaClassDefinition, ClassDefinition, AttributeDefinition, ClassInfo } from '../types';
import type { AuthInfo } from '../auth';

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

const ATTR_TYPES: AttributeDefinition['type'][] = ['string', 'integer', 'float', 'joint-1-1', 'joint-1-n'];

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

  const allClassNames = [...new Set([
    ...allClasses.map((c) => c.class),
    ...classDefs.map((c) => c.class).filter(Boolean),
  ])];

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
  };

  // --- Joint classes management ---
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

  // --- Save ---
  const handleSave = async () => {
    if (!metaClassName.trim()) {
      addToast('error', 'Le nom de la meta-classe est requis');
      return;
    }
    // Clean up: remove empty classes array items, clean attributes
    const cleanClasses: ClassDefinition[] = classDefs
      .filter((c) => c.class.trim())
      .map((c) => {
        const cleanAttrs: AttributeDefinition[] = c.attributes
          .filter((a) => a.name.trim())
          .map((a) => {
            const clean: AttributeDefinition = { domain: a.domain, name: a.name, type: a.type };
            if (a.type === 'joint-1-1' || a.type === 'joint-1-n') {
              clean.classes = a.classes || [];
            }
            if (a.constraint) clean.constraint = a.constraint;
            if (a.sql_constraint) clean.sql_constraint = a.sql_constraint;
            return clean;
          });
        const def: ClassDefinition = { class: c.class, attributes: cleanAttrs };
        if (c.displayname) def.displayname = c.displayname;
        if (c.tenants && c.tenants.length > 0) def.tenants = c.tenants;
        return def;
      });

    const data: MetaClassDefinition = { meta_class: metaClassName, classes: cleanClasses };

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
                    {/* Class name + displayname + tenants */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
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
                            if (newType === 'joint-1-1' || newType === 'joint-1-n') {
                              patch.classes = attr.classes || [];
                            }
                            updateAttribute(classIdx, attrIdx, patch);
                          }}
                          style={smallSelect}
                        >
                          {ATTR_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                        <div>
                          {(attr.type === 'joint-1-1' || attr.type === 'joint-1-n') ? (
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
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                              <input type="text" value={attr.constraint || ''}
                                onChange={(e) => updateAttribute(classIdx, attrIdx, { constraint: e.target.value || undefined })}
                                placeholder="Regexp" style={{ ...smallInput, fontSize: 11 }} />
                              <input type="text" value={attr.sql_constraint || ''}
                                onChange={(e) => updateAttribute(classIdx, attrIdx, { sql_constraint: e.target.value || undefined })}
                                placeholder="SQL constraint" style={{ ...smallInput, fontSize: 11 }} />
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

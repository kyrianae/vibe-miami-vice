import { useEffect, useState } from 'react';
import { apiReadClasses, apiGetDefaultLayers } from '../api';
import type { ClassInfo } from '../types';

interface SidebarProps {
  open: boolean;
  // 'dashboard' gardé dans le type uniquement pour matcher le type Page de
  // App.tsx - en pratique Sidebar n'est jamais monté quand page==='dashboard'
  // (plan-mark3.md action 15, point 2 : retrait conditionnel dans App.tsx).
  page: 'configuration' | 'navigation' | 'diagramme' | 'dashboard' | 'recherche';
  selectedMetaClass: string | null;
  selectedClass: string | null;
  onSelectMetaClass: (mc: string | null) => void;
  onSelectClass: (cls: string | null) => void;
  // Filtre layers (plan-mark3.md action 14) : multi-sélection, mécanisme
  // orthogonal à l'arbre meta_class/class ci-dessus (mono-sélection) - ne
  // touche jamais onSelectMetaClass/onSelectClass. Sur la page diagramme
  // (plan-mark3.md action 15, point 3d), pilote en plus une combo-list qui
  // remplace les chips, et narrow les deux arbres de classes.
  selectedLayers: Set<string>;
  onSelectedLayersChange: (layers: Set<string>) => void;
}

export default function Sidebar({
  open,
  page,
  selectedMetaClass,
  selectedClass,
  onSelectMetaClass,
  onSelectClass,
  selectedLayers,
  onSelectedLayersChange,
}: SidebarProps) {
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  // Filtre texte (plan-mark3.md action 15, point 3c) : une seule case,
  // partagée par les deux arbres (meta_class et layer) et par
  // ConfigurationPage (qui réutilise ce même filtre Sidebar, aucune liste
  // dédiée côté ConfigurationPage.tsx).
  const [filterText, setFilterText] = useState('');
  // Repli/dépli (plan-mark3.md action 15, point 3b) : état local distinct de
  // selectedMetaClass/selectedClass, replié par défaut (Set vide). Les deux
  // arbres ont chacun leur propre Set de clés dépliées.
  const [expandedMeta, setExpandedMeta] = useState<Set<string>>(new Set());
  const [expandedLayerGroups, setExpandedLayerGroups] = useState<Set<string>>(new Set());
  // Layers par défaut persistés en base (plan-mark3.md action 18), fetch
  // ouvert (aucune notion d'authInfo/admin dans ce composant) : toujours
  // proposés même si aucune classe chargée ne les référence encore.
  const [defaultLayers, setDefaultLayers] = useState<string[]>([]);

  useEffect(() => {
    apiReadClasses().then(setClasses).catch(() => {});
  }, [page]);

  useEffect(() => {
    apiGetDefaultLayers().then((r) => setDefaultLayers(r.value)).catch(() => {});
  }, []);

  // Liste des layers connus (plan-mark3.md action 14, point 5 ; union avec
  // default_layers ajoutée action 18) : déduite dynamiquement de toutes les
  // classes chargées, jamais affectée par le filtre texte, même source que
  // ConfigurationPage, union avec la liste persistée des layers par défaut.
  const availableLayers = [...new Set([
    ...classes.flatMap((c) => (c.layers || []).map((l) => l.trim()).filter(Boolean)),
    ...defaultLayers,
  ])].sort();

  // Filtre texte (point 3c) : sous-chaîne insensible à la casse, sur le nom
  // de classe et/ou de meta_class, appliqué aux deux arbres ci-dessous.
  const needle = filterText.trim().toLowerCase();
  const textFiltered = needle
    ? classes.filter((c) => c.class.toLowerCase().includes(needle) || c.meta_class.toLowerCase().includes(needle))
    : classes;

  // Narrow par layers sélectionnés (point 3d) : uniquement sur la page
  // diagramme, où la combo-list remplace les chips - Navigation/
  // Configuration gardent les chips et ne narrowent jamais l'arbre. Classe
  // sans layer = toujours visible (même convention que DiagramPage,
  // isClassVisibleForLayers - les deux consomment le même selectedLayers).
  const layerNarrowActive = page === 'diagramme' && selectedLayers.size > 0;
  const treeClasses = layerNarrowActive
    ? textFiltered.filter((c) => {
        const ls = (c.layers || []).map((l) => l.trim()).filter(Boolean);
        return ls.length === 0 || ls.some((l) => selectedLayers.has(l));
      })
    : textFiltered;

  // Arbre par meta_class (existant).
  const groupedByMeta: Record<string, ClassInfo[]> = {};
  for (const c of treeClasses) {
    if (!groupedByMeta[c.meta_class]) groupedByMeta[c.meta_class] = [];
    groupedByMeta[c.meta_class].push(c);
  }

  // Arbre par layer (nouveau, point 3a) : une classe apparaît dans chaque
  // groupe layer auquel elle appartient (doublons acceptés), classes sans
  // layer absentes de cette section. Sur la page diagramme avec narrow
  // actif, seuls les groupes layer sélectionnés sont construits.
  const groupedByLayer: Record<string, ClassInfo[]> = {};
  for (const c of treeClasses) {
    const layersForClass = (c.layers || []).map((l) => l.trim()).filter(Boolean);
    for (const l of layersForClass) {
      if (layerNarrowActive && !selectedLayers.has(l)) continue;
      if (!groupedByLayer[l]) groupedByLayer[l] = [];
      groupedByLayer[l].push(c);
    }
  }

  const toggleLayer = (layer: string) => {
    const next = new Set(selectedLayers);
    next.has(layer) ? next.delete(layer) : next.add(layer);
    onSelectedLayersChange(next);
  };

  const handleLayersSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    onSelectedLayersChange(new Set(Array.from(e.target.selectedOptions).map((o) => o.value)));
  };

  const toggleExpanded = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set);
    next.has(key) ? next.delete(key) : next.add(key);
    setter(next);
  };

  const handleMetaClick = (mc: string) => {
    if (selectedMetaClass === mc) {
      onSelectMetaClass(null);
      onSelectClass(null);
    } else {
      onSelectMetaClass(mc);
      onSelectClass(null);
    }
  };

  const handleClassClick = (mc: string, cls: string) => {
    onSelectMetaClass(mc);
    onSelectClass(selectedClass === cls ? null : cls);
  };

  return (
    <aside className={`sidebar ${open ? '' : 'collapsed'}`}>
      {/* Filtre texte (point 3c) : une seule case, filtre les deux arbres
          ci-dessous par sous-chaîne sur classe et/ou meta_class. */}
      <div style={{ padding: '12px 16px 0' }}>
        <input
          type="text"
          placeholder="Filtrer les classes..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          style={{ width: '100%', padding: '4px 8px', fontSize: 13, background: 'var(--color-bg)', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: 4 }}
        />
      </div>

      <h3>Types d'objets (par meta-class)</h3>
      <ul>
        <li
          className={!selectedMetaClass ? 'active' : ''}
          onClick={() => { onSelectMetaClass(null); onSelectClass(null); }}
        >
          Tous
        </li>
        {Object.entries(groupedByMeta).map(([mc, cls]) => (
          <li key={mc} style={{ padding: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', cursor: 'pointer' }}>
              <span
                onClick={() => toggleExpanded(expandedMeta, setExpandedMeta, mc)}
                style={{ width: 16, display: 'inline-block', fontSize: 10, color: 'var(--color-text-muted)' }}
                title={expandedMeta.has(mc) ? 'Replier' : 'Déplier'}
              >
                {expandedMeta.has(mc) ? '▼' : '▶'}
              </span>
              <span
                className={selectedMetaClass === mc && !selectedClass ? 'active' : ''}
                style={{ fontWeight: 600 }}
                onClick={() => handleMetaClick(mc)}
              >
                <span className="badge badge-meta">{mc}</span>
              </span>
            </div>
            {expandedMeta.has(mc) && (
              <ul style={{ paddingLeft: 16 }}>
                {cls.map((c) => (
                  <li
                    key={c.class}
                    className={selectedClass === c.class ? 'active' : ''}
                    onClick={() => handleClassClick(mc, c.class)}
                  >
                    <span className="badge badge-class">{c.class}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {/* Arbre par layer (point 3a) : classes groupées par layer, doublons
          acceptés si une classe appartient à plusieurs layers. */}
      {Object.keys(groupedByLayer).length > 0 && (
        <>
          <h3>Types d'objets (par layer)</h3>
          <ul>
            {Object.entries(groupedByLayer).map(([layer, cls]) => (
              <li key={`layer:${layer}`} style={{ padding: 0 }}>
                <div
                  style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', cursor: 'pointer' }}
                  onClick={() => toggleExpanded(expandedLayerGroups, setExpandedLayerGroups, layer)}
                >
                  <span
                    style={{ width: 16, display: 'inline-block', fontSize: 10, color: 'var(--color-text-muted)' }}
                    title={expandedLayerGroups.has(layer) ? 'Replier' : 'Déplier'}
                  >
                    {expandedLayerGroups.has(layer) ? '▼' : '▶'}
                  </span>
                  <span style={{ fontWeight: 600 }}>
                    <span className="badge">{layer}</span>
                  </span>
                </div>
                {expandedLayerGroups.has(layer) && (
                  <ul style={{ paddingLeft: 16 }}>
                    {cls.map((c) => (
                      <li
                        key={`${layer}:${c.meta_class}:${c.class}`}
                        className={selectedClass === c.class ? 'active' : ''}
                        onClick={() => handleClassClick(c.meta_class, c.class)}
                      >
                        <span className="badge badge-meta" style={{ marginRight: 4 }}>{c.meta_class}</span>
                        <span className="badge badge-class">{c.class}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Filtre layers (plan-mark3.md action 14, point 5 ; action 15, point
          3d) : sur la page diagramme, combo-list dédiée (remplace les chips
          et narrow aussi les deux arbres ci-dessus) ; sur les autres pages,
          chips togglables inchangées. */}
      {availableLayers.length > 0 && page === 'diagramme' && (
        <>
          <h3>Layers</h3>
          <div style={{ padding: '0 16px 16px' }}>
            <select
              multiple
              value={[...selectedLayers]}
              onChange={handleLayersSelectChange}
              size={Math.min(availableLayers.length, 8)}
              style={{ width: '100%', background: 'var(--color-bg)', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: 4 }}
            >
              {availableLayers.map((layer) => (
                <option key={layer} value={layer}>{layer}</option>
              ))}
            </select>
          </div>
        </>
      )}
      {availableLayers.length > 0 && page !== 'diagramme' && (
        <>
          <h3>Layers</h3>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '0 16px 16px' }}>
            {availableLayers.map((layer) => (
              <span
                key={layer}
                onClick={() => toggleLayer(layer)}
                className={`badge ${selectedLayers.has(layer) ? 'badge-meta' : ''}`}
                style={{
                  cursor: 'pointer',
                  background: selectedLayers.has(layer) ? undefined : 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                }}
                title={selectedLayers.has(layer) ? 'Retirer ce layer du filtre' : 'Ajouter ce layer au filtre'}
              >
                {layer}
              </span>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}

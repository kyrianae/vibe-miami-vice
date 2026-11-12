import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import * as echarts from 'echarts';
import { apiReadObjects, apiReadObject, apiReadClasses } from '../api';
import type { ObjectSummary, ObjectDetail, ClassInfo } from '../types';

type LayoutType = 'force' | 'circular' | 'tree';

const LAYOUT_LABELS: Record<LayoutType, string> = {
  force: '🔀 Force',
  circular: '🔵 Circulaire',
  tree: '🌳 Organigramme',
};

// Couleurs par classe (palette harmonisée)
const CLASS_COLORS = [
  '#e06c75', '#61afef', '#98c379', '#c678dd', '#e5c07b',
  '#56b6c2', '#d19a66', '#be5046', '#7ec8e3', '#f0a0c0',
];

// Nœuds masqués consécutifs max traversés pour reconstituer un lien transitif
// (A -[membres]-> B -[employeur]-> C avec B masqué = 1 nœud masqué ; avec un
// second masquage derrière C on irait jusqu'à 2). Au-delà, on arrête la
// traversée : un lien reconstitué sur une trop longue chaîne de nœuds masqués
// perd son sens visuel et risque de dégrader le rendu sur un graphe très connecté.
const MAX_HIDDEN_CHAIN_DEPTH = 2;
// Plafond du nombre total d'arêtes reconstituées traversant un même nœud
// masqué donné (toutes arêtes entrantes confondues). Sans ce plafond, un
// nœud masqué à fort fan-in/fan-out (ex. 10 entrées x 10 sorties) générerait
// une explosion combinatoire d'arêtes synthétiques qui dégraderait le rendu
// ECharts. 20 est un compromis arbitraire : assez large pour rester utile sur
// un graphe réaliste, assez bas pour ne pas noyer la vue.
const MAX_RECONSTRUCTED_EDGES_PER_HIDDEN_NODE = 20;

interface DiagramPageProps {
  selectedMetaClass: string | null;
  selectedClass: string | null;
  readOnly: boolean;
}

export default function DiagramPage({ selectedMetaClass, selectedClass, readOnly }: DiagramPageProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  const [objects, setObjects] = useState<ObjectSummary[]>([]);
  const [details, setDetails] = useState<Record<number, ObjectDetail>>({});
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [layout, setLayout] = useState<LayoutType>('force');
  const [hiddenClasses, setHiddenClasses] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  // Load all objects and classes
  useEffect(() => {
    setLoading(true);
    Promise.all([apiReadObjects(), apiReadClasses()])
      .then(([objs, cls]) => {
        setObjects(objs);
        setClasses(cls);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Load all object details
  useEffect(() => {
    if (objects.length === 0) return;
    const toLoad = objects.filter((o) => !details[o.id]);
    if (toLoad.length === 0) return;
    Promise.all(toLoad.map((o) => apiReadObject(o.id).catch(() => null)))
      .then((results) => {
        const newDetails: Record<number, ObjectDetail> = { ...details };
        for (const d of results) {
          if (d) newDetails[d.id] = d;
        }
        setDetails(newDetails);
      });
  }, [objects]); // eslint-disable-line react-hooks/exhaustive-deps

  // Display name resolver
  const resolveDisplayName = useCallback(
    (detail: ObjectDetail): string => {
      const classDef = classes.find(
        (c) => c.meta_class === detail.meta_class && c.class === detail.class
      );
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
    },
    [classes]
  );

  // Color map per class
  const classColorMap = useMemo(() => {
    const uniqueClasses = [...new Set(objects.map((o) => o.class))];
    const map: Record<string, string> = {};
    uniqueClasses.forEach((c, i) => {
      map[c] = CLASS_COLORS[i % CLASS_COLORS.length];
    });
    return map;
  }, [objects]);

  // Unique class list for filters
  const uniqueClasses = useMemo(() => {
    const all = [...new Set(objects.map((o) => o.class))];
    // Group by meta_class
    const grouped: Record<string, string[]> = {};
    for (const o of objects) {
      if (!grouped[o.meta_class]) grouped[o.meta_class] = [];
      if (!grouped[o.meta_class].includes(o.class)) grouped[o.meta_class].push(o.class);
    }
    return { all, grouped };
  }, [objects]);

  // Filter objects based on selection and hidden classes
  const filteredObjects = useMemo(() => {
    return objects.filter((o) => {
      if (selectedMetaClass && o.meta_class !== selectedMetaClass) return false;
      if (selectedClass && o.class !== selectedClass) return false;
      if (hiddenClasses.has(o.class)) return false;
      return true;
    });
  }, [objects, selectedMetaClass, selectedClass, hiddenClasses]);

  // Build graph data
  const graphData = useMemo(() => {
    const visibleIds = new Set(filteredObjects.map((o) => o.id));

    // 1. Graphe d'adjacence complet (tous les objets de `details`, toutes les
    // arêtes), construit AVANT tout filtrage de visibilité, pour permettre la
    // reconstruction de liens transitifs à travers des nœuds masqués.
    type AdjEdge = { targetId: number; attrName: string };
    const adjacency = new Map<number, AdjEdge[]>();
    for (const obj of objects) {
      const detail = details[obj.id];
      if (!detail) continue;
      const edges: AdjEdge[] = [];
      for (const attr of detail.attributes) {
        for (const val of attr.values) {
          if (typeof val === 'object' && val !== null && 'joint_id' in val) {
            edges.push({ targetId: val.joint_id, attrName: attr.name });
          }
        }
      }
      adjacency.set(obj.id, edges);
    }

    // 2. Fermeture transitive locale : depuis un nœud masqué, suit ses arêtes
    // sortantes jusqu'à atteindre des nœuds visibles. `visitedOnPath` protège
    // contre les cycles du chemin de traversée courant (même principe que
    // `in_progress` côté backend pour deref/depth, backend/app.py) — le modèle
    // comporte de vraies jointures récursives (groupe.membres -> groupe).
    const resolveVisibleTargets = (
      hiddenId: number,
      visitedOnPath: Set<number>,
      remainingHiddenDepth: number,
      budget: number
    ): number[] => {
      if (budget <= 0) return [];
      const edges = adjacency.get(hiddenId) || [];
      const result: number[] = [];
      for (const edge of edges) {
        if (result.length >= budget) break;
        const targetId = edge.targetId;
        if (visitedOnPath.has(targetId)) continue;
        if (visibleIds.has(targetId)) {
          result.push(targetId);
          continue;
        }
        if (remainingHiddenDepth <= 0) continue;
        visitedOnPath.add(targetId);
        const deeper = resolveVisibleTargets(
          targetId,
          visitedOnPath,
          remainingHiddenDepth - 1,
          budget - result.length
        );
        visitedOnPath.delete(targetId);
        for (const t of deeper) {
          if (result.length >= budget) break;
          result.push(t);
        }
      }
      return result;
    };

    const nodes: echarts.GraphNodeItemOption[] = [];
    const links: echarts.GraphEdgeItemOption[] = [];
    const categories: { name: string; itemStyle: { color: string } }[] = [];

    // Build category index
    const catIndex: Record<string, number> = {};
    const usedClasses = [...new Set(filteredObjects.map((o) => o.class))];
    usedClasses.forEach((cls, i) => {
      catIndex[cls] = i;
      categories.push({ name: cls, itemStyle: { color: classColorMap[cls] || '#888' } });
    });

    const reconstructedEdgeCountByEntryNode = new Map<number, number>();
    const addedReconstructedLinks = new Set<string>();
    const addedDirectLinks = new Set<string>();
    const hiddenEdgesToProcess: { objId: number; entryHiddenId: number }[] = [];

    // Passe 1 : nœuds + arêtes directes. Remplit entièrement `addedDirectLinks`
    // pour tous les objets visibles avant toute reconstruction (passe 2) : le
    // dédoublonnage lien direct / lien reconstitué ne doit pas dépendre de
    // l'ordre d'itération des arêtes (ex. arête masquée traitée avant l'arête
    // directe vers la même cible, issue d'un autre attribut/objet). Les arêtes
    // vers une cible masquée sont seulement collectées ici, traitées en passe 2.
    for (const obj of filteredObjects) {
      const detail = details[obj.id];
      const label = detail ? resolveDisplayName(detail) : `${obj.class} #${obj.id}`;

      nodes.push({
        id: String(obj.id),
        name: label,
        category: catIndex[obj.class] ?? 0,
        symbolSize: 40,
        itemStyle: { color: classColorMap[obj.class] || '#888' },
        label: { show: true, color: '#fff', fontSize: 11 },
      });

      const edges = adjacency.get(obj.id) || [];
      for (const edge of edges) {
        if (visibleIds.has(edge.targetId)) {
          addedDirectLinks.add(`${obj.id}=>${edge.targetId}`);
          links.push({
            source: String(obj.id),
            target: String(edge.targetId),
            label: { show: true, formatter: edge.attrName, fontSize: 9, color: 'var(--color-text-muted, #999)' },
            lineStyle: { type: 'solid' },
          });
          continue;
        }
        hiddenEdgesToProcess.push({ objId: obj.id, entryHiddenId: edge.targetId });
      }
    }

    // Passe 2 : fermeture transitive vers un/des nœud(s) visible(s) pour chaque
    // arête vers une cible masquée, `addedDirectLinks` étant désormais complet.
    for (const { objId, entryHiddenId } of hiddenEdgesToProcess) {
      const alreadyCount = reconstructedEdgeCountByEntryNode.get(entryHiddenId) || 0;
      const remainingBudget = MAX_RECONSTRUCTED_EDGES_PER_HIDDEN_NODE - alreadyCount;
      if (remainingBudget <= 0) continue;

      const visitedOnPath = new Set<number>([objId, entryHiddenId]);
      const reachable = resolveVisibleTargets(
        entryHiddenId,
        visitedOnPath,
        MAX_HIDDEN_CHAIN_DEPTH - 1,
        remainingBudget
      );

      let added = 0;
      for (const targetId of reachable) {
        const key = `${objId}=>${targetId}`;
        if (addedReconstructedLinks.has(key)) continue;
        // Un lien direct existe déjà pour cette même paire (ex. groupe/sous-groupe
        // partageant un membre direct par ailleurs) : ne pas superposer un pointillé
        // redondant par-dessus un trait plein déjà présent.
        if (addedDirectLinks.has(key)) continue;
        addedReconstructedLinks.add(key);
        links.push({
          source: String(objId),
          target: String(targetId),
          lineStyle: { type: 'dashed' },
        });
        added++;
      }
      reconstructedEdgeCountByEntryNode.set(entryHiddenId, alreadyCount + added);
    }

    return { nodes, links, categories };
  }, [filteredObjects, objects, details, resolveDisplayName, classColorMap]);

  // Toggle class visibility
  const toggleClass = (cls: string) => {
    setHiddenClasses((prev) => {
      const next = new Set(prev);
      if (next.has(cls)) next.delete(cls);
      else next.add(cls);
      return next;
    });
  };

  // Show/hide all
  const showAll = () => setHiddenClasses(new Set());
  const hideAll = () => setHiddenClasses(new Set(uniqueClasses.all));

  // Initialize and update chart
  useEffect(() => {
    if (!chartRef.current) return;

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    }

    const chart = chartInstance.current;

    // Determine layout options based on selected layout type
    const getLayoutOption = (): echarts.EChartsOption => {
      const baseOption: echarts.EChartsOption = {
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'item',
          backgroundColor: 'rgba(30,30,30,0.95)',
          borderColor: '#555',
          textStyle: { color: '#eee', fontSize: 12 },
          formatter: (params: unknown) => {
            const p = params as { dataType: string; data: { name: string; id: string }; name: string };
            if (p.dataType === 'node') {
              const obj = objects.find((o) => String(o.id) === p.data.id);
              return `<b>${p.data.name}</b><br/><em>${obj?.class || ''}</em> (#${p.data.id})`;
            }
            return p.name || '';
          },
        },
        legend: {
          data: graphData.categories.map((c) => c.name),
          orient: 'vertical',
          right: 10,
          top: 10,
          textStyle: { color: 'var(--color-text, #ccc)' },
          inactiveColor: '#555',
        },
        animationDuration: 800,
        animationEasingUpdate: 'quinticInOut',
      };

      if (layout === 'force') {
        return {
          ...baseOption,
          series: [
            {
              type: 'graph',
              layout: 'force',
              data: graphData.nodes,
              links: graphData.links,
              categories: graphData.categories,
              roam: true,
              draggable: true,
              force: {
                repulsion: 300,
                gravity: 0.1,
                edgeLength: [80, 200],
                layoutAnimation: true,
              },
              edgeSymbol: ['none', 'arrow'],
              edgeSymbolSize: [0, 8],
              lineStyle: { color: '#666', curveness: 0.15, width: 1.5 },
              emphasis: {
                focus: 'adjacency',
                lineStyle: { width: 3 },
              },
              label: { position: 'bottom', distance: 5 },
            },
          ],
        };
      }

      if (layout === 'circular') {
        return {
          ...baseOption,
          series: [
            {
              type: 'graph',
              layout: 'circular',
              data: graphData.nodes,
              links: graphData.links,
              categories: graphData.categories,
              roam: true,
              draggable: true,
              circular: { rotateLabel: true },
              edgeSymbol: ['none', 'arrow'],
              edgeSymbolSize: [0, 8],
              lineStyle: { color: '#666', curveness: 0.3, width: 1.5 },
              emphasis: {
                focus: 'adjacency',
                lineStyle: { width: 3 },
              },
              label: { position: 'bottom', distance: 5, rotate: 0 },
            },
          ],
        };
      }

      // Tree layout — use a tree series type
      // We need to convert graph to a tree structure
      // For tree type, find the root nodes (those with no incoming edges) and build hierarchy
      const incomingMap = new Set(graphData.links.map((l) => String(l.target)));
      const rootNodes = graphData.nodes.filter((n) => !incomingMap.has(String(n.id)));

      // Build adjacency for tree
      const children: Record<string, string[]> = {};
      for (const link of graphData.links) {
        const src = String(link.source);
        if (!children[src]) children[src] = [];
        children[src].push(String(link.target));
      }

      const visited = new Set<string>();
      const buildTree = (nodeId: string): unknown => {
        if (visited.has(nodeId)) return null;
        visited.add(nodeId);
        const node = graphData.nodes.find((n) => String(n.id) === nodeId);
        const childIds = children[nodeId] || [];
        const childNodes = childIds
          .map((cid) => buildTree(cid))
          .filter(Boolean);
        return {
          name: node?.name || nodeId,
          itemStyle: node?.itemStyle,
          children: childNodes.length > 0 ? childNodes : undefined,
        };
      };

      const treeRoots = rootNodes.map((n) => buildTree(String(n.id))).filter(Boolean);
      // If no root, show orphans
      const idsInTree = new Set(visited);
      const orphans = graphData.nodes
        .filter((n) => !idsInTree.has(String(n.id)))
        .map((n) => buildTree(String(n.id)))
        .filter(Boolean);
      const allRoots = [...treeRoots, ...orphans];

      const treeData = allRoots.length === 1
        ? allRoots[0]
        : { name: 'Racine', children: allRoots };

      return {
        ...baseOption,
        legend: undefined,
        series: [
          {
            type: 'tree',
            data: [treeData],
            layout: 'orthogonal',
            orient: 'TB',
            roam: true,
            symbolSize: 14,
            initialTreeDepth: -1,
            label: {
              position: 'bottom',
              verticalAlign: 'middle',
              fontSize: 11,
              color: 'var(--color-text, #ccc)',
            },
            lineStyle: { color: '#666', width: 1.5 },
            emphasis: { focus: 'descendant' },
            expandAndCollapse: true,
            animationDuration: 600,
            animationDurationUpdate: 600,
          },
        ],
      };
    };

    chart.setOption(getLayoutOption(), true);

    // Resize handler
    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    // Observe parent resize
    const ro = new ResizeObserver(() => chart.resize());
    if (chartRef.current) ro.observe(chartRef.current);

    return () => {
      window.removeEventListener('resize', handleResize);
      ro.disconnect();
    };
  }, [graphData, layout, objects]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  if (loading) {
    return (
      <div className="diagram-page">
        <div className="diagram-loading">Chargement des données…</div>
      </div>
    );
  }

  return (
    <div className="diagram-page">
      {/* Toolbar */}
      <div className="diagram-toolbar">
        <div className="diagram-toolbar-left">
          <span className="diagram-toolbar-label">Disposition :</span>
          {(Object.keys(LAYOUT_LABELS) as LayoutType[]).map((l) => (
            <button
              key={l}
              className={`diagram-layout-btn ${layout === l ? 'active' : ''}`}
              onClick={() => setLayout(l)}
            >
              {LAYOUT_LABELS[l]}
            </button>
          ))}
        </div>
        <div className="diagram-toolbar-right">
          <span className="diagram-toolbar-label">Filtres :</span>
          <button className="diagram-filter-btn small" onClick={showAll}>Tout</button>
          <button className="diagram-filter-btn small" onClick={hideAll}>Rien</button>
        </div>
      </div>

      {/* Class filter chips */}
      <div className="diagram-filters">
        {Object.entries(uniqueClasses.grouped).map(([mc, clsList]) => (
          <div key={mc} className="diagram-filter-group">
            <span className="diagram-filter-meta">{mc}</span>
            {clsList.map((cls) => (
              <button
                key={cls}
                className={`diagram-chip ${hiddenClasses.has(cls) ? 'hidden' : ''}`}
                style={{
                  borderColor: classColorMap[cls] || '#888',
                  backgroundColor: hiddenClasses.has(cls)
                    ? 'transparent'
                    : `${classColorMap[cls]}33`,
                  color: hiddenClasses.has(cls) ? '#888' : classColorMap[cls],
                }}
                onClick={() => toggleClass(cls)}
              >
                <span
                  className="diagram-chip-dot"
                  style={{ background: hiddenClasses.has(cls) ? '#555' : classColorMap[cls] }}
                />
                {cls}
                <span className="diagram-chip-count">
                  {objects.filter((o) => o.class === cls && (!selectedMetaClass || o.meta_class === selectedMetaClass)).length}
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>

      {/* Stats */}
      <div className="diagram-stats">
        {graphData.nodes.length} objets · {graphData.links.length} liens
      </div>

      {/* Chart */}
      <div ref={chartRef} className="diagram-chart" />
    </div>
  );
}

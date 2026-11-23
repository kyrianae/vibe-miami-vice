import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import * as echarts from 'echarts';
import { apiReadObjects, apiReadObject, apiReadClasses, apiReadObjectFileBlob, apiClassIconUrl } from '../api';
import { findClassIcon, classIconDataUri } from '../classIcons';
import type { ObjectSummary, ObjectDetail, ClassInfo, AttributeDefinition } from '../types';

// Cache des blobs logo résolus (même pattern que fileBlobCache,
// NavigationPage.tsx) : une version de fichier est immuable une fois
// écrite, donc une Promise par clé "<objectId>:<pointeur>" peut être
// partagée indéfiniment. Clé incluant le pointeur entier (pas seulement
// l'objectId) : invalide naturellement l'entrée dès que le pointeur change
// (nouvel upload/nouvelle référence), sans mécanisme d'éviction dédié.
// Correction post-revue (bug 2) : un logo d'objet ne peut pas être rendu
// via une URL brute (`image://${apiObjectFileUrl(...)}`) - un <img>/ECharts
// `image://<url>` ne peut jamais attacher le header Authorization Bearer
// exigé par la lecture tenant-scoped (auth.py/rbac.py, fail-closed), donc
// l'image échouait silencieusement pour tout objet tenant-scoped. Résolu
// ici en Blob authentifié (apiReadObjectFileBlob) transformé en object URL.
const logoBlobCache = new Map<string, Promise<{ blob: Blob; filename: string }>>();
function getCachedLogoBlob(objectId: number, pointer: string) {
  const key = `${objectId}:${pointer}`;
  let entry = logoBlobCache.get(key);
  if (!entry) {
    entry = apiReadObjectFileBlob(objectId, 'logo');
    entry.catch(() => { logoBlobCache.delete(key); });
    logoBlobCache.set(key, entry);
  }
  return entry;
}

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
  // Filtre layers (plan-mark3.md action 14, point 7) : multi-sélection,
  // orthogonal à selectedMetaClass/selectedClass/hiddenClasses ci-dessous.
  // Vide = pas de filtre actif (tout visible).
  selectedLayers: Set<string>;
}

// Classe visible pour le filtre layer actif (plan-mark3.md action 14,
// point 1 ; même predicate que NavigationPage.tsx) : `layers` absent/vide =
// toujours visible, quel que soit le filtre. selectedLayers vide = pas de
// filtre actif (tout visible).
function isClassVisibleForLayers(def: { layers?: string[] } | undefined, selectedLayers: Set<string>): boolean {
  if (selectedLayers.size === 0) return true;
  const layers = def?.layers || [];
  if (layers.length === 0) return true;
  return layers.some((l) => selectedLayers.has(l));
}

// Layer effectif d'un objet (plan-mark3.md action 18, specifications/
// 07-roadmap.md §10.15 ; même predicate que NavigationPage.tsx, dette de
// duplication déjà acceptée pour isClassVisibleForLayers) : union du
// `layers` statique de sa classe et, pour chaque attribut 'select' de la
// classe portant un `layer_map`, des layers mappés à la valeur courante de
// l'objet sur cet attribut (si connue). Repli sur `classDef.layers`
// statique seul si le détail de l'objet n'est pas encore chargé - en
// pratique tous les détails sont chargés en amont (effet ci-dessous), ce
// repli ne joue donc que pendant la fenêtre de chargement initiale.
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

export default function DiagramPage({ selectedMetaClass, selectedClass, readOnly, selectedLayers }: DiagramPageProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  const [objects, setObjects] = useState<ObjectSummary[]>([]);
  const [details, setDetails] = useState<Record<number, ObjectDetail>>({});
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [layout, setLayout] = useState<LayoutType>('force');
  const [hiddenClasses, setHiddenClasses] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  // Logos d'objet résolus en object URL (bug 2, correction post-revue) :
  // pointeur + url pour détecter un pointeur devenu obsolète (nouvel
  // upload/référence) avant de réutiliser une entrée en cache.
  const [resolvedLogos, setResolvedLogos] = useState<Map<number, { pointer: string; url: string }>>(new Map());
  const resolvedLogosRef = useRef<Map<number, { pointer: string; url: string }>>(new Map());

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
      const def = classes.find((c) => c.meta_class === o.meta_class && c.class === o.class);
      // Layer effectif par objet (action 18) : remplace classDef.layers
      // statique seul par le calcul union (voir getObjectEffectiveLayers).
      const effectiveLayers = getObjectEffectiveLayers(def, details[o.id]);
      if (!isClassVisibleForLayers({ layers: effectiveLayers }, selectedLayers)) return false;
      return true;
    });
  }, [objects, selectedMetaClass, selectedClass, hiddenClasses, classes, selectedLayers, details]);

  // Pointeur logo actif par objet (bug 2, correction post-revue) : extrait
  // ici une seule fois, réutilisé à la fois par l'effet de résolution de
  // blob ci-dessous et par graphData (évite toute divergence entre les deux
  // calculs de "cet objet a-t-il un logo actif ?").
  const activeLogoPointers = useMemo(() => {
    const map = new Map<number, string>();
    for (const obj of filteredObjects) {
      const detail = details[obj.id];
      if (!detail) continue;
      const classDef = classes.find((c) => c.meta_class === obj.meta_class && c.class === obj.class);
      const hasLogoAttr = classDef?.attributes.some((a) => a.name === 'logo' && a.type === 'image') ?? false;
      if (!hasLogoAttr) continue;
      const logoValue = detail.attributes.find((a) => a.name === 'logo')?.values[0];
      if (typeof logoValue === 'string' && logoValue.length > 0) map.set(obj.id, logoValue);
    }
    return map;
  }, [filteredObjects, details, classes]);

  // Résolution asynchrone des logos en object URL (bug 2, correction
  // post-revue) : graphData (useMemo synchrone, ECharts) ne peut pas
  // attendre un fetch - tant qu'un logo n'est pas encore résolu ici, le
  // symbole retombe sur le niveau de priorité suivant (icône de classe,
  // §6.4), jamais sur une URL brute cassée. Dès que le blob arrive, le
  // changement de `resolvedLogos` fait recalculer graphData (re-render).
  useEffect(() => {
    let cancelled = false;
    for (const [objectId, pointer] of activeLogoPointers) {
      const current = resolvedLogosRef.current.get(objectId);
      if (current && current.pointer === pointer) continue;
      getCachedLogoBlob(objectId, pointer).then(({ blob }) => {
        if (cancelled) return;
        setResolvedLogos((prev) => {
          if (prev.get(objectId)?.pointer === pointer) return prev;
          const url = URL.createObjectURL(blob);
          const next = new Map(prev);
          const old = next.get(objectId);
          if (old) URL.revokeObjectURL(old.url);
          next.set(objectId, { pointer, url });
          resolvedLogosRef.current = next;
          return next;
        });
      }).catch(() => {});
    }
    // Révoque les entrées dont l'objet/pointeur n'est plus actif (logo
    // changé ou objet sorti du filtre) - jamais de fuite d'object URL.
    setResolvedLogos((prev) => {
      let changed = false;
      const next = new Map(prev);
      for (const [objectId, { pointer, url }] of prev) {
        if (activeLogoPointers.get(objectId) !== pointer) {
          URL.revokeObjectURL(url);
          next.delete(objectId);
          changed = true;
        }
      }
      if (!changed) return prev;
      resolvedLogosRef.current = next;
      return next;
    });
    return () => { cancelled = true; };
  }, [activeLogoPointers]);

  // Révocation finale au démontage (bug 2) : pas seulement sur changement
  // de dataset ci-dessus.
  useEffect(() => {
    return () => {
      for (const { url } of resolvedLogosRef.current.values()) URL.revokeObjectURL(url);
    };
  }, []);

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

      // Ordre de priorité de rendu (plan-mark3.md action 4, point 4) :
      // 1. logo actif de l'objet (attribut réservé "logo", type image,
      //    cf. model/*.json) ; 2. icône de classe choisie manuellement
      //    (point 1, jeu fixe embarqué, data URI - aucune requête réseau) ;
      //    3. icône de secours auto-générée côté backend (point 1bis) ;
      //    4. repli couleur de palette existant (§6.4, itemStyle.color
      //    jamais retiré - un logo/icône cassé en session retombe sur un
      //    rendu <img> cassé le temps d'un rendu, garde-fou serveur côté
      //    lecture, pas de détection d'erreur d'image ajoutée ici).
      const classDef = classes.find((c) => c.meta_class === obj.meta_class && c.class === obj.class);
      const activeLogoPointer = activeLogoPointers.get(obj.id);
      const resolvedLogo = activeLogoPointer ? resolvedLogos.get(obj.id) : undefined;

      let symbol: string | undefined;
      if (resolvedLogo && resolvedLogo.pointer === activeLogoPointer) {
        symbol = `image://${resolvedLogo.url}`;
      } else {
        // Pas (encore) de logo résolu : icône de classe choisie
        // manuellement, puis icône de secours auto-générée (route non
        // filtrée par tenant, URL brute correcte ici - voir
        // routes_read.py), puis repli couleur. Couvre aussi bien l'absence
        // de logo que le cas transitoire "logo actif mais blob pas encore
        // arrivé" (bug 2, correction post-revue) : jamais d'URL brute
        // cassée affichée pour un logo tenant-scoped.
        const manualIcon = findClassIcon(classDef?.icon);
        if (manualIcon) {
          symbol = `image://${classIconDataUri(manualIcon.svg)}`;
        } else if (classDef) {
          symbol = `image://${apiClassIconUrl(classDef.meta_class, classDef.class)}`;
        }
      }

      nodes.push({
        id: String(obj.id),
        name: label,
        category: catIndex[obj.class] ?? 0,
        symbolSize: 40,
        ...(symbol ? { symbol } : {}),
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
  }, [filteredObjects, objects, details, resolveDisplayName, classColorMap, classes, activeLogoPointers, resolvedLogos]);

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

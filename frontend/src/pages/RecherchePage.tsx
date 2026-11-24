import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { apiSearch, apiReadClasses } from '../api';
import type { ClassInfo, AttributeDefinition, SearchResponse, SearchResultRow } from '../types';

// Recherche globale (plan-mark3.md action 21, specifications/
// 07-roadmap.md §10.18). Rendu de ligne DÉDIÉ, volontairement pas extrait
// de NavigationPage.tsx (closure non extractible - cf. DashboardPage.tsx,
// `formatCellValue`, même choix déjà fait) : formatValue de NavigationPage
// ne traduit de toute façon pas boolean en "Oui/Non" (vérifié avant
// réutilisation, cf. consigne explicite de cette action), donc une
// réutilisation telle quelle aurait été incorrecte de toute façon.

// Copie locale de parseFilePointer (NavigationPage.tsx) : pas exportée
// depuis ce fichier, et cette page n'a besoin que de l'extraction du nom de
// fichier (jamais d'aperçu/téléchargement ici - liste de résultats en
// lecture seule).
function parseFilePointerFilename(value: string): string | null {
  if (value.startsWith('ref:')) {
    const colonIndexes: number[] = [];
    let searchFrom = 0;
    for (let i = 0; i < 5; i++) {
      const idx = value.indexOf(':', searchFrom);
      if (idx === -1) return null;
      colonIndexes.push(idx);
      searchFrom = idx + 1;
    }
    return value.slice(colonIndexes[4] + 1);
  }
  if (!value.includes(':')) return null;
  const idx = value.indexOf(':');
  const versionStr = value.slice(0, idx);
  if (!Number.isInteger(Number(versionStr))) return null;
  return value.slice(idx + 1);
}

// Formatage de valeur dédié à cette liste lecture seule - types couverts :
// boolean ("Oui"/"Non", jamais "true"/"false" brut), file/image/csv (nom de
// fichier extrait du pointeur, jamais le pointeur brut), datasource (jamais
// l'ID technique brut affiché comme une valeur - préfixé "→ #" comme le
// fallback non résolu de formatValue dans NavigationPage.tsx). select et
// string restent la valeur brute (déjà une chaîne lisible, select stocke
// directement l'option choisie - pas un ID). secret n'apparaît jamais ici
// (exclusion stricte côté backend).
function formatSearchValue(value: string, attrType: AttributeDefinition['type'] | undefined): string {
  if (attrType === 'boolean') {
    if (value === 'true') return 'Oui';
    if (value === 'false') return 'Non';
    return value;
  }
  if (attrType === 'file' || attrType === 'image' || attrType === 'csv') {
    const filename = parseFilePointerFilename(value);
    return filename ?? value;
  }
  if (attrType === 'datasource') {
    return `→ #${value}`;
  }
  return value;
}

// Formatage BEST-EFFORT des chips "valeurs proches" (fuzzy_suggestions,
// revue action 21 point 6) - contrairement à `formatSearchValue` ci-dessus,
// le serveur ne renvoie qu'une valeur brute sans meta_class/class/attribute
// associés pour ces suggestions (pool toutes classes confondues par
// construction, cf. docstring backend `_fuzzy_candidate_suggestions`) :
// impossible de connaître le type réel exact d'une chip donnée. Détection
// heuristique sur la FORME de la valeur seule, pas sur un type connu :
// "true"/"false" littéral -> "Oui"/"Non" ; forme d'un pointeur fichier
// ("<version>:<nom>" / "ref:...") -> nom de fichier extrait. Un faux
// positif reste possible (ex. une valeur `string` légitime qui ressemble
// par hasard à un pointeur, ex. "10:20") - accepté explicitement, SANS
// garantie totale contrairement à `results` qui connaît le type exact.
function formatFuzzySuggestionBestEffort(value: string): string {
  if (value === 'true') return 'Oui';
  if (value === 'false') return 'Non';
  const filename = parseFilePointerFilename(value);
  if (filename !== null) return filename;
  return value;
}

function classKey(metaClass: string, cls: string): string {
  return `${metaClass}::${cls}`;
}

export default function RecherchePage() {
  const [query, setQuery] = useState('');
  const [fuzzy, setFuzzy] = useState(false);
  const [history, setHistory] = useState(false);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [classes, setClasses] = useState<ClassInfo[]>([]);

  // Sélection de facettes (plan-mark3.md action 21) : OR au sein d'une même
  // catégorie (sélectionner deux classes élargit aux deux), ET entre
  // catégories différentes (sélectionner une classe ET un attribut narrow
  // sur les deux à la fois) - interprétation standard d'une recherche à
  // facettes, non explicitement tranchée par la conception initiale (point
  // laissé à l'implémentation, cf. rapport de fin de tâche).
  const [selectedLayers, setSelectedLayers] = useState<Set<string>>(new Set());
  const [selectedClasses, setSelectedClasses] = useState<Set<string>>(new Set());
  const [selectedAttributes, setSelectedAttributes] = useState<Set<string>>(new Set());

  useEffect(() => {
    apiReadClasses().then(setClasses).catch(() => setClasses([]));
  }, []);

  const attrTypeIndex = useMemo(() => {
    const idx = new Map<string, AttributeDefinition['type']>();
    for (const c of classes) {
      for (const a of c.attributes) {
        idx.set(`${classKey(c.meta_class, c.class)}::${a.name}`, a.type);
      }
    }
    return idx;
  }, [classes]);

  const classLayersIndex = useMemo(() => {
    const idx = new Map<string, string[]>();
    for (const c of classes) {
      idx.set(classKey(c.meta_class, c.class), c.layers ?? []);
    }
    return idx;
  }, [classes]);

  const runSearch = async (q: string, fz: boolean, hist: boolean) => {
    const trimmed = q.trim();
    if (!trimmed) {
      setResponse(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiSearch(trimmed, fz, hist);
      setResponse(res);
      setSelectedLayers(new Set());
      setSelectedClasses(new Set());
      setSelectedAttributes(new Set());
    } catch (err) {
      setResponse(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    runSearch(query, fuzzy, history);
  };

  const handleToggleFuzzy = (v: boolean) => {
    setFuzzy(v);
    if (response != null) runSearch(query, v, history);
  };

  const handleToggleHistory = (v: boolean) => {
    setHistory(v);
    if (response != null) runSearch(query, fuzzy, v);
  };

  const toggleInSet = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key); else next.add(key);
    setter(next);
  };

  const handleSuggestionClick = (suggestion: string) => {
    setQuery(suggestion);
    runSearch(suggestion, fuzzy, history);
  };

  const filteredResults: SearchResultRow[] = useMemo(() => {
    if (!response) return [];
    return response.results.filter((r) => {
      if (selectedClasses.size > 0 && !selectedClasses.has(classKey(r.meta_class, r.class))) return false;
      if (selectedAttributes.size > 0 && !selectedAttributes.has(r.attribute)) return false;
      if (selectedLayers.size > 0) {
        const layers = classLayersIndex.get(classKey(r.meta_class, r.class)) ?? [];
        if (!layers.some((l) => selectedLayers.has(l))) return false;
      }
      return true;
    });
  }, [response, selectedClasses, selectedAttributes, selectedLayers, classLayersIndex]);

  // Regroupement par objet (plan-mark3.md action 21) : plusieurs attributs
  // d'un même objet peuvent matcher - une ligne de résultat par objet, les
  // attributs/valeurs matchant listés dedans, plutôt qu'une ligne par
  // (objet, attribut) brute (lecture plus naturelle qu'une table plate avec
  // des id dupliqués, sans round-trip supplémentaire : regroupement 100%
  // client sur `filteredResults` déjà remonté).
  const groupedResults = useMemo(() => {
    const map = new Map<number, { id: number; meta_class: string; class: string; matches: { attribute: string; value: string; is_current: boolean }[] }>();
    for (const r of filteredResults) {
      let group = map.get(r.id);
      if (!group) {
        group = { id: r.id, meta_class: r.meta_class, class: r.class, matches: [] };
        map.set(r.id, group);
      }
      group.matches.push({ attribute: r.attribute, value: r.value, is_current: r.is_current });
    }
    return [...map.values()].sort((a, b) => a.id - b.id);
  }, [filteredResults]);

  return (
    <div className="search-page">
      <div className="card">
        <h2>Recherche</h2>
        <form className="search-form" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Rechercher dans les attributs de tous les objets…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className="btn btn-primary" disabled={!query.trim() || loading}>
            {loading ? 'Recherche…' : 'Rechercher'}
          </button>
        </form>

        <div className="search-switches" style={{ marginTop: 12 }}>
          <div className="rw-switch" onClick={() => handleToggleFuzzy(!fuzzy)}>
            <span className={`rw-label ${!fuzzy ? 'rw-active' : ''}`}>Exact</span>
            <div className={`rw-toggle ${fuzzy ? 'rw-toggle-on' : ''}`}>
              <div className="rw-thumb" />
            </div>
            <span className={`rw-label ${fuzzy ? 'rw-active' : ''}`}>Fuzzy</span>
          </div>
          <div className="rw-switch" onClick={() => handleToggleHistory(!history)}>
            <span className={`rw-label ${!history ? 'rw-active' : ''}`}>Actifs</span>
            <div className={`rw-toggle ${history ? 'rw-toggle-on' : ''}`}>
              <div className="rw-thumb" />
            </div>
            <span className={`rw-label ${history ? 'rw-active' : ''}`}>Historique</span>
          </div>
        </div>

        {error && <p style={{ color: 'var(--color-danger, #c0392b)', marginTop: 12 }}>Erreur : {error}</p>}
      </div>

      {response && (
        <>
          {response.truncated && (
            <div className="card" style={{ color: 'var(--color-danger, #c0392b)' }}>
              Trop de résultats (limite de 500 atteinte) — affinez la recherche.
            </div>
          )}

          {fuzzy && response.fuzzy_suggestions.length > 0 && (
            <div className="card">
              <h4 style={{ marginBottom: 8 }}>Valeurs proches</h4>
              <div className="search-suggestions">
                {response.fuzzy_suggestions.map((s) => (
                  <button key={s} type="button" className="search-suggestion-chip" onClick={() => handleSuggestionClick(s)}>
                    {formatFuzzySuggestionBestEffort(s)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="card search-facets">
            <div className="search-facet-group">
              <h4>Layers</h4>
              <div className="search-facet-chips">
                {response.facets.layers.length === 0 && <span style={{ color: 'var(--color-text-muted)', fontSize: '0.8rem' }}>—</span>}
                {response.facets.layers.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    className={`search-facet-btn ${selectedLayers.has(f.value) ? 'active' : ''}`}
                    onClick={() => toggleInSet(selectedLayers, setSelectedLayers, f.value)}
                  >
                    {f.value}
                    <span className="search-facet-count">{f.count}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="search-facet-group">
              <h4>Classes</h4>
              <div className="search-facet-chips">
                {response.facets.classes.map((f) => {
                  const key = classKey(f.meta_class, f.class);
                  return (
                    <button
                      key={key}
                      type="button"
                      className={`search-facet-btn ${selectedClasses.has(key) ? 'active' : ''}`}
                      onClick={() => toggleInSet(selectedClasses, setSelectedClasses, key)}
                    >
                      {f.class}
                      <span className="search-facet-count">{f.count}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="search-facet-group">
              <h4>Attributs</h4>
              <div className="search-facet-chips">
                {response.facets.attributes.map((f) => (
                  <button
                    key={f.name}
                    type="button"
                    className={`search-facet-btn ${selectedAttributes.has(f.name) ? 'active' : ''}`}
                    onClick={() => toggleInSet(selectedAttributes, setSelectedAttributes, f.name)}
                  >
                    {f.name}
                    <span className="search-facet-count">{f.count}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            {groupedResults.length === 0 ? (
              <p>Aucun résultat.</p>
            ) : (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Meta-classe</th>
                      <th>Classe</th>
                      <th>Attributs correspondants</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedResults.map((g) => (
                      <tr key={g.id}>
                        <td>#{g.id}</td>
                        <td><span className="badge badge-meta">{g.meta_class}</span></td>
                        <td><span className="badge badge-class">{g.class}</span></td>
                        <td>
                          {g.matches.map((m, i) => {
                            const attrType = attrTypeIndex.get(`${classKey(g.meta_class, g.class)}::${m.attribute}`);
                            return (
                              <div key={i}>
                                <strong>{m.attribute}</strong> : {formatSearchValue(m.value, attrType)}
                                {history && (
                                  <span className={`search-current-badge ${m.is_current ? 'search-current-badge-active' : 'search-current-badge-historic'}`}>
                                    {m.is_current ? 'actif' : 'historique'}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

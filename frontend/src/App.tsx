import { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import Sidebar from './components/Sidebar';
import ConfigurationPage from './pages/ConfigurationPage';
import NavigationPage from './pages/NavigationPage';
import DiagramPage from './pages/DiagramPage';
import DashboardPage from './pages/DashboardPage';
import RecherchePage from './pages/RecherchePage';
import { getAuthInfo, type AuthInfo } from './auth';

type Page = 'configuration' | 'navigation' | 'diagramme' | 'dashboard' | 'recherche';
type Theme = 'dark' | 'midnight' | 'light';

// Filtre layers (plan-mark3.md action 14, point 2) : multi-sélection,
// orthogonale à selectedMetaClass/selectedClass (mono-sélection) -
// persistée en localStorage pour survivre à un reload, clé alignée sur la
// convention déjà en place (AUTH_TOKEN_STORAGE_KEY, frontend/src/api.ts).
const SELECTED_LAYERS_STORAGE_KEY = 'miami-vice-selected-layers';

function loadSelectedLayers(): Set<string> {
  try {
    const raw = localStorage.getItem(SELECTED_LAYERS_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed.filter((l) => typeof l === 'string')) : new Set();
  } catch {
    return new Set();
  }
}

export default function App() {
  const [page, setPage] = useState<Page>('navigation');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [readOnly, setReadOnly] = useState(false);
  const [theme, setTheme] = useState<Theme>('dark');
  const [selectedMetaClass, setSelectedMetaClass] = useState<string | null>(null);
  const [selectedClass, setSelectedClass] = useState<string | null>(null);
  const [selectedLayers, setSelectedLayers] = useState<Set<string>>(() => loadSelectedLayers());
  const [authInfo, setAuthInfo] = useState<AuthInfo>(() => getAuthInfo(null));

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Persistance localStorage (plan-mark3.md action 14, point 2) : écrite à
  // chaque changement ; vide = clé supprimée (pas de "[]" qui traînerait
  // sans jamais gêner, mais plus simple à relire comme "pas de filtre").
  useEffect(() => {
    try {
      if (selectedLayers.size === 0) localStorage.removeItem(SELECTED_LAYERS_STORAGE_KEY);
      else localStorage.setItem(SELECTED_LAYERS_STORAGE_KEY, JSON.stringify([...selectedLayers]));
    } catch {
      // Stockage indisponible (mode privé strict, quota...) : le filtre
      // reste fonctionnel pour la session en cours, juste non persisté.
    }
  }, [selectedLayers]);

  // RBAC multi-tenant (plan.md action 11) : si la page Configuration est
  // affichée et que l'utilisateur devient (ou est) tenant-readonly, on la
  // quitte automatiquement - l'entrée de menu correspondante est elle-même
  // masquée côté Navbar, donc cette page ne doit jamais rester accessible.
  useEffect(() => {
    if (page === 'configuration' && authInfo.isTenantReadonly) {
      setPage('navigation');
    }
  }, [page, authInfo.isTenantReadonly]);

  return (
    <>
      <Navbar page={page} onPageChange={setPage} readOnly={readOnly} onToggleReadOnly={setReadOnly} theme={theme} onThemeChange={setTheme} onAuthChange={setAuthInfo} />
      <div className="layout">
        {/* Dashboard (plan-mark3.md action 15, point 2) : ni Sidebar ni
            bouton toggle, absence complète du DOM (pas juste open=false) -
            DashboardPage ne consomme ni meta_class/class/layers. Recherche
            (action 21) : même traitement, même raison - la recherche porte
            sur toutes les classes/meta-classes, un filtre Sidebar par
            classe n'a pas de sens ici. */}
        {page !== 'dashboard' && page !== 'recherche' && (
          <button
            className={`sidebar-toggle ${sidebarOpen ? 'shifted' : ''}`}
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? '◀' : '▶'}
          </button>
        )}
        {page !== 'dashboard' && page !== 'recherche' && (
          <Sidebar
            open={sidebarOpen}
            page={page}
            selectedMetaClass={selectedMetaClass}
            selectedClass={selectedClass}
            onSelectMetaClass={setSelectedMetaClass}
            onSelectClass={setSelectedClass}
            selectedLayers={selectedLayers}
            onSelectedLayersChange={setSelectedLayers}
          />
        )}
        <div className="main-content">
          {page === 'configuration' ? (
            <ConfigurationPage
              selectedMetaClass={selectedMetaClass}
              authInfo={authInfo}
            />
          ) : page === 'diagramme' ? (
            <DiagramPage
              selectedMetaClass={selectedMetaClass}
              selectedClass={selectedClass}
              readOnly={readOnly}
              selectedLayers={selectedLayers}
            />
          ) : page === 'dashboard' ? (
            <DashboardPage readOnly={readOnly} />
          ) : page === 'recherche' ? (
            <RecherchePage />
          ) : (
            <NavigationPage
              selectedMetaClass={selectedMetaClass}
              selectedClass={selectedClass}
              readOnly={readOnly}
              authInfo={authInfo}
              selectedLayers={selectedLayers}
            />
          )}
        </div>
      </div>
    </>
  );
}

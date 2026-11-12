import { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import Sidebar from './components/Sidebar';
import ConfigurationPage from './pages/ConfigurationPage';
import NavigationPage from './pages/NavigationPage';
import DiagramPage from './pages/DiagramPage';
import { getAuthInfo, type AuthInfo } from './auth';

type Page = 'configuration' | 'navigation' | 'diagramme';
type Theme = 'dark' | 'midnight' | 'light';

export default function App() {
  const [page, setPage] = useState<Page>('navigation');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [readOnly, setReadOnly] = useState(false);
  const [theme, setTheme] = useState<Theme>('dark');
  const [selectedMetaClass, setSelectedMetaClass] = useState<string | null>(null);
  const [selectedClass, setSelectedClass] = useState<string | null>(null);
  const [authInfo, setAuthInfo] = useState<AuthInfo>(() => getAuthInfo(null));

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

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
        <button
          className={`sidebar-toggle ${sidebarOpen ? 'shifted' : ''}`}
          onClick={() => setSidebarOpen(!sidebarOpen)}
        >
          {sidebarOpen ? '◀' : '▶'}
        </button>
        <Sidebar
          open={sidebarOpen}
          page={page}
          selectedMetaClass={selectedMetaClass}
          selectedClass={selectedClass}
          onSelectMetaClass={setSelectedMetaClass}
          onSelectClass={setSelectedClass}
        />
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
            />
          ) : (
            <NavigationPage
              selectedMetaClass={selectedMetaClass}
              selectedClass={selectedClass}
              readOnly={readOnly}
              authInfo={authInfo}
            />
          )}
        </div>
      </div>
    </>
  );
}

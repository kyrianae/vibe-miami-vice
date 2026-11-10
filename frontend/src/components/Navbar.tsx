import { useState, useEffect } from 'react';
import { apiLogin, getAuthToken, setAuthToken } from '../api';
import { getAuthInfo, type AuthInfo } from '../auth';

type Theme = 'dark' | 'midnight' | 'light';

const THEME_LABELS: Record<Theme, string> = {
  dark: '🌑 Dark',
  midnight: '🌙 Midnight',
  light: '☀️ Light',
};

interface NavbarProps {
  page: 'configuration' | 'navigation' | 'diagramme';
  onPageChange: (page: 'configuration' | 'navigation' | 'diagramme') => void;
  readOnly: boolean;
  onToggleReadOnly: (v: boolean) => void;
  theme: Theme;
  onThemeChange: (t: Theme) => void;
  onAuthChange: (info: AuthInfo) => void;
}

export default function Navbar({ page, onPageChange, readOnly, onToggleReadOnly, theme, onThemeChange, onAuthChange }: NavbarProps) {
  const [loggedIn, setLoggedIn] = useState<boolean>(() => !!getAuthToken());
  const [authInfo, setAuthInfo] = useState<AuthInfo>(() => getAuthInfo(getAuthToken()));
  const [showLogin, setShowLogin] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Synchronise l'état RBAC décodé vers App au montage (y compris pour un
  // utilisateur déjà connecté via un token persisté en localStorage).
  useEffect(() => {
    onAuthChange(authInfo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateAuthInfo = (info: AuthInfo) => {
    setAuthInfo(info);
    onAuthChange(info);
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await apiLogin(username, password);
      setLoggedIn(true);
      setShowLogin(false);
      setPassword('');
      updateAuthInfo(getAuthInfo(getAuthToken()));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de connexion');
    }
  };

  const handleLogout = () => {
    setAuthToken(null);
    setLoggedIn(false);
    updateAuthInfo(getAuthInfo(null));
  };

  return (
    <nav className="navbar">
      <h1>Miami Vice</h1>
      <button
        className={page === 'navigation' ? 'active' : ''}
        onClick={() => onPageChange('navigation')}
      >
        Navigation
      </button>
      {/* RBAC multi-tenant (plan.md action 11) : entrée de menu entièrement
          masquée (pas juste désactivée) pour le rôle tenant-readonly. */}
      {!authInfo.isTenantReadonly && (
        <button
          className={page === 'configuration' ? 'active' : ''}
          onClick={() => onPageChange('configuration')}
        >
          Configuration
        </button>
      )}
      <button
        className={page === 'diagramme' ? 'active' : ''}
        onClick={() => onPageChange('diagramme')}
      >
        Diagramme
      </button>
      <div className="navbar-spacer" />
      <select
        className="theme-select"
        value={theme}
        onChange={(e) => onThemeChange(e.target.value as Theme)}
      >
        {(Object.keys(THEME_LABELS) as Theme[]).map((t) => (
          <option key={t} value={t}>{THEME_LABELS[t]}</option>
        ))}
      </select>
      <div className="rw-switch" onClick={() => onToggleReadOnly(!readOnly)}>
        <span className={`rw-label ${readOnly ? 'rw-active' : ''}`}>RO</span>
        <div className={`rw-toggle ${readOnly ? '' : 'rw-toggle-on'}`}>
          <div className="rw-thumb" />
        </div>
        <span className={`rw-label ${!readOnly ? 'rw-active' : ''}`}>RW</span>
      </div>
      <div className="auth-box" style={{ position: 'relative' }}>
        {loggedIn ? (
          <button onClick={handleLogout}>Déconnexion</button>
        ) : (
          <button onClick={() => setShowLogin((v) => !v)}>Connexion</button>
        )}
        {showLogin && !loggedIn && (
          <form
            onSubmit={handleLogin}
            style={{
              position: 'absolute',
              top: '100%',
              right: 0,
              background: 'var(--bg-secondary, #222)',
              padding: '0.75rem',
              borderRadius: '4px',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
              zIndex: 10,
              minWidth: '200px',
            }}
          >
            <input
              type="text"
              placeholder="Utilisateur"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
            <input
              type="password"
              placeholder="Mot de passe"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button type="submit">Se connecter</button>
            {error && <span style={{ color: 'red', fontSize: '0.85em' }}>{error}</span>}
          </form>
        )}
      </div>
    </nav>
  );
}

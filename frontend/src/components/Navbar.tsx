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
}

export default function Navbar({ page, onPageChange, readOnly, onToggleReadOnly, theme, onThemeChange }: NavbarProps) {
  return (
    <nav className="navbar">
      <h1>Miami Vice</h1>
      <button
        className={page === 'navigation' ? 'active' : ''}
        onClick={() => onPageChange('navigation')}
      >
        Navigation
      </button>
      <button
        className={page === 'configuration' ? 'active' : ''}
        onClick={() => onPageChange('configuration')}
      >
        Configuration
      </button>
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
    </nav>
  );
}

import { useEffect, useState } from 'react';
import { apiReadClasses } from '../api';
import type { ClassInfo } from '../types';

interface SidebarProps {
  open: boolean;
  // 'dashboard' ajouté (plan-mark3.md action 10b) : uniquement pour matcher
  // le type Page de App.tsx (qui passe `page` tel quel) - Sidebar ne
  // branche sur aucune valeur spécifique de `page` autre que la dep du
  // useEffect ci-dessous.
  page: 'configuration' | 'navigation' | 'diagramme' | 'dashboard';
  selectedMetaClass: string | null;
  selectedClass: string | null;
  onSelectMetaClass: (mc: string | null) => void;
  onSelectClass: (cls: string | null) => void;
}

export default function Sidebar({
  open,
  page,
  selectedMetaClass,
  selectedClass,
  onSelectMetaClass,
  onSelectClass,
}: SidebarProps) {
  const [classes, setClasses] = useState<ClassInfo[]>([]);

  useEffect(() => {
    apiReadClasses().then(setClasses).catch(() => {});
  }, [page]);

  // Grouper par meta_class
  const grouped: Record<string, ClassInfo[]> = {};
  for (const c of classes) {
    if (!grouped[c.meta_class]) grouped[c.meta_class] = [];
    grouped[c.meta_class].push(c);
  }

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
      <h3>Types d'objets</h3>
      <ul>
        <li
          className={!selectedMetaClass ? 'active' : ''}
          onClick={() => { onSelectMetaClass(null); onSelectClass(null); }}
        >
          Tous
        </li>
        {Object.entries(grouped).map(([mc, cls]) => (
          <li key={mc} style={{ padding: 0 }}>
            <div
              style={{ padding: '8px 16px', cursor: 'pointer', fontWeight: 600 }}
              className={selectedMetaClass === mc && !selectedClass ? 'active' : ''}
              onClick={() => handleMetaClick(mc)}
            >
              <span className="badge badge-meta">{mc}</span>
            </div>
            {selectedMetaClass === mc && (
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
    </aside>
  );
}

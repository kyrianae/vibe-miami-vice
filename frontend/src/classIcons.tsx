// Jeu fixe d'icônes de classe embarquées côté frontend (plan-mark3.md
// action 4, point 1 ; specifications/07-roadmap.md §10.8) : un identifiant
// choisi ici (champ "icon" du schéma, model/schema.json) n'est jamais un
// upload libre - juste une clé dans ce registre statique. Rendu en SVG
// inline (markup brut, pas de JSX) pour pouvoir être encodé directement en
// data URI (classIconDataUri) et utilisé comme `symbol: 'image://...'`
// ECharts dans DiagramPage.tsx, sans aucune requête réseau.
//
// viewBox uniforme 0 0 24 24, trait de couleur fixe (pas currentColor,
// cf. ClassIconDef) : un data URI encodé est rendu hors de tout contexte
// CSS (symbole ECharts), donc une couleur héritée ne s'appliquerait pas.
// Gris moyen plutôt que blanc/noir fixe : reste lisible aussi bien sur un
// thème clair que sombre (frontend/src/styles.css, --color-bg).

export interface ClassIconDef {
  id: string;
  label: string;
  // Markup <svg ...>...</svg> complet, viewBox "0 0 24 24", stroke gris
  // moyen fixe : rendu correct dans la grille de sélection
  // (ConfigurationPage.tsx, thèmes clair/sombre/midnight) et comme symbole
  // ECharts (DiagramPage.tsx) sans dépendre d'un contexte CSS.
  svg: string;
}

const STROKE = 'stroke="#8a8d98" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"';

function icon(id: string, label: string, body: string): ClassIconDef {
  return {
    id,
    label,
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ${STROKE}>${body}</svg>`,
  };
}

export const CLASS_ICONS: ClassIconDef[] = [
  icon('server', 'Serveur', '<rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><circle cx="7" cy="7" r="0.4" fill="#8a8d98" stroke="none"/><circle cx="7" cy="17" r="0.4" fill="#8a8d98" stroke="none"/>'),
  icon('database', 'Base de données', '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
  icon('network', 'Réseau', '<circle cx="12" cy="4" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 6v6M12 12l-6 5M12 12l6 5"/>'),
  icon('router', 'Routeur / Switch', '<rect x="2" y="9" width="20" height="7" rx="1"/><path d="M6 9V6M10 9V6M14 9V6M18 9V6"/>'),
  icon('person', 'Personne', '<circle cx="12" cy="7" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>'),
  icon('group', 'Groupe / Organisation', '<circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M2 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><path d="M13.5 15a5 5 0 0 1 7.5 4.3"/>'),
  icon('org-chart', 'Organigramme', '<rect x="9" y="2" width="6" height="4" rx="1"/><rect x="2" y="16" width="6" height="4" rx="1"/><rect x="16" y="16" width="6" height="4" rx="1"/><path d="M12 6v5M5 16v-3h14v3"/>'),
  icon('ticket', 'Ticket', '<path d="M3 9a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v1.5a1.5 1.5 0 0 0 0 3V15a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1.5a1.5 1.5 0 0 0 0-3Z"/><path d="M10 7v10" stroke-dasharray="2 2"/>'),
  icon('application', 'Application', '<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M3 9h18"/><circle cx="6" cy="6.5" r="0.4" fill="#8a8d98" stroke="none"/>'),
  icon('datacenter', 'Datacenter / Bâtiment', '<path d="M4 21V6l8-3 8 3v15"/><path d="M4 21h16"/><path d="M9 21v-4h6v4"/><path d="M9 9h1M14 9h1M9 13h1M14 13h1"/>'),
  icon('calendar', 'Planning', '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'),
  icon('contract', 'Contrat', '<path d="M6 2h9l5 5v15H6Z"/><path d="M15 2v5h5"/><path d="M9 13h6M9 17h6"/>'),
  icon('supplier', 'Fournisseur', '<path d="M3 10l2-6h14l2 6"/><path d="M4 10h16v10H4Z"/><path d="M10 20v-5h4v5"/>'),
  icon('inventory', 'Inventaire', '<rect x="3" y="7" width="18" height="13" rx="1"/><path d="M3 11h18"/><path d="M9 7V5a3 3 0 0 1 6 0v2"/>'),
  icon('link', 'Lien / Dépendance', '<path d="M9 15 15 9"/><path d="M8 13 5 16a3 3 0 0 0 4 4l3-3"/><path d="M16 11l3-3a3 3 0 0 0-4-4l-3 3"/>'),
  icon('folder', 'Dossier / Document', '<path d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>'),
  icon('globe', 'Service global', '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>'),
  icon('shield', 'Sécurité', '<path d="M12 3l7 3v6c0 5-3 8-7 9-4-1-7-4-7-9V6Z"/><path d="M9 12l2 2 4-4"/>'),
];

export function findClassIcon(id: string | undefined | null): ClassIconDef | undefined {
  if (!id) return undefined;
  return CLASS_ICONS.find((i) => i.id === id);
}

// Encodage en data URI directement utilisable par ECharts (`image://<uri>`)
// ou un <img src=...> : pas de base64 (évite les soucis d'échappement
// UTF-8 de btoa pour un éventuel futur libellé accentué dans le markup),
// encodeURIComponent suffit pour un data URI SVG.
export function classIconDataUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

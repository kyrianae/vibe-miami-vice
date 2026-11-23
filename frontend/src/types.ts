// Types pour le modèle de données

export interface AttributeDefinition {
  domain: string;
  name: string;
  type: 'string' | 'integer' | 'float' | 'joint-1-1' | 'joint-1-n' | 'file' | 'image' | 'csv' | 'select' | 'datasource' | 'secret' | 'boolean';
  // Classes cibles autorisées : requis pour joint-1-1/joint-1-n (jointure)
  // ET pour datasource (classes datasource_* acceptées par ce pointeur,
  // plan-mark3.md action 9 - même champ réutilisé).
  classes?: string[];
  constraint?: string;
  sql_constraint?: string;
  // Séparateur de colonnes, réservé au type 'csv' (plan-mark3.md action 3).
  // Défaut ',' côté frontend si absent (voir NavigationPage.tsx).
  separator?: string;
  // Liste fixe des valeurs autorisées, réservée au type 'select'
  // (plan-mark3.md action 7). Requis côté model/schema.json si type = select.
  values?: string[];
  // Layer dynamique piloté par un attribut 'select' (plan-mark3.md action 18) :
  // {valeur: [layers]}, censé être un sous-ensemble de `values` (non vérifié
  // côté frontend). La seule présence de ce champ marque l'attribut comme
  // pilotant le layer effectif de l'objet - pas de flag booléen séparé.
  // Sans objet pour les autres types. Voir getObjectEffectiveLayers dans
  // NavigationPage.tsx/DiagramPage.tsx pour le calcul du layer effectif.
  layer_map?: Record<string, string[]>;
}

export interface ClassDefinition {
  class: string;
  displayname?: string;
  // RBAC multi-tenant (plan.md action 11) : tenants autorisés à utiliser
  // cette classe (noms de groupes Keycloak, sans '/'). Absent/vide =
  // utilisable dans tous les tenants.
  tenants?: string[];
  // Calques thématiques (plan-mark3.md action 14) : tag texte libre (comme
  // tenants), pas un mécanisme RBAC - sert uniquement au filtre d'affichage
  // IHM/diagramme (selectedLayers). Absent/vide = classe toujours visible
  // quel que soit le filtre layer actif.
  layers?: string[];
  // Icône par défaut de la classe (plan-mark3.md action 4, point 1) :
  // identifiant dans le jeu fixe frontend/src/classIcons.tsx, jamais un
  // upload libre. Absent = pas d'icône manuelle choisie (repli sur l'icône
  // auto-générée backend, puis la couleur de palette, cf. DiagramPage.tsx).
  icon?: string;
  attributes: AttributeDefinition[];
}

export interface MetaClassDefinition {
  meta_class: string;
  classes: ClassDefinition[];
}

export interface MetaClassInfo {
  id: number;
  meta_class: string;
}

export interface ClassInfo {
  meta_class: string;
  class: string;
  displayname?: string;
  tenants?: string[];
  // Calques thématiques (plan-mark3.md action 14), cf. ClassDefinition.layers.
  layers?: string[];
  icon?: string;
  attributes: AttributeDefinition[];
}

// Entrée de GET /api/logos (plan-mark3.md action 4, point 2/3) : emplacement
// PHYSIQUE déjà aplati (jamais un pointeur "ref:" intermédiaire, voir
// backend/routes_files.py) d'un logo actuellement actif sur un objet,
// utilisée par le sélecteur de réutilisation d'un logo existant
// (NavigationPage.tsx).
export interface LogoEntry {
  class: string;
  object_id: number;
  attribute: string;
  version: number;
  filename: string;
  display_name: string;
}

export interface ObjectSummary {
  id: number;
  meta_class: string;
  class: string;
  // RBAC multi-tenant (plan.md action 11.1) : liste de tenants (noms de
  // groupes Keycloak, sans '/'). Absente/vide = objet hors tenant,
  // visible/éditable depuis tous les tenants.
  tenants?: string[];
}

export interface AttributeValue {
  domain: string;
  name: string;
  values: (string | number | { joint_id: number })[];
}

export interface ObjectDetail extends ObjectSummary {
  attributes: AttributeValue[];
}

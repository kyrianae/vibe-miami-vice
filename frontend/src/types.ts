// Types pour le modèle de données

export interface AttributeDefinition {
  domain: string;
  name: string;
  type: 'string' | 'integer' | 'float' | 'joint-1-1' | 'joint-1-n';
  classes?: string[];
  constraint?: string;
  sql_constraint?: string;
}

export interface ClassDefinition {
  class: string;
  displayname?: string;
  // RBAC multi-tenant (plan.md action 11) : tenants autorisés à utiliser
  // cette classe (noms de groupes Keycloak, sans '/'). Absent/vide =
  // utilisable dans tous les tenants.
  tenants?: string[];
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
  attributes: AttributeDefinition[];
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

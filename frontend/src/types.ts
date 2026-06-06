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
  attributes: AttributeDefinition[];
}

export interface ObjectSummary {
  id: number;
  meta_class: string;
  class: string;
}

export interface AttributeValue {
  domain: string;
  name: string;
  values: (string | number | { joint_id: number })[];
}

export interface ObjectDetail extends ObjectSummary {
  attributes: AttributeValue[];
}

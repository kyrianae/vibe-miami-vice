-- Schema des objets
CREATE TABLE object (
    id SERIAL PRIMARY KEY,
    meta_class TEXT NOT NULL,
    class TEXT NOT NULL,
    -- RBAC multi-tenant (plan.md action 11.1) : NULL/chaîne vide = objet
    -- hors tenant, visible/éditable depuis tous les tenants ; sinon liste de
    -- noms de tenants (groupes Keycloak sans le '/' préfixe) séparés par des
    -- virgules, ex. "tenant1,tenant2". Filtrage en lecture via
    -- string_to_array(tenants, ',') && %s::text[] (overlap Postgres).
    tenants TEXT NULL,
    -- Suppression logique (plan-mark2.md action 6.0/6.1) : NULL = objet
    -- actif. Une suppression pose deleted_at = now() sans retirer la
    -- ligne physiquement ; la purge (action 6.2) s'en chargera plus tard.
    deleted_at TIMESTAMPTZ NULL
);

CREATE INDEX idx_object_tenants ON object(tenants);

CREATE TABLE attribute (
    id SERIAL PRIMARY KEY,
    object_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY (object_id) REFERENCES object(id) ON DELETE CASCADE,
    -- Historisation (plan-mark2.md action 6.0) : une seule ligne attribute
    -- par (objet, nom), réutilisée à chaque écriture ; l'historique vit
    -- dans attribute_value (valid_from/valid_to), jamais dans des lignes
    -- attribute en doublon. Garde-fou contre deux écritures concurrentes
    -- qui créeraient chacune l'attribut.
    CONSTRAINT attribute_object_name_unique UNIQUE (object_id, name)
);

CREATE TABLE attribute_value (
    id SERIAL PRIMARY KEY,
    attribute_id INTEGER NOT NULL,
    value_integer INTEGER,
    value_float DOUBLE PRECISION,
    value_string TEXT,
    joint_id INTEGER,
    -- Historisation (plan-mark2.md action 6.0) : la version courante d'une
    -- valeur est celle où valid_to IS NULL. Une réécriture de l'attribut
    -- ferme l'ancienne valeur (valid_to = now()) plutôt que de la
    -- supprimer, et insère une nouvelle ligne valid_from = now().
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ NULL,
    FOREIGN KEY (attribute_id) REFERENCES attribute(id) ON DELETE CASCADE,
    FOREIGN KEY (joint_id) REFERENCES object(id) ON DELETE SET NULL,
    CHECK (
        (value_integer IS NOT NULL AND value_float IS NULL AND value_string IS NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NOT NULL AND value_string IS NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NULL AND value_string IS NOT NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NULL AND value_string IS NULL AND joint_id IS NOT NULL)
    )
);

-- Requis par les actions 6.1 (cascade suppression logique)/6.2 (purge), qui
-- filtrent toutes deux sur joint_id (plan-mark2.md action 6.0).
CREATE INDEX idx_attribute_value_joint_id ON attribute_value(joint_id);

-- Stockage JSON des définitions de classes
CREATE TABLE definition (
    id SERIAL PRIMARY KEY,
    meta_class TEXT NOT NULL UNIQUE,
    data JSONB NOT NULL
);

-- Configuration applicative générique clé/valeur (plan-mark2.md action 6.2) :
-- une colonne dédiée par paramètre futur serait moins cohérent avec la
-- philosophie dynamique du reste du projet.
CREATE TABLE app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Période de grâce (en jours) avant la purge physique différée (action
-- 6.2) des objets soft-deleted (object.deleted_at) ; configurable à chaud
-- via GET/PUT /api/config/purge_grace_period_days, sans redémarrage du
-- backend.
INSERT INTO app_config (key, value) VALUES ('purge_grace_period_days', '30');

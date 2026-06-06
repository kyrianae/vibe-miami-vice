-- Schema des objets
CREATE TABLE object (
    id SERIAL PRIMARY KEY,
    meta_class TEXT NOT NULL,
    class TEXT NOT NULL
);

CREATE TABLE attribute (
    id SERIAL PRIMARY KEY,
    object_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY (object_id) REFERENCES object(id) ON DELETE CASCADE
);

CREATE TABLE attribute_value (
    id SERIAL PRIMARY KEY,
    attribute_id INTEGER NOT NULL,
    value_integer INTEGER,
    value_float DOUBLE PRECISION,
    value_string TEXT,
    joint_id INTEGER,
    FOREIGN KEY (attribute_id) REFERENCES attribute(id) ON DELETE CASCADE,
    FOREIGN KEY (joint_id) REFERENCES object(id) ON DELETE SET NULL,
    CHECK (
        (value_integer IS NOT NULL AND value_float IS NULL AND value_string IS NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NOT NULL AND value_string IS NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NULL AND value_string IS NOT NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NULL AND value_string IS NULL AND joint_id IS NOT NULL)
    )
);

-- Stockage JSON des définitions de classes
CREATE TABLE definition (
    id SERIAL PRIMARY KEY,
    meta_class TEXT NOT NULL UNIQUE,
    data JSONB NOT NULL
);

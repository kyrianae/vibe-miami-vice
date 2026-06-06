CREATE TABLE object (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meta_class TEXT NOT NULL,
    class TEXT NOT NULL
);

CREATE TABLE attribute (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY (object_id) REFERENCES object(id)
);

CREATE TABLE attribute_value (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attribute_id INTEGER NOT NULL,
    value_integer INTEGER,
    value_float REAL,
    value_string TEXT,
    joint_id INTEGER,
    FOREIGN KEY (attribute_id) REFERENCES attribute(id),
    FOREIGN KEY (joint_id) REFERENCES object(id),
    CHECK (
        (value_integer IS NOT NULL AND value_float IS NULL AND value_string IS NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NOT NULL AND value_string IS NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NULL AND value_string IS NOT NULL AND joint_id IS NULL) OR
        (value_integer IS NULL AND value_float IS NULL AND value_string IS NULL AND joint_id IS NOT NULL)
    )
);

-- Insertion d'une personne physique avec nom et prénom
INSERT INTO object (meta_class, class) VALUES ('personne', 'personne_physique');

INSERT INTO attribute (object_id, domain, name) VALUES (1, 'details', 'nom');
INSERT INTO attribute (object_id, domain, name) VALUES (1, 'details', 'prenom');

INSERT INTO attribute_value (attribute_id, value_string) VALUES (1, 'Doe');
INSERT INTO attribute_value (attribute_id, value_string) VALUES (2, 'John');

-- Insertion d'un groupe
INSERT INTO object (meta_class, class) VALUES ('personne', 'groupe');

INSERT INTO attribute (object_id, domain, name) VALUES (2, 'details', 'nom');
INSERT INTO attribute (object_id, domain, name) VALUES (2, 'details', 'membres');

-- Insertion du groupe A-Team avec John Doe comme membre
INSERT INTO object (meta_class, class) VALUES ('personne', 'groupe');

INSERT INTO attribute_value (attribute_id, value_string) VALUES (3, 'A-Team');
INSERT INTO attribute_value (attribute_id, joint_id) VALUES (4, 1);
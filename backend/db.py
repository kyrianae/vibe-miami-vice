import json
import os

import psycopg2
from flask import g

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://miami:vice@localhost:5432/miami_vice")
SCHEMA_PATH = os.environ.get("SCHEMA_PATH", "/model/schema.json")


def get_db():
    """Ouvre une nouvelle connexion à la base de données si aucune n'existe pour le contexte actuel."""
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = False
    return g.db


def close_db(e=None):
    """Ferme la connexion à la base de données à la fin de la requête."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)

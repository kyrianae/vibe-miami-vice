import glob
import json
import os

import jsonschema

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "model")


def test_every_repo_model_file_matches_schema():
    """Non-régression (plan-mark3.md action 17) : chaque model/*.json du dépôt
    (hors schema.json lui-même) doit rester valide contre model/schema.json,
    pour éviter qu'une future extension de modèle casse silencieusement un
    fichier sans que /api/init ne le détecte autrement qu'en "skipped"."""
    schema_path = os.path.join(MODEL_DIR, "schema.json")
    with open(schema_path) as f:
        schema = json.load(f)

    jsonschema.Draft7Validator.check_schema(schema)
    validator = jsonschema.Draft7Validator(schema)

    model_files = sorted(
        f for f in glob.glob(os.path.join(MODEL_DIR, "*.json"))
        if os.path.basename(f) != "schema.json"
    )
    assert model_files, "aucun fichier model/*.json trouvé"

    failures = {}
    for path in model_files:
        with open(path) as f:
            data = json.load(f)
        errors = list(validator.iter_errors(data))
        if errors:
            failures[os.path.basename(path)] = [e.message for e in errors]

    assert failures == {}, failures

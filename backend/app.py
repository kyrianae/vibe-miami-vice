import os

from flask import Flask

from db import get_db, close_db, load_schema  # noqa: F401 (ré-export, cf. plan-mark3.md action 1)
from rbac import AuthContext, get_auth_context, _existing_class_out_of_tenant_scope  # noqa: F401
from auth import require_auth

app = Flask(__name__)

# Limite de taille d'upload (plan-mark3.md action 3, point 5) : une API avec
# authentification mais sans limite de taille de corps reste un vecteur de
# déni de service par remplissage disque, même chose que le refus du depth
# illimité §10.1. 20 Mo par défaut, configurable via MAX_UPLOAD_SIZE_BYTES
# (même pattern que FILE_STORAGE_ROOT/SCHEMA_PATH). Flask/Werkzeug applique
# cette limite à TOUTE requête (pas seulement les routes fichier), en
# s'appuyant sur app.config relu dynamiquement à chaque requête - un test
# peut donc monkeypatcher app.config["MAX_CONTENT_LENGTH"] directement sans
# avoir besoin de relancer le process pour simuler une limite basse.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(20 * 1024 * 1024)))

# Imports des Blueprints après la création de `app` : chaque module
# routes_*.py fait `import app` à son propre niveau module (pour pouvoir
# relire dynamiquement app.get_db/app.get_auth_context à l'intérieur de ses
# fonctions de route, cf. plan-mark3.md action 1, point technique critique
# sur les tests qui monkeypatchent miami_app.get_db/miami_app.get_auth_context),
# mais n'accède à aucun attribut de `app` au niveau module : pas de souci
# d'import circulaire tant que ce fichier importe ces modules après avoir
# défini `app` lui-même.
import routes_read
import routes_write
import routes_init
import routes_admin
import routes_files

# Hook d'authentification et fermeture de la connexion DB : enregistrement
# explicite (plutôt que décorateur) puisque require_auth/close_db sont
# désormais définis dans auth.py/db.py.
app.before_request(require_auth)
app.teardown_appcontext(close_db)

# Enregistrement des Blueprints. Flask applique before_request_funcs[None]
# (require_auth) à toutes les routes quel que soit l'ordre d'enregistrement
# des Blueprints vis-à-vis de l'appel ci-dessus : pas de dépendance d'ordre.
app.register_blueprint(routes_read.read_bp)
app.register_blueprint(routes_write.write_bp)
app.register_blueprint(routes_init.init_bp)
app.register_blueprint(routes_admin.admin_bp)
app.register_blueprint(routes_files.files_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

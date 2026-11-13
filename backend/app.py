from flask import Flask

from db import get_db, close_db, load_schema  # noqa: F401 (ré-export, cf. plan-mark3.md action 1)
from rbac import AuthContext, get_auth_context, _existing_class_out_of_tenant_scope  # noqa: F401
from auth import require_auth

app = Flask(__name__)

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

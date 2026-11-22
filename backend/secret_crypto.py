"""Chiffrement symétrique des attributs de type « secret » (plan-mark3.md
action 8 ; détail de conception : specifications/07-roadmap.md §10.10).

Fichier volontairement autonome (même esprit que file_storage.py /
file_validation.py) : aucun import de app.py/routes_*.py/db.py.

Clé : variable d'environnement `SECRET_ENCRYPTION_KEY`, lue dynamiquement
via `os.environ.get(...)` DANS le corps de chaque fonction publique
(jamais en constante de module figée à l'import) - même pattern que
`FILE_STORAGE_ROOT` (file_storage.py) et `SCHEMA_PATH`/`MODEL_DIR`
(db.py/routes_init.py) : permet aux tests de monkeypatcher la variable
sans recharger le module, et évite de figer une clé dans le process au
chargement, avant qu'un environnement réel ne soit configuré.

Clé UNIQUE globale (pas par tenant, décision utilisateur 2026-11-22) :
un seul secret côté infra à gérer/faire tourner. Un tenant-admin n'a de
toute façon jamais accès au déchiffrement (RBAC strict, voir
routes_read.py, route reveal réservée global-admin) - une clé par tenant
n'apporterait donc aucune isolation supplémentaire ici, pour une
complexité de gestion de clé bien plus grande.

Chiffrement : Fernet (cryptography.fernet), déjà présent dans
requirements.txt - pas de nouvelle dépendance (AES-128-CBC + HMAC-SHA256
authentifié, format avec horodatage + nonce intégrés). Chiffrement
réellement opaque : un attribute_value.value_string issu d'ici n'est
jamais une simple valeur « masquée » réversible sans la clé, il est
cryptographiquement illisible pour quiconque ne la détient pas, y compris
un administrateur de la base de données.

Fernet.encrypt produit un token non déterministe (nonce aléatoire à
chaque appel) : chiffrer deux fois la même valeur en clair produit deux
tokens différents. Conséquence assumée pour l'historisation
(_apply_attribute_diff, routes_write.py) : contrairement aux autres types
scalaires, une resoumission de la même valeur en clair pour un attribut
« secret » n'est JAMAIS dédupliquée (le token chiffré ne matche jamais un
token déjà stocké) - elle ferme systématiquement la version active et en
ouvre une nouvelle, même si le texte en clair n'a pas changé. C'est la
contrepartie normale d'un chiffrement réellement opaque (pas de
comparaison possible sans déchiffrer), pas un bug.

Comportement clé absente/invalide - choix assumé à l'implémentation
(point ouvert de specifications/07-roadmap.md §10.10, tranché ici) :
RUNTIME, PAS fail-fast au démarrage de l'application. Une erreur
explicite (SecretEncryptionKeyError, sous-classe de RuntimeError) n'est
levée qu'au moment effectif d'un chiffrement ou déchiffrement - jamais de
crash au boot de l'API. Raison : rien n'impose qu'un déploiement donné
utilise un attribut de type « secret » dans son modèle ; bloquer TOUT
démarrage de l'API pour une clé non configurée pénaliserait aussi les
déploiements qui n'en ont pas besoin (même philosophie que
FILE_STORAGE_ROOT/SCHEMA_PATH, jamais vérifiés au démarrage). En
contrepartie stricte : aucune valeur en clair n'est jamais stockée, ni
aucun repli silencieux (ex. stocker en clair si la clé manque) - l'appel
échoue net, à charge de l'appelant (routes_write.py/routes_read.py) de le
traduire en réponse HTTP explicite (500), jamais un succès trompeur.
"""
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretEncryptionKeyError(RuntimeError):
    """`SECRET_ENCRYPTION_KEY` absente ou syntaxiquement invalide au moment
    d'une opération de chiffrement/déchiffrement d'un attribut `secret`."""


def _get_fernet():
    raw_key = os.environ.get("SECRET_ENCRYPTION_KEY")
    if not raw_key:
        raise SecretEncryptionKeyError(
            "Variable d'environnement SECRET_ENCRYPTION_KEY absente : "
            "impossible de chiffrer/déchiffrer un attribut de type 'secret'"
        )
    try:
        key_bytes = raw_key.encode("utf-8") if isinstance(raw_key, str) else raw_key
        return Fernet(key_bytes)
    except (ValueError, TypeError) as e:
        raise SecretEncryptionKeyError(
            f"SECRET_ENCRYPTION_KEY invalide (clé Fernet urlsafe-base64 32 octets attendue, "
            f"cf. cryptography.fernet.Fernet.generate_key()) : {e}"
        ) from e


def encrypt_secret(plaintext):
    """Chiffre `plaintext` (str) et retourne le token Fernet (str, ASCII
    urlsafe-base64) destiné à être stocké tel quel dans
    attribute_value.value_string. Lève SecretEncryptionKeyError si la clé
    est absente/invalide - jamais de valeur en clair renvoyée dans ce cas."""
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token):
    """Déchiffre un token produit par `encrypt_secret` et retourne le texte
    en clair (str). Lève SecretEncryptionKeyError si la clé est
    absente/invalide, ValueError si le token ne peut pas être déchiffré
    avec la clé actuelle (corrompu, tronqué, ou chiffré avec une autre
    clé) - dans les deux cas, jamais de valeur partielle ou par défaut
    renvoyée silencieusement."""
    fernet = _get_fernet()
    try:
        token_bytes = token.encode("ascii") if isinstance(token, str) else token
        return fernet.decrypt(token_bytes).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Jeton secret invalide ou clé de déchiffrement incorrecte") from e

"""Validation de contenu + écriture sûre pour les attributs file/image/csv
(plan-mark3.md action 3), partagée entre routes_files.py (upload sur un
objet existant) et routes_write.py (création fusionnée objet+fichier(s),
point A de la revue croisée post-premier-passage).

Module séparé plutôt qu'un import de l'un vers l'autre : routes_files.py
importe déjà `_apply_attribute_diff` depuis routes_write.py - un import
inverse (routes_write.py -> routes_files.py) créerait un cycle au chargement
du module. Ce fichier n'importe ni l'un ni l'autre.

Décision de sécurité SVG (specifications/07-roadmap.md §10.8) : pas de
sanitization du SVG à l'upload (trop fragile sans lib externe dédiée),
accepté tel quel après validation structurelle (XML bien formé, racine
<svg>) - mais parsé via `defusedxml` et non `xml.etree.ElementTree` brut :
un `ET.fromstring` nu sur un contenu non fiable est vulnérable à l'expansion
d'entités XML ("billion laughs", CWE-776, DoS mémoire/CPU). Content-Type
toujours servi en Content-Disposition: attachment pour un SVG en lecture
(routes_files.py), cohérent avec l'absence d'aperçu <img> côté frontend.
"""
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
from flask import abort

_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "svg"}
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def extension_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_image_content(filename, content):
    """Validation stricte du type `image` (plan-mark3.md action 3, point 6) :
    extension dans la liste blanche ET contenu vérifié par signature binaire
    (jpg/png) ou structure XML (svg, via defusedxml). Lève abort(400) sinon."""
    ext = extension_of(filename)
    if ext not in _IMAGE_EXTENSIONS:
        abort(400, description=f"Extension d'image non autorisée : {ext!r} (attendu parmi {sorted(_IMAGE_EXTENSIONS)})")

    if ext in ("jpg", "jpeg"):
        if not content.startswith(_JPEG_MAGIC):
            abort(400, description="Contenu ne correspond pas à la signature JPEG attendue (extension .jpg/.jpeg)")
    elif ext == "png":
        if not content.startswith(_PNG_MAGIC):
            abort(400, description="Contenu ne correspond pas à la signature PNG attendue (extension .png)")
    elif ext == "svg":
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            abort(400, description="Contenu SVG invalide : XML mal formé")
        except DefusedXmlException as e:
            # Entity expansion ("billion laughs"), DTD externe, etc. (CWE-776)
            # - defusedxml lève avant toute expansion mémoire/CPU coûteuse.
            abort(400, description=f"Contenu SVG invalide : construction XML dangereuse rejetée ({e})")
        root_tag = root.tag.rsplit("}", 1)[-1]
        if root_tag != "svg":
            abort(400, description="Contenu SVG invalide : élément racine attendu <svg>")


def validate_csv_content(filename, content):
    """Validation minimale du type `csv` (correction post-revue, point D2) :
    extension .csv obligatoire, contenu décodable en texte (utf-8, repli
    latin-1) - écarte un binaire évident déguisé en .csv. Ne valide pas la
    structure CSV elle-même (nombre de colonnes cohérent, etc., hors
    périmètre de cette passe).

    Note : un décodage latin-1 réussit pour toute séquence d'octets (chaque
    octet 0-255 a un point de code latin-1 valide) - le repli n'échoue donc
    jamais en pratique. Comportement assumé tel quel (demande explicite) :
    seul un contenu rejeté par UTF-8 ET structurellement refusé par les deux
    serait écarté, ce qui ne couvre qu'un sous-ensemble des binaires
    possibles. Validation volontairement faible, pas une détection de
    binaire robuste.
    """
    ext = extension_of(filename)
    if ext != "csv":
        abort(400, description=f"Extension de fichier csv non autorisée : {ext!r} (attendu 'csv')")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content.decode("latin-1")
        except UnicodeDecodeError:
            abort(400, description="Contenu csv illisible : ni UTF-8 ni latin-1 (fichier probablement binaire)")


def save_file_or_400(storage, class_name, object_id, attribute_name, filename, content):
    """Enveloppe `FileStorage.save` : transforme les noms de fichiers limites
    non catchés en amont (correction post-revue, point D1) en 400 propre au
    lieu d'une 500 brute - `"."` (sanitize passe, puis `IsADirectoryError` à
    l'écriture car le chemin résultant désigne le dossier de version
    lui-même) et `\\` (non découpé par `os.path.basename` sous Linux,
    `_sanitize_segment` lève `ValueError`)."""
    try:
        return storage.save(class_name, object_id, attribute_name, filename, content)
    except (ValueError, IsADirectoryError, NotADirectoryError, FileExistsError) as e:
        abort(400, description=f"Nom de fichier invalide pour l'attribut {attribute_name!r} : {e}")

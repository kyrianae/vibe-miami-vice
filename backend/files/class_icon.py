"""Icône de secours générée localement pour une classe sans logo NI icône
choisie manuellement (plan-mark3.md action 4, point 1bis ; détail de
conception : specifications/07-roadmap.md §10.8).

Décision actée (vérification faite le 2026-11-14, voir plan-mark3.md) :
svgrepo.com n'est PAS utilisé. Leur page de recherche est une SPA sans
contenu statique scrappable par une simple requête HTTP, et il n'existe
aucune API `api.svgrepo.com` documentée (404 constaté à la vérification).
Conformément à la clause de repli explicitement prévue par la spec ("si
indisponible/trop fragile, le fallback rond+nom devient le comportement
par défaut permanent, pas un bloqueur, un choix de repli assumé"), ce
module n'implémente AUCUN appel réseau : seul le chemin de repli local
(rond + initiales de la classe) est implémenté, comme comportement par
défaut permanent - pas un filet de sécurité temporaire.

Répartition frontend/backend (à ne pas confondre) :
- Le jeu fixe d'icônes choisies manuellement (champ "icon" du schéma,
  point 1) est entièrement embarqué côté frontend (frontend/src/
  classIcons.tsx) - ce module ne les sert JAMAIS.
- Ce module ne génère/sert QUE le fallback automatique, dernier recours
  avant la couleur de palette (§6.4), pour une classe sans logo ni icône
  manuelle. Route HTTP : GET /api/class_icon/<meta_class>/<class>
  (routes_read.py), appelée par le frontend seulement dans ce cas précis.

Étape d'« homogénéisation » (_normalize_svg) : isolée bien qu'elle ne fasse
aujourd'hui qu'envelopper le SVG généré dans un viewBox fixe (pas de
stroke sur un rond plein + texte) - structuré ainsi pour qu'un futur appel
réseau externe (si jamais une source d'icônes fiable est retenue) puisse
brancher sur cette même étape de normalisation sans réécrire le reste du
module.

Cache : mémoire process (dict, par nom de classe) + fichier sur disque
sous <FILE_STORAGE_ROOT>/_class_icon_cache/<nom_classe>.svg - pas de
nouvelle table SQL (cohérent avec "aucune nouvelle colonne/table par
défaut" de l'action 3) : réutilise la même racine de stockage que
FileStorage (action 2) plutôt qu'un répertoire totalement séparé, sans
pour autant passer par l'API FileStorage (pas de triplet class/object_id/
attribut pertinent ici, une classe n'est pas un objet). Régénéré
uniquement si absent des deux caches.
"""
import hashlib
import os
from xml.sax.saxutils import escape as _xml_escape

ICON_VIEWBOX = "0 0 64 64"
ICON_STROKE_WIDTH = 0  # pas de trait sur un rond plein + texte ; constante
# conservée pour une future étape d'homogénéisation d'un SVG externe
# (normalisation de stroke-width), voir docstring de module.

CLASS_ICON_CACHE_SUBDIR = "_class_icon_cache"

# Dupliquée depuis CLASS_COLORS (frontend/src/pages/DiagramPage.tsx) : mêmes
# 10 valeurs hex, pour une cohérence visuelle entre l'icône de secours
# générée ici et la couleur de palette par classe du diagramme (§6.4).
# Assignation volontairement DIFFÉRENTE de celle du frontend : le frontend
# assigne par index d'apparition parmi les objets chargés en session (non
# déterministe, dépend de l'ordre de chargement) ; ce module doit être
# déterministe par nom de classe seul (même classe -> même couleur, y
# compris entre deux process backend ou deux sessions frontend
# différentes), d'où un hash stable plutôt qu'un index d'apparition.
CLASS_COLORS = (
    "#e06c75", "#61afef", "#98c379", "#c678dd", "#e5c07b",
    "#56b6c2", "#d19a66", "#be5046", "#7ec8e3", "#f0a0c0",
)

_memory_cache = {}


def _color_for_class(class_name):
    """Couleur déterministe (hash stable SHA-256 du nom de classe, indépendant
    du process/de la session) choisie dans CLASS_COLORS."""
    digest = hashlib.sha256(class_name.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(CLASS_COLORS)
    return CLASS_COLORS[index]


def _initials_for_class(class_name):
    """Initiales affichées dans le rond : nom tel quel (majuscules) si <= 4
    caractères visibles, sinon 2 premières lettres de chaque mot distinct (ou
    les 2 premières lettres du seul mot si un seul mot), selon la consigne
    "initiales si le nom dépasse ~3-4 caractères visibles"."""
    cleaned = class_name.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return "?"
    if len(cleaned) <= 4:
        return cleaned.upper()
    words = [w for w in cleaned.split() if w]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return words[0][:2].upper()


def _normalize_svg(inner_markup, viewbox=ICON_VIEWBOX):
    """Étape d'« homogénéisation », isolée pour qu'un futur appel réseau
    externe (non implémenté ici, voir docstring de module) puisse brancher
    dessus sans refactoring : enveloppe le markup interne dans un <svg> au
    viewBox fixe. Rien d'autre à normaliser pour un rond plein + texte (pas
    de stroke, cf. ICON_STROKE_WIDTH)."""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">{inner_markup}</svg>'


def _render_fallback_markup(class_name, color):
    initials = _xml_escape(_initials_for_class(class_name))
    circle = f'<circle cx="32" cy="32" r="30" fill="{color}" stroke-width="{ICON_STROKE_WIDTH}" />'
    text = (
        '<text x="32" y="33" text-anchor="middle" dominant-baseline="central" '
        'font-family="sans-serif" font-size="22" font-weight="600" fill="#ffffff">'
        f"{initials}</text>"
    )
    return circle + text


def _sanitize_cache_filename(class_name):
    """Nom de fichier de cache sûr pour un nom de classe arbitraire - jamais
    de composant de chemin (`/`, `..`) : une classe invalide produit
    simplement un nom de fichier dégradé (pas d'erreur), le pire cas étant
    une régénération superflue, jamais un path traversal."""
    safe = "".join(c if (c.isalnum() or c in ("_", "-", ".")) and c != ".." else "_" for c in class_name)
    return safe or "_"


def _cache_file_path(class_name):
    root = os.environ.get("FILE_STORAGE_ROOT", "/data/files")
    return os.path.join(root, CLASS_ICON_CACHE_SUBDIR, f"{_sanitize_cache_filename(class_name)}.svg")


def generate_class_fallback_icon(class_name):
    """Retourne le SVG (str) de secours pour `class_name` : rond uni (couleur
    déterministe, voir _color_for_class) avec les initiales de la classe
    centrées dedans (voir _initials_for_class). Mis en cache (mémoire process
    puis disque) : généré une seule fois par nom de classe, jamais recalculé
    à chaque requête."""
    cached = _memory_cache.get(class_name)
    if cached is not None:
        return cached

    cache_path = _cache_file_path(class_name)
    if os.path.isfile(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            svg = f.read()
        _memory_cache[class_name] = svg
        return svg

    color = _color_for_class(class_name)
    svg = _normalize_svg(_render_fallback_markup(class_name, color))

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(svg)
    _memory_cache[class_name] = svg
    return svg

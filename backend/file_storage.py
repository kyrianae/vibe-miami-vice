"""Interface de stockage de fichiers (action 2, plan-mark3.md ; détail de
conception : specifications/07-roadmap.md §10.7).

Prérequis bloquant pour les attributs « fichier » (tocheck.md #14),
« image » (#15) et le logo surchargeable par objet (#16) : définit
comment stocker des fichiers liés à un objet, avec une arborescence
`/class/id/attribut/version`, derrière une interface abstraite
remplaçable par une implémentation S3/MinIO plus tard sans modifier le
code appelant.

Fichier volontairement autonome : aucun import de app.py/routes_*.py/
db.py. Pas de route HTTP, pas de câblage à un type d'attribut ici — ça
reste le périmètre de #14 (action future, distincte).
"""
import os
import shutil
from abc import ABC, abstractmethod

FILE_STORAGE_ROOT = os.environ.get("FILE_STORAGE_ROOT", "/data/files")


class FileStorage(ABC):
    """Interface abstraite de stockage de fichiers versionnés, liés à un
    triplet (classe, identifiant d'objet, nom d'attribut)."""

    @abstractmethod
    def save(self, class_name, object_id, attribute_name, filename, content):
        """Enregistre `content` (bytes) comme nouvelle version de l'attribut
        `attribute_name` de l'objet (class_name, object_id), sous le nom
        `filename`. Retourne le numéro de version créé (int)."""
        raise NotImplementedError

    @abstractmethod
    def read(self, class_name, object_id, attribute_name, version, filename):
        """Lit et retourne le contenu (bytes) de la version `version` de
        l'attribut `attribute_name` de l'objet (class_name, object_id).
        Lève FileNotFoundError si le fichier n'existe pas."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, class_name, object_id, attribute_name, version=None):
        """Supprime une version précise (si `version` fourni) ou tout
        l'historique de versions de l'attribut (si `version` est None).
        N'échoue pas si l'élément visé est déjà absent."""
        raise NotImplementedError

    @abstractmethod
    def list_versions(self, class_name, object_id, attribute_name):
        """Retourne la liste triée (croissante) des numéros de version
        existants pour ce triplet. Liste vide si aucune version."""
        raise NotImplementedError

    @abstractmethod
    def list_all(self):
        """Énumère TOUT le contenu du stockage, tous objets/attributs
        confondus : liste de tuples (class_name, object_id, attribute_name,
        version, filename). Coûteux (parcours complet), réservé à la
        maintenance (sweep des fichiers orphelins, plan-mark3.md action 3
        point B de la revue croisée) - jamais appelé par le chemin
        d'écriture/lecture normal, qui connaît toujours son triplet cible
        à l'avance."""
        raise NotImplementedError


def _sanitize_segment(value, segment_name):
    """Interdit tout composant de chemin dangereux dans un segment de
    l'arborescence (class_name, object_id, attribute_name ou filename).

    Ces segments proviennent potentiellement d'une entrée utilisateur non
    fiable (nom d'attribut ou nom de fichier choisi côté appelant) : on
    applique la même règle stricte à tous les segments plutôt que de ne
    sanitizer que `filename`, pour éviter qu'un path traversal se glisse
    par un autre segment (ex. un `object_id` ou `attribute_name` mal
    contrôlé en amont).

    Refuse (ValueError) : valeur vide, chemin absolu, présence de `..`, ou
    présence d'un séparateur de chemin (`/`, `os.sep`, et `\\` par
    prudence vis-à-vis d'un usage multi-OS potentiel).
    """
    value = str(value)
    if not value:
        raise ValueError(f"{segment_name} ne peut pas être vide")
    if ".." in value:
        raise ValueError(f"{segment_name} ne peut pas contenir '..'")
    if "/" in value or "\\" in value or (os.sep != "/" and os.sep in value):
        raise ValueError(f"{segment_name} ne peut pas contenir de séparateur de chemin")
    if os.path.isabs(value):
        raise ValueError(f"{segment_name} ne peut pas être un chemin absolu")
    if os.path.basename(value) != value:
        raise ValueError(f"{segment_name} invalide")
    return value


class LocalFileStorage(FileStorage):
    """Implémentation à plat de `FileStorage` : stockage sur le système de
    fichiers local, racine configurable via `FILE_STORAGE_ROOT`.

    Arborescence : <root>/<class>/<object_id>/<attribute_name>/<version>/
    <filename>.

    Versionnement : entier incrémental déterminé par listing des
    sous-dossiers numériques existants dans
    <root>/<class>/<object_id>/<attribute_name>/ — aucun compteur en
    mémoire ni en base, le filesystem fait foi. Nouvelle version = max
    existant + 1 (ou 1 si aucune version). Jamais d'écrasement d'une
    version déjà écrite.
    """

    def __init__(self, root=None):
        # Relecture de la variable d'environnement à l'instanciation (pas au
        # chargement du module) : permet aux tests de monkeypatcher
        # FILE_STORAGE_ROOT avant de créer l'instance, comme MODEL_DIR dans
        # routes_init.py (lu dans le corps de la fonction, pas en constante
        # de module figée à l'import).
        self.root = root if root is not None else os.environ.get("FILE_STORAGE_ROOT", "/data/files")

    def _attribute_dir(self, class_name, object_id, attribute_name):
        class_name = _sanitize_segment(class_name, "class_name")
        object_id = _sanitize_segment(object_id, "object_id")
        attribute_name = _sanitize_segment(attribute_name, "attribute_name")
        return os.path.join(self.root, class_name, str(object_id), attribute_name)

    def _existing_versions(self, attribute_dir):
        if not os.path.isdir(attribute_dir):
            return []
        versions = []
        for entry in os.listdir(attribute_dir):
            if entry.isdigit():
                versions.append(int(entry))
        return sorted(versions)

    def save(self, class_name, object_id, attribute_name, filename, content):
        filename = _sanitize_segment(filename, "filename")
        attribute_dir = self._attribute_dir(class_name, object_id, attribute_name)
        existing = self._existing_versions(attribute_dir)
        new_version = (existing[-1] + 1) if existing else 1

        version_dir = os.path.join(attribute_dir, str(new_version))
        os.makedirs(version_dir, exist_ok=True)

        filepath = os.path.join(version_dir, filename)
        with open(filepath, "wb") as f:
            f.write(content)

        return new_version

    def read(self, class_name, object_id, attribute_name, version, filename):
        filename = _sanitize_segment(filename, "filename")
        attribute_dir = self._attribute_dir(class_name, object_id, attribute_name)
        filepath = os.path.join(attribute_dir, str(version), filename)
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Fichier introuvable : {filepath}")
        with open(filepath, "rb") as f:
            return f.read()

    def delete(self, class_name, object_id, attribute_name, version=None):
        attribute_dir = self._attribute_dir(class_name, object_id, attribute_name)
        if version is None:
            target = attribute_dir
        else:
            target = os.path.join(attribute_dir, str(version))
        shutil.rmtree(target, ignore_errors=True)

    def list_versions(self, class_name, object_id, attribute_name):
        attribute_dir = self._attribute_dir(class_name, object_id, attribute_name)
        return self._existing_versions(attribute_dir)

    def list_all(self):
        results = []
        if not os.path.isdir(self.root):
            return results
        for class_name in os.listdir(self.root):
            class_path = os.path.join(self.root, class_name)
            if not os.path.isdir(class_path):
                continue
            for object_dir in os.listdir(class_path):
                if not object_dir.isdigit():
                    continue
                object_path = os.path.join(class_path, object_dir)
                if not os.path.isdir(object_path):
                    continue
                object_id = int(object_dir)
                for attribute_name in os.listdir(object_path):
                    attribute_path = os.path.join(object_path, attribute_name)
                    if not os.path.isdir(attribute_path):
                        continue
                    for version_dir in os.listdir(attribute_path):
                        if not version_dir.isdigit():
                            continue
                        version_path = os.path.join(attribute_path, version_dir)
                        if not os.path.isdir(version_path):
                            continue
                        version = int(version_dir)
                        for filename in os.listdir(version_path):
                            filepath = os.path.join(version_path, filename)
                            if os.path.isfile(filepath):
                                results.append((class_name, object_id, attribute_name, version, filename))
        return results

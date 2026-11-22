"""Tests de `backend/file_storage.py` (action 2, plan-mark3.md ; détail de
conception : specifications/07-roadmap.md §10.7).

Racine de stockage isolée par test via `tmp_path` +
`monkeypatch.setenv("FILE_STORAGE_ROOT", str(tmp_path))`, même pattern que
`MODEL_DIR` dans test_model_driven_typing.py.

Lancer depuis la racine du dépôt :

    .venv/bin/pytest backend/tests/test_file_storage.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from files.file_storage import LocalFileStorage  # noqa: E402


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_ROOT", str(tmp_path))
    return LocalFileStorage()


# ---------------------------------------------------------------------
# Round-trip save/read
# ---------------------------------------------------------------------

def test_save_read_round_trip(storage):
    version = storage.save("personne", "42", "photo", "avatar.png", b"\x89PNG\x0d\x0a")
    assert version == 1
    content = storage.read("personne", "42", "photo", version, "avatar.png")
    assert content == b"\x89PNG\x0d\x0a"


# ---------------------------------------------------------------------
# Versions multiples incrémentales
# ---------------------------------------------------------------------

def test_multiple_versions_incremental_and_independently_readable(storage):
    v1 = storage.save("personne", "42", "cv", "cv.pdf", b"contenu v1")
    v2 = storage.save("personne", "42", "cv", "cv.pdf", b"contenu v2")
    assert v1 == 1
    assert v2 == 2

    assert storage.read("personne", "42", "cv", v1, "cv.pdf") == b"contenu v1"
    assert storage.read("personne", "42", "cv", v2, "cv.pdf") == b"contenu v2"


def test_multiple_versions_do_not_overwrite_each_other_on_disk(storage, tmp_path):
    storage.save("personne", "42", "cv", "cv.pdf", b"contenu v1")
    storage.save("personne", "42", "cv", "cv.pdf", b"contenu v2")

    assert os.path.isfile(tmp_path / "personne" / "42" / "cv" / "1" / "cv.pdf")
    assert os.path.isfile(tmp_path / "personne" / "42" / "cv" / "2" / "cv.pdf")


# ---------------------------------------------------------------------
# Refus de nom de fichier dangereux (path traversal)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("dangerous_filename", [
    "../../etc/passwd",
    "/etc/passwd",
    "..",
    "sub/dir/file.txt",
])
def test_save_rejects_dangerous_filename(storage, tmp_path, dangerous_filename):
    with pytest.raises(ValueError):
        storage.save("personne", "42", "photo", dangerous_filename, b"contenu")

    for root, _dirs, files in os.walk(tmp_path):
        for f in files:
            assert False, f"fichier écrit en dehors du flux attendu : {os.path.join(root, f)}"


@pytest.mark.parametrize("dangerous_filename", [
    "../../etc/passwd",
    "/etc/passwd",
    "..",
    "sub/dir/file.txt",
])
def test_read_rejects_dangerous_filename(storage, dangerous_filename):
    with pytest.raises(ValueError):
        storage.read("personne", "42", "photo", 1, dangerous_filename)


# ---------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------

def test_delete_single_version_removes_it_but_keeps_others(storage):
    v1 = storage.save("personne", "42", "cv", "cv.pdf", b"contenu v1")
    v2 = storage.save("personne", "42", "cv", "cv.pdf", b"contenu v2")

    storage.delete("personne", "42", "cv", version=v1)

    with pytest.raises(FileNotFoundError):
        storage.read("personne", "42", "cv", v1, "cv.pdf")

    assert storage.read("personne", "42", "cv", v2, "cv.pdf") == b"contenu v2"


def test_delete_without_version_removes_whole_history(storage):
    storage.save("personne", "42", "cv", "cv.pdf", b"contenu v1")
    storage.save("personne", "42", "cv", "cv.pdf", b"contenu v2")

    storage.delete("personne", "42", "cv")

    assert storage.list_versions("personne", "42", "cv") == []


def test_delete_already_absent_does_not_raise(storage):
    storage.delete("personne", "999", "cv", version=5)
    storage.delete("personne", "999", "cv")


# ---------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------

def test_list_versions_empty_before_any_save(storage):
    assert storage.list_versions("personne", "42", "cv") == []


def test_list_versions_sorted_after_multiple_saves(storage):
    storage.save("personne", "42", "cv", "cv.pdf", b"v1")
    storage.save("personne", "42", "cv", "cv.pdf", b"v2")
    storage.save("personne", "42", "cv", "cv.pdf", b"v3")

    assert storage.list_versions("personne", "42", "cv") == [1, 2, 3]


def test_list_versions_after_partial_delete(storage):
    storage.save("personne", "42", "cv", "cv.pdf", b"v1")
    storage.save("personne", "42", "cv", "cv.pdf", b"v2")
    storage.save("personne", "42", "cv", "cv.pdf", b"v3")

    storage.delete("personne", "42", "cv", version=2)

    assert storage.list_versions("personne", "42", "cv") == [1, 3]


def test_list_versions_independent_per_attribute_and_object(storage):
    storage.save("personne", "42", "cv", "cv.pdf", b"a")
    storage.save("personne", "42", "photo", "p.png", b"b")
    storage.save("personne", "43", "cv", "cv.pdf", b"c")

    assert storage.list_versions("personne", "42", "cv") == [1]
    assert storage.list_versions("personne", "42", "photo") == [1]
    assert storage.list_versions("personne", "43", "cv") == [1]

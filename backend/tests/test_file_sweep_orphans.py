"""Tests ciblés plan-mark3.md action 3 (correction post-revue croisée, point
B) : sweep de maintenance des fichiers orphelins du stockage
(POST /api/admin/sweep_orphan_files, routes_admin.py).

Réutilise les fixtures/CLASSES de test_file_attribute_type.py (db_and_ctx,
client, isolated_storage_root) plutôt que de redéfinir un FakeDB/FakeConn :
le sweep s'appuie sur exactement les mêmes requêtes attribute/attribute_value
que le reste du module fichier, déjà gérées par FileFakeCursor (y compris la
requête de correspondance pointeur ajoutée pour ce sweep).

Lancer avec, depuis la racine du dépôt :
    SCHEMA_PATH="$(pwd)/model/schema.json" .venv/bin/pytest backend/tests/test_file_sweep_orphans.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as miami_app  # noqa: E402
from test_model_driven_typing import make_ctx  # noqa: E402
from test_file_attribute_type import (  # noqa: E402,F401
    client,
    db_and_ctx,
    isolated_storage_root,
    _create_dossier,
    _upload,
)
from files.file_storage import LocalFileStorage  # noqa: E402


def test_sweep_removes_file_never_indexed_in_db(client, db_and_ctx, isolated_storage_root):
    object_id = _create_dossier(client)
    _upload(client, object_id, "piece_jointe", "v1.txt", b"contenu v1")

    # Simule un fichier écrit sur disque sans jamais avoir été indexé en
    # base (crash entre FileStorage.save et le commit, cf. routes_write.py
    # _write_object_multipart/_cleanup_saved_files) : appel direct à
    # FileStorage.save, jamais via la route d'upload (qui, elle, indexe
    # toujours en même temps).
    storage = LocalFileStorage()
    orphan_version = storage.save("dossier", object_id, "piece_jointe", "orphan.txt", b"jamais indexe")
    assert orphan_version == 2

    resp = storage.list_all()
    assert len(resp) == 2

    sweep_resp = client.post("/api/admin/sweep_orphan_files")
    assert sweep_resp.status_code == 200, sweep_resp.get_data(as_text=True)
    purged = sweep_resp.get_json()["purged"]
    assert len(purged) == 1
    assert purged[0]["version"] == 2
    assert purged[0]["filename"] == "orphan.txt"

    remaining = storage.list_all()
    assert len(remaining) == 1
    assert remaining[0][3] == 1  # version indexée conservée

    # Le fichier indexé reste lisible normalement après le sweep.
    get_resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe")
    assert get_resp.status_code == 200
    assert get_resp.data == b"contenu v1"


def test_sweep_keeps_historized_closed_version_within_grace_window(client, db_and_ctx, isolated_storage_root):
    object_id = _create_dossier(client)
    _upload(client, object_id, "piece_jointe", "v1.txt", b"contenu v1")
    _upload(client, object_id, "piece_jointe", "v2.txt", b"contenu v2")

    storage = LocalFileStorage()
    assert len(storage.list_all()) == 2

    sweep_resp = client.post("/api/admin/sweep_orphan_files")
    assert sweep_resp.status_code == 200
    assert sweep_resp.get_json()["purged"] == []

    remaining = storage.list_all()
    assert len(remaining) == 2, "la version 1 (fermée/historisée) doit être conservée, pas seulement la version active"

    v1_resp = client.get(f"/api/read/object/{object_id}/file/piece_jointe?version=1")
    assert v1_resp.status_code == 200
    assert v1_resp.data == b"contenu v1"


def test_sweep_no_orphan_is_a_noop(client, db_and_ctx, isolated_storage_root):
    object_id = _create_dossier(client)
    _upload(client, object_id, "piece_jointe", "v1.txt", b"contenu v1")

    resp = client.post("/api/admin/sweep_orphan_files")
    assert resp.status_code == 200
    assert resp.get_json()["purged_count"] == 0

    storage = LocalFileStorage()
    assert len(storage.list_all()) == 1


@pytest.mark.parametrize("ctx_kwargs", [
    {"is_tenant_admin": True, "tenants": ["tenant1"]},
    {"is_tenant_readonly": True, "tenants": ["tenant1"]},
])
def test_sweep_rbac_rejected_for_non_global_admin(client, db_and_ctx, isolated_storage_root, monkeypatch, ctx_kwargs):
    monkeypatch.setattr(miami_app, "get_auth_context", lambda: make_ctx(**ctx_kwargs))
    resp = client.post("/api/admin/sweep_orphan_files")
    assert resp.status_code == 403


def test_sweep_rbac_allowed_for_global_admin(client, db_and_ctx, isolated_storage_root):
    resp = client.post("/api/admin/sweep_orphan_files")
    assert resp.status_code == 200

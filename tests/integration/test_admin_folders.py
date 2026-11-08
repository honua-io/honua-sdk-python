"""Folder lifecycle on an explicitly supplied disposable Service."""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from honua_admin import HonuaAdminClient
from honua_sdk import HonuaHttpError

pytestmark = [pytest.mark.integration, pytest.mark.staging, pytest.mark.smoke]


def _find_service(admin, service_name):
    service = next((item for item in admin.list_services() if item.service_name == service_name), None)
    if service is None:
        pytest.fail("HONUA_FOLDER_TEST_SERVICE must name an existing disposable Service")
    return service


@pytest.fixture
def folder_admin(smoke_config):
    service_name = os.environ.get("HONUA_FOLDER_TEST_SERVICE")
    if not smoke_config.enable_write_smoke or not service_name:
        pytest.skip("Folder writes require write smoke and an explicit disposable Service")
    with HonuaAdminClient(smoke_config.base_url, api_key=smoke_config.api_key) as admin:
        service = _find_service(admin, service_name)
        assert service.folder_id is None, "The disposable Service must start in Root"
        _, etag = admin.list_folders()
        assert etag is not None
        folder, created_etag = admin.create_folder("Sdk" + uuid4().hex[:16], title="SDK live Folder", if_match=etag)
        try:
            yield admin, service_name, folder, etag, created_etag
        finally:
            _, cleanup_etag = admin.list_folders()
            current = _find_service(admin, service_name)
            if current.folder_id == folder.metadata.id:
                assert cleanup_etag is not None
                cleanup_etag = admin.move_service(service_name, None, if_match=cleanup_etag)
            remaining, cleanup_etag = admin.list_folders()
            if any(item.metadata.id == folder.metadata.id for item in remaining):
                assert cleanup_etag is not None
                admin.delete_folder(folder.metadata.id, if_match=cleanup_etag)


def test_admin_folder_lifecycle_persists_membership_aliases_and_preconditions(folder_admin, smoke_config) -> None:
    admin, service_name, folder, old_etag, etag = folder_admin
    assert etag is not None
    assert folder.metadata.title == "SDK live Folder"
    with pytest.raises(HonuaHttpError) as stale:
        admin.update_folder(folder.metadata.id, title="Stale", if_match=old_etag)
    assert stale.value.status_code == 412
    assert admin.list_folders()[1] == etag
    etag = admin.move_service(service_name, folder.metadata.id, if_match=etag)
    current = _find_service(admin, service_name)
    assert current.folder_id == folder.metadata.id
    assert current.folder_name == folder.metadata.name
    assert etag is not None
    with pytest.raises(HonuaHttpError) as non_empty:
        admin.delete_folder(folder.metadata.id, if_match=etag)
    assert non_empty.value.status_code == 409
    renamed, etag = admin.update_folder(folder.metadata.id, name=folder.metadata.name + "Renamed", title=None, if_match=etag)
    assert renamed.metadata.title is None
    assert folder.metadata.name in renamed.previous_names
    assert etag is not None
    etag = admin.move_service(service_name, None, if_match=etag)
    assert etag is not None
    admin.delete_folder(folder.metadata.id, if_match=etag)
    assert all(item.metadata.id != folder.metadata.id for item in admin.list_folders()[0])
    assert _find_service(admin, service_name).folder_id is None
    # Saved connections keep using the old Folder path after rename and deletion.
    public_name = current.public_name or service_name
    path = f"{smoke_config.base_url.rstrip('/')}/rest/services/{folder.metadata.name}/{public_name}/FeatureServer"
    headers = {"X-API-Key": smoke_config.api_key} if smoke_config.api_key else {}
    response = httpx.get(path, params={"f": "json"}, headers=headers)
    assert response.status_code == 200, response.text
    assert "error" not in response.json()

"""Folder metadata and optimistic concurrency on both Admin clients."""

from __future__ import annotations

import inspect
import json
from types import EllipsisType

import httpx
import pytest

from honua_admin import AdminServiceSummary, AsyncHonuaAdminClient, HonuaAdminClient, PublishLayerRequest
from honua_sdk import HonuaHttpError

from .conftest import make_api_response


def _folder_response(request: httpx.Request, namespace: str | None) -> httpx.Response:
    assert request.method == "GET"
    assert request.url.path == "/api/v1/admin/folders"
    assert request.url.params.get("namespace") == namespace
    return httpx.Response(
        200,
        headers={"ETag": '"catalog-17"'},
        json=make_api_response([
            {
                "metadata": {"id": "folder-1", "name": "Survey", "title": "Field survey", "tenant": None},
                "previousNames": ["SurveyOld"],
                "deleted": False,
            },
        ]),
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("namespace", [None, "", "workspace"])
async def test_list_folders_preserves_metadata_namespace_and_snapshot_etag(asynchronous: bool, namespace: str | None) -> None:
    client_type = AsyncHonuaAdminClient if asynchronous else HonuaAdminClient
    client = client_type("http://test.honua.io", transport=httpx.MockTransport(lambda request: _folder_response(request, namespace)))
    try:
        result = client.list_folders(namespace=namespace)
        if inspect.isawaitable(result):
            result = await result
        folders, etag = result
        assert etag == '\"catalog-17\"'
        assert len(folders) == 1
        assert folders[0].metadata.id == "folder-1"
        assert folders[0].metadata.name == "Survey"
        assert folders[0].metadata.title == "Field survey"
        assert folders[0].metadata.tenant is None
        assert folders[0].previous_names == ["SurveyOld"]
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(("operation", "folder_id"), [("create", None), ("update", None), ("delete", None), ("move", None), ("move", "folder-1")])
async def test_folder_mutations_send_preconditions_and_preserve_returned_etag(asynchronous: bool, operation: str, folder_id: str | None) -> None:
    methods = {"create": "POST", "update": "PATCH", "delete": "DELETE", "move": "PUT"}
    paths = {
        "create": "/api/v1/admin/folders", "update": "/api/v1/admin/folders/folder-1",
        "delete": "/api/v1/admin/folders/folder-1", "move": "/api/v1/admin/services/test/folder",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == methods[operation]
        assert request.url.path == paths[operation]
        assert request.url.params["namespace"] == "workspace"
        assert request.headers["If-Match"] == '"catalog-17"'
        if operation in {"create", "update"}:
            assert json.loads(request.content) == {"name": "Survey", "title": "Field survey"}
            return httpx.Response(
                201 if operation == "create" else 200,
                headers={"ETag": '"catalog-18"'},
                json=make_api_response({"metadata": {"id": "folder-1", "name": "Survey", "title": "Field survey"}}),
            )
        if operation == "move":
            assert json.loads(request.content) == {"folderId": folder_id}
        return httpx.Response(204, headers={"ETag": '"catalog-18"'})

    client_type = AsyncHonuaAdminClient if asynchronous else HonuaAdminClient
    client = client_type("http://test.honua.io", transport=httpx.MockTransport(handler))
    options = {"if_match": '"catalog-17"', "namespace": "workspace"}
    try:
        if operation == "create":
            result = client.create_folder("Survey", title="Field survey", **options)
        elif operation == "update":
            result = client.update_folder("folder-1", name="Survey", title="Field survey", **options)
        elif operation == "delete":
            result = client.delete_folder("folder-1", **options)
        else:
            result = client.move_service("test", folder_id, **options)
        if inspect.isawaitable(result):
            result = await result
        if operation in {"create", "update"}:
            folder, etag = result
            assert folder.metadata.id == "folder-1"
            assert folder.metadata.name == "Survey"
            assert folder.metadata.title == "Field survey"
        else:
            etag = result
        assert etag == '"catalog-18"'
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.parametrize("title", [Ellipsis, None, "New title"])
def test_update_folder_distinguishes_omitted_title_from_clearing(make_client, title: str | EllipsisType | None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        expected = {} if title is Ellipsis else {"title": title}
        assert json.loads(request.content) == expected
        assert "namespace" not in request.url.params
        return httpx.Response(200, json=make_api_response({"metadata": {"id": "folder-1", "name": "Survey"}}))

    with make_client(handler) as client:
        options = {} if title is Ellipsis else {"title": title}
        client.update_folder("folder-1", if_match='"catalog-17"', **options)


@pytest.mark.parametrize("status", [403, 409, 412, 428])
def test_create_folder_preserves_http_error(make_client, status: int) -> None:
    with make_client(lambda _: httpx.Response(status, json={"detail": "Refresh the catalog and retry."})) as client:
        with pytest.raises(HonuaHttpError) as caught:
            client.create_folder("Survey", if_match='"catalog-17"')
    assert caught.value.status_code == status


@pytest.mark.parametrize("organized", [False, True])
def test_service_summary_preserves_folder_and_display_metadata(organized: bool) -> None:
    body = {"serviceName": "logical-parcels", "description": "", "layerCount": 1, "enabledProtocols": ["FeatureServer"]}
    if organized:
        body.update({"folderId": "folder-1", "folderName": "Survey", "publicName": "Parcels", "title": "Field parcels",
                     "folderMutationIssues": ["Retired path is reserved."]})
    result = AdminServiceSummary.from_dict(body)
    assert result.service_name == "logical-parcels"
    assert result.folder_id == ("folder-1" if organized else None)
    assert result.folder_name == ("Survey" if organized else None)
    assert result.public_name == ("Parcels" if organized else None)
    assert result.title == ("Field parcels" if organized else None)
    assert result.folder_mutation_issues == (["Retired path is reserved."] if organized else [])


def test_publish_layer_legacy_defaults_preserve_wire_body() -> None:
    assert PublishLayerRequest(table="parcels").to_dict() == {"schema": "public", "table": "parcels", "enabled": True}


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("folder_id", [Ellipsis, None, "folder-1"])
async def test_publish_layer_preserves_omitted_root_and_folder_choices(asynchronous: bool, folder_id) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/admin/connections/conn-1/layers"
        body = json.loads(request.content)
        assert body["serviceName"] == "logical-parcels"
        assert body["publicName"] == "Parcels"
        if folder_id is Ellipsis:
            assert "folderId" not in body
        else:
            assert body["folderId"] == folder_id
        return httpx.Response(200, json=make_api_response({
            "storageLayerId": 4, "layerName": "Parcels", "schema": "public", "table": "parcels", "description": None,
            "geometryType": "Point", "srid": 4326, "primaryKey": "id", "fieldCount": 1, "enabled": True,
            "serviceName": "logical-parcels",
        }))

    selection = {} if folder_id is Ellipsis else {"folder_id": folder_id}
    publication = PublishLayerRequest(table="parcels", service_name="logical-parcels", public_name="Parcels", **selection)
    client_type = AsyncHonuaAdminClient if asynchronous else HonuaAdminClient
    client = client_type("http://test.honua.io", transport=httpx.MockTransport(handler))
    try:
        result = client.publish_layer("conn-1", publication)
        if inspect.isawaitable(result):
            result = await result
        assert result.service_name == "logical-parcels"
        assert result.storage_layer_id == 4
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("operation", ["update", "delete", "move"])
async def test_folder_mutations_encode_each_logical_path_segment(asynchronous: bool, operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        expected = b"/api/v1/admin/services/a%2Fb%20c/folder" if operation == "move" else b"/api/v1/admin/folders/f%2F1"
        assert request.url.raw_path == expected
        if operation == "move":
            assert json.loads(request.content) == {"folderId": "f/1"}
        return httpx.Response(200, json=make_api_response({"metadata": {"id": "f/1", "name": "Survey"}}))

    client_type = AsyncHonuaAdminClient if asynchronous else HonuaAdminClient
    client = client_type("http://test.honua.io", transport=httpx.MockTransport(handler))
    try:
        if operation == "move":
            result = client.move_service("a/b c", "f/1", if_match='"catalog-17"')
        elif operation == "update":
            result = client.update_folder("f/1", name="Survey", if_match='"catalog-17"')
        else:
            result = client.delete_folder("f/1", if_match='"catalog-17"')
        if inspect.isawaitable(result):
            await result
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()

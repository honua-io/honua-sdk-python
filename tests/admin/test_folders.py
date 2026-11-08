"""Folder metadata and optimistic concurrency on both Admin clients."""

from __future__ import annotations

import httpx
import pytest

from honua_admin import AsyncHonuaAdminClient

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


@pytest.mark.parametrize("namespace", [None, "workspace"])
def test_list_folders_preserves_metadata_namespace_and_snapshot_etag(make_client, namespace: str | None) -> None:
    with make_client(lambda request: _folder_response(request, namespace)) as client:
        folders, etag = client.list_folders(namespace=namespace)
    assert etag == '"catalog-17"'
    assert len(folders) == 1
    assert folders[0].metadata.id == "folder-1"
    assert folders[0].metadata.name == "Survey"
    assert folders[0].metadata.title == "Field survey"
    assert folders[0].metadata.tenant is None
    assert folders[0].previous_names == ["SurveyOld"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("namespace", [None, "workspace"])
async def test_async_list_folders_preserves_metadata_namespace_and_snapshot_etag(namespace: str | None) -> None:
    transport = httpx.MockTransport(lambda request: _folder_response(request, namespace))
    async with AsyncHonuaAdminClient("http://test.honua.io", transport=transport) as client:
        folders, etag = await client.list_folders(namespace=namespace)
    assert etag == '"catalog-17"'
    assert len(folders) == 1
    assert folders[0].metadata.id == "folder-1"
    assert folders[0].metadata.name == "Survey"
    assert folders[0].metadata.title == "Field survey"
    assert folders[0].metadata.tenant is None
    assert folders[0].previous_names == ["SurveyOld"]

"""Public catalog paths round-trip through the shared GeoServices adapters."""

from __future__ import annotations

import inspect

import httpx
import pytest

import honua_sdk
from honua_sdk import AsyncHonuaClient, HonuaClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("public_path", ["Parcels", "Survey/Parcels"])
@pytest.mark.parametrize("operation", ["query", "metadata", "edit", "export"])
async def test_geoservices_uses_public_path_at_each_adapter(asynchronous: bool, public_path: str, operation: str) -> None:
    suffixes = {"query": "FeatureServer/0/query", "metadata": "FeatureServer", "edit": "FeatureServer/0/applyEdits", "export": "MapServer/export"}

    def handler(request: httpx.Request) -> httpx.Response:
        expected = f"/rest/services/{public_path}/{suffixes[operation]}".encode()
        assert request.url.raw_path.split(b"?")[0] == expected
        if operation == "edit":
            return httpx.Response(200, json={"addResults": [{"objectId": 1, "success": True}]})
        return httpx.Response(200, json={"features": [], "layers": [], "href": "https://example.invalid/map.png"})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("http://test.honua.io", transport=httpx.MockTransport(handler))
    try:
        service_type = "MapServer" if operation == "export" else "FeatureServer"
        service = public_path if "/" not in public_path else honua_sdk.ServiceAddress(f"http://test.honua.io/rest/services/{public_path}/{service_type}")
        if operation == "query":
            result = client.query_features(service, 0)
        elif operation == "metadata":
            result = client.feature_server(service).metadata()
        elif operation == "edit":
            result = client.apply_edits(service, 0, adds=[{"attributes": {"name": "Parcel"}}])
        else:
            result = client.export_map(service, [0, 0, 1, 1])
        if inspect.isawaitable(result):
            await result
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_folder_catalog_returns_public_service_paths(asynchronous: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path.split(b"?")[0] == b"/rest/services/Survey"
        return httpx.Response(200, json={"services": [{"name": "Survey/Parcels", "type": "FeatureServer"}]})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("http://test.honua.io", transport=httpx.MockTransport(handler))
    try:
        result = client.list_services(folder_name="Survey")
        if inspect.isawaitable(result):
            result = await result
        assert result["services"][0]["name"] == "Survey/Parcels"
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()

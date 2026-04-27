from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import CallableAuthProvider
from honua_sdk.async_client import AsyncHonuaClient
from honua_sdk.errors import HonuaHttpError


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio


async def test_query_features_builds_expected_request() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"features": []})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        response = await client.query_features(
            "default",
            2,
            where="objectid > 10",
            out_fields=["objectid", "name"],
            return_geometry=False,
        )

    assert response == {"features": []}
    assert seen["method"] == "GET"
    assert seen["path"] == "/rest/services/default/FeatureServer/2/query"
    assert seen["query"]["f"] == "json"
    assert seen["query"]["where"] == "objectid > 10"
    assert seen["query"]["outFields"] == "objectid,name"
    assert seen["query"]["returnGeometry"] == "false"


async def test_list_services_returns_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/services"
        return httpx.Response(200, json={"services": [{"name": "s1"}]})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        response = await client.list_services()

    assert response == {"services": [{"name": "s1"}]}


async def test_ogc_features_items_builds_expected_request() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["raw_path"] = request.url.raw_path.decode("ascii").split("?")[0]
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [{"type": "Feature"}]})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        response = await client.ogc_features().collection("team alpha/parcels").items(
            limit=25,
            offset=5,
            bbox="-158,21,-157,22",
            filter="status = 'active'",
            properties=["name", "status"],
        )

    assert response["features"] == [{"type": "Feature"}]
    assert seen["method"] == "GET"
    assert seen["raw_path"] == "/ogc/features/collections/team%20alpha%2Fparcels/items"
    assert seen["query"]["f"] == "json"
    assert seen["query"]["limit"] == "25"
    assert seen["query"]["offset"] == "5"
    assert seen["query"]["bbox"] == "-158,21,-157,22"
    assert seen["query"]["filter"] == "status = 'active'"
    assert seen["query"]["properties"] == "name,status"


async def test_ogc_features_items_all_paginates() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append((query["limit"], query["offset"]))
        offset = int(query["offset"])
        limit = int(query["limit"])
        page = [{"type": "Feature", "id": value} for value in range(offset + 1, offset + limit + 1)]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": page})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        features = await client.ogc_features().collection("parcels").items_all(page_size=2, limit=3)

    assert [feature["id"] for feature in features] == [1, 2, 3]
    assert seen == [("2", "0"), ("1", "2")]


async def test_auth_headers_are_attached() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient(
        "http://example.test",
        transport=transport,
        api_key="test-key",
        bearer_token="test-token",
    ) as client:
        response = await client.readiness()

    assert response["status"] == "ready"
    assert seen["x_api_key"] == "test-key"
    assert seen["authorization"] == "Bearer test-token"


async def test_auth_provider_headers_are_resolved_per_request() -> None:
    seen: list[str] = []
    api_keys = iter(["async-key-1", "async-key-2"])

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key", ""))
        if request.url.path == "/healthz/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(200, json={"services": []})

    transport = httpx.MockTransport(handler)
    auth_provider = CallableAuthProvider(lambda: {"X-API-Key": next(api_keys)})

    async with AsyncHonuaClient("http://example.test", transport=transport, auth_provider=auth_provider) as client:
        await client.readiness()
        await client.list_services()

    assert seen == ["async-key-1", "async-key-2"]


async def test_non_success_raises_honua_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": 404, "message": "Service not found"}},
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            await client.list_services()

    err = exc_info.value
    assert err.status_code == 404
    assert err.message == "Service not found"
    assert isinstance(err.body, dict)


async def test_context_manager_closes_client() -> None:
    closed = {"called": False}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = AsyncHonuaClient("http://example.test", transport=transport)

    original_aclose = client._client.aclose

    async def track_close() -> None:
        closed["called"] = True
        await original_aclose()

    client._client.aclose = track_close  # type: ignore[method-assign]

    async with client:
        await client.readiness()

    assert closed["called"] is True


async def test_transport_errors_are_normalized_to_honua_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            await client.readiness()

    err = exc_info.value
    assert err.status_code == 0
    assert err.message == "Transport error: connection failed"
    assert isinstance(err.body, dict)
    assert err.body["type"] == "ConnectError"
    assert err.body["url"] == "http://example.test/healthz/ready"


async def test_apply_edits_posts_json_payload() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"addResults": [{"success": True}]})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        response = await client.apply_edits(
            "default",
            5,
            adds=[{"attributes": {"name": "A"}}],
            deletes=[1, 3],
            rollback_on_failure=True,
        )

    assert response["addResults"][0]["success"] is True
    assert seen["method"] == "POST"
    assert seen["path"] == "/rest/services/default/FeatureServer/5/applyEdits"
    assert seen["payload"]["f"] == "json"
    assert seen["payload"]["rollbackOnFailure"] is True
    assert seen["payload"]["adds"][0]["attributes"]["name"] == "A"
    assert seen["payload"]["deletes"] == [1, 3]


async def test_client_rejects_both_client_and_transport() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async_client = httpx.AsyncClient()
    with pytest.raises(ValueError, match="Provide either"):
        AsyncHonuaClient(
            "http://example.test",
            client=async_client,
            transport=transport,
        )
    await async_client.aclose()


async def test_external_client_not_closed() -> None:
    """When an external httpx.AsyncClient is provided, close() should not close it."""
    closed = {"called": False}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    external = httpx.AsyncClient(base_url="http://example.test", transport=transport)

    original_aclose = external.aclose

    async def track_close() -> None:
        closed["called"] = True
        await original_aclose()

    external.aclose = track_close  # type: ignore[method-assign]

    client = AsyncHonuaClient("http://example.test", client=external)
    async with client:
        pass

    assert closed["called"] is False

    # Clean up the external client
    await original_aclose()

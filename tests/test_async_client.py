from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import CallableAuthProvider, FeatureQuery
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


async def test_list_service_summaries_returns_typed_catalog_entries() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/services"
        return httpx.Response(
            200,
            json={"services": [{"name": "parcels", "type": "FeatureServer"}]},
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        services = await client.list_service_summaries()

    assert services[0].name == "parcels"
    assert services[0].type == "FeatureServer"


async def test_capabilities_reads_data_plane_contract() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "serverVersion": "2026.4.0",
                "protocols": ["stac", {"id": "ogc_features"}],
                "features": {"grpc": True},
            },
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        capabilities = await client.capabilities()
        supports_grpc = await client.supports("grpc")

    assert seen == ["/api/v1/capabilities", "/api/v1/capabilities"]
    assert capabilities.server_version == "2026.4.0"
    assert capabilities.supports("stac") is True
    assert capabilities.supports("ogc-features") is True
    assert supports_grpc is True


async def test_capabilities_falls_back_to_readiness_and_catalog_for_older_servers() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/capabilities":
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if request.url.path == "/healthz/ready":
            return httpx.Response(200, json={"serverVersion": "2026.3.0"})
        if request.url.path == "/rest/services":
            return httpx.Response(200, json={"services": [{"name": "parcels", "type": "FeatureServer"}]})
        raise AssertionError(f"unexpected path {request.url.path}")

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        capabilities = await client.capabilities()

    assert seen == ["/api/v1/capabilities", "/healthz/ready", "/rest/services"]
    assert capabilities.supports("geoservices") is True
    assert capabilities.supports("feature-server") is True


async def test_geocoder_factory_reuses_client_auth_and_locator() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path.decode("ascii").split("?")[0]
        seen["api_key"] = request.headers.get("x-api-key", "")
        return httpx.Response(200, json={"suggestions": []})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport, api_key="test-key") as client:
        geocoder = client.geocoder(locator="Address Locator")
        assert await geocoder.suggest("Main") == []

    assert seen["raw_path"] == "/rest/services/Address%20Locator/GeocodeServer/suggest"
    assert seen["api_key"] == "test-key"


async def test_query_features_all_returns_typed_paginated_features() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append((query["resultOffset"], query["resultRecordCount"]))
        offset = int(query["resultOffset"])
        return httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"objectid": offset + 1}},
                    {"attributes": {"objectid": offset + 2}},
                ],
                "exceededTransferLimit": offset == 0,
            },
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        features = await client.query_features_all("parcels", 0, page_size=2, limit=3)

    assert [feature.object_id for feature in features] == [1, 2, 3]
    assert seen == [("0", "2"), ("2", "1")]


async def test_shared_query_feature_server_normalizes_common_args() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        assert request.url.path == "/rest/services/parcels/FeatureServer/0/query"
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "attributes": {"objectid": 10, "name": "A"},
                        "geometry": {"x": -157.8, "y": 21.3},
                    }
                ],
                "exceededTransferLimit": False,
            },
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        result = await client.query(
            FeatureQuery(
                source="parcels",
                where="status = 'active'",
                fields=["objectid", "name"],
                bbox=[-158, 21, -157, 22],
                limit=1,
            )
        )

    assert result.protocol == "feature-server"
    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.id == 10
    assert feature.properties == {"objectid": 10, "name": "A"}
    assert feature.geometry == {"x": -157.8, "y": 21.3}
    assert seen["where"] == "status = 'active'"
    assert seen["outFields"] == "objectid,name"
    assert seen["resultRecordCount"] == "1"
    assert seen["geometryType"] == "esriGeometryEnvelope"


async def test_shared_query_routes_async_ogc_and_odata() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        query = dict(request.url.params.multi_items())
        seen.append({"path": raw_path, "query": query})
        if raw_path == "/ogc/features/collections/parcels/items":
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "id": "p1", "properties": {"name": "Parcel 1"}}],
                },
            )
        if raw_path == "/odata/Layers(4)/Features":
            return httpx.Response(200, json={"value": [{"ObjectId": 7, "Name": "Road"}]})
        raise AssertionError(f"unexpected path {raw_path}")

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        ogc_items = [
            item
            async for item in client.iter_query(
                "parcels",
                protocol="ogc-features",
                filter="status = 'active'",
                fields=["name"],
                limit=1,
            )
        ]
        odata = await client.query(
            FeatureQuery(
                source="4",
                protocol="odata",
                filter="Status eq 'active'",
                fields=["ObjectId", "Name"],
                limit=1,
            )
        )

    assert ogc_items[0].id == "p1"
    assert ogc_items[0].properties == {"name": "Parcel 1"}
    assert odata.features[0].id == 7
    assert odata.features[0].properties == {"ObjectId": 7, "Name": "Road"}
    assert seen == [
        {
            "path": "/ogc/features/collections/parcels/items",
            "query": {
                "f": "json",
                "limit": "1",
                "offset": "0",
                "filter": "status = 'active'",
                "properties": "name",
            },
        },
        {
            "path": "/odata/Layers(4)/Features",
            "query": {
                "$filter": "Status eq 'active'",
                "$select": "ObjectId,Name",
                "$top": "1",
                "$skip": "0",
            },
        },
    ]


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


async def test_ogc_features_items_all_zero_limit_does_not_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("items_all(limit=0) should not issue a request")

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        features = await client.ogc_features().collection("parcels").items_all(limit=0)

    assert features == []


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


async def test_custom_http_client_rejects_sdk_auth_options() -> None:
    client = httpx.AsyncClient(
        base_url="http://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    try:
        with pytest.raises(ValueError, match="supplied `client`"):
            AsyncHonuaClient("http://ignored.test", client=client, api_key="test-key")
    finally:
        await client.aclose()


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


async def test_apply_edits_result_returns_typed_operation_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"addResults": [{"success": True, "objectId": 10}]})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        result = await client.apply_edits_result("parcels", 0, adds=[{"attributes": {"name": "A"}}])

    assert result.add_results[0].success is True
    assert result.add_results[0].object_id == 10
    assert result.all_succeeded is True


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

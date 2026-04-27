from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import CallableAuthProvider, HonuaClient, HonuaHttpError


def test_query_features_builds_expected_request() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"features": []})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        response = client.query_features(
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


def test_query_features_url_encodes_service_id_path_segment() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path.decode("ascii").split("?")[0]
        return httpx.Response(200, json={"features": []})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        client.query_features("team alpha/default", 2)

    assert seen["raw_path"] == "/rest/services/team%20alpha%2Fdefault/FeatureServer/2/query"


def test_ogc_features_metadata_and_items_build_expected_requests() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        query = dict(request.url.params.multi_items())
        seen.append({"method": request.method, "raw_path": raw_path, "query": query})

        if raw_path == "/ogc/features":
            return httpx.Response(200, json={"title": "Honua OGC API Features"})
        if raw_path == "/ogc/features/collections":
            return httpx.Response(200, json={"collections": [{"id": "team alpha/parcels"}]})
        if raw_path == "/ogc/features/collections/team%20alpha%2Fparcels":
            return httpx.Response(200, json={"id": "team alpha/parcels"})
        if raw_path == "/ogc/features/collections/team%20alpha%2Fparcels/queryables":
            return httpx.Response(200, json={"properties": {"status": {"type": "string"}}})
        if raw_path == "/ogc/features/collections/team%20alpha%2Fparcels/items":
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [{"type": "Feature"}]})
        raise AssertionError(f"Unexpected OGC path: {raw_path}")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        ogc = client.ogc_features()
        assert ogc.landing()["title"] == "Honua OGC API Features"
        assert ogc.collections()["collections"][0]["id"] == "team alpha/parcels"

        parcels = ogc.collection("team alpha/parcels")
        assert parcels.metadata()["id"] == "team alpha/parcels"
        assert parcels.queryables()["properties"]["status"]["type"] == "string"
        response = parcels.items(
            limit=50,
            offset=10,
            bbox=[-158, 21, -157, 22],
            datetime="2026-01-01T00:00:00Z/..",
            filter="status = 'active'",
            ids=["p1", "p2"],
            properties=["name", "status"],
            sortby="-updated",
            crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            extra_params={"profile": "seed"},
        )

    assert response["features"] == [{"type": "Feature"}]
    assert [entry["raw_path"] for entry in seen] == [
        "/ogc/features",
        "/ogc/features/collections",
        "/ogc/features/collections/team%20alpha%2Fparcels",
        "/ogc/features/collections/team%20alpha%2Fparcels/queryables",
        "/ogc/features/collections/team%20alpha%2Fparcels/items",
    ]
    item_query = seen[-1]["query"]
    assert item_query["f"] == "json"
    assert item_query["profile"] == "seed"
    assert item_query["limit"] == "50"
    assert item_query["offset"] == "10"
    assert item_query["bbox"] == "-158,21,-157,22"
    assert item_query["datetime"] == "2026-01-01T00:00:00Z/.."
    assert item_query["filter"] == "status = 'active'"
    assert item_query["ids"] == "p1,p2"
    assert item_query["properties"] == "name,status"
    assert item_query["sortby"] == "-updated"
    assert item_query["crs"] == "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


def test_ogc_features_items_all_paginates_with_limit() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append((query["limit"], query["offset"]))
        offset = int(query["offset"])
        limit = int(query["limit"])
        page = [{"type": "Feature", "id": value} for value in range(offset + 1, offset + limit + 1)]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": page})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        features = client.ogc_features().collection("parcels").items_all(page_size=2, limit=5)

    assert [feature["id"] for feature in features] == [1, 2, 3, 4, 5]
    assert seen == [("2", "0"), ("2", "2"), ("1", "4")]


def test_ogc_features_item_crud_uses_geojson_endpoints() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        payload = json.loads(request.content.decode("utf-8")) if request.content else None
        seen.append(
            {
                "method": request.method,
                "raw_path": raw_path,
                "content_type": request.headers.get("content-type", ""),
                "payload": payload,
            }
        )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"type": "Feature", "id": "p/1"})

    transport = httpx.MockTransport(handler)
    feature = {"type": "Feature", "geometry": None, "properties": {"status": "active"}}
    with HonuaClient("http://example.test", transport=transport) as client:
        parcels = client.ogc_features().collection("parcels")
        assert parcels.create_item(feature)["id"] == "p/1"
        assert parcels.replace_item("p/1", feature)["id"] == "p/1"
        assert parcels.patch_item("p/1", {"properties": {"status": "retired"}})["id"] == "p/1"
        parcels.delete_item("p/1")

    assert [(entry["method"], entry["raw_path"]) for entry in seen] == [
        ("POST", "/ogc/features/collections/parcels/items"),
        ("PUT", "/ogc/features/collections/parcels/items/p%2F1"),
        ("PATCH", "/ogc/features/collections/parcels/items/p%2F1"),
        ("DELETE", "/ogc/features/collections/parcels/items/p%2F1"),
    ]
    assert seen[0]["content_type"] == "application/geo+json"
    assert seen[0]["payload"] == feature
    assert seen[1]["content_type"] == "application/geo+json"
    assert seen[2]["content_type"] == "application/merge-patch+json"
    assert seen[2]["payload"] == {"properties": {"status": "retired"}}


def test_apply_edits_posts_json_payload() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"addResults": [{"success": True}]})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        response = client.apply_edits(
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


def test_auth_headers_are_attached() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "http://example.test",
        transport=transport,
        api_key="test-key",
        bearer_token="test-token",
    ) as client:
        response = client.readiness()

    assert response["status"] == "ready"
    assert seen["x_api_key"] == "test-key"
    assert seen["authorization"] == "Bearer test-token"


def test_auth_provider_headers_are_resolved_per_request() -> None:
    seen: list[str] = []
    api_keys = iter(["rotated-key-1", "rotated-key-2"])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key", ""))
        if request.url.path == "/healthz/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(200, json={"services": []})

    transport = httpx.MockTransport(handler)
    auth_provider = CallableAuthProvider(lambda: {"X-API-Key": next(api_keys)})

    with HonuaClient("http://example.test", transport=transport, auth_provider=auth_provider) as client:
        client.readiness()
        client.list_services()

    assert seen == ["rotated-key-1", "rotated-key-2"]


def test_auth_provider_cannot_be_combined_with_static_bearer_token() -> None:
    auth_provider = CallableAuthProvider(lambda: {"Authorization": "Bearer dynamic"})

    with pytest.raises(ValueError, match="bearer_token.*auth_provider"):
        HonuaClient(
            "http://example.test",
            bearer_token="static",
            auth_provider=auth_provider,
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )


def test_non_success_raises_honua_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": 404, "message": "Service not found"}},
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            _ = client.list_services()

    err = exc_info.value
    assert err.status_code == 404
    assert err.message == "Service not found"
    assert isinstance(err.body, dict)


def test_does_not_follow_redirects_by_default() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("x-api-key", "")))
        if request.url.host == "example.test":
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example/healthz/ready"},
            )
        raise AssertionError("Redirect target should not be requested by default")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, api_key="test-key") as client:
        response = client.readiness()

    assert response == {}
    assert len(seen) == 1
    assert seen[0][0] == "http://example.test/healthz/ready"
    assert seen[0][1] == "test-key"


def test_follow_redirects_does_not_forward_sensitive_headers_to_different_host() -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.host or "",
                request.headers.get("x-api-key", ""),
                request.headers.get("authorization", ""),
            )
        )
        if request.url.host == "example.test":
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example/healthz/ready"},
            )
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "http://example.test",
        transport=transport,
        api_key="test-key",
        bearer_token="test-token",
        follow_redirects=True,
    ) as client:
        response = client.readiness()

    assert response == {"status": "ready"}
    assert len(seen) == 2
    assert seen[0] == ("example.test", "test-key", "Bearer test-token")
    assert seen[1] == ("evil.example", "", "")


def test_follow_redirects_does_not_forward_auth_provider_headers_to_different_host() -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.host or "",
                request.headers.get("x-api-key", ""),
                request.headers.get("authorization", ""),
            )
        )
        if request.url.host == "example.test":
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example/healthz/ready"},
            )
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    auth_provider = CallableAuthProvider(
        lambda: {
            "Authorization": "Bearer dynamic-token",
            "X-API-Key": "dynamic-key",
        }
    )
    with HonuaClient(
        "http://example.test",
        transport=transport,
        auth_provider=auth_provider,
        follow_redirects=True,
    ) as client:
        response = client.readiness()

    assert response == {"status": "ready"}
    assert seen == [
        ("example.test", "dynamic-key", "Bearer dynamic-token"),
        ("evil.example", "", ""),
    ]


def test_transport_errors_are_normalized_to_honua_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.readiness()

    err = exc_info.value
    assert err.status_code == 0
    assert err.message == "Transport error: connection failed"
    assert isinstance(err.body, dict)
    assert err.body["type"] == "ConnectError"
    assert err.body["url"] == "http://example.test/healthz/ready"

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import CallableAuthProvider, DataPlaneCapabilities, FeatureQuery, HonuaClient, HonuaHttpError
from honua_sdk.errors import HonuaTransportError


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


def test_list_service_summaries_returns_typed_catalog_entries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/services"
        return httpx.Response(
            200,
            json={
                "services": [
                    {"name": "parcels", "type": "FeatureServer", "url": "/rest/services/parcels/FeatureServer"}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        services = client.list_service_summaries()

    assert len(services) == 1
    assert services[0].name == "parcels"
    assert services[0].type == "FeatureServer"
    assert services[0].raw["url"] == "/rest/services/parcels/FeatureServer"


def test_capabilities_reads_data_plane_contract() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "serverVersion": "2026.4.0",
                "releaseChannel": "beta",
                "protocols": [
                    "stac",
                    {"id": "ogc_features", "enabled": True},
                    {"id": "wms", "enabled": False},
                ],
                "features": {"grpc": True, "experimental": False},
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        capabilities = client.capabilities()

    assert isinstance(capabilities, DataPlaneCapabilities)
    assert seen == ["/api/v1/capabilities"]
    assert capabilities.server_version == "2026.4.0"
    assert capabilities.release_channel == "beta"
    assert capabilities.supports("stac") is True
    assert capabilities.supports("ogc-features") is True
    assert capabilities.supports("wms") is False
    assert capabilities.supports("grpc") is True
    assert capabilities.supports("experimental") is False


def test_capabilities_falls_back_to_readiness_and_catalog_for_older_servers() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/capabilities":
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if request.url.path == "/healthz/ready":
            return httpx.Response(200, json={"serverVersion": "2026.3.0"})
        if request.url.path == "/rest/services":
            return httpx.Response(
                200,
                json={
                    "services": [
                        {"name": "parcels", "type": "FeatureServer"},
                        {"name": "World", "type": "GeocodeServer"},
                    ]
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        capabilities = client.capabilities()

    assert seen == ["/api/v1/capabilities", "/healthz/ready", "/rest/services"]
    assert capabilities.server_version == "2026.3.0"
    assert capabilities.supports("geoservices") is True
    assert capabilities.supports("feature-server") is True
    assert capabilities.supports("geocoding") is True
    assert capabilities.supports("service-catalog") is True


def test_geocoder_factory_reuses_client_auth_and_locator() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path.decode("ascii").split("?")[0]
        seen["api_key"] = request.headers.get("x-api-key", "")
        return httpx.Response(200, json={"suggestions": []})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, api_key="test-key") as client:
        geocoder = client.geocoder(locator="Address Locator")
        assert geocoder.suggest("Main") == []

    assert seen["raw_path"] == "/rest/services/Address%20Locator/GeocodeServer/suggest"
    assert seen["api_key"] == "test-key"


def test_query_feature_set_returns_typed_features() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/services/parcels/FeatureServer/0/query"
        return httpx.Response(
            200,
            json={
                "geometryType": "esriGeometryPoint",
                "spatialReference": {"wkid": 4326},
                "fields": [{"name": "objectid", "type": "esriFieldTypeOID"}],
                "features": [
                    {
                        "attributes": {"objectid": 10, "name": "A"},
                        "geometry": {"x": -157.8, "y": 21.3},
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        feature_set = client.query_feature_set("parcels", 0)

    assert feature_set.geometry_type == "esriGeometryPoint"
    assert feature_set.spatial_reference == {"wkid": 4326}
    assert feature_set.features[0].object_id == 10
    assert feature_set.features[0].attributes["name"] == "A"


def test_query_features_all_pages_until_transfer_limit_clears() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append((query["resultOffset"], query["resultRecordCount"]))
        offset = int(query["resultOffset"])
        features = [
            {"attributes": {"objectid": offset + 1}},
            {"attributes": {"objectid": offset + 2}},
        ]
        return httpx.Response(
            200,
            json={
                "features": features,
                "exceededTransferLimit": offset == 0,
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        features = client.query_features_all("parcels", 0, page_size=2, limit=3)

    assert [feature.object_id for feature in features] == [1, 2, 3]
    assert seen == [("0", "2"), ("2", "1")]


def test_query_features_all_stops_on_non_advancing_cursor() -> None:
    # issue #107.4: a server that ignores ``resultOffset`` returns the same
    # full page with exceededTransferLimit=true forever. The non-advancing
    # cursor guard must stop after the first page rather than looping to
    # max_pages and duplicating features.
    call_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        # Always the same two objectids, regardless of the requested offset.
        return httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"objectid": 1}},
                    {"attributes": {"objectid": 2}},
                ],
                "exceededTransferLimit": True,
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        features = client.query_features_all("parcels", 0, page_size=2, max_pages=100)

    # Only the first page is kept; no duplicates, and we stop after detecting
    # the stall (one extra probe page) rather than walking all 100 pages.
    assert [feature.object_id for feature in features] == [1, 2]
    assert call_count["n"] <= 2


def test_shared_query_feature_server_normalizes_common_args() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
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
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.query(
            "parcels",
            where="status = 'active'",
            fields=["objectid", "name"],
            bbox=[-158, 21, -157, 22],
            limit=1,
        )

    assert result.protocol == "feature-server"
    assert result.source == "parcels"
    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.id == 10
    assert feature.properties == {"objectid": 10, "name": "A"}
    assert feature.geometry == {"x": -157.8, "y": 21.3}
    assert feature.protocol == "feature-server"
    assert seen["where"] == "status = 'active'"
    assert seen["outFields"] == "objectid,name"
    assert seen["returnGeometry"] == "true"
    assert seen["resultOffset"] == "0"
    assert seen["resultRecordCount"] == "1"
    assert seen["geometryType"] == "esriGeometryEnvelope"
    assert seen["spatialRel"] == "esriSpatialRelIntersects"


def test_shared_query_routes_ogc_stac_and_odata() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        query = dict(request.url.params.multi_items())
        seen.append({"path": raw_path, "query": query})
        if raw_path == "/ogc/features/collections/parcels/items":
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "p1",
                            "properties": {"name": "Parcel 1"},
                            "geometry": {"type": "Point", "coordinates": [0, 0]},
                        }
                    ],
                },
            )
        if raw_path == "/stac/collections/imagery/items":
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "scene-1",
                            "properties": {"datetime": "2026-01-01T00:00:00Z"},
                            "geometry": {"type": "Point", "coordinates": [1, 1]},
                        }
                    ],
                },
            )
        if raw_path == "/odata/Layers(4)/Features":
            return httpx.Response(200, json={"value": [{"ObjectId": 7, "Name": "Road", "Geometry": {"x": 1}}]})
        raise AssertionError(f"unexpected path {raw_path}")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        ogc = client.query(
            "parcels",
            protocol="ogc-features",
            filter="status = 'active'",
            fields=["name"],
            bbox=[-158, 21, -157, 22],
            limit=1,
        )
        stac = client.query(
            FeatureQuery(
                source="imagery",
                protocol="stac",
                filter="eo:cloud_cover < 10",
                bbox=[-158, 21, -157, 22],
                fields=["datetime"],
                limit=1,
            )
        )
        odata = client.query(
            FeatureQuery(
                source="4",
                protocol="odata",
                filter="Status eq 'active'",
                fields=["ObjectId", "Name"],
                limit=1,
            )
        )

    assert ogc.features[0].id == "p1"
    assert ogc.features[0].properties == {"name": "Parcel 1"}
    assert stac.features[0].id == "scene-1"
    assert stac.features[0].properties == {"datetime": "2026-01-01T00:00:00Z"}
    assert odata.features[0].id == 7
    assert odata.features[0].properties == {"ObjectId": 7, "Name": "Road"}
    assert odata.features[0].geometry == {"x": 1}
    assert seen == [
        {
            "path": "/ogc/features/collections/parcels/items",
            "query": {
                "f": "json",
                "limit": "1",
                "offset": "0",
                "bbox": "-158,21,-157,22",
                "filter": "status = 'active'",
                "properties": "name",
            },
        },
        {
            "path": "/stac/collections/imagery/items",
            "query": {
                "filter": "eo:cloud_cover < 10",
                "bbox": "-158,21,-157,22",
                "fields": "datetime",
                "limit": "1",
                "offset": "0",
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


def test_ogc_features_items_all_zero_limit_does_not_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("items_all(limit=0) should not issue a request")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        features = client.ogc_features().collection("parcels").items_all(limit=0)

    assert features == []


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


def test_apply_edits_result_returns_typed_operation_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "addResults": [{"success": True, "objectId": 10}],
                "updateResults": [{"success": True, "objectId": 11}],
                "deleteResults": [{"success": False, "objectId": 12, "error": {"message": "locked"}}],
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.apply_edits_result("parcels", 0, deletes=[12])

    assert result.add_results[0].object_id == 10
    assert result.update_results[0].success is True
    assert result.delete_results[0].error == {"message": "locked"}
    assert result.all_succeeded is False


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


@pytest.mark.parametrize(
    "auth_kwargs",
    [
        {"api_key": "test-key"},
        {"bearer_token": "test-token"},
        {"auth_provider": CallableAuthProvider(lambda: {"X-API-Key": "test-key"})},
    ],
)
def test_custom_http_client_rejects_sdk_auth_options(auth_kwargs: dict[str, object]) -> None:
    client = httpx.Client(
        base_url="http://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    try:
        with pytest.raises(ValueError, match="supplied `client`"):
            HonuaClient("http://ignored.test", client=client, **auth_kwargs)
    finally:
        client.close()


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


def test_follow_redirects_does_not_forward_sensitive_headers_on_scheme_downgrade() -> None:
    # An https -> http downgrade to the *same* host/port must strip credentials:
    # without the scheme in the trusted-origin key both URLs normalize to the
    # same (host, port) and the headers would leak over plaintext.
    seen: list[tuple[str, str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.scheme,
                request.url.host or "",
                request.headers.get("x-api-key", ""),
                request.headers.get("authorization", ""),
            )
        )
        if request.url.scheme == "https":
            return httpx.Response(
                302,
                headers={"Location": "http://api.example/healthz/ready"},
            )
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "https://api.example",
        transport=transport,
        api_key="test-key",
        bearer_token="test-token",
        follow_redirects=True,
    ) as client:
        response = client.readiness()

    assert response == {"status": "ready"}
    assert seen == [
        ("https", "api.example", "test-key", "Bearer test-token"),
        ("http", "api.example", "", ""),
    ]


def test_base_url_path_prefix_is_preserved_on_every_request() -> None:
    # A base URL with a sub-path prefix (reverse-proxy mount) must be honored;
    # the endpoint path is joined onto the prefix rather than replacing it.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    with HonuaClient("https://host.example/honua/", transport=transport) as client:
        client.readiness()

    assert seen == ["/honua/healthz/ready"]


def test_root_base_url_leaves_request_path_unchanged() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    with HonuaClient("https://host.example", transport=transport) as client:
        client.readiness()

    assert seen == ["/healthz/ready"]


def test_transport_errors_are_normalized_to_honua_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(HonuaTransportError) as exc_info:
            client.readiness()

    err = exc_info.value
    assert "Transport error: connection failed" in str(err)
    assert err.cause_type == "ConnectError"
    assert err.url == "http://example.test/healthz/ready"


def test_timeout_errors_are_normalized_to_honua_timeout_error() -> None:
    from honua_sdk.errors import HonuaTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(HonuaTimeoutError) as exc_info:
            client.readiness()

    err = exc_info.value
    assert isinstance(err, HonuaTransportError)
    assert err.cause_type == "ReadTimeout"


def test_http_401_raises_honua_auth_error() -> None:
    from honua_sdk.errors import HonuaAuthError

    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": {"message": "no token"}})
    )
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        with pytest.raises(HonuaAuthError) as exc_info:
            client.readiness()

    err = exc_info.value
    assert isinstance(err, HonuaHttpError)
    assert err.status_code == 401
    assert err.message == "no token"


def test_http_429_raises_rate_limit_error_with_retry_after() -> None:
    from honua_sdk.errors import HonuaRateLimitError

    transport = httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": "12"}, json={"detail": "slow down"})
    )
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        with pytest.raises(HonuaRateLimitError) as exc_info:
            client.readiness()

    err = exc_info.value
    assert isinstance(err, HonuaHttpError)
    assert err.status_code == 429
    assert err.retry_after == 12.0
    assert err.message == "slow down"


@pytest.mark.parametrize("protocol", ["ogc-features", "stac"])
def test_dispatcher_rejects_silent_where_to_cql_forwarding(protocol: str) -> None:
    """Mirror ``Source.query``: legacy dispatcher must not silently route SQL ``where`` to CQL.

    The dispatcher previously fed ``where`` directly into the OGC/STAC
    ``filter`` slot, which silently mis-typed SQL as CQL2-text. The
    canonical :class:`Source` facade raises here; this test pins the
    same shape on :meth:`HonuaClient.query` / :meth:`HonuaClient.iter_query`.
    """
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"features": []}))
    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(ValueError, match="cql_filter"):
            client.query(
                "collection-1",
                protocol=protocol,
                where="STATE='CA'",
                limit=1,
            )
        with pytest.raises(ValueError, match="cql_filter"):
            list(
                client.iter_query(
                    "collection-1",
                    protocol=protocol,
                    where="STATE='CA'",
                    limit=1,
                )
            )


@pytest.mark.parametrize("protocol", ["ogc-features", "stac"])
def test_dispatcher_accepts_filter_for_cql_protocols(protocol: str) -> None:
    """``filter=`` (CQL slot) keeps working on the legacy dispatcher."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        if path.startswith("/ogc/features/") or path.startswith("/stac/"):
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": []},
            )
        raise AssertionError(f"unexpected path {path}")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.query(
            "collection-1",
            protocol=protocol,
            filter="STATE='CA'",
            limit=1,
        )
    assert result.protocol == protocol

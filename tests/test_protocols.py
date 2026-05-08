from __future__ import annotations

from typing import Any

import httpx

from honua_sdk import BinaryResponse, HonuaClient, HonuaHttpError, ODataQuery


def test_protocol_factories_build_expected_geoservices_paths() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        if raw_path.endswith("/export") or raw_path.endswith("/exportImage") or "/tile/" in raw_path:
            return httpx.Response(200, content=b"image-bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        assert client.feature_server("team alpha/default").metadata()["ok"] is True
        assert client.feature_server("team alpha/default").layer_metadata(2)["ok"] is True
        assert client.map_server("basemap").metadata()["ok"] is True
        assert client.map_server("basemap").layer_metadata(3)["ok"] is True
        assert client.map_server("basemap").export([-158, 21, -157, 22]) == b"image-bytes"
        assert client.map_server("basemap").identify(
            geometry={"x": -157.8, "y": 21.3},
            map_extent=[-158, 21, -157, 22],
            image_display="400,400,96",
        )["ok"] is True
        assert client.image_server("imagery").metadata()["ok"] is True
        assert client.image_server("imagery").export_image([-158, 21, -157, 22]) == b"image-bytes"
        assert client.geometry_server().project([{"x": 1, "y": 2}], in_sr=4326, out_sr=3857)["ok"] is True

    assert [entry["raw_path"] for entry in seen] == [
        "/rest/services/team%20alpha%2Fdefault/FeatureServer",
        "/rest/services/team%20alpha%2Fdefault/FeatureServer/2",
        "/rest/services/basemap/MapServer",
        "/rest/services/basemap/MapServer/3",
        "/rest/services/basemap/MapServer/export",
        "/rest/services/basemap/MapServer/identify",
        "/rest/services/imagery/ImageServer",
        "/rest/services/imagery/ImageServer/exportImage",
        "/rest/services/Utilities/Geometry/GeometryServer/project",
    ]
    assert seen[5]["query"]["geometry"] == '{"x":-157.8,"y":21.3}'
    assert seen[8]["query"]["geometries"] == '[{"x":1,"y":2}]'


def test_ogc_maps_tiles_coverages_and_processes_build_expected_paths() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        if raw_path.endswith("/map") or "/tiles/WebMercatorQuad/" in raw_path or raw_path.endswith("/coverage"):
            return httpx.Response(200, content=b"bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        assert client.ogc_maps().landing()["ok"] is True
        assert client.ogc_maps().collection_map("admin/bounds", bbox=[-180, -90, 180, 90]) == b"bytes"
        assert client.ogc_tiles().collections()["ok"] is True
        assert client.ogc_tiles().tile("WebMercatorQuad", "0", 0, 0, collection_id="admin/bounds") == b"bytes"
        assert client.ogc_coverages().coverage("elevation", response_format="tiff") == b"bytes"
        assert client.ogc_processes().processes()["ok"] is True
        assert client.ogc_processes().execute("honua-geoprocessing", {"inputs": {}})["ok"] is True

    assert [(entry["method"], entry["raw_path"]) for entry in seen] == [
        ("GET", "/ogc/maps"),
        ("GET", "/ogc/maps/collections/admin%2Fbounds/map"),
        ("GET", "/ogc/tiles/collections"),
        ("GET", "/ogc/tiles/collections/admin%2Fbounds/tiles/WebMercatorQuad/0/0/0"),
        ("GET", "/ogc/coverages/collections/elevation/coverage"),
        ("GET", "/ogc/processes/processes"),
        ("POST", "/ogc/processes/processes/honua-geoprocessing/execution"),
    ]
    assert seen[1]["query"] == {"f": "png", "bbox": "-180,-90,180,90"}
    assert seen[4]["query"] == {"f": "tiff"}


def test_ogc_records_builds_discovery_search_and_detail_requests() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        records = client.ogc_records()
        assert records.landing()["ok"] is True
        assert records.conformance()["ok"] is True
        assert records.collections()["ok"] is True
        assert records.collection("metadata/catalog").metadata()["ok"] is True
        assert records.queryables("metadata/catalog")["ok"] is True
        assert records.records(
            "metadata/catalog",
            limit=10,
            offset=5,
            bbox=[-158, 21, -157, 22],
            datetime="2026-01-01/2026-01-31",
            filter="properties.theme = 'planning'",
            q="shoreline",
            ids=["rec-1", "rec-2"],
            properties=["title", "theme"],
            sortby="-updated",
            type="dataset",
            extra_params={"filter-lang": "cql2-text"},
        )["ok"] is True
        assert records.record("metadata/catalog", "record/1")["ok"] is True
        assert records.search(json_body={"q": "shoreline", "limit": 1})["ok"] is True
        assert records.collection("metadata/catalog").search(params={"q": "roads"})["ok"] is True

    assert [(entry["method"], entry["raw_path"]) for entry in seen] == [
        ("GET", "/ogc/records"),
        ("GET", "/ogc/records/conformance"),
        ("GET", "/ogc/records/collections"),
        ("GET", "/ogc/records/collections/metadata%2Fcatalog"),
        ("GET", "/ogc/records/collections/metadata%2Fcatalog/queryables"),
        ("GET", "/ogc/records/collections/metadata%2Fcatalog/items"),
        ("GET", "/ogc/records/collections/metadata%2Fcatalog/items/record%2F1"),
        ("POST", "/ogc/records/search"),
        ("GET", "/ogc/records/collections/metadata%2Fcatalog/items"),
    ]
    assert seen[5]["query"] == {
        "f": "json",
        "limit": "10",
        "offset": "5",
        "bbox": "-158,21,-157,22",
        "datetime": "2026-01-01/2026-01-31",
        "filter": "properties.theme = 'planning'",
        "q": "shoreline",
        "ids": "rec-1,rec-2",
        "properties": "title,theme",
        "sortby": "-updated",
        "type": "dataset",
        "filter-lang": "cql2-text",
    }


def test_ogc_records_iterators_follow_next_links_and_clip_limit() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append(query)
        offset = int(query.get("offset", "0"))
        features = [{"type": "Feature", "id": f"record-{value}"} for value in range(offset + 1, offset + 3)]
        links = []
        if offset == 0:
            links.append(
                {
                    "rel": "next",
                    "href": "http://example.test/ogc/records/collections/catalog/items?offset=2&limit=2",
                }
            )
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features, "links": links})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        records = list(client.ogc_records().collection("catalog").iter_records(page_size=2, limit=3))

    assert [record["id"] for record in records] == ["record-1", "record-2", "record-3"]
    assert seen == [{"f": "json", "limit": "2", "offset": "0"}, {"offset": "2", "limit": "2"}]


def test_ogc_records_errors_and_auth_use_shared_http_client() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        return httpx.Response(404, json={"error": {"message": "record not found"}})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, api_key="records-key") as client:
        try:
            client.ogc_records().record("catalog", "missing")
        except Exception as exc:
            assert isinstance(exc, HonuaHttpError)
        else:
            raise AssertionError("Expected HonuaHttpError")

    assert seen["x_api_key"] == "records-key"


def test_stac_classic_ogc_and_odata_build_expected_paths() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        if raw_path == "/wfs" or raw_path.endswith("/wms") or raw_path.endswith("/wmts") or raw_path.endswith("$metadata"):
            return httpx.Response(200, content=b"<xml />")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        assert client.stac().catalog()["ok"] is True
        assert client.stac().items("landsat")["ok"] is True
        assert client.stac().search(json_body={"collections": ["landsat"]})["ok"] is True
        assert client.wfs().capabilities() == "<xml />"
        assert client.wms("basemap").capabilities() == "<xml />"
        assert client.wmts("basemap").tile(
            layer="basemap",
            tile_matrix_set="WebMercatorQuad",
            tile_matrix="0",
            tile_row=0,
            tile_col=0,
        ) == b"<xml />"
        assert client.odata().service_document()["ok"] is True
        assert client.odata().metadata() == "<xml />"
        assert client.odata().features(layer_id=4)["ok"] is True

    assert [(entry["method"], entry["raw_path"]) for entry in seen] == [
        ("GET", "/stac"),
        ("GET", "/stac/collections/landsat/items"),
        ("POST", "/stac/search"),
        ("GET", "/wfs"),
        ("GET", "/ogc/services/basemap/wms"),
        ("GET", "/ogc/services/basemap/wmts"),
        ("GET", "/odata"),
        ("GET", "/odata/$metadata"),
        ("GET", "/odata/Layers(4)/Features"),
    ]
    assert seen[3]["query"] == {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}
    assert seen[5]["query"]["request"] == "GetTile"


def test_feature_server_query_pages_and_items_paginate() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append((query["resultOffset"], query["resultRecordCount"]))
        offset = int(query["resultOffset"])
        count = int(query["resultRecordCount"])
        features = [{"attributes": {"objectid": offset + index + 1}} for index in range(count)]
        return httpx.Response(
            200,
            json={
                "features": features,
                "exceededTransferLimit": offset == 0,
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        feature_server = client.feature_server("parcels")
        pages = list(feature_server.query_pages(0, page_size=2, limit=3))
        items = list(feature_server.query_items(0, page_size=2, limit=3))

    assert [[feature.object_id for feature in page.features] for page in pages] == [[1, 2], [3]]
    assert [feature.object_id for feature in items] == [1, 2, 3]
    assert seen == [("0", "2"), ("2", "1"), ("0", "2"), ("2", "1")]


def test_stac_item_iterators_follow_next_links_and_clip_limit() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append(query)
        offset = int(query.get("offset", "0"))
        page = [{"type": "Feature", "id": f"scene-{value}"} for value in range(offset + 1, offset + 3)]
        links = []
        if offset == 0:
            links.append(
                {
                    "rel": "next",
                    "href": "http://example.test/stac/collections/imagery/items?offset=2&limit=2",
                }
            )
        return httpx.Response(200, json={"type": "FeatureCollection", "features": page, "links": links})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        items = list(client.stac().iter_items("imagery", page_size=2, limit=3))

    assert [item["id"] for item in items] == ["scene-1", "scene-2", "scene-3"]
    assert seen == [{"limit": "2", "offset": "0"}, {"offset": "2", "limit": "2"}]


def test_odata_query_helpers_and_iterators() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append(query)
        skip = int(query.get("$skip", "0"))
        value = [{"ObjectId": skip + 1}, {"ObjectId": skip + 2}]
        payload: dict[str, Any] = {"value": value}
        if skip == 0:
            payload["@odata.nextLink"] = "http://example.test/odata/Layers(4)/Features?$skip=2&$top=2"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        features = list(
            client.odata().iter_features(
                layer_id=4,
                query=ODataQuery(
                    filter="Status eq 'active'",
                    select=["ObjectId", "Name"],
                    orderby=["Name"],
                    top=999,
                    skip=999,
                    count=True,
                ),
                page_size=2,
                limit=3,
                extra_params={"custom": "seed"},
            )
        )

    assert [feature["ObjectId"] for feature in features] == [1, 2, 3]
    assert seen == [
        {
            "$filter": "Status eq 'active'",
            "$select": "ObjectId,Name",
            "$orderby": "Name",
            "$top": "2",
            "$skip": "0",
            "$count": "true",
            "custom": "seed",
        },
        {"$skip": "2", "$top": "2"},
    ]


def test_odata_single_call_query_params_are_serialized() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        return httpx.Response(200, json={"value": []})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        client.odata().layers(
            query=ODataQuery(filter="from-query", select=["id"], orderby=["name"], count=False),
            filter="from-kwarg",
            top=10,
            skip=5,
            extra_params={"$filter": "from-extra"},
        )

    assert seen == {
        "$filter": "from-extra",
        "$select": "id",
        "$orderby": "name",
        "$top": "10",
        "$skip": "5",
        "$count": "false",
    }


def test_wms_and_wmts_response_helpers_return_binary_metadata() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            content=b"image-bytes",
            headers={
                "content-type": "image/png",
                "cache-control": "max-age=60",
                "etag": '"tile-v1"',
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        map_response = client.wms("basemap").map_response(
            layers=["roads", "parcels"],
            bbox=[-158, 21, -157, 22],
            width=256,
            height=256,
        )
        tile_response = client.wmts("basemap").tile_response(
            layer="basemap",
            tile_matrix_set="WebMercatorQuad",
            tile_matrix="0",
            tile_row=0,
            tile_col=0,
        )

    assert isinstance(map_response, BinaryResponse)
    assert map_response.content == b"image-bytes"
    assert map_response.content_type == "image/png"
    assert map_response.cache_control == "max-age=60"
    assert map_response.etag == '"tile-v1"'
    assert tile_response.content == b"image-bytes"
    assert seen[0]["request"] == "GetMap"
    assert seen[0]["layers"] == "roads,parcels"
    assert seen[1]["request"] == "GetTile"

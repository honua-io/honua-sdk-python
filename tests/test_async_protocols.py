from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.protocols import BinaryResponse, ODataQuery


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio


def test_async_client_exposes_sync_protocol_factories() -> None:
    factory_names = {
        "feature_server",
        "map_server",
        "image_server",
        "geometry_server",
        "ogc_features",
        "ogc_maps",
        "ogc_tiles",
        "ogc_coverages",
        "ogc_processes",
        "stac",
        "wfs",
        "wms",
        "wmts",
        "odata",
    }

    assert factory_names <= set(dir(HonuaClient))
    assert factory_names <= set(dir(AsyncHonuaClient))


async def test_async_protocol_factories_build_expected_geoservices_paths() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        if raw_path.endswith("/export") or raw_path.endswith("/exportImage") or "/tile/" in raw_path:
            return httpx.Response(200, content=b"image-bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        assert (await client.feature_server("team alpha/default").metadata())["ok"] is True
        assert (await client.feature_server("team alpha/default").layer_metadata(2))["ok"] is True
        assert (await client.map_server("basemap").metadata())["ok"] is True
        assert (await client.map_server("basemap").layer_metadata(3))["ok"] is True
        assert await client.map_server("basemap").export([-158, 21, -157, 22]) == b"image-bytes"
        assert (
            await client.map_server("basemap").identify(
                geometry={"x": -157.8, "y": 21.3},
                map_extent=[-158, 21, -157, 22],
                image_display="400,400,96",
            )
        )["ok"] is True
        assert (await client.image_server("imagery").metadata())["ok"] is True
        assert await client.image_server("imagery").export_image([-158, 21, -157, 22]) == b"image-bytes"
        assert (await client.geometry_server().project([{"x": 1, "y": 2}], in_sr=4326, out_sr=3857))["ok"] is True

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


async def test_async_ogc_maps_tiles_coverages_and_processes_build_expected_paths() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        if raw_path.endswith("/map") or "/tiles/WebMercatorQuad/" in raw_path or raw_path.endswith("/coverage"):
            return httpx.Response(200, content=b"bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        assert (await client.ogc_maps().landing())["ok"] is True
        assert await client.ogc_maps().collection_map("admin/bounds", bbox=[-180, -90, 180, 90]) == b"bytes"
        assert (await client.ogc_tiles().collections())["ok"] is True
        assert await client.ogc_tiles().tile("WebMercatorQuad", "0", 0, 0, collection_id="admin/bounds") == b"bytes"
        assert await client.ogc_coverages().coverage("elevation", response_format="tiff") == b"bytes"
        assert (await client.ogc_processes().processes())["ok"] is True
        assert (await client.ogc_processes().execute("honua-geoprocessing", {"inputs": {}}))["ok"] is True

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


async def test_async_stac_classic_ogc_and_odata_build_expected_paths() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        if raw_path == "/wfs" or raw_path.endswith("/wms") or raw_path.endswith("/wmts") or raw_path.endswith("$metadata"):
            return httpx.Response(200, content=b"<xml />")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        assert (await client.stac().catalog())["ok"] is True
        assert (await client.stac().items("landsat"))["ok"] is True
        assert (await client.stac().search(json_body={"collections": ["landsat"]}))["ok"] is True
        assert await client.wfs().capabilities() == "<xml />"
        assert await client.wms("basemap").capabilities() == "<xml />"
        assert await client.wmts("basemap").tile(
            layer="basemap",
            tile_matrix_set="WebMercatorQuad",
            tile_matrix="0",
            tile_row=0,
            tile_col=0,
        ) == b"<xml />"
        assert (await client.odata().service_document())["ok"] is True
        assert await client.odata().metadata() == "<xml />"
        assert (await client.odata().features(layer_id=4))["ok"] is True

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


async def test_async_stac_iter_items_follow_next_links_and_clip_limit() -> None:
    seen: list[dict[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
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
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        items = [item async for item in client.stac().iter_items("imagery", page_size=2, limit=3)]

    assert [item["id"] for item in items] == ["scene-1", "scene-2", "scene-3"]
    assert seen == [{"limit": "2", "offset": "0"}, {"offset": "2", "limit": "2"}]


async def test_async_odata_query_helpers_and_iterators() -> None:
    seen: list[dict[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        seen.append(query)
        skip = int(query.get("$skip", "0"))
        payload: dict[str, Any] = {
            "value": [{"ObjectId": skip + 1}, {"ObjectId": skip + 2}],
        }
        if skip == 0:
            payload["@odata.nextLink"] = "http://example.test/odata/Layers(4)/Features?$skip=2&$top=2"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        features = [
            feature
            async for feature in client.odata().iter_features(
                layer_id=4,
                query=ODataQuery(filter="Status eq 'active'", select=["ObjectId"], count=True),
                page_size=2,
                limit=3,
            )
        ]

    assert [feature["ObjectId"] for feature in features] == [1, 2, 3]
    assert seen == [
        {
            "$filter": "Status eq 'active'",
            "$select": "ObjectId",
            "$top": "2",
            "$skip": "0",
            "$count": "true",
        },
        {"$skip": "2", "$top": "2"},
    ]


async def test_async_wms_response_helper_returns_binary_metadata() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            content=b"image-bytes",
            headers={"content-type": "image/png", "etag": '"map-v1"'},
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        response = await client.wms("basemap").map_response(
            layers="roads",
            bbox=[-158, 21, -157, 22],
            width=256,
            height=256,
        )

    assert isinstance(response, BinaryResponse)
    assert response.content == b"image-bytes"
    assert response.content_type == "image/png"
    assert response.etag == '"map-v1"'
    assert seen["request"] == "GetMap"


async def test_async_ogc_records_builds_requests_and_iterates_pages() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        query = dict(request.url.params.multi_items())
        seen.append({"method": request.method, "raw_path": raw_path, "query": query})
        if raw_path.endswith("/items"):
            offset = int(query.get("offset", "0"))
            records = [{"id": f"record-{offset + 1}"}, {"id": f"record-{offset + 2}"}]
            payload: dict[str, Any] = {"records": records}
            if offset == 0:
                payload["links"] = [
                    {
                        "rel": "next",
                        "href": "http://example.test/ogc/records/collections/catalog/items?offset=2&limit=2",
                    }
                ]
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        assert (await client.ogc_records().landing())["ok"] is True
        assert (await client.ogc_records().collection("catalog").metadata())["ok"] is True
        assert (await client.ogc_records().record("catalog", "record/1"))["ok"] is True
        records = [
            record
            async for record in client.ogc_records().collection("catalog").iter_records(
                page_size=2,
                limit=3,
                bbox=[-158, 21, -157, 22],
                datetime="2026-01-01/..",
                filter="properties.kind = 'dataset'",
                q="coast",
            )
        ]

    assert [record["id"] for record in records] == ["record-1", "record-2", "record-3"]
    assert [(entry["method"], entry["raw_path"]) for entry in seen] == [
        ("GET", "/ogc/records"),
        ("GET", "/ogc/records/collections/catalog"),
        ("GET", "/ogc/records/collections/catalog/items/record%2F1"),
        ("GET", "/ogc/records/collections/catalog/items"),
        ("GET", "/ogc/records/collections/catalog/items"),
    ]
    assert seen[3]["query"] == {
        "f": "json",
        "limit": "2",
        "offset": "0",
        "bbox": "-158,21,-157,22",
        "datetime": "2026-01-01/..",
        "filter": "properties.kind = 'dataset'",
        "q": "coast",
    }
    assert seen[4]["query"] == {"offset": "2", "limit": "2"}


async def test_async_ogc_records_helpers_aliases_and_search() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        query = dict(request.url.params.multi_items())
        seen.append({"method": request.method, "raw_path": raw_path, "query": query})
        if raw_path.endswith("/items"):
            offset = int(query.get("offset", "0"))
            records = [{"id": f"record-{offset + 1}"}, {"id": f"record-{offset + 2}"}]
            payload: dict[str, Any] = {"records": records}
            if offset == 0:
                payload["links"] = [
                    {
                        "rel": "next",
                        "href": "http://example.test/ogc/records/collections/catalog/items?offset=2&limit=2",
                    }
                ]
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        records_client = client.ogc_records()

        # Top-level async record_pages/records_all/iter_records delegate to the collection.
        pages = [page async for page in records_client.record_pages("catalog", page_size=2, limit=4)]
        assert [r["id"] for page in pages for r in page["records"]] == [
            "record-1",
            "record-2",
            "record-3",
            "record-4",
        ]
        assert [r["id"] for r in await records_client.records_all("catalog", page_size=2, limit=2)] == [
            "record-1",
            "record-2",
        ]
        assert [r["id"] async for r in records_client.iter_records("catalog", page_size=2, limit=2)] == [
            "record-1",
            "record-2",
        ]

        # Collection-level aliases (items/item/iter_items/items_all) + search.
        collection = records_client.collection("catalog")
        assert (await collection.items(limit=1))["records"][0]["id"] == "record-1"
        # item() fetches a single record detail (non-/items path -> handler returns {"ok": True}).
        assert (await collection.item("record/9"))["ok"] is True
        assert [r["id"] for r in await collection.items_all(page_size=2, limit=2)] == ["record-1", "record-2"]
        assert [r["id"] async for r in collection.iter_items(page_size=2, limit=2)] == ["record-1", "record-2"]
        assert (await collection.search(json_body={"q": "x"}))["records"][0]["id"] == "record-1"

    # search with json_body on a collection POSTs to the collection items path.
    assert ("POST", "/ogc/records/collections/catalog/items") in [
        (entry["method"], entry["raw_path"]) for entry in seen
    ]


async def test_async_ogc_records_pagination_edge_cases() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        # Always a single short page with no next link, to exercise the
        # short-page termination branch.
        return httpx.Response(200, json={"records": [{"id": "only-1"}]})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        collection = client.ogc_records().collection("catalog")
        # limit=0 -> generator yields nothing (early return branch).
        assert [page async for page in collection.record_pages(limit=0)] == []
        # Single short page, no next link -> terminates after one page.
        pages = [page async for page in collection.record_pages(page_size=5, limit=5)]
        assert len(pages) == 1
        assert [r["id"] for r in await collection.records_all(page_size=5, limit=5)] == ["only-1"]


async def test_async_ogc_records_top_level_aliases_and_search_variants() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "raw_path": raw_path})
        return httpx.Response(200, json={"records": [{"id": "r-1"}]})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        records = client.ogc_records()
        # Discovery endpoints: conformance/openapi/collections.
        assert "records" in await records.conformance()
        assert "records" in await records.openapi()
        assert "records" in await records.collections()
        # Top-level client items()/item() aliases (delegate to records()/record()).
        assert (await records.items("catalog", limit=1))["records"][0]["id"] == "r-1"
        assert (await records.item("catalog", "rec/1"))["records"][0]["id"] == "r-1"
        # queryables() on the async collection wrapper.
        assert (await records.collection("catalog").queryables())["records"][0]["id"] == "r-1"
        # search() without a collection GETs the catalog-wide /search endpoint.
        assert (await records.search(params={"q": "x"}))["records"][0]["id"] == "r-1"

    assert ("GET", "/ogc/records/search") in [(e["method"], e["raw_path"]) for e in seen]
    assert ("GET", "/ogc/records/collections/catalog/queryables") in [(e["method"], e["raw_path"]) for e in seen]

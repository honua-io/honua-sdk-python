"""Coverage uplift tests for ``honua_sdk.protocols``.

These exercise less-trafficked endpoints (OGC Coverages, OGC Processes,
OGC Maps styled tiles, WFS transactions, WMS GetFeatureInfo, OData
pagination + aggregations) and the async equivalents. They complement
``test_protocols.py`` and ``test_async_protocols.py``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.protocols import BinaryResponse, ODataQuery


# --------------------------------------------------------------------------
# Sync OGC Maps / Tiles / Coverages / Processes
# --------------------------------------------------------------------------


def test_ogc_maps_openapi_styled_and_tilesets_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(raw)
        if raw.endswith("/map") or raw.endswith("/night/map"):
            return httpx.Response(200, content=b"map-bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        maps = client.ogc_maps()
        assert maps.conformance()["ok"] is True
        assert maps.openapi()["ok"] is True
        assert maps.map(collections=["a", "b"], bbox=[0, 0, 1, 1]) == b"map-bytes"
        assert (
            maps.styled_collection_map("places", "night", bbox=[0, 0, 1, 1]) == b"map-bytes"
        )
        assert maps.collection_tilesets("places")["ok"] is True
        assert maps.collection_tileset("places", "WebMercatorQuad")["ok"] is True

    assert "/ogc/maps/conformance" in seen
    assert "/ogc/maps/openapi.json" in seen
    assert "/ogc/maps/map" in seen
    assert "/ogc/maps/collections/places/styles/night/map" in seen
    assert "/ogc/maps/collections/places/map/tiles" in seen
    assert "/ogc/maps/collections/places/map/tiles/WebMercatorQuad" in seen


def test_ogc_tiles_landing_conformance_collection_matrix_and_dataset_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode("ascii").split("?")[0])
        if "/tiles/" in request.url.path and request.url.path.split("/")[-2].isdigit():
            return httpx.Response(200, content=b"tile-bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        tiles = client.ogc_tiles()
        assert tiles.landing()["ok"] is True
        assert tiles.conformance()["ok"] is True
        assert tiles.collection("imagery")["ok"] is True
        assert tiles.tile_matrix_sets()["ok"] is True
        assert tiles.tile_matrix_set("WebMercatorQuad")["ok"] is True
        assert tiles.dataset_tilesets()["ok"] is True
        assert tiles.collection_tilesets("imagery")["ok"] is True
        assert tiles.tile("WebMercatorQuad", "0", 0, 0) == b"tile-bytes"

    # Assert the constructed request paths (mirroring the sibling OGC maps
    # test) so the coverage-uplift test pins behavior, not just the mock body.
    assert seen == [
        "/ogc/tiles",
        "/ogc/tiles/conformance",
        "/ogc/tiles/collections/imagery",
        "/ogc/tiles/tileMatrixSets",
        "/ogc/tiles/tileMatrixSets/WebMercatorQuad",
        "/ogc/tiles/tiles",
        "/ogc/tiles/collections/imagery/tiles",
        "/ogc/tiles/tiles/WebMercatorQuad/0/0/0",
    ]


def test_ogc_coverages_collections_collection_and_coverage_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(path)
        if path.endswith("/coverage"):
            return httpx.Response(200, content=b"raster-bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        coverages = client.ogc_coverages()
        assert coverages.landing()["ok"] is True
        assert coverages.collections()["ok"] is True
        assert coverages.collection("elevation")["ok"] is True
        assert coverages.coverage("elevation", response_format="tiff") == b"raster-bytes"

    assert "/ogc/coverages/collections/elevation" in seen
    assert "/ogc/coverages/collections/elevation/coverage" in seen


def test_ogc_processes_lifecycle_endpoints() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.raw_path.decode("ascii").split("?")[0]))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        processes = client.ogc_processes()
        assert processes.landing()["ok"] is True
        assert processes.conformance()["ok"] is True
        assert processes.process("buffer")["ok"] is True
        assert processes.jobs()["ok"] is True
        assert processes.job("job-1")["ok"] is True
        assert processes.job_results("job-1")["ok"] is True
        processes.dismiss_job("job-1")

    methods = {m for m, _ in seen}
    assert "GET" in methods
    assert "DELETE" in methods
    assert ("DELETE", "/ogc/processes/jobs/job-1") in seen


# --------------------------------------------------------------------------
# Sync STAC: collections, collection, item, search_pages, search_items
# --------------------------------------------------------------------------


def test_stac_collections_collection_and_item_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode("ascii").split("?")[0])
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        stac = client.stac()
        assert stac.collections()["ok"] is True
        assert stac.collection("imagery")["ok"] is True
        assert stac.item("imagery", "scene-1")["ok"] is True

    assert "/stac/collections" in seen
    assert "/stac/collections/imagery" in seen
    assert "/stac/collections/imagery/items/scene-1" in seen


def test_stac_search_pages_and_items_with_post_body() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Body-mode search uses POST.
        assert request.method == "POST"
        body = bytes(request.read()).decode("utf-8") if request.content else "{}"
        seen.append({"path": request.url.path, "body": body})
        # Single page response (no nextLink), exhausted by short page.
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "scene-1"}],
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        items = client.stac().search_items(
            json_body={"collections": ["landsat"]},
            page_size=10,
            limit=5,
        )

    assert items[0]["id"] == "scene-1"
    assert seen[0]["path"] == "/stac/search"
    assert '"collections":["landsat"]' in seen[0]["body"]


def test_stac_iter_search_items_with_get_params() -> None:
    pages: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages.append(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "x"}],
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        items = list(
            client.stac().iter_search_items(
                params={"collections": "landsat"},
                page_size=10,
                limit=1,
            )
        )

    assert len(items) == 1
    assert pages[0]["collections"] == "landsat"
    assert pages[0]["limit"] == "1"


def test_stac_items_all_returns_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "a"}, {"type": "Feature", "id": "b"}],
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        items = client.stac().items_all("imagery", page_size=10, limit=2)

    assert [item["id"] for item in items] == ["a", "b"]


def test_stac_search_pages_with_zero_limit_short_circuits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Should not make any requests for limit=0")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        pages = list(client.stac().search_pages(limit=0))

    assert pages == []


# --------------------------------------------------------------------------
# Sync WFS / WMS
# --------------------------------------------------------------------------


def test_wfs_describe_feature_type_and_get_feature_and_transaction() -> None:
    seen: list[tuple[str, dict[str, str], bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = bytes(request.read()) if request.method == "POST" else b""
        seen.append(
            (request.method, dict(request.url.params.multi_items()), body)
        )
        return httpx.Response(200, content=b"<xml />")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        wfs = client.wfs()
        assert wfs.describe_feature_type(["topp:roads"]) == "<xml />"
        assert wfs.get_feature(type_names="topp:roads") == "<xml />"
        assert wfs.transaction("<Transaction />") == "<xml />"

    assert seen[0][1]["request"] == "DescribeFeatureType"
    assert seen[1][1]["request"] == "GetFeature"
    assert seen[2][0] == "POST"
    assert b"Transaction" in seen[2][2]


def test_wms_feature_info_returns_bytes_and_response_metadata() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            content=b"info-bytes",
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        info = client.wms("basemap").feature_info(
            layers="roads",
            query_layers="roads",
            i=10,
            j=20,
            bbox=[-1, -1, 1, 1],
            width=256,
            height=256,
        )
        info_response = client.wms("basemap").feature_info_response(
            layers="roads",
            query_layers="roads",
            i=10,
            j=20,
            bbox=[-1, -1, 1, 1],
            width=256,
            height=256,
        )

    assert info == b"info-bytes"
    assert isinstance(info_response, BinaryResponse)
    assert info_response.content == b"info-bytes"
    assert info_response.content_type == "application/json"
    assert seen[0]["request"] == "GetFeatureInfo"


def test_wms_map_returns_bytes_using_map_response_internally() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"png-bytes", headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.wms("basemap").map(
            layers=["roads"], bbox=[0, 0, 1, 1], width=128, height=128
        )

    assert result == b"png-bytes"


def test_wmts_tile_returns_bytes_using_tile_response_internally() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"tile-png", headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.wmts("basemap").tile(
            layer="basemap",
            tile_matrix_set="WebMercatorQuad",
            tile_matrix="0",
            tile_row=0,
            tile_col=0,
        )

    assert result == b"tile-png"


# --------------------------------------------------------------------------
# Sync FeatureServer / ImageServer / GeometryServer extras
# --------------------------------------------------------------------------


def test_featureserver_query_related_records_builds_request() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        seen["path"] = request.url.path
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        client.feature_server("Parcels").query_related_records(
            2, object_ids=[1, 2], relationship_id=4
        )

    assert seen["path"] == "/rest/services/Parcels/FeatureServer/2/queryRelatedRecords"
    assert seen["objectIds"] == "1,2"
    assert seen["relationshipId"] == "4"


def test_featureserver_query_pages_rejects_invalid_arguments() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"features": []}))
    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(ValueError):
            list(client.feature_server("X").query_pages(0, page_size=0))
        with pytest.raises(ValueError):
            list(client.feature_server("X").query_pages(0, max_pages=0))


def test_featureserver_query_pages_returns_when_limit_is_zero() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"features": []}))
    with HonuaClient("http://example.test", transport=transport) as client:
        pages = list(client.feature_server("X").query_pages(0, limit=0))
    assert pages == []


def test_image_server_default_path_when_no_service_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        imagery = client.image_server()
        assert imagery.path == "/rest/services/ImageServer"
        assert imagery.metadata()["ok"] is True
        assert imagery.query()["ok"] is True
        assert imagery.legend()["ok"] is True
        assert imagery.identify({"x": 0, "y": 0})["ok"] is True


def test_geometry_server_buffer_and_simplify_round_trip() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        gs = client.geometry_server()
        assert gs.metadata()["ok"] is True
        assert gs.buffer([{"x": 0, "y": 0}], in_sr=4326, distances=[10], unit="meter")["ok"] is True
        assert gs.simplify([{"x": 0, "y": 0}], sr=4326)["ok"] is True

    assert seen[1]["distances"] == "10"
    assert seen[1]["unit"] == "meter"
    assert seen[2]["sr"] == "4326"


def test_map_server_tile_returns_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"tile-bytes")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.map_server("basemap").tile(level=0, row=0, col=0)

    assert result == b"tile-bytes"


def test_image_server_export_image_with_size() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        return httpx.Response(200, content=b"img")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").export_image(
            [0, 0, 1, 1], size=(256, 128), extra_params={"compression": "lz77"}
        )

    assert seen["size"] == "256,128"
    assert seen["compression"] == "lz77"


# --------------------------------------------------------------------------
# Sync OData: layer_pages, iter_layers, layers_all, features_all,
# feature_pages, feature() lookup, service_document, metadata, layer()
# --------------------------------------------------------------------------


def test_odata_service_document_metadata_and_lookups() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append((request.method, path))
        if path.endswith("$metadata"):
            return httpx.Response(200, content=b"<edmx />", headers={"content-type": "application/xml"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        odata = client.odata()
        assert odata.service_document()["ok"] is True
        assert odata.metadata() == "<edmx />"
        assert odata.layer(7)["ok"] is True
        assert odata.feature(layer_id=7, object_id=11)["ok"] is True

    assert ("GET", "/odata") in seen
    assert ("GET", "/odata/$metadata") in seen
    assert ("GET", "/odata/Layers(7)") in seen
    assert ("GET", "/odata/Features(LayerId=7,ObjectId=11)") in seen


def test_odata_layer_pages_iter_layers_layers_all_use_pagination() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params.multi_items())
        seen.append(params)
        skip = int(params.get("$skip", "0"))
        return httpx.Response(
            200,
            json={"value": [{"id": skip + 1}, {"id": skip + 2}]},
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        odata = client.odata()
        pages = list(odata.layer_pages(page_size=2, limit=2))
        layers_iter = list(odata.iter_layers(page_size=2, limit=2))
        layers_all = odata.layers_all(page_size=2, limit=2)

    assert len(pages) == 1
    assert [layer["id"] for layer in layers_iter] == [1, 2]
    assert [layer["id"] for layer in layers_all] == [1, 2]


def test_odata_features_pages_feature_pages_alias_and_features_all() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(200, json={"value": [{"ObjectId": 1}]})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        odata = client.odata()
        pages = list(odata.features_pages(layer_id=4, page_size=10, limit=1))
        alias_pages = list(odata.feature_pages(layer_id=4, page_size=10, limit=1))
        all_features = odata.features_all(layer_id=4, page_size=10, limit=1)

    assert len(pages) == 1
    assert len(alias_pages) == 1
    assert all_features[0]["ObjectId"] == 1


def test_odata_layers_zero_limit_short_circuits() -> None:
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("should not request"))
    )
    with HonuaClient("http://example.test", transport=transport) as client:
        pages = list(client.odata().layer_pages(limit=0))
    assert pages == []


def test_odata_query_class_defaults_round_trip_through_helpers() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(200, json={"value": []})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        client.odata().features(query=ODataQuery(count=True))

    assert seen[0]["$count"] == "true"


# --------------------------------------------------------------------------
# BinaryResponse helper
# --------------------------------------------------------------------------


def test_binary_response_from_httpx_extracts_metadata() -> None:
    response = httpx.Response(
        200,
        content=b"abc",
        headers={
            "content-type": "image/png",
            "cache-control": "max-age=10",
            "etag": '"abc"',
            "last-modified": "Mon",
            "expires": "Tue",
        },
    )
    binary = BinaryResponse.from_httpx(response)
    assert binary.content == b"abc"
    assert binary.content_type == "image/png"
    assert binary.cache_control == "max-age=10"
    assert binary.etag == '"abc"'
    assert binary.last_modified == "Mon"
    assert binary.expires == "Tue"
    assert binary.status_code == 200


# --------------------------------------------------------------------------
# Async equivalents
# --------------------------------------------------------------------------


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_async_ogc_coverages_endpoints() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path.endswith("/coverage"):
            return httpx.Response(200, content=b"img")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        coverages = client.ogc_coverages()
        assert (await coverages.landing())["ok"] is True
        assert (await coverages.collections())["ok"] is True
        assert (await coverages.collection("elevation"))["ok"] is True
        assert await coverages.coverage("elevation") == b"img"


@pytest.mark.anyio
async def test_async_ogc_processes_lifecycle() -> None:
    methods: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        processes = client.ogc_processes()
        assert (await processes.landing())["ok"] is True
        assert (await processes.conformance())["ok"] is True
        assert (await processes.processes())["ok"] is True
        assert (await processes.process("buffer"))["ok"] is True
        assert (await processes.execute("buffer", {"inputs": {}}))["ok"] is True
        assert (await processes.jobs())["ok"] is True
        assert (await processes.job("job-1"))["ok"] is True
        assert (await processes.job_results("job-1"))["ok"] is True
        await processes.dismiss_job("job-1")

    assert ("DELETE", "/ogc/processes/jobs/job-1") in methods


@pytest.mark.anyio
async def test_async_ogc_maps_styled_and_tileset_endpoints() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path.endswith("/map") or path.endswith("/night/map"):
            return httpx.Response(200, content=b"img")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        maps = client.ogc_maps()
        assert (await maps.landing())["ok"] is True
        assert (await maps.conformance())["ok"] is True
        assert (await maps.openapi())["ok"] is True
        assert await maps.map(collections=["a"], bbox=[0, 0, 1, 1]) == b"img"
        assert (
            await maps.styled_collection_map("places", "night", bbox=[0, 0, 1, 1])
            == b"img"
        )
        assert (await maps.collection_tilesets("places"))["ok"] is True
        assert (await maps.collection_tileset("places", "WebMercatorQuad"))["ok"] is True


@pytest.mark.anyio
async def test_async_ogc_tiles_endpoints() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if "/tiles/" in request.url.path and request.url.path.split("/")[-2].isdigit():
            return httpx.Response(200, content=b"t")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        tiles = client.ogc_tiles()
        assert (await tiles.landing())["ok"] is True
        assert (await tiles.conformance())["ok"] is True
        assert (await tiles.collections())["ok"] is True
        assert (await tiles.collection("imagery"))["ok"] is True
        assert (await tiles.tile_matrix_sets())["ok"] is True
        assert (await tiles.tile_matrix_set("WebMercatorQuad"))["ok"] is True
        assert (await tiles.dataset_tilesets())["ok"] is True
        assert (await tiles.collection_tilesets("imagery"))["ok"] is True
        assert await tiles.tile("WebMercatorQuad", "0", 0, 0) == b"t"


@pytest.mark.anyio
async def test_async_stac_collections_collection_item_and_search_helpers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "id": "s1"}],
                },
            )
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        stac = client.stac()
        assert (await stac.collections())["ok"] is True
        assert (await stac.collection("imagery"))["ok"] is True
        assert (await stac.item("imagery", "scene-1"))["ok"] is True
        items = await stac.search_items(json_body={"collections": ["x"]}, limit=1)
        assert items[0]["id"] == "s1"


@pytest.mark.anyio
async def test_async_stac_iter_search_items_with_get_params() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"type": "FeatureCollection", "features": [{"type": "Feature", "id": "a"}]},
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        items = [
            item
            async for item in client.stac().iter_search_items(
                params={"collections": "x"}, page_size=10, limit=1
            )
        ]
    assert items[0]["id"] == "a"


@pytest.mark.anyio
async def test_async_stac_items_all_returns_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "x"}],
            },
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        items = await client.stac().items_all("imagery", page_size=10, limit=1)
    assert items[0]["id"] == "x"


@pytest.mark.anyio
async def test_async_wfs_describe_and_transaction() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, dict(request.url.params.multi_items())))
        return httpx.Response(200, content=b"<xml />")

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        wfs = client.wfs()
        assert await wfs.describe_feature_type(["topp:roads"]) == "<xml />"
        assert await wfs.get_feature(type_names="topp:roads") == "<xml />"
        assert await wfs.transaction(b"<Transaction />") == "<xml />"

    assert seen[0][1]["request"] == "DescribeFeatureType"
    assert seen[2][0] == "POST"


@pytest.mark.anyio
async def test_async_wms_feature_info_and_map_helpers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"img",
            headers={"content-type": "image/png"},
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        wms = client.wms("basemap")
        assert await wms.map(layers=["roads"], bbox=[0, 0, 1, 1], width=128, height=128) == b"img"
        info = await wms.feature_info(
            layers="roads",
            query_layers="roads",
            i=10,
            j=10,
            bbox=[0, 0, 1, 1],
            width=256,
            height=256,
        )
        assert info == b"img"
        info_response = await wms.feature_info_response(
            layers="roads",
            query_layers="roads",
            i=10,
            j=10,
            bbox=[0, 0, 1, 1],
            width=256,
            height=256,
        )
        assert isinstance(info_response, BinaryResponse)
        assert (await wms.capabilities()) == "img"


@pytest.mark.anyio
async def test_async_wmts_tile_helpers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"t", headers={"content-type": "image/png"}
        )

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        wmts = client.wmts("basemap")
        assert (
            await wmts.tile(
                layer="basemap",
                tile_matrix_set="WebMercatorQuad",
                tile_matrix="0",
                tile_row=0,
                tile_col=0,
            )
        ) == b"t"
        assert (await wmts.capabilities()) == "t"


@pytest.mark.anyio
async def test_async_featureserver_query_related_records_and_layer_metadata() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        seen["path"] = request.url.path
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        fs = client.feature_server("Parcels")
        assert (await fs.layer_metadata(2))["ok"] is True
        assert (
            await fs.query_related_records(2, object_ids=[1, 2], relationship_id=4)
        )["ok"] is True

    assert seen["path"].endswith("/queryRelatedRecords")
    assert seen["objectIds"] == "1,2"


@pytest.mark.anyio
async def test_async_image_server_default_path_endpoints() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tile/0/0/0"):
            return httpx.Response(200, content=b"t")
        if request.url.path.endswith("/exportImage"):
            return httpx.Response(200, content=b"img")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        imagery = client.image_server()
        assert imagery.path == "/rest/services/ImageServer"
        assert (await imagery.metadata())["ok"] is True
        assert (await imagery.identify({"x": 0, "y": 0}))["ok"] is True
        assert (await imagery.query())["ok"] is True
        assert (await imagery.legend())["ok"] is True
        assert await imagery.tile(0, 0, 0) == b"t"
        assert await imagery.export_image([0, 0, 1, 1], size=(2, 2)) == b"img"


@pytest.mark.anyio
async def test_async_geometry_server_buffer_and_simplify() -> None:
    seen: list[dict[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        gs = client.geometry_server()
        assert (await gs.metadata())["ok"] is True
        assert (
            await gs.buffer([{"x": 0, "y": 0}], in_sr=4326, distances=[5], unit="meter")
        )["ok"] is True
        assert (await gs.simplify([{"x": 0, "y": 0}], sr=4326))["ok"] is True
        assert (await gs.project([{"x": 0, "y": 0}], in_sr=4326, out_sr=3857))["ok"] is True


@pytest.mark.anyio
async def test_async_map_server_tile_and_identify() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if "/tile/" in request.url.path:
            return httpx.Response(200, content=b"t")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        ms = client.map_server("basemap")
        assert (await ms.metadata())["ok"] is True
        assert (await ms.layer_metadata(0))["ok"] is True
        assert (
            await ms.identify(
                geometry={"x": 0, "y": 0},
                map_extent=[0, 0, 1, 1],
                image_display="100,100,96",
                layers="show:0",
            )
        )["ok"] is True
        assert await ms.tile(0, 0, 0) == b"t"


@pytest.mark.anyio
async def test_async_odata_layer_pages_iter_layers_layers_all_features_pages() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [{"id": 1}]})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        odata = client.odata()
        pages = [page async for page in odata.layer_pages(page_size=10, limit=1)]
        layers = [layer async for layer in odata.iter_layers(page_size=10, limit=1)]
        layers_all = await odata.layers_all(page_size=10, limit=1)
        feature_pages = [page async for page in odata.features_pages(layer_id=4, page_size=10, limit=1)]
        alias_pages = [page async for page in odata.feature_pages(layer_id=4, page_size=10, limit=1)]
        feats_all = await odata.features_all(layer_id=4, page_size=10, limit=1)
        feats_iter = [
            f async for f in odata.iter_features(layer_id=4, page_size=10, limit=1)
        ]

    assert len(pages) == 1
    assert len(layers) == 1
    assert len(layers_all) == 1
    assert len(feature_pages) == 1
    assert len(alias_pages) == 1
    assert len(feats_all) == 1
    assert len(feats_iter) == 1


@pytest.mark.anyio
async def test_async_odata_service_document_metadata_and_lookups() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("$metadata"):
            return httpx.Response(200, content=b"<edmx />")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        odata = client.odata()
        assert (await odata.service_document())["ok"] is True
        assert (await odata.metadata()) == "<edmx />"
        assert (await odata.layer(7))["ok"] is True
        assert (await odata.feature(7, 11))["ok"] is True

from __future__ import annotations

from typing import Any

import httpx

from honua_sdk import HonuaClient


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

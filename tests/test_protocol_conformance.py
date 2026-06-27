"""OGC/STAC request-conformance regressions (issue #127, AUD-163/164/165).

These pin the mandatory parameters that spec-compliant WMS/WMTS servers require
by default, and the STAC POST ``/search`` method+body pagination contract.
"""

from __future__ import annotations

import json

import httpx

from honua_sdk import HonuaClient


def test_wms_getmap_always_emits_styles_and_crs() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(200, content=b"img", headers={"content-type": "image/png"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        client.wms("basemap").map(layers=["roads"], bbox=[-158, 21, -157, 22], width=256, height=256)

    params = seen[0]
    assert params["request"] == "GetMap"
    # STYLES is mandatory in WMS 1.1.1/1.3.0 (empty value = default style).
    assert params["styles"] == ""
    assert params["crs"] == "EPSG:4326"


def test_wms_getfeatureinfo_emits_mandatory_crs_and_info_format() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        client.wms("basemap").feature_info(
            layers=["roads"],
            query_layers=["roads"],
            i=128,
            j=128,
            bbox=[-158, 21, -157, 22],
            width=256,
            height=256,
        )

    params = seen[0]
    assert params["request"] == "GetFeatureInfo"
    assert params["info_format"] == "application/json"
    assert params["crs"] == "EPSG:4326"
    assert params["styles"] == ""


def test_wmts_gettile_emits_mandatory_style() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(200, content=b"img", headers={"content-type": "image/png"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        client.wmts("basemap").tile(
            layer="basemap",
            tile_matrix_set="WebMercatorQuad",
            tile_matrix="0",
            tile_row=0,
            tile_col=0,
        )

    params = seen[0]
    assert params["request"] == "GetTile"
    # STYLE is mandatory in WMTS 1.0.0 GetTile KVP; defaults to "default".
    assert params["style"] == "default"


def test_stac_post_search_pagination_reposts_next_link_with_body() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        calls.append((request.method, body))
        if body.get("token") == "page-2":
            # Continuation page (reached only by honoring the POST next link).
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": [{"type": "Feature", "id": "s-2"}], "links": []},
            )
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "s-1"}],
                "links": [
                    {
                        "rel": "next",
                        "method": "POST",
                        "href": "http://example.test/stac/search",
                        "merge": True,
                        "body": {"token": "page-2"},
                    }
                ],
            },
        )

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        items = client.stac().search_items(
            json_body={"collections": ["imagery"], "offset": 0},
            page_size=1,
            limit=2,
        )

    assert [item["id"] for item in items] == ["s-1", "s-2"]
    # Both requests are POSTs (the continuation is not silently downgraded to GET)
    assert [method for method, _ in calls] == ["POST", "POST"]
    # The continuation merges the link body onto the original request body.
    assert calls[1][1]["token"] == "page-2"
    assert calls[1][1]["collections"] == ["imagery"]

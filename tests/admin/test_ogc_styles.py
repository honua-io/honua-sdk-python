"""Tests for the styleId-keyed OGC API - Styles client (ADR-0048)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import HonuaHttpError
from honua_admin import (
    HonuaAdminClient,
    OgcStyleLink,
    OgcStyleMetadata,
    OgcStylesheet,
    OgcStyleSummary,
    OgcStylesList,
)

_MAPBOX_STYLE = {
    "version": 8,
    "name": "Parcels",
    "layers": [
        {
            "id": "parcels-fill",
            "type": "fill",
            "paint": {"fill-color": "#3388ff", "fill-opacity": 0.4},
        },
    ],
}

_STYLES_LIST = {
    "styles": [
        {
            "id": "parcels",
            "title": "Parcels",
            "links": [
                {
                    "href": "http://test.honua.io/ogc/styles/parcels",
                    "rel": "stylesheet",
                    "type": "application/vnd.mapbox.style+json",
                    "title": "MapLibre/Mapbox stylesheet",
                },
            ],
        },
        {
            "id": "roads",
            "title": "Roads",
            "links": [],
        },
    ],
    "default": "parcels",
    "links": [
        {"href": "http://test.honua.io/ogc/styles", "rel": "self", "type": "application/json"},
    ],
}


def test_list_styles(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json=_STYLES_LIST)

    with make_client(handler) as client:
        result = client.list_styles()

    assert seen["method"] == "GET"
    assert seen["path"] == "/ogc/styles"
    assert seen["query"]["f"] == "json"
    assert isinstance(result, OgcStylesList)
    assert result.default == "parcels"
    assert [s.style_id for s in result.styles] == ["parcels", "roads"]
    parcels = result.styles[0]
    assert isinstance(parcels, OgcStyleSummary)
    assert parcels.title == "Parcels"
    assert isinstance(parcels.links[0], OgcStyleLink)
    assert parcels.links[0].rel == "stylesheet"
    assert parcels.links[0].type == "application/vnd.mapbox.style+json"
    assert result.links[0].rel == "self"


def test_list_styles_empty_body(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    with make_client(handler) as client:
        result = client.list_styles()

    assert isinstance(result, OgcStylesList)
    assert result.styles == []
    assert result.default is None


def test_get_stylesheet_default_mapbox(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["accept"] = request.headers.get("accept")
        return httpx.Response(
            200,
            json=_MAPBOX_STYLE,
            headers={"content-type": "application/vnd.mapbox.style+json"},
        )

    with make_client(handler) as client:
        sheet = client.get_stylesheet("parcels")

    assert seen["method"] == "GET"
    assert seen["path"] == "/ogc/styles/parcels"
    assert seen["accept"] == "application/vnd.mapbox.style+json"
    assert isinstance(sheet, OgcStylesheet)
    assert sheet.style_id == "parcels"
    assert sheet.encoding == "mapbox-style"
    assert sheet.media_type == "application/vnd.mapbox.style+json"
    assert sheet.as_json()["version"] == 8


def test_get_stylesheet_sld_encoding(make_client) -> None:
    seen: dict[str, Any] = {}
    sld_body = '<?xml version="1.0"?><StyledLayerDescriptor/>'

    def handler(request: httpx.Request) -> httpx.Response:
        seen["accept"] = request.headers.get("accept")
        return httpx.Response(
            200,
            content=sld_body.encode("utf-8"),
            headers={"content-type": "application/vnd.ogc.sld+xml;version=1.1"},
        )

    with make_client(handler) as client:
        sheet = client.get_stylesheet("parcels", encoding="sld-1.1")

    assert seen["accept"] == "application/vnd.ogc.sld+xml;version=1.1"
    assert sheet.encoding == "sld-1.1"
    assert sheet.content == sld_body
    with pytest.raises(ValueError):
        sheet.as_json()


def test_get_stylesheet_path_escaping(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path.decode("ascii")
        return httpx.Response(200, json=_MAPBOX_STYLE)

    with make_client(handler) as client:
        client.get_stylesheet("a b/c")

    assert "a%20b%2Fc" in seen["raw_path"]


def test_get_stylesheet_406(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(406, json={"message": "Not acceptable"})

    with make_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.get_stylesheet("parcels", encoding="sld-1.0")

    assert exc_info.value.status_code == 406


def test_get_style_metadata(make_client) -> None:
    seen: dict[str, Any] = {}
    payload = {
        "id": "parcels",
        "title": "Parcels",
        "description": "Cadastral parcels",
        "keywords": ["cadastre", "parcels"],
        "license": "CC-BY-4.0",
        "version": "3",
        "links": [
            {
                "href": "http://test.honua.io/ogc/styles/parcels",
                "rel": "stylesheet",
                "type": "application/vnd.mapbox.style+json",
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json=payload)

    with make_client(handler) as client:
        meta = client.get_style_metadata("parcels")

    assert seen["method"] == "GET"
    assert seen["path"] == "/ogc/styles/parcels/metadata"
    assert isinstance(meta, OgcStyleMetadata)
    assert meta.style_id == "parcels"
    assert meta.description == "Cadastral parcels"
    assert meta.keywords == ["cadastre", "parcels"]
    assert meta.license == "CC-BY-4.0"
    assert meta.version == "3"
    assert meta.links[0].rel == "stylesheet"


def test_get_style_metadata_404(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Style 'nope' not found."})

    with make_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.get_style_metadata("nope")

    assert exc_info.value.status_code == 404


def test_update_style(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type")
        seen["prefer"] = request.headers.get("prefer")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(204)

    with make_client(handler) as client:
        result = client.update_style("parcels", _MAPBOX_STYLE)

    assert result is None
    assert seen["method"] == "PUT"
    assert seen["path"] == "/ogc/styles/parcels"
    assert seen["content_type"] == "application/vnd.mapbox.style+json"
    assert seen["prefer"] is None
    assert seen["body"]["version"] == 8


def test_update_style_strict(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["prefer"] = request.headers.get("prefer")
        return httpx.Response(204)

    with make_client(handler) as client:
        client.update_style("parcels", _MAPBOX_STYLE, strict=True)

    assert seen["prefer"] == "handling=strict"


def test_update_style_400(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "MapLibre style is invalid."})

    with make_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.update_style("parcels", {"version": 8})

    assert exc_info.value.status_code == 400


def test_update_style_404(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Style 'nope' not found."})

    with make_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.update_style("nope", _MAPBOX_STYLE)

    assert exc_info.value.status_code == 404


def test_get_stylesheet_invalid_encoding_rejected_before_request() -> None:
    """Unknown encodings raise ValueError without issuing a request."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be made")

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
        with pytest.raises(ValueError):
            client.get_stylesheet("parcels", encoding="geojson")  # type: ignore[arg-type]

"""Async coverage for the styleId-keyed OGC API - Styles client (ADR-0048)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_admin import (
    AsyncHonuaAdminClient,
    OgcStyleMetadata,
    OgcStylesheet,
    OgcStylesList,
)
from honua_sdk import HonuaHttpError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


pytestmark = pytest.mark.anyio


def _async_admin_client(handler: Any) -> AsyncHonuaAdminClient:
    transport = httpx.MockTransport(handler)
    return AsyncHonuaAdminClient("http://test.honua.io", transport=transport)


_MAPBOX_STYLE = {"version": 8, "layers": []}


async def test_async_list_styles() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={"styles": [{"id": "parcels", "title": "Parcels", "links": []}], "default": "parcels"},
        )

    async with _async_admin_client(handler) as client:
        result = await client.list_styles()

    assert seen["method"] == "GET"
    assert seen["path"] == "/ogc/styles"
    assert isinstance(result, OgcStylesList)
    assert result.default == "parcels"
    assert result.styles[0].style_id == "parcels"


async def test_async_get_stylesheet() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["accept"] = request.headers.get("accept")
        return httpx.Response(
            200,
            json=_MAPBOX_STYLE,
            headers={"content-type": "application/vnd.mapbox.style+json"},
        )

    async with _async_admin_client(handler) as client:
        sheet = await client.get_stylesheet("parcels")

    assert seen["accept"] == "application/vnd.mapbox.style+json"
    assert isinstance(sheet, OgcStylesheet)
    assert sheet.encoding == "mapbox-style"
    assert sheet.as_json()["version"] == 8


async def test_async_get_style_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ogc/styles/parcels/metadata"
        return httpx.Response(200, json={"id": "parcels", "title": "Parcels", "links": []})

    async with _async_admin_client(handler) as client:
        meta = await client.get_style_metadata("parcels")

    assert isinstance(meta, OgcStyleMetadata)
    assert meta.style_id == "parcels"
    assert meta.keywords == []


async def test_async_update_style() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["content_type"] = request.headers.get("content-type")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(204)

    async with _async_admin_client(handler) as client:
        result = await client.update_style("parcels", _MAPBOX_STYLE, strict=True)

    assert result is None
    assert seen["method"] == "PUT"
    assert seen["content_type"] == "application/vnd.mapbox.style+json"
    assert seen["body"]["version"] == 8


async def test_async_update_style_404() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    async with _async_admin_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            await client.update_style("nope", _MAPBOX_STYLE)

    assert exc_info.value.status_code == 404

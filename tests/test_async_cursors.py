"""Async cursor + geodataframe ergonomics tests (AsyncSource surface)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient
from honua_sdk.cursors import AsyncInsertCursor, AsyncSearchCursor, AsyncUpdateCursor
from honua_sdk.models import SourceDescriptor, SourceLocator


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


pytestmark = pytest.mark.anyio

_PAGE = {
    "geometryType": "esriGeometryPoint",
    "spatialReference": {"wkid": 4326},
    "fields": [{"name": "objectid", "type": "esriFieldTypeOID"}],
    "features": [
        {"attributes": {"objectid": 1, "name": "A"}, "geometry": {"x": 10.0, "y": 20.0}},
        {"attributes": {"objectid": 2, "name": "B"}, "geometry": {"x": 30.0, "y": 40.0}},
    ],
    "exceededTransferLimit": False,
}


def _descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="parcels",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="parcels", layer_id=0),
    )


def _edit_transport(edits: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/applyEdits"):
            edits.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"addResults": [{"success": True}], "updateResults": [{"success": True}]})
        return httpx.Response(200, json=_PAGE)

    return httpx.MockTransport(handler)


async def test_async_search_cursor_yields_rows() -> None:
    async with AsyncHonuaClient("http://example.test", transport=_edit_transport([])) as client:
        source = client.source(_descriptor())
        cursor = source.search_cursor()
        assert isinstance(cursor, AsyncSearchCursor)
        rows = [row async for row in cursor.rows()]
    assert [r.object_id for r in rows] == [1, 2]


async def test_async_iter_rows_alias() -> None:
    async with AsyncHonuaClient("http://example.test", transport=_edit_transport([])) as client:
        source = client.source(_descriptor())
        oids = [row.object_id async for row in source.iter_rows()]
    assert oids == [1, 2]


async def test_async_insert_cursor_flushes_on_exit() -> None:
    edits: list[dict[str, Any]] = []
    async with AsyncHonuaClient("http://example.test", transport=_edit_transport(edits)) as client:
        source = client.source(_descriptor())
        async with source.insert_cursor() as cursor:
            assert isinstance(cursor, AsyncInsertCursor)
            cursor.insert_row({"name": "X"}, {"x": 1.0, "y": 1.0})
    assert len(edits) == 1
    assert edits[0]["adds"][0]["attributes"]["name"] == "X"


async def test_async_update_cursor_iterate_and_write_back() -> None:
    edits: list[dict[str, Any]] = []
    async with AsyncHonuaClient("http://example.test", transport=_edit_transport(edits)) as client:
        source = client.source(_descriptor())
        async with source.update_cursor() as cursor:
            assert isinstance(cursor, AsyncUpdateCursor)
            async for row in cursor:
                cursor.update_row(row, attributes={"name": row.attributes["name"].lower()})
    assert len(edits) == 1
    assert {u["attributes"]["name"] for u in edits[0]["updates"]} == {"a", "b"}


async def test_async_to_geodataframe() -> None:
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("shapely")
    async with AsyncHonuaClient("http://example.test", transport=_edit_transport([])) as client:
        source = client.source(_descriptor())
        gdf = await source.to_geodataframe()
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 2


async def test_async_schema() -> None:
    from honua_sdk import LayerSchema

    metadata = {"id": 0, "name": "Parcels", "geometryType": "esriGeometryPolygon", "fields": []}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=metadata)

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        schema = await client.source(_descriptor()).schema()
    assert isinstance(schema, LayerSchema)
    assert schema.geometry_type == "Polygon"

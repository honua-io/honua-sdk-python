"""Tests for arcpy.da-style cursor ergonomics and the first-class to_geodataframe.

Covers:
* ``Source.search_cursor`` / ``iter_rows`` — lazy row iteration with positional
  value tuples and the ``"SHAPE@"`` geometry token (``SearchCursor`` analogue).
* ``Source.update_cursor`` / ``insert_cursor`` — batched write-back over
  ``apply_edits`` (``UpdateCursor`` / ``InsertCursor`` analogues).
* ``Result.to_geodataframe`` / ``Source.to_geodataframe`` — the SEDF-equivalent
  one-call geopandas bridge (gated on the optional geopandas extra).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import HonuaClient
from honua_sdk.cursors import SHAPE_TOKEN, InsertCursor, Row, SearchCursor, UpdateCursor
from honua_sdk.models import SourceDescriptor, SourceLocator

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


def _query_transport(captured: dict[str, Any] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["query_params"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json=_PAGE)

    return httpx.MockTransport(handler)


def _edit_transport(edits: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/applyEdits"):
            edits.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"addResults": [{"success": True}], "updateResults": [{"success": True}]})
        return httpx.Response(200, json=_PAGE)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# SearchCursor
# ---------------------------------------------------------------------------


def test_search_cursor_yields_rows() -> None:
    with HonuaClient("http://example.test", transport=_query_transport()) as client:
        source = client.source(_descriptor())
        cursor = source.search_cursor()
        assert isinstance(cursor, SearchCursor)
        rows = list(cursor.rows())

    assert [r.object_id for r in rows] == [1, 2]
    assert all(isinstance(r, Row) for r in rows)
    assert rows[0].attributes["name"] == "A"


def test_search_cursor_field_projection_with_shape_token() -> None:
    pytest.importorskip("shapely")
    with HonuaClient("http://example.test", transport=_query_transport()) as client:
        source = client.source(_descriptor())
        values = list(source.search_cursor(["name", SHAPE_TOKEN]))

    assert values[0][0] == "A"
    assert values[0][1].geom_type == "Point"
    assert (values[0][1].x, values[0][1].y) == (10.0, 20.0)


def test_search_cursor_is_lazy() -> None:
    """The cursor must stream rows, not materialize them eagerly on creation."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_PAGE)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        source = client.source(_descriptor())
        cursor = source.search_cursor()
        assert calls["n"] == 0  # no request until iteration begins
        iterator = cursor.rows()
        first = next(iterator)
        assert first.object_id == 1
        assert calls["n"] == 1


def test_search_cursor_forwards_where_and_out_fields() -> None:
    cap: dict[str, Any] = {}
    with HonuaClient("http://example.test", transport=_query_transport(cap)) as client:
        source = client.source(_descriptor())
        list(source.search_cursor(["name"], where="VALUE > 100").rows())

    assert cap["query_params"].get("where") == "VALUE > 100"
    assert cap["query_params"].get("outFields") == "name"


def test_iter_rows_alias() -> None:
    with HonuaClient("http://example.test", transport=_query_transport()) as client:
        source = client.source(_descriptor())
        rows = list(source.iter_rows())
    assert [r.object_id for r in rows] == [1, 2]


def test_search_cursor_forwards_geometry_filter() -> None:
    cap: dict[str, Any] = {}
    geom = {"x": 1.0, "y": 2.0}
    with HonuaClient("http://example.test", transport=_query_transport(cap)) as client:
        source = client.source(_descriptor())
        list(source.search_cursor([SHAPE_TOKEN], geometry_filter=geom).rows())
    assert "geometry" in cap["query_params"]


def test_search_cursor_context_manager() -> None:
    with HonuaClient("http://example.test", transport=_query_transport()) as client:
        source = client.source(_descriptor())
        with source.search_cursor() as cursor:
            rows = list(cursor.rows())
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# InsertCursor
# ---------------------------------------------------------------------------


def test_insert_cursor_batches_and_flushes_on_exit() -> None:
    edits: list[dict[str, Any]] = []
    with HonuaClient("http://example.test", transport=_edit_transport(edits)) as client:
        source = client.source(_descriptor())
        with source.insert_cursor(batch_size=2) as cursor:
            assert isinstance(cursor, InsertCursor)
            cursor.insert_row({"name": "X"}, {"x": 1.0, "y": 1.0})
            cursor.insert_row({"name": "Y"}, {"x": 2.0, "y": 2.0})  # fills batch -> flush
            assert len(edits) == 1  # auto-flushed at batch_size
            cursor.insert_row({"name": "Z"})  # remainder flushed on __exit__

    assert len(edits) == 2
    assert edits[0]["adds"][0]["attributes"]["name"] == "X"
    assert edits[0]["adds"][0]["geometry"] == {"x": 1.0, "y": 1.0}
    assert edits[1]["adds"][0]["attributes"]["name"] == "Z"


def test_insert_cursor_empty_flush_returns_none() -> None:
    with HonuaClient("http://example.test", transport=_edit_transport([])) as client:
        source = client.source(_descriptor())
        cursor = source.insert_cursor()
        assert cursor.flush() is None
        assert cursor.results == ()


def test_cursor_rejects_non_positive_batch_size() -> None:
    with HonuaClient("http://example.test", transport=_edit_transport([])) as client:
        source = client.source(_descriptor())
        with pytest.raises(ValueError, match="batch_size"):
            source.insert_cursor(batch_size=0)


# ---------------------------------------------------------------------------
# UpdateCursor (iterate rows, edit, write back)
# ---------------------------------------------------------------------------


def test_update_cursor_iterates_and_writes_back() -> None:
    edits: list[dict[str, Any]] = []
    with HonuaClient("http://example.test", transport=_edit_transport(edits)) as client:
        source = client.source(_descriptor())
        with source.update_cursor() as cursor:
            assert isinstance(cursor, UpdateCursor)
            for row in cursor:
                cursor.update_row(row, attributes={"name": row.attributes["name"].lower()})

    assert len(edits) == 1  # single batch flushed on exit
    updates = edits[0]["updates"]
    # The source carries its OID under the lowercase ``objectid`` key; update_row
    # must reuse that exact key and NOT also inject a canonical ``OBJECTID`` (which
    # would leave two object-id-like keys for the same row and corrupt the edit).
    for update in updates:
        oid_keys = [k for k in update["attributes"] if k in ("objectid", "objectId", "OBJECTID")]
        assert oid_keys == ["objectid"], oid_keys
    assert {u["attributes"]["objectid"] for u in updates} == {1, 2}
    assert {u["attributes"]["name"] for u in updates} == {"a", "b"}


def test_update_cursor_batch_size_flushes_mid_iteration() -> None:
    edits: list[dict[str, Any]] = []
    with HonuaClient("http://example.test", transport=_edit_transport(edits)) as client:
        source = client.source(_descriptor())
        cursor = source.update_cursor(batch_size=1)
        for row in cursor:
            cursor.update_row(row)  # each update flushes immediately
        assert len(edits) == 2
        assert cursor.flush() is None  # nothing pending
    assert len(cursor.results) == 2


def test_update_row_without_object_id_raises() -> None:
    from honua_sdk.models import QueryFeature

    with HonuaClient("http://example.test", transport=_edit_transport([])) as client:
        source = client.source(_descriptor())
        cursor = source.update_cursor()
        row = Row(feature=QueryFeature(id=None, properties={"name": "no-oid"}))
        with pytest.raises(ValueError, match="object id"):
            cursor.update_row(row)


def test_update_row_adds_canonical_objectid_only_when_absent() -> None:
    from honua_sdk.models import QueryFeature

    edits: list[dict[str, Any]] = []
    with HonuaClient("http://example.test", transport=_edit_transport(edits)) as client:
        source = client.source(_descriptor())
        cursor = source.update_cursor(batch_size=1)
        # OID present only via the feature id, not in properties -> canonical
        # ``OBJECTID`` is injected.
        cursor.update_row(Row(feature=QueryFeature(id=7, properties={"name": "x"})))
    attrs = edits[0]["updates"][0]["attributes"]
    oid_keys = [k for k in attrs if k in ("objectid", "objectId", "OBJECTID")]
    assert oid_keys == ["OBJECTID"]
    assert attrs["OBJECTID"] == 7


# ---------------------------------------------------------------------------
# to_geodataframe (SEDF equivalent)
# ---------------------------------------------------------------------------


def test_result_to_geodataframe() -> None:
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("shapely")
    with HonuaClient("http://example.test", transport=_query_transport()) as client:
        source = client.source(_descriptor())
        result = source.query()
        gdf = result.to_geodataframe()

    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 2
    assert list(gdf["name"]) == ["A", "B"]
    assert gdf.geometry.iloc[0].geom_type == "Point"
    assert (gdf.geometry.iloc[0].x, gdf.geometry.iloc[0].y) == (10.0, 20.0)


def test_source_to_geodataframe_one_call() -> None:
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("shapely")
    with HonuaClient("http://example.test", transport=_query_transport()) as client:
        source = client.source(_descriptor())
        gdf = source.to_geodataframe()
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 2

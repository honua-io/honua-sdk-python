"""Regression tests for the pre-release performance / resource-lifecycle audit (#131).

Covers:

* geopandas conversion no longer boxes a pandas Series per row (columnar
  records + one geometry pass) and still produces identical output, including
  the geometry-only and null-geometry edge cases.
* the FeatureServer non-advancing-cursor guard compares against the previous
  page only, so its tracking set stays bounded on the streaming path while
  still stopping a server that ignores ``resultOffset``.
* with_options/copy independent clones reuse a caller-supplied transport
  without closing it, so closing the clone no longer tears down the original's
  connection pool.
"""

from __future__ import annotations

import httpx
import pytest

from honua_sdk import HonuaClient

gpd = pytest.importorskip("geopandas")
from shapely.geometry import Point

from honua_sdk.geopandas import (
    geodataframe_to_features,
    geodataframe_to_geojson,
)


# ---------------------------------------------------------------------------
# geopandas columnar conversion
# ---------------------------------------------------------------------------


def test_geodataframe_to_features_columnar_output() -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["a", "b"], "value": [1, 2]},
        geometry=[Point(-117.1, 32.7), None],
    )
    features = geodataframe_to_features(gdf)
    assert features[0]["attributes"] == {"name": "a", "value": 1}
    assert features[0]["geometry"] == {"x": -117.1, "y": 32.7}
    # None geometry yields an attributes-only feature (no "geometry" key).
    assert features[1]["attributes"] == {"name": "b", "value": 2}
    assert "geometry" not in features[1]


def test_geodataframe_to_features_geometry_only_frame() -> None:
    # No attribute columns: to_dict("records") would return [] — the conversion
    # must still emit one (empty-attributes) feature per row.
    gdf = gpd.GeoDataFrame(geometry=[Point(0, 0), Point(1, 1)])
    features = geodataframe_to_features(gdf)
    assert len(features) == 2
    assert all(f["attributes"] == {} for f in features)
    assert features[1]["geometry"] == {"x": 1.0, "y": 1.0}


def test_geodataframe_to_geojson_columnar_output() -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["a"]},
        geometry=[Point(5, 6)],
    )
    fc = geodataframe_to_geojson(gdf)
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["properties"] == {"name": "a"}
    assert fc["features"][0]["geometry"] == {"type": "Point", "coordinates": (5.0, 6.0)}


# ---------------------------------------------------------------------------
# FeatureServer non-advancing-cursor guard (bounded tracking set)
# ---------------------------------------------------------------------------


def test_query_pages_stops_on_non_advancing_cursor() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        # Server ignores resultOffset and returns the SAME page forever.
        return httpx.Response(
            200,
            json={
                "features": [{"attributes": {"objectid": 1}}, {"attributes": {"objectid": 2}}],
                "exceededTransferLimit": True,
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        pages = list(client.feature_server("parcels").query_pages(0, page_size=2, max_pages=10))

    # First page yielded; the identical second page trips the guard and stops —
    # we do NOT loop to max_pages.
    assert [[f.object_id for f in p.features] for p in pages] == [[1, 2]]
    assert calls["n"] == 2


def test_query_pages_advancing_cursor_yields_all_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        offset = int(query["resultOffset"])
        count = int(query["resultRecordCount"])
        features = [{"attributes": {"objectid": offset + i + 1}} for i in range(count)]
        return httpx.Response(200, json={"features": features, "exceededTransferLimit": offset == 0})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        pages = list(client.feature_server("parcels").query_pages(0, page_size=2, limit=3))
    assert [[f.object_id for f in p.features] for p in pages] == [[1, 2], [3]]


# ---------------------------------------------------------------------------
# with_options independent clone does not close the shared transport
# ---------------------------------------------------------------------------


class _CloseTrackingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ready"})

    def close(self) -> None:
        self.closed = True


def test_independent_clone_does_not_close_caller_transport() -> None:
    caller_transport = _CloseTrackingTransport()
    original = HonuaClient(
        "http://example.test", transport=caller_transport, timeout=30.0, max_retries=0
    )
    try:
        # base_url override -> independent, clone-owned httpx.Client.
        clone = original.with_options(base_url="http://other.test")
        assert clone._client is not original._client
        assert clone._owns_client is True
        clone.close()
        # Closing the clone must NOT tear down the caller-supplied transport
        # that the original still depends on.
        assert caller_transport.closed is False
        # The original is still usable after the clone was closed.
        assert original.readiness() == {"status": "ready"}
    finally:
        original.close()
    # The original owns the caller transport and closes it on its own close.
    assert caller_transport.closed is True


def test_smaller_timeout_clone_still_routes_through_shared_transport() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout", {}))
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "http://example.test", transport=transport, timeout=30.0, max_retries=0
    ) as original:
        # Smaller timeout -> independent clone, but it must still reuse the
        # (mock) transport, applying the tighter transport-level timeout.
        clone = original.with_options(timeout=1.0)
        assert clone.readiness() == {"status": "ready"}
        clone.close()
    assert seen and seen[0]["connect"] == 1.0

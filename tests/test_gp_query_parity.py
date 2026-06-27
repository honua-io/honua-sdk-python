"""GP query-parity tests: spatial filters, statistics/aggregation, pagination, gRPC binding.

Covers the GeoServices REST request-construction parity gaps closed for Esri-SDK
"select by location" + analytics:

* ``Query.spatial_filter`` / ``FeatureQuery.spatial_filter`` translated to the
  GeoServices ``geometry``/``geometryType``/``spatialRel``/``inSR`` params for an
  arbitrary geometry + each :class:`SpatialRelationship`, including
  ``within-distance`` (``distance`` + ``units``).
* ``out_statistics`` / ``group_by`` / ``return_distinct_values`` /
  ``return_count_only`` translated to ``outStatistics`` /
  ``groupByFieldsForStatistics`` / ``returnDistinctValues`` / ``returnCountOnly``.
* ``max_pages=None`` walks unbounded; a bounded walk that truncates warns.
* :meth:`HonuaClient.grpc` builds the analytic gRPC client from the same config.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import HonuaClient, Query, SourceDescriptor
from honua_sdk._geoservices_query import (
    coerce_geometry,
    normalize_spatial_relationship,
    spatial_filter_params,
    statistics_params,
)


# ---------------------------------------------------------------------------
# Pure translation helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relationship", "expected"),
    [
        ("intersects", "esriSpatialRelIntersects"),
        ("within", "esriSpatialRelWithin"),
        ("contains", "esriSpatialRelContains"),
        ("crosses", "esriSpatialRelCrosses"),
        ("touches", "esriSpatialRelTouches"),
        ("overlaps", "esriSpatialRelOverlaps"),
        ("envelope-intersects", "esriSpatialRelEnvelopeIntersects"),
        ("within-distance", "esriSpatialRelIntersects"),
        # gRPC-style SCREAMING_SNAKE and raw Esri tokens both accepted.
        ("WITHIN", "esriSpatialRelWithin"),
        ("esriSpatialRelOverlaps", "esriSpatialRelOverlaps"),
    ],
)
def test_normalize_spatial_relationship(relationship: str, expected: str) -> None:
    assert normalize_spatial_relationship(relationship) == expected


def test_normalize_spatial_relationship_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported spatial relationship"):
        normalize_spatial_relationship("near-ish")


def test_coerce_geometry_esri_polygon_passthrough() -> None:
    esri = {"rings": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    geometry, gtype = coerce_geometry(esri)
    assert gtype == "esriGeometryPolygon"
    assert geometry == esri


def test_coerce_geometry_geojson_polygon() -> None:
    geojson = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    geometry, gtype = coerce_geometry(geojson)
    assert gtype == "esriGeometryPolygon"
    assert geometry == {"rings": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}


def test_coerce_geometry_geojson_point_with_z() -> None:
    geometry, gtype = coerce_geometry({"type": "Point", "coordinates": [1, 2, 3]})
    assert gtype == "esriGeometryPoint"
    assert geometry == {"x": 1, "y": 2, "z": 3}


def test_coerce_geometry_geo_interface() -> None:
    class _FakeShapely:
        @property
        def __geo_interface__(self) -> dict[str, Any]:
            return {"type": "Point", "coordinates": [10.0, 20.0]}

    geometry, gtype = coerce_geometry(_FakeShapely())
    assert gtype == "esriGeometryPoint"
    assert geometry == {"x": 10.0, "y": 20.0}


def test_spatial_filter_params_polygon_intersects() -> None:
    params = spatial_filter_params(
        {
            "geometry": {"rings": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
            "relationship": "intersects",
            "in_sr": 3857,
        }
    )
    assert params["geometryType"] == "esriGeometryPolygon"
    assert params["spatialRel"] == "esriSpatialRelIntersects"
    assert params["inSR"] == 3857
    assert json.loads(params["geometry"]) == {"rings": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}


def test_spatial_filter_params_defaults_in_sr_to_4326() -> None:
    params = spatial_filter_params({"geometry": {"x": 1, "y": 2}})
    assert params["geometryType"] == "esriGeometryPoint"
    assert params["spatialRel"] == "esriSpatialRelIntersects"
    assert params["inSR"] == 4326


def test_spatial_filter_params_reads_embedded_spatial_reference() -> None:
    params = spatial_filter_params(
        {"geometry": {"x": 1, "y": 2, "spatialReference": {"wkid": 2193}}}
    )
    assert params["inSR"] == 2193


def test_spatial_filter_params_within_distance() -> None:
    params = spatial_filter_params(
        {
            "geometry": {"x": 1, "y": 2},
            "relationship": "within-distance",
            "distance": 500,
            "units": "meters",
        }
    )
    assert params["spatialRel"] == "esriSpatialRelIntersects"
    assert params["distance"] == 500
    assert params["units"] == "esriSRUnit_Meter"


def test_spatial_filter_params_within_distance_requires_distance() -> None:
    with pytest.raises(ValueError, match="requires a 'distance'"):
        spatial_filter_params({"geometry": {"x": 1, "y": 2}, "relationship": "within-distance"})


def test_statistics_params_out_statistics_and_group_by() -> None:
    params = statistics_params(
        out_statistics=[
            {"statistic_type": "sum", "on_statistic_field": "pop", "out_statistic_field_name": "total_pop"},
            {"statistic_type": "avg", "on_statistic_field": "age"},
        ],
        group_by=["state", "county"],
    )
    stats = json.loads(params["outStatistics"])
    assert stats[0] == {
        "statisticType": "sum",
        "onStatisticField": "pop",
        "outStatisticFieldName": "total_pop",
    }
    # Default out-name when omitted.
    assert stats[1]["outStatisticFieldName"] == "avg_age"
    assert params["groupByFieldsForStatistics"] == "state,county"


def test_statistics_params_distinct_and_count_only() -> None:
    params = statistics_params(return_distinct_values=True, return_count_only=True)
    assert params["returnDistinctValues"] == "true"
    assert params["returnCountOnly"] == "true"


def test_statistics_params_rejects_unknown_statistic_type() -> None:
    with pytest.raises(ValueError, match="Unsupported statistic type"):
        statistics_params(out_statistics=[{"statistic_type": "median", "on_statistic_field": "x"}])


def test_statistics_params_requires_field_and_type() -> None:
    with pytest.raises(ValueError, match="requires a 'statistic_type'"):
        statistics_params(out_statistics=[{"statistic_type": "sum"}])


@pytest.mark.parametrize(
    ("geojson", "expected"),
    [
        ({"type": "MultiPoint", "coordinates": [[0, 0], [1, 1]]}, {"points": [[0, 0], [1, 1]]}),
        ({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, {"paths": [[[0, 0], [1, 1]]]}),
        (
            {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]]},
            {"paths": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]]},
        ),
        (
            {"type": "MultiPolygon", "coordinates": [[[[0, 0], [0, 1], [1, 1], [0, 0]]]]},
            {"rings": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
        ),
    ],
)
def test_coerce_geometry_geojson_multipart(geojson: dict[str, Any], expected: dict[str, Any]) -> None:
    geometry, _ = coerce_geometry(geojson)
    assert geometry == expected


def test_coerce_geometry_rejects_unknown_geojson_type() -> None:
    with pytest.raises(ValueError, match="Unsupported GeoJSON geometry type"):
        coerce_geometry({"type": "GeometryCollection", "coordinates": []})


def test_coerce_geometry_rejects_non_geometry() -> None:
    with pytest.raises(TypeError, match="Esri JSON mapping"):
        coerce_geometry("not-a-geometry")


def test_coerce_geometry_requires_value() -> None:
    with pytest.raises(ValueError, match="requires a geometry"):
        coerce_geometry(None)


@pytest.mark.parametrize(
    ("esri", "expected_type"),
    [
        ({"x": 1, "y": 2}, "esriGeometryPoint"),
        ({"paths": [[[0, 0], [1, 1]]]}, "esriGeometryPolyline"),
        ({"points": [[0, 0]]}, "esriGeometryMultipoint"),
        ({"xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1}, "esriGeometryEnvelope"),
    ],
)
def test_coerce_geometry_infers_esri_type(esri: dict[str, Any], expected_type: str) -> None:
    _, gtype = coerce_geometry(esri)
    assert gtype == expected_type


def test_coerce_geometry_unknown_esri_shape_raises() -> None:
    with pytest.raises(ValueError, match="Could not infer the Esri geometry type"):
        coerce_geometry({"unknown": 1})


def test_spatial_filter_params_explicit_geometry_type_override() -> None:
    params = spatial_filter_params(
        {"geometry": {"unknown": 1}, "geometry_type": "esriGeometryPolygon"}
    )
    assert params["geometryType"] == "esriGeometryPolygon"


def test_spatial_filter_params_reads_sr_wkt() -> None:
    params = spatial_filter_params(
        {"geometry": {"x": 1, "y": 2}, "in_sr": {"wkt": "PROJCS[...]"}}
    )
    assert params["inSR"] == "PROJCS[...]"


@pytest.mark.parametrize(
    ("units", "expected"),
    [
        ("ft", "esriSRUnit_Foot"),
        ("miles", "esriSRUnit_StatuteMile"),
        ("esriSRUnit_Meter", "esriSRUnit_Meter"),
    ],
)
def test_spatial_filter_params_distance_unit_aliases(units: str, expected: str) -> None:
    params = spatial_filter_params(
        {
            "geometry": {"x": 1, "y": 2},
            "relationship": "within-distance",
            "distance": 1,
            "units": units,
        }
    )
    assert params["units"] == expected


def test_spatial_filter_params_rejects_unknown_units() -> None:
    with pytest.raises(ValueError, match="Unsupported distance unit"):
        spatial_filter_params(
            {
                "geometry": {"x": 1, "y": 2},
                "relationship": "within-distance",
                "distance": 1,
                "units": "furlongs",
            }
        )


# ---------------------------------------------------------------------------
# End-to-end through client.query (FeatureServer REST path)
# ---------------------------------------------------------------------------


def _capture_client(captured: dict[str, Any], *, exceeded: bool = False) -> HonuaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"features": [], "exceededTransferLimit": exceeded})

    return HonuaClient("https://example.test", transport=httpx.MockTransport(handler))


def test_query_polygon_spatial_filter_emits_geoservices_params() -> None:
    captured: dict[str, Any] = {}
    polygon = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    with _capture_client(captured) as client:
        client.query(
            "default",
            spatial_filter={"geometry": polygon, "relationship": "within", "in_sr": 4326},
        )
    params = captured["query"]
    assert params["geometryType"] == "esriGeometryPolygon"
    assert params["spatialRel"] == "esriSpatialRelWithin"
    assert params["inSR"] == "4326"
    assert json.loads(params["geometry"]) == {"rings": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}


@pytest.mark.parametrize(
    ("relationship", "expected_rel"),
    [
        ("intersects", "esriSpatialRelIntersects"),
        ("within", "esriSpatialRelWithin"),
        ("contains", "esriSpatialRelContains"),
        ("crosses", "esriSpatialRelCrosses"),
        ("touches", "esriSpatialRelTouches"),
        ("overlaps", "esriSpatialRelOverlaps"),
    ],
)
def test_query_each_spatial_relationship(relationship: str, expected_rel: str) -> None:
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        client.query(
            "default",
            spatial_filter={"geometry": {"x": 1, "y": 2}, "relationship": relationship},
        )
    assert captured["query"]["spatialRel"] == expected_rel


def test_query_within_distance_emits_distance_and_units() -> None:
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        client.query(
            "default",
            spatial_filter={
                "geometry": {"x": 1, "y": 2},
                "relationship": "within-distance",
                "distance": 1000,
                "units": "km",
            },
        )
    params = captured["query"]
    assert params["distance"] == "1000"
    assert params["units"] == "esriSRUnit_Kilometer"


def test_query_out_statistics_and_group_by() -> None:
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        client.query(
            "default",
            out_statistics=[{"statistic_type": "count", "on_statistic_field": "objectid"}],
            group_by="category",
        )
    params = captured["query"]
    assert json.loads(params["outStatistics"])[0]["statisticType"] == "count"
    assert params["groupByFieldsForStatistics"] == "category"


def test_query_return_distinct_and_count_only() -> None:
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        client.query("default", return_distinct_values=True, return_count_only=True)
    params = captured["query"]
    assert params["returnDistinctValues"] == "true"
    assert params["returnCountOnly"] == "true"


# ---------------------------------------------------------------------------
# Pagination: unbounded walk + truncation warning
# ---------------------------------------------------------------------------


def _paginating_client(page_count: int, *, always_exceeded: bool = False) -> HonuaClient:
    """A client whose FeatureServer returns ``page_count`` non-empty pages.

    Each page reports ``exceededTransferLimit=True`` until the last; with
    ``always_exceeded`` every page (including the last yielded) keeps the flag
    set so a bounded walk truncates mid-stream.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params.multi_items())
        offset = int(params.get("resultOffset", 0))
        record_count = int(params.get("resultRecordCount", 1000))
        index = offset // record_count
        last = index >= page_count - 1
        feature = {"attributes": {"objectid": offset + 1}}
        exceeded = True if always_exceeded else not last
        body = {"features": [feature], "exceededTransferLimit": exceeded}
        return httpx.Response(200, json=body)

    return HonuaClient("https://example.test", transport=httpx.MockTransport(handler))


def test_iter_query_unbounded_walks_past_default_cap() -> None:
    # 150 pages of one feature each — would silently stop at the old 100 cap.
    with _paginating_client(150) as client:
        features = list(client.iter_query("default", page_size=1, max_pages=None))
    assert len(features) == 150


def test_query_unbounded_collects_all_pages() -> None:
    with _paginating_client(120) as client:
        result = client.query("default", page_size=1, max_pages=None)
    assert len(result.features) == 120


def test_query_warns_when_bounded_walk_truncates() -> None:
    with _paginating_client(10, always_exceeded=True) as client:
        with pytest.warns(ResourceWarning, match="max_pages=3"):
            result = client.query("default", page_size=1, max_pages=3)
    assert len(result.features) == 3
    assert result.exceeded_transfer_limit is True


def test_query_does_not_warn_when_limit_set() -> None:
    import warnings

    with _paginating_client(10, always_exceeded=True) as client:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            result = client.query("default", page_size=1, max_pages=3, limit=2)
    assert len(result.features) == 2


# ---------------------------------------------------------------------------
# Source facade: spatial filter + aggregation routing
# ---------------------------------------------------------------------------


def _feature_server_descriptor() -> SourceDescriptor:
    return SourceDescriptor.from_dict(
        {
            "id": "default",
            "protocol": "geoservices-feature-service",
            "locator": {"service_id": "default", "layer_id": 0},
            "capabilities": ["query"],
        }
    )


def test_source_query_spatial_filter_routes_to_feature_server() -> None:
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        source = client.source(_feature_server_descriptor())
        source.query(spatial_filter={"geometry": {"x": 1, "y": 2}, "relationship": "contains"})
    assert captured["query"]["spatialRel"] == "esriSpatialRelContains"


def test_source_query_aggregation_routes_to_statistics() -> None:
    captured: dict[str, Any] = {}
    query = Query(
        aggregation={
            "out_statistics": [{"statistic_type": "max", "on_statistic_field": "elevation"}],
            "group_by": "zone",
            "return_distinct_values": True,
        }
    )
    with _capture_client(captured) as client:
        source = client.source(_feature_server_descriptor())
        source.query(query)
    params = captured["query"]
    assert json.loads(params["outStatistics"])[0]["statisticType"] == "max"
    assert params["groupByFieldsForStatistics"] == "zone"
    assert params["returnDistinctValues"] == "true"


def test_source_query_rejects_spatial_filter_on_non_feature_server() -> None:
    descriptor = SourceDescriptor.from_dict(
        {
            "id": "items",
            "protocol": "ogc-features",
            "locator": {"collection_id": "items"},
            "capabilities": ["query"],
        }
    )
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        source = client.source(descriptor)
        with pytest.raises(ValueError, match="only supported on the GeoServices FeatureServer"):
            source.query(spatial_filter={"geometry": {"x": 1, "y": 2}})


# ---------------------------------------------------------------------------
# gRPC binding
# ---------------------------------------------------------------------------


def test_grpc_factory_builds_client_from_base_config() -> None:
    grpc = pytest.importorskip("grpc")
    with HonuaClient(
        "https://example.test:8443",
        api_key="secret-key",
    ) as client:
        grpc_client = client.grpc(insecure=True)
        try:
            # Target derived from the REST authority (host:port).
            assert grpc_client._channel is not None
            # Auth carried as gRPC metadata derived from the SDK api_key.
            metadata = dict(grpc_client._metadata)
            assert any("secret-key" in str(value) for value in metadata.values())
        finally:
            grpc_client.close()
    assert grpc is not None


def test_grpc_factory_target_defaults_to_base_authority() -> None:
    pytest.importorskip("grpc")
    from honua_sdk.client import _grpc_target_from_base_url

    with HonuaClient("https://example.test:8443", api_key="k") as client:
        assert _grpc_target_from_base_url(client._base_url) == "example.test:8443"


@pytest.mark.anyio
async def test_async_grpc_factory_builds_async_client() -> None:
    pytest.importorskip("grpc")
    from honua_sdk import AsyncHonuaClient
    from honua_sdk.grpc import HonuaGrpcAsyncClient

    async with AsyncHonuaClient("https://example.test", api_key="k") as client:
        grpc_client = client.grpc(insecure=True)
        try:
            assert isinstance(grpc_client, HonuaGrpcAsyncClient)
        finally:
            await grpc_client.close()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_bbox_envelope_filter_still_works() -> None:
    """The bbox shorthand remains the envelope-intersects path (no regression)."""
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        client.query("default", bbox=(0, 0, 10, 10))
    params = captured["query"]
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert params["spatialRel"] == "esriSpatialRelIntersects"
    assert json.loads(params["geometry"])["xmin"] == 0


def test_spatial_filter_takes_precedence_over_bbox() -> None:
    captured: dict[str, Any] = {}
    with _capture_client(captured) as client:
        client.query(
            "default",
            bbox=(0, 0, 10, 10),
            spatial_filter={"geometry": {"x": 1, "y": 2}, "relationship": "within"},
        )
    params = captured["query"]
    assert params["geometryType"] == "esriGeometryPoint"
    assert params["spatialRel"] == "esriSpatialRelWithin"

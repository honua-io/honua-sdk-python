"""Coverage uplift tests for ``honua_sdk.geopandas``.

These tests target uncovered branches in geometry conversion, CRS
parsing, and ``_json_safe_value`` value coercion. The geopandas
optional extra is required.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

gpd = pytest.importorskip("geopandas")
pd = pytest.importorskip("pandas")
shapely = pytest.importorskip("shapely")

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from honua_sdk import geopandas as honua_gp
from honua_sdk.geopandas import (
    _crs_from_geojson,
    _crs_from_spatial_reference,
    _esri_geometry_to_shapely,
    _json_safe_value,
    _normalize_geojson_crs_identifier,
    _shapely_to_esri_geometry,
    features_to_geodataframe,
    geodataframe_to_features,
    ogc_features_to_geodataframe,
)


# ---------------------------------------------------------------------------
# CRS parsing edge cases
# ---------------------------------------------------------------------------


class TestCrsParsing:
    def test_spatial_reference_none_or_empty_returns_none(self) -> None:
        assert _crs_from_spatial_reference(None) is None
        assert _crs_from_spatial_reference({}) is None

    def test_spatial_reference_unknown_wkid_passes_through(self) -> None:
        # 32632 is not in _WKID_TO_EPSG so it should fall through to "EPSG:32632"
        assert _crs_from_spatial_reference({"wkid": 32632}) == "EPSG:32632"

    def test_spatial_reference_no_wkid_keys(self) -> None:
        assert _crs_from_spatial_reference({"name": "WGS84"}) is None

    def test_crs_from_geojson_string_value(self) -> None:
        assert (
            _crs_from_geojson(
                {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326", "features": []}
            )
            == "EPSG:4326"
        )

    def test_crs_from_geojson_coord_ref_sys_alias(self) -> None:
        assert (
            _crs_from_geojson({"coordRefSys": "EPSG:3857", "features": []})
            == "EPSG:3857"
        )

    def test_crs_from_geojson_object_with_top_level_name(self) -> None:
        # raw_crs has no properties dict but has a top-level name
        assert (
            _crs_from_geojson({"crs": {"name": "EPSG:3857"}, "features": []})
            == "EPSG:3857"
        )

    def test_crs_from_geojson_object_with_href(self) -> None:
        assert (
            _crs_from_geojson(
                {
                    "crs": {"properties": {"href": "https://example/EPSG/4326"}},
                    "features": [],
                }
            )
            == "EPSG:4326"
        )

    def test_crs_from_geojson_object_with_code_property(self) -> None:
        assert (
            _crs_from_geojson(
                {"crs": {"properties": {"code": "EPSG:3857"}}, "features": []}
            )
            == "EPSG:3857"
        )

    def test_crs_from_geojson_object_top_level_code(self) -> None:
        # properties is not a mapping; should fall through to top-level lookups
        assert (
            _crs_from_geojson({"crs": {"properties": None, "code": "EPSG:3857"}})
            == "EPSG:3857"
        )

    def test_crs_from_geojson_unhandled_mapping_returns_none(self) -> None:
        # Mapping with no recognized keys at all
        assert _crs_from_geojson({"crs": {"unrelated": 7}}) is None

    def test_crs_from_geojson_other_type(self) -> None:
        # raw_crs is neither str nor mapping -> returns None
        assert _crs_from_geojson({"crs": 12345}) is None

    def test_normalize_crs_identifier_empty(self) -> None:
        assert _normalize_geojson_crs_identifier("") is None
        assert _normalize_geojson_crs_identifier("   ") is None

    def test_normalize_crs_identifier_crs84_variants(self) -> None:
        assert _normalize_geojson_crs_identifier("CRS84") == "EPSG:4326"
        assert _normalize_geojson_crs_identifier("OGC:CRS84") == "EPSG:4326"
        assert (
            _normalize_geojson_crs_identifier(
                "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
            )
            == "EPSG:4326"
        )

    def test_normalize_crs_identifier_no_epsg_falls_back_to_raw(self) -> None:
        # No EPSG segment, no CRS84 - returns the original
        assert _normalize_geojson_crs_identifier("custom-crs") == "custom-crs"


# ---------------------------------------------------------------------------
# Esri JSON -> Shapely geometry conversions
# ---------------------------------------------------------------------------


class TestEsriToShapely:
    def test_none_geometry_returns_none(self) -> None:
        assert _esri_geometry_to_shapely(None) is None

    def test_point_with_null_coords(self) -> None:
        assert _esri_geometry_to_shapely({"x": None, "y": None}) is None
        assert _esri_geometry_to_shapely({"x": 1.0, "y": None}) is None

    def test_multipoint(self) -> None:
        geom = _esri_geometry_to_shapely({"points": [[0, 0], [1, 1]]})
        assert isinstance(geom, MultiPoint)
        assert len(list(geom.geoms)) == 2

    def test_empty_multipoint(self) -> None:
        assert _esri_geometry_to_shapely({"points": []}) is None

    def test_polyline_single_path_is_linestring(self) -> None:
        geom = _esri_geometry_to_shapely({"paths": [[[0, 0], [1, 1]]]})
        assert isinstance(geom, LineString)

    def test_polyline_multi_paths_is_multilinestring(self) -> None:
        geom = _esri_geometry_to_shapely(
            {"paths": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]]}
        )
        assert isinstance(geom, MultiLineString)

    def test_empty_polyline(self) -> None:
        assert _esri_geometry_to_shapely({"paths": []}) is None

    def test_polygon_with_hole(self) -> None:
        # Exterior CW (Esri convention), hole CCW
        exterior_cw = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]
        hole_ccw = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]
        geom = _esri_geometry_to_shapely({"rings": [exterior_cw, hole_ccw]})
        assert isinstance(geom, Polygon)
        # Polygon area = 100 - 4 = 96
        assert geom.area == pytest.approx(96.0)

    def test_polygon_with_multiple_exteriors_is_multipolygon(self) -> None:
        ext1 = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]
        ext2 = [[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]
        geom = _esri_geometry_to_shapely({"rings": [ext1, ext2]})
        assert isinstance(geom, MultiPolygon)

    def test_empty_polygon(self) -> None:
        assert _esri_geometry_to_shapely({"rings": []}) is None

    def test_unknown_geometry_returns_none(self) -> None:
        assert _esri_geometry_to_shapely({"foo": "bar"}) is None


# ---------------------------------------------------------------------------
# Shapely -> Esri JSON geometry conversions
# ---------------------------------------------------------------------------


class TestShapelyToEsri:
    def test_none_geometry_returns_none(self) -> None:
        assert _shapely_to_esri_geometry(None) is None

    def test_multipoint(self) -> None:
        result = _shapely_to_esri_geometry(MultiPoint([(0, 0), (1, 1)]))
        assert result == {"points": [[0.0, 0.0], [1.0, 1.0]]}

    def test_linestring(self) -> None:
        result = _shapely_to_esri_geometry(LineString([(0, 0), (1, 1)]))
        assert result == {"paths": [[[0.0, 0.0], [1.0, 1.0]]]}

    def test_multilinestring(self) -> None:
        result = _shapely_to_esri_geometry(
            MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]])
        )
        assert result == {
            "paths": [[[0.0, 0.0], [1.0, 1.0]], [[2.0, 2.0], [3.0, 3.0]]]
        }

    def test_polygon_with_hole(self) -> None:
        poly = Polygon(
            [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)],
            holes=[[(2, 2), (2, 4), (4, 4), (4, 2), (2, 2)]],
        )
        result = _shapely_to_esri_geometry(poly)
        assert result is not None
        assert len(result["rings"]) == 2

    def test_multipolygon_with_holes(self) -> None:
        p1 = Polygon(
            [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)],
            holes=[[(2, 2), (2, 4), (4, 4), (4, 2), (2, 2)]],
        )
        p2 = Polygon([(20, 20), (20, 30), (30, 30), (30, 20), (20, 20)])
        result = _shapely_to_esri_geometry(MultiPolygon([p1, p2]))
        assert result is not None
        assert len(result["rings"]) == 3

    def test_unsupported_geometry_type_raises(self) -> None:
        class _NotAGeometry:
            pass

        with pytest.raises(TypeError, match="Unsupported geometry type"):
            _shapely_to_esri_geometry(_NotAGeometry())


# ---------------------------------------------------------------------------
# _json_safe_value
# ---------------------------------------------------------------------------


class TestJsonSafeValue:
    def test_none(self) -> None:
        assert _json_safe_value(None) is None

    def test_dict_passthrough(self) -> None:
        assert _json_safe_value({"a": 1, "b": None}) == {"a": 1, "b": None}

    def test_list_and_tuple(self) -> None:
        assert _json_safe_value([1, 2]) == [1, 2]
        assert _json_safe_value((1, 2)) == [1, 2]

    def test_datetime_iso(self) -> None:
        value = dt.datetime(2026, 4, 27, 12, 0, 0)
        assert _json_safe_value(value) == "2026-04-27T12:00:00"

    def test_date_iso(self) -> None:
        assert _json_safe_value(dt.date(2026, 4, 27)) == "2026-04-27"

    def test_pandas_na(self) -> None:
        assert _json_safe_value(pd.NA) is None

    def test_numpy_scalar_item(self) -> None:
        import numpy as np

        value = np.int64(42)
        assert _json_safe_value(value) == 42

    def test_string_passthrough(self) -> None:
        assert _json_safe_value("hello") == "hello"


# ---------------------------------------------------------------------------
# Public roundtrip exercising MultiPolygon / unknown geometry combinations
# ---------------------------------------------------------------------------


class TestPublicSurfaceMultiGeom:
    def test_features_to_geodataframe_multipolygon_roundtrip(self) -> None:
        ext1 = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]
        ext2 = [[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]
        response: dict[str, Any] = {
            "spatialReference": {"wkid": 4326},
            "features": [
                {"attributes": {"id": 1}, "geometry": {"rings": [ext1, ext2]}},
            ],
        }
        gdf = features_to_geodataframe(response)
        features = geodataframe_to_features(gdf)
        assert "rings" in features[0]["geometry"]
        assert len(features[0]["geometry"]["rings"]) == 2

    def test_ogc_features_to_geodataframe_with_crs84_crs_property(self) -> None:
        response: dict[str, Any] = {
            "type": "FeatureCollection",
            "crs": "OGC:CRS84",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "x"},
                    "geometry": {"type": "Point", "coordinates": [1, 2]},
                },
            ],
        }
        gdf = ogc_features_to_geodataframe(response)
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 4326


# ---------------------------------------------------------------------------
# ImportError fallback path
# ---------------------------------------------------------------------------


def test_ensure_deps_raises_when_geopandas_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the import-error branch of ``_ensure_deps``."""

    monkeypatch.setattr(honua_gp, "_HAS_DEPS", False)
    with pytest.raises(ImportError, match="geopandas"):
        honua_gp._ensure_deps()

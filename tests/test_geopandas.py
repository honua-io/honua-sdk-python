"""Tests for honua_sdk.geopandas integration."""

from __future__ import annotations

import json

import pytest

gpd = pytest.importorskip("geopandas")
pd = pytest.importorskip("pandas")
shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString, MultiPoint, Point, Polygon

from honua_sdk.geopandas import (
    features_to_geodataframe,
    geodataframe_to_features,
)


# ---------------------------------------------------------------------------
# Fixtures: sample Esri JSON responses
# ---------------------------------------------------------------------------

POINT_RESPONSE: dict = {
    "spatialReference": {"wkid": 4326, "latestWkid": 4326},
    "features": [
        {
            "attributes": {"objectid": 1, "name": "Honolulu"},
            "geometry": {"x": -157.8583, "y": 21.3069},
        },
        {
            "attributes": {"objectid": 2, "name": "Hilo"},
            "geometry": {"x": -155.09, "y": 19.7297},
        },
    ],
}

POLYGON_RESPONSE: dict = {
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "features": [
        {
            "attributes": {"objectid": 10, "zone": "A"},
            "geometry": {
                "rings": [
                    [
                        [0.0, 0.0],
                        [10.0, 0.0],
                        [10.0, 10.0],
                        [0.0, 10.0],
                        [0.0, 0.0],
                    ]
                ]
            },
        },
    ],
}

POLYLINE_RESPONSE: dict = {
    "spatialReference": {"wkid": 4326},
    "features": [
        {
            "attributes": {"objectid": 20, "route": "R1"},
            "geometry": {
                "paths": [
                    [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]],
                ]
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# Point features
# ---------------------------------------------------------------------------


class TestPointFeatures:
    def test_point_features_to_geodataframe(self) -> None:
        gdf = features_to_geodataframe(POINT_RESPONSE)

        assert len(gdf) == 2
        assert list(gdf.columns) == ["objectid", "name", "geometry"]
        assert gdf.iloc[0]["name"] == "Honolulu"
        assert gdf.iloc[1]["name"] == "Hilo"

        pt = gdf.geometry.iloc[0]
        assert isinstance(pt, Point)
        assert pt.x == pytest.approx(-157.8583)
        assert pt.y == pytest.approx(21.3069)

    def test_point_crs_is_set(self) -> None:
        gdf = features_to_geodataframe(POINT_RESPONSE)
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 4326


# ---------------------------------------------------------------------------
# Polygon features
# ---------------------------------------------------------------------------


class TestPolygonFeatures:
    def test_polygon_features_to_geodataframe(self) -> None:
        gdf = features_to_geodataframe(POLYGON_RESPONSE)

        assert len(gdf) == 1
        assert gdf.iloc[0]["zone"] == "A"

        geom = gdf.geometry.iloc[0]
        assert isinstance(geom, Polygon)
        assert geom.area == pytest.approx(100.0)

    def test_polygon_crs_maps_102100_to_3857(self) -> None:
        gdf = features_to_geodataframe(POLYGON_RESPONSE)
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 3857


# ---------------------------------------------------------------------------
# Empty and null edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_features_list(self) -> None:
        response: dict = {
            "spatialReference": {"wkid": 4326},
            "features": [],
        }
        gdf = features_to_geodataframe(response)
        assert len(gdf) == 0
        assert isinstance(gdf, gpd.GeoDataFrame)

    def test_null_geometry_included_as_none(self) -> None:
        response: dict = {
            "spatialReference": {"wkid": 4326},
            "features": [
                {"attributes": {"objectid": 1, "name": "no-geom"}, "geometry": None},
                {"attributes": {"objectid": 2, "name": "has-geom"}, "geometry": {"x": 0.0, "y": 0.0}},
            ],
        }
        gdf = features_to_geodataframe(response)
        assert len(gdf) == 2
        assert gdf.geometry.iloc[0] is None
        assert isinstance(gdf.geometry.iloc[1], Point)

    def test_missing_spatial_reference(self) -> None:
        response: dict = {
            "features": [
                {"attributes": {"objectid": 1}, "geometry": {"x": 1.0, "y": 2.0}},
            ],
        }
        gdf = features_to_geodataframe(response)
        assert len(gdf) == 1
        assert gdf.crs is None

    def test_feature_missing_geometry_key(self) -> None:
        response: dict = {
            "features": [
                {"attributes": {"objectid": 5}},
            ],
        }
        gdf = features_to_geodataframe(response)
        assert len(gdf) == 1
        assert gdf.geometry.iloc[0] is None


# ---------------------------------------------------------------------------
# CRS detection
# ---------------------------------------------------------------------------


class TestCrsDetection:
    def test_latest_wkid_preferred(self) -> None:
        """latestWkid should be checked first (more current EPSG code)."""
        response: dict = {
            "spatialReference": {"wkid": 102100, "latestWkid": 3857},
            "features": [],
        }
        gdf = features_to_geodataframe(response)
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 3857

    def test_wkid_fallback(self) -> None:
        response: dict = {
            "spatialReference": {"wkid": 4326},
            "features": [],
        }
        gdf = features_to_geodataframe(response)
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 4326

    def test_arbitrary_wkid(self) -> None:
        response: dict = {
            "spatialReference": {"wkid": 32632},
            "features": [],
        }
        gdf = features_to_geodataframe(response)
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 32632


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_point_roundtrip(self) -> None:
        gdf = features_to_geodataframe(POINT_RESPONSE)
        features = geodataframe_to_features(gdf)

        assert len(features) == 2
        assert features[0]["attributes"]["name"] == "Honolulu"
        assert features[0]["geometry"]["x"] == pytest.approx(-157.8583)
        assert features[0]["geometry"]["y"] == pytest.approx(21.3069)

    def test_polygon_roundtrip(self) -> None:
        gdf = features_to_geodataframe(POLYGON_RESPONSE)
        features = geodataframe_to_features(gdf)

        assert len(features) == 1
        assert features[0]["attributes"]["zone"] == "A"
        assert "rings" in features[0]["geometry"]

        # Reconstruct and verify the round-tripped polygon has same area.
        response2 = {"features": features}
        gdf2 = features_to_geodataframe(response2)
        assert gdf2.geometry.iloc[0].area == pytest.approx(100.0)

    def test_polyline_roundtrip(self) -> None:
        gdf = features_to_geodataframe(POLYLINE_RESPONSE)
        features = geodataframe_to_features(gdf)

        assert len(features) == 1
        assert features[0]["attributes"]["route"] == "R1"
        assert "paths" in features[0]["geometry"]

    def test_null_geometry_roundtrip(self) -> None:
        response: dict = {
            "features": [
                {"attributes": {"objectid": 1}, "geometry": None},
            ],
        }
        gdf = features_to_geodataframe(response)
        features = geodataframe_to_features(gdf)

        assert len(features) == 1
        assert features[0]["attributes"]["objectid"] == 1
        assert "geometry" not in features[0]

    def test_geodataframe_to_features_returns_json_safe_attributes(self) -> None:
        frame = pd.DataFrame(
            {
                "count": pd.Series([1], dtype="Int64"),
                "missing": pd.Series([pd.NA], dtype="Int64"),
                "observed_at": [pd.Timestamp("2026-04-27T12:00:00Z")],
            }
        )
        gdf = gpd.GeoDataFrame(frame, geometry=[Point(0, 0)], crs="EPSG:4326")

        features = geodataframe_to_features(gdf)

        json.dumps(features)
        attrs = features[0]["attributes"]
        assert attrs["count"] == 1
        assert type(attrs["count"]) is int
        assert attrs["missing"] is None
        assert attrs["observed_at"] == "2026-04-27T12:00:00+00:00"

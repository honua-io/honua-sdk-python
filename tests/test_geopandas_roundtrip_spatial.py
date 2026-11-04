"""GeoPandas round-trip + spatial-workflow integration test.

Exercises a realistic analyst loop end to end:

1. Start from an Esri JSON feature-query response (as ``query_features`` returns).
2. Convert to a GeoDataFrame with ``features_to_geodataframe``.
3. Run a real spatial workflow: buffer the points and spatial-join them against
   zone polygons.
4. Convert the derived layer back to Esri JSON features with
   ``geodataframe_to_features`` (the ``apply_edits`` payload shape).
5. Re-ingest the payload and assert geometric + attribute integrity survived the
   full round trip.

Skips cleanly when the optional ``geopandas``/``shapely`` extras are absent so
collection never fails on the core lane.
"""

from __future__ import annotations

import math

import pytest

gpd = pytest.importorskip("geopandas")
pytest.importorskip("shapely")

from shapely.geometry import shape as _shapely_shape

from honua_sdk.geopandas import (
    features_to_geodataframe,
    geodataframe_to_features,
)

# A small projected (EPSG:3857-style, metres) point layer so buffer distances are
# meaningful and areas are exact. Two stations sit inside zone A, one inside zone B.
STATIONS_RESPONSE: dict = {
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "features": [
        {"attributes": {"objectid": 1, "name": "alpha"}, "geometry": {"x": 10.0, "y": 10.0}},
        {"attributes": {"objectid": 2, "name": "bravo"}, "geometry": {"x": 30.0, "y": 30.0}},
        {"attributes": {"objectid": 3, "name": "charlie"}, "geometry": {"x": 130.0, "y": 130.0}},
    ],
}

ZONES_RESPONSE: dict = {
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "features": [
        {
            "attributes": {"zone_id": "A"},
            "geometry": {"rings": [[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]]},
        },
        {
            "attributes": {"zone_id": "B"},
            "geometry": {
                "rings": [[[100.0, 100.0], [200.0, 100.0], [200.0, 200.0], [100.0, 200.0], [100.0, 100.0]]]
            },
        },
    ],
}

BUFFER_RADIUS = 5.0


def test_buffer_and_spatial_join_roundtrip_preserves_integrity() -> None:
    stations = features_to_geodataframe(STATIONS_RESPONSE)
    zones = features_to_geodataframe(ZONES_RESPONSE)

    assert len(stations) == 3
    # CRS survived the Esri JSON -> GeoDataFrame conversion.
    assert stations.crs is not None
    assert stations.crs.to_epsg() == 3857

    # --- Spatial op 1: buffer the point stations into circular footprints. ---
    buffered = stations.copy()
    buffered["geometry"] = stations.geometry.buffer(BUFFER_RADIUS)
    assert (buffered.geometry.geom_type == "Polygon").all()
    # Buffered area is ~ pi * r^2; default 8-segment quadrant buffer slightly
    # under-estimates the true circle, so use a tolerant relative check.
    assert buffered.geometry.area.iloc[0] == pytest.approx(math.pi * BUFFER_RADIUS**2, rel=0.05)

    # --- Spatial op 2: spatial-join buffered footprints onto zone polygons. ---
    joined = gpd.sjoin(buffered, zones, how="left", predicate="intersects")
    by_name = {row["name"]: row["zone_id"] for _, row in joined.iterrows()}
    assert by_name == {"alpha": "A", "bravo": "A", "charlie": "B"}

    # --- Round trip: derived layer -> Esri JSON -> GeoDataFrame again. ---
    # Drop the join bookkeeping column so the payload mirrors a real write set.
    out = joined.drop(columns=[c for c in joined.columns if c.startswith("index_")])
    features = geodataframe_to_features(out)

    assert len(features) == 3
    # Attributes round-tripped as JSON-safe values, including the joined zone.
    first = next(f for f in features if f["attributes"]["name"] == "alpha")
    assert first["attributes"]["zone_id"] == "A"
    assert first["attributes"]["objectid"] == 1
    assert "rings" in first["geometry"]

    # Re-ingest and confirm geometry integrity (area preserved within float tol).
    reloaded = features_to_geodataframe({"features": features})
    assert len(reloaded) == 3

    original_areas = sorted(out.geometry.area.tolist())
    reloaded_areas = sorted(reloaded.geometry.area.tolist())
    for original, restored in zip(original_areas, reloaded_areas, strict=True):
        assert restored == pytest.approx(original)

    # Geometry shape identity also survives: the alpha footprint contains its seed point.
    alpha_geom = _shapely_shape(
        {
            "type": "Polygon",
            "coordinates": [[(pt[0], pt[1]) for pt in first["geometry"]["rings"][0]]],
        }
    )
    assert alpha_geom.contains(_shapely_shape({"type": "Point", "coordinates": (10.0, 10.0)}))


def test_roundtrip_preserves_attribute_columns_without_geometry_loss() -> None:
    stations = features_to_geodataframe(STATIONS_RESPONSE)

    features = geodataframe_to_features(stations)
    reloaded = features_to_geodataframe({"features": features})

    assert sorted(reloaded.columns) == sorted(stations.columns)
    assert reloaded["name"].tolist() == stations["name"].tolist()
    assert reloaded["objectid"].tolist() == stations["objectid"].tolist()
    # Point coordinates are exactly preserved through the round trip.
    assert reloaded.geometry.x.tolist() == stations.geometry.x.tolist()
    assert reloaded.geometry.y.tolist() == stations.geometry.y.tolist()

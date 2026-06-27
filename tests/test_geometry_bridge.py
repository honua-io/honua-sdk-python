"""Tests for the first-class geometry bridge on the typed feature models.

Covers ``Feature``/``QueryFeature`` ``__geo_interface__`` (pure-dict, no
third-party dependency) and ``to_shapely()`` / ``geometry_shape`` (optional
shapely dep, gated with ``importorskip``) for the Esri-JSON (FeatureServer) and
GeoJSON (OGC/STAC) encodings — point/line/polygon, Z/M, and ring orientation.
"""

from __future__ import annotations

import pytest

from honua_sdk import Feature, QueryFeature
from honua_sdk.models._geometry import geometry_to_geo_interface

# ---------------------------------------------------------------------------
# Pure ``__geo_interface__`` path (no shapely required)
# ---------------------------------------------------------------------------


def test_esri_point_geo_interface() -> None:
    feature = Feature(attributes={"objectid": 1}, geometry={"x": -157.8, "y": 21.3})
    assert feature.__geo_interface__ == {"type": "Point", "coordinates": [-157.8, 21.3]}


def test_esri_point_with_z_keeps_z() -> None:
    geom = {"hasZ": True, "x": 1.0, "y": 2.0, "z": 3.0}
    assert geometry_to_geo_interface(geom) == {"type": "Point", "coordinates": [1.0, 2.0, 3.0]}


def test_esri_point_m_only_dropped() -> None:
    """An M ordinate (no Z) must be dropped — GeoJSON has no M dimension."""
    geom = {"hasM": True, "x": 1.0, "y": 2.0, "m": 99.0}
    assert geometry_to_geo_interface(geom) == {"type": "Point", "coordinates": [1.0, 2.0]}


def test_esri_polyline_single_path_is_linestring() -> None:
    geom = {"paths": [[[0.0, 0.0], [1.0, 1.0]]]}
    assert geometry_to_geo_interface(geom) == {
        "type": "LineString",
        "coordinates": [[0.0, 0.0], [1.0, 1.0]],
    }


def test_esri_polyline_multi_path_is_multilinestring() -> None:
    geom = {"paths": [[[0.0, 0.0], [1.0, 1.0]], [[5.0, 5.0], [6.0, 6.0]]]}
    out = geometry_to_geo_interface(geom)
    assert out is not None
    assert out["type"] == "MultiLineString"
    assert len(out["coordinates"]) == 2


def test_esri_polyline_with_z() -> None:
    geom = {"hasZ": True, "paths": [[[0.0, 0.0, 5.0], [1.0, 1.0, 6.0]]]}
    assert geometry_to_geo_interface(geom) == {
        "type": "LineString",
        "coordinates": [[0.0, 0.0, 5.0], [1.0, 1.0, 6.0]],
    }


def test_esri_polygon_with_hole_orientation() -> None:
    """Esri exterior ring (CW) + hole (CCW) -> Polygon with one interior ring."""
    geom = {
        "rings": [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],  # CW exterior
            [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]],  # CCW hole
        ]
    }
    out = geometry_to_geo_interface(geom)
    assert out is not None
    assert out["type"] == "Polygon"
    assert len(out["coordinates"]) == 2  # exterior + 1 hole


def test_esri_multipolygon_two_exteriors() -> None:
    geom = {
        "rings": [
            [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]],
            [[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]],
        ]
    }
    out = geometry_to_geo_interface(geom)
    assert out is not None
    assert out["type"] == "MultiPolygon"
    assert len(out["coordinates"]) == 2


def test_esri_multipoint() -> None:
    geom = {"points": [[0.0, 0.0], [1.0, 1.0]]}
    assert geometry_to_geo_interface(geom) == {
        "type": "MultiPoint",
        "coordinates": [[0.0, 0.0], [1.0, 1.0]],
    }


def test_geojson_geometry_passthrough() -> None:
    geom = {"type": "Point", "coordinates": [1.0, 2.0]}
    feature = QueryFeature(id=1, properties={}, geometry=geom)
    assert feature.__geo_interface__ == geom


def test_geojson_geometry_collection() -> None:
    geom = {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "Point", "coordinates": [0.0, 0.0]},
            {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
        ],
    }
    out = geometry_to_geo_interface(geom)
    assert out is not None
    assert out["type"] == "GeometryCollection"
    assert len(out["geometries"]) == 2


def test_empty_esri_collections_yield_none() -> None:
    assert geometry_to_geo_interface({"rings": []}) is None
    assert geometry_to_geo_interface({"paths": []}) is None
    assert geometry_to_geo_interface({"points": []}) is None
    assert geometry_to_geo_interface({"x": None, "y": None}) is None


def test_none_geometry_yields_none() -> None:
    assert Feature(attributes={}).__geo_interface__ is None
    assert QueryFeature(id=1, properties={}).__geo_interface__ is None
    assert geometry_to_geo_interface({}) is None


# ---------------------------------------------------------------------------
# shapely-backed path (optional dependency)
# ---------------------------------------------------------------------------


def test_to_shapely_point() -> None:
    pytest.importorskip("shapely")
    feature = Feature(attributes={}, geometry={"x": 10.0, "y": 20.0})
    shape = feature.to_shapely()
    assert shape is not None
    assert shape.geom_type == "Point"
    assert (shape.x, shape.y) == (10.0, 20.0)


def test_to_shapely_polygon_with_hole_area() -> None:
    pytest.importorskip("shapely")
    geom = {
        "rings": [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
            [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]],
        ]
    }
    shape = QueryFeature(id=1, properties={}, geometry=geom).to_shapely()
    assert shape is not None
    assert shape.geom_type == "Polygon"
    assert shape.area == pytest.approx(100.0 - 4.0)  # 10x10 minus 2x2 hole
    assert len(shape.interiors) == 1


def test_to_shapely_z_is_preserved() -> None:
    pytest.importorskip("shapely")
    geom = {"hasZ": True, "x": 1.0, "y": 2.0, "z": 3.0}
    shape = Feature(attributes={}, geometry=geom).to_shapely()
    assert shape is not None
    assert shape.has_z
    assert next(iter(shape.coords)) == (1.0, 2.0, 3.0)


def test_to_shapely_multipoint_and_multilinestring() -> None:
    pytest.importorskip("shapely")
    mp = Feature(attributes={}, geometry={"points": [[0.0, 0.0], [1.0, 1.0]]}).to_shapely()
    assert mp is not None
    assert mp.geom_type == "MultiPoint"

    mls = Feature(
        attributes={},
        geometry={"paths": [[[0.0, 0.0], [1.0, 1.0]], [[5.0, 5.0], [6.0, 6.0]]]},
    ).to_shapely()
    assert mls is not None
    assert mls.geom_type == "MultiLineString"


def test_to_shapely_geojson_linestring() -> None:
    pytest.importorskip("shapely")
    geom = {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]]}
    shape = QueryFeature(id=1, properties={}, geometry=geom).to_shapely()
    assert shape is not None
    assert shape.geom_type == "LineString"
    assert shape.length == pytest.approx(2 * (2 ** 0.5))


def test_geometry_shape_is_cached() -> None:
    pytest.importorskip("shapely")
    feature = Feature(attributes={}, geometry={"x": 1.0, "y": 2.0})
    first = feature.geometry_shape
    second = feature.geometry_shape
    assert first is second  # cached identity


def test_to_shapely_none_geometry() -> None:
    pytest.importorskip("shapely")
    assert Feature(attributes={}).to_shapely() is None
    assert Feature(attributes={}).geometry_shape is None


def test_to_shapely_raises_clear_error_without_shapely(monkeypatch: pytest.MonkeyPatch) -> None:
    """When shapely is absent, ``to_shapely`` raises a clear, install-hinting error."""
    import builtins

    from honua_sdk.models import _geometry

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "shapely" or name.startswith("shapely."):
            raise ImportError("No module named 'shapely'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    feature = Feature(attributes={}, geometry={"x": 1.0, "y": 2.0})
    with pytest.raises(ImportError, match=r"pip install honua-sdk\[geopandas\]"):
        feature.to_shapely()
    # The pure-dict path must keep working without shapely.
    assert _geometry.geometry_to_geo_interface({"x": 1.0, "y": 2.0}) == {
        "type": "Point",
        "coordinates": [1.0, 2.0],
    }


def test_feature_plugs_into_shapely_shape() -> None:
    """The model satisfies the ``__geo_interface__`` protocol end-to-end."""
    pytest.importorskip("shapely")
    from shapely.geometry import shape as shapely_shape

    feature = QueryFeature(id=1, properties={}, geometry={"x": 3.0, "y": 4.0})
    geom = shapely_shape(feature)
    assert geom.geom_type == "Point"
    assert (geom.x, geom.y) == (3.0, 4.0)

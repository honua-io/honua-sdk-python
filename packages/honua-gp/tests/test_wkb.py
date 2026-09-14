"""GeoJSON -> WKB encoding for the ``geometry.*`` processes (#226).

Expected bytes are written out by hand from the OGC Simple Features WKB layout
(byte order, uint32 type, counts, float64 ordinates), not produced by the
encoder.
"""

from __future__ import annotations

import pytest

from honua_gp._wkb import WkbEncodingError, geojson_to_base64_wkb, geojson_to_wkb, position_count

ZERO = "0000000000000000"
ONE = "000000000000f03f"
TWO = "0000000000000040"
THREE = "0000000000000840"


@pytest.mark.parametrize(
    ("geometry", "expected_hex"),
    [
        pytest.param({"type": "Point", "coordinates": [1, 2]}, "01" "01000000" + ONE + TWO, id="point"),
        pytest.param({"type": "Point", "coordinates": [1, 2, 3]}, "01" "e9030000" + ONE + TWO + THREE, id="point-z"),
        pytest.param(
            {"type": "LineString", "coordinates": [[0, 0], [1, 2]]},
            "01" "02000000" "02000000" + ZERO + ZERO + ONE + TWO,
            id="linestring",
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "01" "03000000" "01000000" "04000000" + ZERO + ZERO + ONE + ZERO + ONE + ONE + ZERO + ZERO,
            id="polygon",
        ),
        pytest.param(
            {"type": "MultiPoint", "coordinates": [[1, 2], [0, 0]]},
            "01" "04000000" "02000000" + "01" "01000000" + ONE + TWO + "01" "01000000" + ZERO + ZERO,
            id="multipoint",
        ),
        pytest.param(
            {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]},
            "01" "06000000" "01000000"
            + "01" "03000000" "01000000" "04000000" + ZERO + ZERO + ONE + ZERO + ONE + ONE + ZERO + ZERO,
            id="multipolygon",
        ),
        pytest.param(
            {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [1, 2]}]},
            "01" "07000000" "01000000" + "01" "01000000" + ONE + TWO,
            id="collection",
        ),
    ],
)
def test_geojson_encodes_to_iso_wkb(geometry: dict, expected_hex: str) -> None:
    assert geojson_to_wkb(geometry).hex() == expected_hex


def test_base64_form() -> None:
    assert geojson_to_base64_wkb({"type": "Point", "coordinates": [1, 2]}) == "AQEAAAAAAAAAAADwPwAAAAAAAABA"


@pytest.mark.parametrize(
    "geometry",
    [
        pytest.param(None, id="null"),
        pytest.param({"type": "Circle", "coordinates": [0, 0]}, id="unknown-type"),
        pytest.param({"type": "Point", "coordinates": [1, "2"]}, id="string-ordinate"),
        pytest.param({"type": "Point", "coordinates": [1, float("nan")]}, id="nan"),
        pytest.param({"type": "Point", "coordinates": [True, 2]}, id="bool-ordinate"),
        pytest.param({"type": "LineString", "coordinates": [[0, 0], [1, 1, 1]]}, id="mixed-dimensions"),
        pytest.param({"type": "Point", "coordinates": [1, 2, 3, 4]}, id="measure"),
        pytest.param({"type": "Polygon", "coordinates": "ring"}, id="malformed"),
        pytest.param({"type": "GeometryCollection"}, id="no-geometries"),
    ],
)
def test_unencodable_geometry_raises(geometry: object) -> None:
    with pytest.raises(WkbEncodingError):
        geojson_to_wkb(geometry)


def test_position_count() -> None:
    assert position_count({"type": "Polygon", "coordinates": []}) == 0
    assert position_count({"type": "MultiPoint", "coordinates": [[0, 0], [1, 1]]}) == 2

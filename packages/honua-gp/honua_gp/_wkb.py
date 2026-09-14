"""Encode GeoJSON geometries as ISO WKB for honua-server's ``geometry.*`` processes.

The ``geometry.*`` processes take base64-encoded WKB (``wkb`` / ``wkbs``) plus a
separate ``srid``, so the WKB carries no embedded SRID. Coordinates are written
little-endian as given; 3D positions use the ISO ``+1000`` Z type codes.
Measures (4D positions) are not supported.
"""

from __future__ import annotations

import base64
import math
import struct
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

_TYPE_CODES = {
    "Point": 1,
    "LineString": 2,
    "Polygon": 3,
    "MultiPoint": 4,
    "MultiLineString": 5,
    "MultiPolygon": 6,
    "GeometryCollection": 7,
}
# Nesting depth of a position inside ``coordinates`` for each type.
_POSITION_DEPTH = {
    "Point": 0,
    "LineString": 1,
    "MultiPoint": 1,
    "Polygon": 2,
    "MultiLineString": 2,
    "MultiPolygon": 3,
}
_Z_OFFSET = 1000


class WkbEncodingError(ValueError):
    """The GeoJSON geometry cannot be encoded as WKB."""


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _kind(geometry: Any) -> str:
    if not isinstance(geometry, Mapping):
        raise WkbEncodingError("geometry is not a GeoJSON object")
    kind = geometry.get("type")
    if kind not in _TYPE_CODES:
        raise WkbEncodingError(f"unsupported GeoJSON geometry type {kind!r}")
    return str(kind)


def _members(geometry: Mapping[str, Any]) -> list[Any]:
    members = geometry.get("geometries")
    if not _is_sequence(members):
        raise WkbEncodingError("GeometryCollection has no geometries array")
    return list(members)


def _positions(geometry: Any) -> Iterator[Sequence[Any]]:
    kind = _kind(geometry)
    if kind == "GeometryCollection":
        for member in _members(geometry):
            yield from _positions(member)
        return

    def walk(value: Any, depth: int) -> Iterator[Sequence[Any]]:
        if not _is_sequence(value):
            raise WkbEncodingError(f"{kind} coordinates are malformed")
        if depth == 0:
            yield value
            return
        for item in value:
            yield from walk(item, depth - 1)

    yield from walk(geometry.get("coordinates"), _POSITION_DEPTH[kind])


def position_count(geometry: Any) -> int:
    """Number of positions in ``geometry``; ``0`` for an empty geometry."""

    return sum(1 for _ in _positions(geometry))


def _dimension(geometry: Any) -> int:
    dimensions = {len(position) for position in _positions(geometry)}
    if not dimensions:
        return 2
    if len(dimensions) != 1 or not dimensions <= {2, 3}:
        raise WkbEncodingError("positions must all be 2D or all be 3D")
    return dimensions.pop()


def _position(value: Sequence[Any], dimension: int) -> bytes:
    if len(value) != dimension or not all(
        isinstance(ordinate, (int, float)) and not isinstance(ordinate, bool) and math.isfinite(ordinate)
        for ordinate in value
    ):
        raise WkbEncodingError(f"position {list(value)!r} is not a finite {dimension}D coordinate")
    return struct.pack(f"<{dimension}d", *(float(ordinate) for ordinate in value))


def _count(items: Sequence[Any]) -> bytes:
    return struct.pack("<I", len(items))


def _encode(geometry: Any, dimension: int) -> bytes:
    kind = _kind(geometry)
    code = _TYPE_CODES[kind] + (_Z_OFFSET if dimension == 3 else 0)
    head = struct.pack("<BI", 1, code)
    if kind == "GeometryCollection":
        members = _members(geometry)
        return head + _count(members) + b"".join(_encode(member, dimension) for member in members)

    coordinates = geometry.get("coordinates")
    if kind == "Point":
        return head + _position(coordinates, dimension)
    if kind == "LineString":
        return head + _count(coordinates) + b"".join(_position(point, dimension) for point in coordinates)
    if kind == "Polygon":
        return head + _count(coordinates) + b"".join(
            _count(ring) + b"".join(_position(point, dimension) for point in ring) for ring in coordinates
        )
    member_kind = kind.removeprefix("Multi")
    return head + _count(coordinates) + b"".join(
        _encode({"type": member_kind, "coordinates": member}, dimension) for member in coordinates
    )


def geojson_to_wkb(geometry: Any) -> bytes:
    """Encode a GeoJSON geometry object as little-endian ISO WKB."""

    return _encode(geometry, _dimension(geometry))


def geojson_to_base64_wkb(geometry: Any) -> str:
    return base64.b64encode(geojson_to_wkb(geometry)).decode("ascii")


__all__ = ["WkbEncodingError", "geojson_to_base64_wkb", "geojson_to_wkb", "position_count"]

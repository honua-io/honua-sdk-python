"""Shared data models for the sync/async GeocodeServer clients.

These types are defined once here and imported by both the asynchronous
source-of-truth (:mod:`honua_sdk.async_geocoding`) and its generated
synchronous mirror (:mod:`honua_sdk.geocoding`), so the codegen transform in
``scripts/gen_sync.py`` only has to mirror the client class — the models do
not differ between the two transports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass
class GeocodeResult:
    address: str
    latitude: float
    longitude: float
    score: float
    attributes: dict[str, str | None]


@dataclass
class ReverseGeocodeResult:
    address: str
    latitude: float
    longitude: float
    attributes: dict[str, str | None]


@dataclass
class GeocodeSuggestion:
    text: str
    magic_key: str
    is_collection: bool


def _extract_location_xy(location: Any) -> tuple[float, float] | None:
    """Return ``(longitude, latitude)`` from a GeocodeServer ``location``.

    Returns ``None`` when the location is missing, not a mapping, or lacks a
    usable ``x``/``y`` pair. Defaulting absent coordinates to ``0`` would
    silently emit a valid-looking ``(0, 0)`` "null island" result that masks
    a geocode miss — so a missing location is treated as "no result" instead.
    """
    if not isinstance(location, Mapping):
        return None
    raw_x = location.get("x")
    raw_y = location.get("y")
    if raw_x is None or raw_y is None:
        return None
    try:
        return float(raw_x), float(raw_y)
    except (TypeError, ValueError):
        return None

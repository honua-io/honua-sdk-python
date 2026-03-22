"""Honua Python SDK scaffold."""

from __future__ import annotations

try:
    from importlib.metadata import version as _meta_version

    __version__: str = _meta_version("honua-sdk")
except Exception:  # pragma: no cover — editable / not-installed fallback
    __version__ = "0.0.0.dev0"

from .admin import HonuaAdminClient
from .client import HonuaClient
from .errors import HonuaError, HonuaGrpcError, HonuaHttpError
from .geocoding import (
    GeocodeResult,
    GeocodeSuggestion,
    HonuaGeocodingClient,
    ReverseGeocodeResult,
)

__all__ = [
    "__version__",
    "GeocodeResult",
    "GeocodeSuggestion",
    "HonuaAdminClient",
    "HonuaClient",
    "HonuaError",
    "HonuaGrpcError",
    "HonuaHttpError",
    "HonuaGeocodingClient",
    "ReverseGeocodeResult",
]

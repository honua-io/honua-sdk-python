"""Honua Python SDK -- data-plane and protocol clients.

Optional GeoPandas integration is available via ``honua_sdk.geopandas``::

    from honua_sdk.geopandas import features_to_geodataframe, geodataframe_to_features

Install with:  ``pip install honua-sdk[geopandas]``
"""

from __future__ import annotations

try:
    from importlib.metadata import version as _meta_version

    __version__: str = _meta_version("honua-sdk")
except Exception:  # pragma: no cover -- editable / not-installed fallback
    __version__ = "0.0.0.dev0"

from .async_client import AsyncHonuaClient
from .async_geocoding import AsyncHonuaGeocodingClient
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
    "AsyncHonuaClient",
    "AsyncHonuaGeocodingClient",
    "GeocodeResult",
    "GeocodeSuggestion",
    "HonuaClient",
    "HonuaError",
    "HonuaGrpcError",
    "HonuaHttpError",
    "HonuaGeocodingClient",
    "ReverseGeocodeResult",
]

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

from .auth import (
    AuthProvider,
    BearerToken,
    CallableAuthProvider,
    InMemoryTokenStore,
    RefreshableBearerTokenProvider,
    StaticAuthProvider,
    TokenStore,
)
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
from .models import ApplyEditsResult, DataPlaneCapabilities, EditOperationResult, Feature, FeatureSet, ServiceSummary
from .ogc import (
    AsyncHonuaOgcFeatureCollection,
    AsyncHonuaOgcFeatures,
    HonuaOgcFeatureCollection,
    HonuaOgcFeatures,
)
from .protocols import (
    AsyncGeoServicesFeatureServerClient,
    AsyncGeoServicesGeometryServerClient,
    AsyncGeoServicesImageServerClient,
    AsyncGeoServicesMapServerClient,
    AsyncODataClient,
    AsyncOgcCoveragesClient,
    AsyncOgcMapsClient,
    AsyncOgcProcessesClient,
    AsyncOgcTilesClient,
    AsyncStacClient,
    AsyncWfsClient,
    AsyncWmsClient,
    AsyncWmtsClient,
    GeoServicesFeatureServerClient,
    GeoServicesGeometryServerClient,
    GeoServicesImageServerClient,
    GeoServicesMapServerClient,
    ODataClient,
    OgcCoveragesClient,
    OgcMapsClient,
    OgcProcessesClient,
    OgcTilesClient,
    StacClient,
    WfsClient,
    WmsClient,
    WmtsClient,
)

__all__ = [
    "__version__",
    "AuthProvider",
    "AsyncHonuaClient",
    "AsyncHonuaGeocodingClient",
    "AsyncGeoServicesFeatureServerClient",
    "AsyncGeoServicesGeometryServerClient",
    "AsyncGeoServicesImageServerClient",
    "AsyncGeoServicesMapServerClient",
    "AsyncHonuaOgcFeatureCollection",
    "AsyncHonuaOgcFeatures",
    "AsyncODataClient",
    "AsyncOgcCoveragesClient",
    "AsyncOgcMapsClient",
    "AsyncOgcProcessesClient",
    "AsyncOgcTilesClient",
    "AsyncStacClient",
    "AsyncWfsClient",
    "AsyncWmsClient",
    "AsyncWmtsClient",
    "ApplyEditsResult",
    "BearerToken",
    "CallableAuthProvider",
    "DataPlaneCapabilities",
    "EditOperationResult",
    "Feature",
    "FeatureSet",
    "GeocodeResult",
    "GeocodeSuggestion",
    "GeoServicesFeatureServerClient",
    "GeoServicesGeometryServerClient",
    "GeoServicesImageServerClient",
    "GeoServicesMapServerClient",
    "HonuaClient",
    "HonuaError",
    "HonuaGrpcError",
    "HonuaHttpError",
    "HonuaGeocodingClient",
    "HonuaOgcFeatureCollection",
    "HonuaOgcFeatures",
    "InMemoryTokenStore",
    "ODataClient",
    "OgcCoveragesClient",
    "OgcMapsClient",
    "OgcProcessesClient",
    "OgcTilesClient",
    "RefreshableBearerTokenProvider",
    "ReverseGeocodeResult",
    "ServiceSummary",
    "StacClient",
    "StaticAuthProvider",
    "TokenStore",
    "WfsClient",
    "WmsClient",
    "WmtsClient",
]

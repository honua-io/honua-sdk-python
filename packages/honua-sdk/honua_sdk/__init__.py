"""Honua Python SDK -- data-plane and protocol clients.

The top-level namespace exposes the *task-oriented* public surface: the
sync/async :class:`HonuaClient` and :class:`AsyncHonuaClient`, the geocoding
clients, typed models (:class:`Query`, :class:`Result`,
:class:`SourceDescriptor`, etc.), the :class:`Source` / :class:`AsyncSource`
facade, the auth helpers, and the error hierarchy.

Per-protocol HTTP handler classes (``GeoServicesFeatureServerClient``,
``StacClient``, ``WfsClient``, ``HonuaOgcFeatures``, the ``Async*`` variants,
helper dataclasses like ``BinaryResponse`` / ``ODataQuery``, and the
``BboxValue`` / ``CsvValue`` / ``JsonObject`` type aliases) live under the
``honua_sdk.protocols`` and ``honua_sdk.ogc`` submodules to keep the
top-level namespace focused::

    from honua_sdk.protocols import BinaryResponse, ODataQuery, WfsClient
    from honua_sdk.ogc import HonuaOgcFeatures

Optional GeoPandas integration is available via ``honua_sdk.geopandas``::

    from honua_sdk.geopandas import features_to_geodataframe, geodataframe_to_features

Install with:  ``pip install honua-sdk[geopandas]``

Optional raster interop (for server geoprocessing output) is available via
``honua_sdk.raster``::

    from honua_sdk.raster import geotiff_to_xarray, open_geotiff

Install with:  ``pip install honua-sdk[raster]``
"""

from __future__ import annotations

try:
    from importlib.metadata import version as _meta_version

    __version__: str = _meta_version("honua-sdk")
except Exception:  # pragma: no cover -- editable / not-installed fallback
    __version__ = "0.0.0.dev0"

from ._geocoding_models import (
    GeocodeResult,
    GeocodeSuggestion,
    ReverseGeocodeResult,
)
from .async_client import AsyncHonuaClient
from .async_geocoding import AsyncHonuaGeocodingClient
from .auth import (
    AsyncAuthProvider,
    AsyncRefreshableBearerTokenProvider,
    AuthProvider,
    BearerToken,
    CallableAuthProvider,
    InMemoryTokenStore,
    RefreshableBearerTokenProvider,
    StaticAuthProvider,
    TokenStore,
)
from .client import HonuaClient
from .errors import (
    HonuaAuthError,
    HonuaCapabilityNotSupportedError,
    HonuaError,
    HonuaGrpcError,
    HonuaHttpError,
    HonuaRateLimitError,
    HonuaTimeoutError,
    HonuaTransportError,
)
from .geocoding import HonuaGeocodingClient
from .models import (
    CAPABILITIES,
    DEFAULT_CAPABILITIES,
    PROTOCOL_ALIASES,
    PROTOCOLS,
    ApplyEditsResult,
    Capability,
    DataPlaneCapabilities,
    DegradedReason,
    EditOperationResult,
    Extent,
    Feature,
    FeatureQuery,
    FeatureQueryResult,
    FeatureSet,
    Field,
    LayerSchema,
    Pagination,
    Protocol,
    Query,
    QueryFeature,
    QueryProtocol,
    Result,
    ServiceSummary,
    SourceDescriptor,
    SourceLocator,
    capability_set,
    default_capabilities,
    normalize_capability,
    normalize_protocol,
)
from .source import AsyncSource, Source

# Per-protocol handler classes (sync + async), helper dataclasses, and type
# aliases intentionally do NOT appear in ``__all__``. Import them from
# ``honua_sdk.protocols`` or ``honua_sdk.ogc`` instead.

__all__ = [  # noqa: RUF022 -- grouped by category for human discoverability
    "__version__",
    # Clients (sync + async, data-plane + geocoding)
    "HonuaClient",
    "AsyncHonuaClient",
    "HonuaGeocodingClient",
    "AsyncHonuaGeocodingClient",
    # Source / Query facade
    "Source",
    "AsyncSource",
    "SourceDescriptor",
    "SourceLocator",
    "Query",
    "Pagination",
    "Result",
    "QueryFeature",
    "DegradedReason",
    "FeatureQuery",
    "FeatureQueryResult",
    # Typed layer schema (arcpy.Describe / ListFields equivalent)
    "LayerSchema",
    "Field",
    "Extent",
    # Legacy / protocol-shaped models still surfaced at the top level
    "Feature",
    "FeatureSet",
    "ApplyEditsResult",
    "EditOperationResult",
    "DataPlaneCapabilities",
    "ServiceSummary",
    # Geocoding result models
    "GeocodeResult",
    "GeocodeSuggestion",
    "ReverseGeocodeResult",
    # Protocol / capability registry + normalization helpers
    "Protocol",
    "QueryProtocol",
    "Capability",
    "PROTOCOLS",
    "PROTOCOL_ALIASES",
    "CAPABILITIES",
    "DEFAULT_CAPABILITIES",
    "normalize_protocol",
    "normalize_capability",
    "capability_set",
    "default_capabilities",
    # Auth
    "AuthProvider",
    "AsyncAuthProvider",
    "AsyncRefreshableBearerTokenProvider",
    "BearerToken",
    "CallableAuthProvider",
    "InMemoryTokenStore",
    "RefreshableBearerTokenProvider",
    "StaticAuthProvider",
    "TokenStore",
    # Error hierarchy
    "HonuaError",
    "HonuaCapabilityNotSupportedError",
    "HonuaHttpError",
    "HonuaAuthError",
    "HonuaRateLimitError",
    "HonuaTransportError",
    "HonuaTimeoutError",
    "HonuaGrpcError",
]

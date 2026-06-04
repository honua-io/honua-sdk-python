"""Honua 3D scene metadata, elevation, and offline-package clients.

This module mirrors the .NET ``Honua.Sdk.Scenes`` / ``Honua.Sdk.Abstractions.Scenes``
surface for the Python SDK. It is **data-access focused** -- it discovers scene
metadata, resolves render-ready tileset/terrain endpoint URLs, queries the
server elevation HTTP API, and parses + validates offline scene-package
manifests. It does **not** perform any 3D rendering.

Reach the sync clients via :meth:`HonuaClient.scenes` /
:meth:`HonuaClient.elevation` and the async variants via
:meth:`AsyncHonuaClient.scenes` / :meth:`AsyncHonuaClient.elevation`.

The wire contract (field names, capability identifiers, package asset types,
SHA-256 validation, expiry/auth/stale semantics) matches the .NET reference
implementation so that scene metadata, elevation responses, and offline
package manifests parse identically across SDKs.
"""

# ruff: noqa: E501, PLR0913, PLR2004

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx

from honua_sdk._http import _encode_path_segment
from honua_sdk.errors import HonuaError

from ._base import (
    BinaryResponse,
    JsonObject,
    Params,
    _AsyncProtocol,
    _params,
    _SyncProtocol,
)

# ---------------------------------------------------------------------------
# Well-known constants (mirrors HonuaSceneCapabilities / *Modes / *AssetTypes)
# ---------------------------------------------------------------------------


class HonuaSceneCapabilities:
    """Well-known scene capability identifiers advertised by scene metadata."""

    THREE_D_TILES = "3d-tiles"
    TERRAIN = "terrain"
    ELEVATION_PROFILE = "elevation-profile"
    I3S = "i3s"


class HonuaSceneAccessModes:
    """Well-known access modes for scene render endpoints."""

    PUBLIC = "public"
    SIGNED_URL = "signed-url"
    PROXY = "proxy"
    HEADERS = "headers"

    _SUPPORTED = frozenset({PUBLIC, SIGNED_URL, PROXY, HEADERS})

    @classmethod
    def is_supported(cls, mode: str | None) -> bool:
        return mode is not None and mode.lower() in cls._SUPPORTED


class HonuaScenePackageAssetTypes:
    """Cacheable asset types for offline 3D scene packages."""

    SCENE_METADATA = "scene-metadata"
    THREE_D_TILESET = "3d-tileset"
    THREE_D_TILE_CONTENT = "3d-tile-content"
    TERRAIN_TILE = "terrain-tile"
    TEXTURE = "texture"
    ELEVATION_PROFILE = "elevation-profile"
    LICENSE_ATTRIBUTION = "license-attribution"

    _SUPPORTED = frozenset(
        {
            SCENE_METADATA,
            THREE_D_TILESET,
            THREE_D_TILE_CONTENT,
            TERRAIN_TILE,
            TEXTURE,
            ELEVATION_PROFILE,
            LICENSE_ATTRIBUTION,
        }
    )

    @classmethod
    def is_supported(cls, asset_type: str | None) -> bool:
        return asset_type is not None and asset_type.lower() in cls._SUPPORTED


class HonuaScenePackageEditionGates:
    """Edition gates advertised by offline scene packages."""

    COMMUNITY = "community"
    PRO = "pro"
    ENTERPRISE = "enterprise"

    _SUPPORTED = frozenset({COMMUNITY, PRO, ENTERPRISE})

    @classmethod
    def is_supported(cls, edition_gate: str | None) -> bool:
        return edition_gate is not None and edition_gate.lower() in cls._SUPPORTED


# ---------------------------------------------------------------------------
# Errors (mirror HonuaSceneException; kept module-local to avoid widening the
# top-level honua_sdk.errors surface)
# ---------------------------------------------------------------------------


class HonuaSceneError(HonuaError):
    """Raised when a scene request fails or a scene response is malformed."""


class HonuaScenePackageError(HonuaError):
    """Raised when an offline scene-package manifest cannot be parsed."""


# ---------------------------------------------------------------------------
# Scene metadata / resolution models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HonuaSceneAuthRequirements:
    """Authentication requirements for a scene or endpoint."""

    requires_authentication: bool = False
    schemes: tuple[str, ...] = ()
    policy: str | None = None

    @classmethod
    def none(cls) -> HonuaSceneAuthRequirements:
        return cls()


@dataclass(frozen=True)
class HonuaSceneCoordinate:
    """WGS84 scene coordinate used for suggested camera centers."""

    latitude: float
    longitude: float
    height: float | None = None


@dataclass(frozen=True)
class HonuaSceneBounds:
    """Spatial extent of a scene in WGS84 degrees, optionally with a height range."""

    min_longitude: float
    min_latitude: float
    max_longitude: float
    max_latitude: float
    min_height: float | None = None
    max_height: float | None = None


@dataclass(frozen=True)
class HonuaSceneAccessCachePolicy:
    """Cache policy advertised for a resolved scene access envelope."""

    public: bool | None = None
    max_age_seconds: int | None = None
    stale_while_revalidate_seconds: int | None = None
    no_store: bool = False


@dataclass(frozen=True)
class HonuaSceneAccessEnvelope:
    """Renderer-safe access metadata for resolved scene URLs."""

    mode: str
    refresh_after: datetime | None = None
    expires_at: datetime | None = None
    cors_mode: str | None = None
    cache: HonuaSceneAccessCachePolicy = field(default_factory=HonuaSceneAccessCachePolicy)
    custom_headers_allowed: bool = False
    revocation_key: str | None = None

    @property
    def is_supported_mode(self) -> bool:
        return HonuaSceneAccessModes.is_supported(self.mode)

    @property
    def is_browser_safe(self) -> bool:
        return self.mode.lower() in (
            HonuaSceneAccessModes.PUBLIC,
            HonuaSceneAccessModes.SIGNED_URL,
            HonuaSceneAccessModes.PROXY,
        )

    def is_expired(self, utc_now: datetime) -> bool:
        return self.expires_at is not None and utc_now >= self.expires_at

    def should_refresh(self, utc_now: datetime) -> bool:
        return self.refresh_after is not None and utc_now >= self.refresh_after


@dataclass(frozen=True)
class HonuaSceneEndpoint:
    """URL and format metadata for a scene resource such as a 3D Tiles root or terrain provider."""

    kind: str
    url: str
    media_type: str | None = None
    format: str | None = None
    requires_authentication: bool = False
    headers: Mapping[str, str] = field(default_factory=dict)
    access: HonuaSceneAccessEnvelope | None = None


@dataclass(frozen=True)
class HonuaSceneLink:
    """Related link advertised by scene metadata."""

    rel: str
    href: str
    type: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class HonuaSceneSummary:
    """Summary metadata for a scene in a catalog list response."""

    id: str
    name: str
    description: str | None = None
    bounds: HonuaSceneBounds | None = None
    capabilities: tuple[str, ...] = ()
    attribution: tuple[str, ...] = ()
    auth: HonuaSceneAuthRequirements = field(default_factory=HonuaSceneAuthRequirements.none)
    updated_at: datetime | None = None
    raw_response: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class HonuaSceneMetadata:
    """Detailed metadata for a single scene."""

    id: str
    name: str
    description: str | None = None
    tileset: HonuaSceneEndpoint | None = None
    terrain: HonuaSceneEndpoint | None = None
    center: HonuaSceneCoordinate | None = None
    bounds: HonuaSceneBounds | None = None
    capabilities: tuple[str, ...] = ()
    attribution: tuple[str, ...] = ()
    auth: HonuaSceneAuthRequirements = field(default_factory=HonuaSceneAuthRequirements.none)
    links: tuple[HonuaSceneLink, ...] = ()
    updated_at: datetime | None = None
    raw_response: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class HonuaSceneResolution:
    """Render-ready scene URLs resolved by the server for a specific client request."""

    scene_id: str
    tileset_url: str | None = None
    terrain_url: str | None = None
    endpoints: tuple[HonuaSceneEndpoint, ...] = ()
    capabilities: tuple[str, ...] = ()
    auth: HonuaSceneAuthRequirements = field(default_factory=HonuaSceneAuthRequirements.none)
    expires_at: datetime | None = None
    access: HonuaSceneAccessEnvelope | None = None
    raw_response: JsonObject = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Elevation models (mirror server /elevation/{datasetId}/value + /profile)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ElevationSourceMetadata:
    """Source metadata returned with an elevation value or profile response."""

    raster_ids: tuple[int, ...] = ()
    raster_count: int = 0
    source_srid: int | None = None
    source_crs: str | None = None
    pixel_type: str | None = None
    no_data_value: float | None = None
    vertical_unit: str | None = None
    vertical_datum: str | None = None
    vertical_unit_assumption: str | None = None
    band: int = 1
    raw_response: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ElevationValue:
    """Result of sampling elevation at a single coordinate."""

    dataset_id: str
    layer_id: int
    elevation: float | None
    no_data: bool
    out_of_bounds: bool
    x: float
    y: float
    query_srid: int | None
    mosaic_rule: str
    source: ElevationSourceMetadata
    raw_response: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ElevationProfileSample:
    """A single ordered distance/elevation sample along a profile line."""

    distance_meters: float
    elevation: float | None
    no_data: bool


@dataclass(frozen=True)
class ElevationProfile:
    """Result of sampling elevation along a line geometry."""

    dataset_id: str
    layer_id: int
    sample_count: int
    line_length_meters: float
    line_srid: int
    mosaic_rule: str
    is_all_no_data: bool
    samples: tuple[ElevationProfileSample, ...]
    source: ElevationSourceMetadata
    raw_response: JsonObject = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Offline scene-package manifest models
# ---------------------------------------------------------------------------

CURRENT_PACKAGE_SCHEMA_VERSION = "honua.scene-package.v1"


@dataclass(frozen=True)
class HonuaScenePackageLod:
    """Level-of-detail range for an offline scene package."""

    min_zoom: int | None = None
    max_zoom: int | None = None
    max_geometric_error_meters: float | None = None


@dataclass(frozen=True)
class HonuaScenePackageByteBudget:
    """Package byte budget advertised before download."""

    max_package_bytes: int | None = None
    declared_bytes: int | None = None


@dataclass(frozen=True)
class HonuaScenePackageAsset:
    """File or payload entry in an offline 3D scene package."""

    key: str | None = None
    type: str | None = None
    role: str | None = None
    path: str | None = None
    content_type: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    etag: str | None = None
    required: bool = False


@dataclass(frozen=True)
class HonuaScenePackageManifest:
    """Offline 3D scene package manifest shared by server packaging and runtimes."""

    schema_version: str | None = None
    package_id: str | None = None
    scene_id: str | None = None
    display_name: str | None = None
    edition_gate: str | None = None
    server_revision: str | None = None
    created_at_utc: datetime | None = None
    stale_after_utc: datetime | None = None
    offline_use_expires_at_utc: datetime | None = None
    auth_expires_at_utc: datetime | None = None
    extent: HonuaSceneBounds | None = None
    lod: HonuaScenePackageLod | None = None
    byte_budget: HonuaScenePackageByteBudget | None = None
    attribution: tuple[str, ...] = ()
    assets: tuple[HonuaScenePackageAsset, ...] = ()
    raw_manifest: JsonObject = field(default_factory=dict)

    @staticmethod
    def parse_json(data: str | bytes | Mapping[str, Any]) -> HonuaScenePackageManifest:
        """Parse a JSON manifest document (text, bytes, or pre-parsed mapping)."""
        return parse_scene_package_manifest(data)

    def validate(
        self,
        utc_now: datetime,
        available_asset_keys: Iterable[str] | None = None,
    ) -> HonuaScenePackageValidationResult:
        """Validate this manifest, optionally marking missing local assets as partial."""
        return validate_scene_package_manifest(self, utc_now, available_asset_keys)


class HonuaScenePackageState(StrEnum):
    """Runtime state derived from manifest validation and local asset availability."""

    READY = "ready"
    STALE = "stale"
    EXPIRED = "expired"
    PARTIAL = "partial"
    INVALID = "invalid"


class HonuaScenePackageValidationSeverity(StrEnum):
    """Severity for manifest validation findings."""

    WARNING = "warning"
    ERROR = "error"


class HonuaScenePackageValidationCodes:
    """Well-known validation issue codes for offline scene package manifests."""

    UNSUPPORTED_SCHEMA_VERSION = "unsupported-schema-version"
    MISSING_PACKAGE_ID = "missing-package-id"
    MISSING_SCENE_ID = "missing-scene-id"
    UNSUPPORTED_EDITION_GATE = "unsupported-edition-gate"
    MISSING_SERVER_REVISION = "missing-server-revision"
    MISSING_CREATED_AT = "missing-created-at"
    MISSING_STALE_AFTER = "missing-stale-after"
    MISSING_OFFLINE_USE_EXPIRY = "missing-offline-use-expiry"
    INVALID_EXPIRY_ORDER = "invalid-expiry-order"
    INVALID_EXTENT = "invalid-extent"
    INVALID_LOD = "invalid-lod"
    INVALID_BYTE_BUDGET = "invalid-byte-budget"
    OVER_BYTE_BUDGET = "over-byte-budget"
    MISSING_ASSETS = "missing-assets"
    NULL_ASSET = "null-asset"
    MISSING_REQUIRED_SCENE_METADATA = "missing-required-scene-metadata"
    MISSING_REQUIRED_ASSET = "missing-required-asset"
    DUPLICATE_ASSET_KEY = "duplicate-asset-key"
    UNSUPPORTED_ASSET_TYPE = "unsupported-asset-type"
    INVALID_ASSET_PATH = "invalid-asset-path"
    INVALID_ASSET_BYTES = "invalid-asset-bytes"
    INVALID_ASSET_HASH = "invalid-asset-hash"
    OFFLINE_USE_EXPIRED = "offline-use-expired"
    AUTH_EXPIRED = "auth-expired"
    STALE = "stale"


@dataclass(frozen=True)
class HonuaScenePackageValidationIssue:
    """A single manifest validation finding."""

    code: str
    message: str
    severity: HonuaScenePackageValidationSeverity = HonuaScenePackageValidationSeverity.ERROR
    asset_key: str | None = None


@dataclass(frozen=True)
class HonuaScenePackageValidationResult:
    """Result of validating an offline scene package manifest."""

    state: HonuaScenePackageState
    issues: tuple[HonuaScenePackageValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not any(
            issue.severity == HonuaScenePackageValidationSeverity.ERROR for issue in self.issues
        )

    @property
    def has_warnings(self) -> bool:
        return any(
            issue.severity == HonuaScenePackageValidationSeverity.WARNING for issue in self.issues
        )


# ---------------------------------------------------------------------------
# JSON extraction helpers (case-insensitive, multi-key, mirroring the .NET parser)
# ---------------------------------------------------------------------------


def _get_value(element: Any, *names: str) -> Any:
    if not isinstance(element, Mapping):
        return None
    lowered: dict[str, Any] | None = None
    for name in names:
        if name in element:
            return element[name]
        if lowered is None:
            lowered = {str(k).lower(): v for k, v in element.items()}
        candidate = lowered.get(name.lower())
        if candidate is not None:
            return candidate
    return None


def _get_str(element: Any, *names: str) -> str | None:
    value = _get_value(element, *names)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _get_bool(element: Any, *names: str) -> bool | None:
    value = _get_value(element, *names)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    return None


def _get_float(element: Any, *names: str) -> float | None:
    value = _get_value(element, *names)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _get_int(element: Any, *names: str) -> int | None:
    value = _get_value(element, *names)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _get_str_array(element: Any, *names: str) -> tuple[str, ...]:
    value = _get_value(element, *names)
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ()


def _parse_datetime(element: Any, *names: str) -> datetime | None:
    text = _get_str(element, *names)
    if text is None:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _add_capability(capabilities: set[str], capability: str | None) -> None:
    if capability and capability.strip():
        capabilities.add(capability.strip())


# ---------------------------------------------------------------------------
# Scene JSON parsing
# ---------------------------------------------------------------------------


def _parse_auth(root: Any) -> HonuaSceneAuthRequirements:
    auth_element = _get_value(root, "auth")
    auth = auth_element if isinstance(auth_element, Mapping) else root

    is_public = _get_bool(auth, "public", "isPublic")
    requires = _get_bool(auth, "requiresAuthentication", "requiresAuth", "required")
    if requires is None:
        requires = _get_bool(root, "requiresAuthentication", "requiresAuth")
    if requires is None:
        requires = (not is_public) if is_public is not None else False

    return HonuaSceneAuthRequirements(
        requires_authentication=requires,
        schemes=_get_str_array(auth, "schemes", "methods"),
        policy=_get_str(auth, "policy", "policyId"),
    )


def _normalize_access_mode(value: str) -> str:
    mode = value.strip().replace("_", "-").lower()
    return {
        "signedurl": HonuaSceneAccessModes.SIGNED_URL,
        "signed-url": HonuaSceneAccessModes.SIGNED_URL,
        "header": HonuaSceneAccessModes.HEADERS,
        "headers": HonuaSceneAccessModes.HEADERS,
        "proxy": HonuaSceneAccessModes.PROXY,
        "public": HonuaSceneAccessModes.PUBLIC,
    }.get(mode, value.strip().replace("_", "-"))


def _parse_access_cache_policy(access: Any) -> HonuaSceneAccessCachePolicy:
    cache = _get_value(access, "cache")
    if not isinstance(cache, Mapping):
        return HonuaSceneAccessCachePolicy()
    return HonuaSceneAccessCachePolicy(
        public=_get_bool(cache, "public", "shared"),
        max_age_seconds=_get_int(cache, "maxAgeSeconds", "maxAge"),
        stale_while_revalidate_seconds=_get_int(cache, "staleWhileRevalidateSeconds", "staleWhileRevalidate"),
        no_store=_get_bool(cache, "noStore", "no-store") or False,
    )


def _parse_access_envelope(root: Any) -> HonuaSceneAccessEnvelope | None:
    access_element = _get_value(root, "access")
    has_access_object = isinstance(access_element, Mapping)
    access = access_element if has_access_object else root

    if has_access_object:
        raw_mode = _get_str(access, "mode", "accessMode", "type")
    else:
        raw_mode = _get_str(access, "mode", "accessMode") or _get_str(root, "accessMode")

    if not raw_mode and not has_access_object:
        return None

    mode = _normalize_access_mode(raw_mode or "unknown")
    expires_at = _parse_datetime(access, "expiresAtUtc", "expiresAt", "expiration", "validUntil")
    if expires_at is None and has_access_object:
        expires_at = _parse_datetime(root, "expiresAt", "expiration", "validUntil")

    custom_headers = _get_bool(access, "customHeadersAllowed", "headersAllowed", "allowCustomHeaders")
    if custom_headers is None:
        custom_headers = mode.lower() == HonuaSceneAccessModes.HEADERS

    return HonuaSceneAccessEnvelope(
        mode=mode,
        refresh_after=_parse_datetime(access, "refreshAfterUtc", "refreshAfter", "refreshAt"),
        expires_at=expires_at,
        cors_mode=_get_str(access, "corsMode", "cors"),
        cache=_parse_access_cache_policy(access),
        custom_headers_allowed=custom_headers,
        revocation_key=_get_str(access, "revocationKey", "revision", "serverRevision"),
    )


def _parse_headers(endpoint: Any) -> dict[str, str]:
    headers = _get_value(endpoint, "headers")
    if not isinstance(headers, Mapping):
        return {}
    return {str(k): v for k, v in headers.items() if isinstance(v, str)}


def _parse_endpoint_object(
    endpoint: Mapping[str, Any],
    default_kind: str,
    inherited_requires_auth: bool,
    inherited_access: HonuaSceneAccessEnvelope | None,
) -> HonuaSceneEndpoint:
    url = _get_str(endpoint, "url", "href")
    if url is None:
        raise HonuaSceneError(f"Scene endpoint '{default_kind}' is missing a url.")
    access = _parse_access_envelope(endpoint) or inherited_access
    requires_auth = _get_bool(endpoint, "requiresAuthentication", "requiresAuth")
    return HonuaSceneEndpoint(
        kind=_get_str(endpoint, "kind", "type") or default_kind,
        url=url,
        media_type=_get_str(endpoint, "mediaType", "contentType"),
        format=_get_str(endpoint, "format") or default_kind,
        requires_authentication=requires_auth if requires_auth is not None else inherited_requires_auth,
        headers=_parse_headers(endpoint),
        access=access,
    )


def _parse_endpoint(
    root: Any,
    default_kind: str,
    object_property: str,
    url_property: str,
    inherited_access: HonuaSceneAccessEnvelope | None,
) -> HonuaSceneEndpoint | None:
    inherited_requires_auth = _parse_auth(root).requires_authentication

    endpoint = _get_value(root, object_property)
    if isinstance(endpoint, Mapping):
        return _parse_endpoint_object(endpoint, default_kind, inherited_requires_auth, inherited_access)

    endpoints = _get_value(root, "endpoints")
    if isinstance(endpoints, Mapping):
        nested = _get_value(endpoints, object_property)
        if isinstance(nested, Mapping):
            return _parse_endpoint_object(nested, default_kind, inherited_requires_auth, inherited_access)

    url = _get_str(root, url_property)
    if url is None:
        return None
    return HonuaSceneEndpoint(
        kind=default_kind,
        url=url,
        media_type="application/json" if default_kind == HonuaSceneCapabilities.THREE_D_TILES else None,
        format=default_kind,
        requires_authentication=inherited_requires_auth,
        access=inherited_access,
    )


def _parse_endpoint_array(
    root: Any,
    inherited_access: HonuaSceneAccessEnvelope | None,
) -> list[HonuaSceneEndpoint]:
    endpoints = _get_value(root, "endpoints")
    if not isinstance(endpoints, Sequence) or isinstance(endpoints, (str, bytes)):
        return []
    inherited_requires_auth = _parse_auth(root).requires_authentication
    result: list[HonuaSceneEndpoint] = []
    for endpoint in endpoints:
        if isinstance(endpoint, Mapping):
            kind = _get_str(endpoint, "kind", "type") or "resource"
            result.append(
                _parse_endpoint_object(endpoint, kind, inherited_requires_auth, inherited_access)
            )
    return result


def _parse_capabilities(root: Any, endpoints: Sequence[HonuaSceneEndpoint]) -> tuple[str, ...]:
    capabilities: set[str] = set()
    value = _get_value(root, "capabilities")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if isinstance(item, str):
                _add_capability(capabilities, item)
    elif isinstance(value, Mapping):
        for name, flag in value.items():
            if flag is not False:
                _add_capability(capabilities, str(name))
    elif isinstance(value, str):
        for capability in value.split(","):
            _add_capability(capabilities, capability)

    for endpoint in endpoints:
        _add_capability(capabilities, endpoint.kind)
        _add_capability(capabilities, endpoint.format)

    return tuple(sorted(capabilities, key=str.lower))


def _parse_attribution(root: Any) -> tuple[str, ...]:
    for property_name in ("attribution", "attributions"):
        value = _get_value(root, property_name)
        if isinstance(value, str):
            text = value.strip()
            return (text,) if text else ()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ()


def _parse_bounds(root: Any) -> HonuaSceneBounds | None:
    bounds = _get_value(root, "bounds")
    if isinstance(bounds, Mapping):
        min_lon = _get_float(bounds, "minLongitude", "west", "xmin")
        min_lat = _get_float(bounds, "minLatitude", "south", "ymin")
        max_lon = _get_float(bounds, "maxLongitude", "east", "xmax")
        max_lat = _get_float(bounds, "maxLatitude", "north", "ymax")
        if None not in (min_lon, min_lat, max_lon, max_lat):
            return HonuaSceneBounds(
                min_longitude=min_lon,  # type: ignore[arg-type]
                min_latitude=min_lat,  # type: ignore[arg-type]
                max_longitude=max_lon,  # type: ignore[arg-type]
                max_latitude=max_lat,  # type: ignore[arg-type]
                min_height=_get_float(bounds, "minHeight", "zmin"),
                max_height=_get_float(bounds, "maxHeight", "zmax"),
            )

    bbox = _get_value(root, "bbox")
    if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes)):
        return None
    values = [float(item) for item in bbox if isinstance(item, (int, float)) and not isinstance(item, bool)]
    if len(values) >= 6:
        return HonuaSceneBounds(
            min_longitude=values[0],
            min_latitude=values[1],
            min_height=values[2],
            max_longitude=values[3],
            max_latitude=values[4],
            max_height=values[5],
        )
    if len(values) >= 4:
        return HonuaSceneBounds(
            min_longitude=values[0],
            min_latitude=values[1],
            max_longitude=values[2],
            max_latitude=values[3],
        )
    return None


def _parse_coordinate(root: Any, property_name: str) -> HonuaSceneCoordinate | None:
    coordinate = _get_value(root, property_name)
    if isinstance(coordinate, Mapping):
        latitude = _get_float(coordinate, "latitude", "lat", "y")
        longitude = _get_float(coordinate, "longitude", "lon", "lng", "x")
        if latitude is not None and longitude is not None:
            return HonuaSceneCoordinate(
                latitude=latitude,
                longitude=longitude,
                height=_get_float(coordinate, "height", "z"),
            )
    if isinstance(coordinate, Sequence) and not isinstance(coordinate, (str, bytes)):
        values = [float(item) for item in coordinate if isinstance(item, (int, float)) and not isinstance(item, bool)]
        if len(values) >= 2:
            return HonuaSceneCoordinate(
                longitude=values[0],
                latitude=values[1],
                height=values[2] if len(values) >= 3 else None,
            )
    return None


def _parse_links(root: Any) -> tuple[HonuaSceneLink, ...]:
    links = _get_value(root, "links")
    if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
        return ()
    result: list[HonuaSceneLink] = []
    for link in links:
        if not isinstance(link, Mapping):
            continue
        href = _get_str(link, "href", "url")
        if href is None:
            raise HonuaSceneError("Scene link is missing an href.")
        result.append(
            HonuaSceneLink(
                rel=_get_str(link, "rel") or "related",
                href=href,
                type=_get_str(link, "type", "mediaType"),
                title=_get_str(link, "title"),
            )
        )
    return tuple(result)


def _enumerate_scene_items(root: Any) -> list[Mapping[str, Any]]:
    if isinstance(root, Sequence) and not isinstance(root, (str, bytes)):
        return [item for item in root if isinstance(item, Mapping)]
    for property_name in ("scenes", "items", "features"):
        items = _get_value(root, property_name)
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            return [item for item in items if isinstance(item, Mapping)]
    raise HonuaSceneError("Scene list response must contain a scenes array.")


def parse_scene_summary(element: Mapping[str, Any]) -> HonuaSceneSummary:
    scene_id = _get_str(element, "id", "sceneId")
    if scene_id is None:
        raise HonuaSceneError("Scene item is missing an id.")
    access = _parse_access_envelope(element)
    tileset = _parse_endpoint(element, HonuaSceneCapabilities.THREE_D_TILES, "tileset", "tilesetUrl", access)
    terrain = _parse_endpoint(element, HonuaSceneCapabilities.TERRAIN, "terrain", "terrainUrl", access)
    endpoints = [endpoint for endpoint in (tileset, terrain) if endpoint is not None]
    return HonuaSceneSummary(
        id=scene_id,
        name=_get_str(element, "name", "title") or scene_id,
        description=_get_str(element, "description"),
        bounds=_parse_bounds(element),
        capabilities=_parse_capabilities(element, endpoints),
        attribution=_parse_attribution(element),
        auth=_parse_auth(element),
        updated_at=_parse_datetime(element, "updatedAt", "modifiedAt", "lastModified"),
        raw_response=dict(element),
    )


def parse_scene_metadata(element: Mapping[str, Any]) -> HonuaSceneMetadata:
    scene_id = _get_str(element, "id", "sceneId")
    if scene_id is None:
        raise HonuaSceneError("Scene metadata is missing an id.")
    access = _parse_access_envelope(element)
    tileset = _parse_endpoint(element, HonuaSceneCapabilities.THREE_D_TILES, "tileset", "tilesetUrl", access)
    terrain = _parse_endpoint(element, HonuaSceneCapabilities.TERRAIN, "terrain", "terrainUrl", access)
    endpoints = [endpoint for endpoint in (tileset, terrain) if endpoint is not None]
    return HonuaSceneMetadata(
        id=scene_id,
        name=_get_str(element, "name", "title") or scene_id,
        description=_get_str(element, "description"),
        tileset=tileset,
        terrain=terrain,
        center=_parse_coordinate(element, "center"),
        bounds=_parse_bounds(element),
        capabilities=_parse_capabilities(element, endpoints),
        attribution=_parse_attribution(element),
        auth=_parse_auth(element),
        links=_parse_links(element),
        updated_at=_parse_datetime(element, "updatedAt", "modifiedAt", "lastModified"),
        raw_response=dict(element),
    )


def _find_endpoint_url(endpoints: Sequence[HonuaSceneEndpoint], kind: str) -> str | None:
    for endpoint in endpoints:
        if endpoint.kind.lower() == kind.lower() or (endpoint.format or "").lower() == kind.lower():
            return endpoint.url
    return None


def parse_scene_resolution(root: Mapping[str, Any], fallback_scene_id: str) -> HonuaSceneResolution:
    scene_id = _get_str(root, "sceneId", "id") or fallback_scene_id
    access = _parse_access_envelope(root)
    tileset = _parse_endpoint(root, HonuaSceneCapabilities.THREE_D_TILES, "tileset", "tilesetUrl", access)
    terrain = _parse_endpoint(root, HonuaSceneCapabilities.TERRAIN, "terrain", "terrainUrl", access)

    endpoints: list[HonuaSceneEndpoint] = list(_parse_endpoint_array(root, access))
    for endpoint in (tileset, terrain):
        if endpoint is not None:
            endpoints.append(endpoint)
    # de-dupe by (kind, url) preserving order
    seen: set[tuple[str, str]] = set()
    deduped: list[HonuaSceneEndpoint] = []
    for endpoint in endpoints:
        key = (endpoint.kind, endpoint.url)
        if key not in seen:
            seen.add(key)
            deduped.append(endpoint)

    capabilities = _parse_capabilities(root, deduped)
    return HonuaSceneResolution(
        scene_id=scene_id,
        tileset_url=_get_str(root, "tilesetUrl")
        or (tileset.url if tileset else None)
        or _find_endpoint_url(deduped, HonuaSceneCapabilities.THREE_D_TILES),
        terrain_url=_get_str(root, "terrainUrl")
        or (terrain.url if terrain else None)
        or _find_endpoint_url(deduped, HonuaSceneCapabilities.TERRAIN),
        endpoints=tuple(deduped),
        capabilities=capabilities,
        auth=_parse_auth(root),
        expires_at=_parse_datetime(root, "expiresAt", "expiration", "validUntil")
        or (access.expires_at if access is not None else None),
        access=access,
        raw_response=dict(root),
    )


def _ensure_capabilities(
    scene_id: str,
    available: Sequence[str],
    required: Sequence[str] | None,
) -> None:
    if not required:
        return
    available_lower = {item.lower() for item in available}
    missing = [item for item in required if item and item.lower() not in available_lower]
    if missing:
        raise HonuaSceneError(
            f"Scene '{scene_id}' does not expose required capability: {', '.join(missing)}."
        )


def _scene_list_params(
    capabilities: Sequence[str] | None,
    include_disabled: bool | None,
    response_format: str,
    extra_params: Params,
) -> dict[str, Any]:
    params: dict[str, Any] = {"f": response_format}
    if capabilities:
        params["capabilities"] = ",".join(item for item in capabilities if item)
    if include_disabled is not None:
        params["includeDisabled"] = "true" if include_disabled else "false"
    return _params(params, extra_params)


def _scene_resolve_params(
    required_capabilities: Sequence[str] | None,
    include_terrain: bool,
    response_format: str,
    extra_params: Params,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "f": response_format,
        "includeTerrain": "true" if include_terrain else "false",
    }
    if required_capabilities:
        params["capabilities"] = ",".join(item for item in required_capabilities if item)
    return _params(params, extra_params)


# ---------------------------------------------------------------------------
# Elevation JSON parsing
# ---------------------------------------------------------------------------


def _parse_elevation_source(root: Any) -> ElevationSourceMetadata:
    source = _get_value(root, "source")
    if not isinstance(source, Mapping):
        return ElevationSourceMetadata()
    raster_ids_raw = _get_value(source, "rasterIds")
    raster_ids: tuple[int, ...] = ()
    if isinstance(raster_ids_raw, Sequence) and not isinstance(raster_ids_raw, (str, bytes)):
        raster_ids = tuple(
            int(item) for item in raster_ids_raw if isinstance(item, (int, float)) and not isinstance(item, bool)
        )
    return ElevationSourceMetadata(
        raster_ids=raster_ids,
        raster_count=_get_int(source, "rasterCount") or 0,
        source_srid=_get_int(source, "sourceSrid"),
        source_crs=_get_str(source, "sourceCrs"),
        pixel_type=_get_str(source, "pixelType"),
        no_data_value=_get_float(source, "noDataValue"),
        vertical_unit=_get_str(source, "verticalUnit"),
        vertical_datum=_get_str(source, "verticalDatum"),
        vertical_unit_assumption=_get_str(source, "verticalUnitAssumption"),
        band=_get_int(source, "band") or 1,
        raw_response=dict(source),
    )


def parse_elevation_value(root: Mapping[str, Any]) -> ElevationValue:
    dataset_id = _get_str(root, "datasetId")
    if dataset_id is None:
        raise HonuaSceneError("Elevation value response is missing datasetId.")
    layer_id = _get_int(root, "layerId")
    return ElevationValue(
        dataset_id=dataset_id,
        layer_id=layer_id if layer_id is not None else 0,
        elevation=_get_float(root, "elevation"),
        no_data=_get_bool(root, "noData") or False,
        out_of_bounds=_get_bool(root, "outOfBounds") or False,
        x=_get_float(root, "x") or 0.0,
        y=_get_float(root, "y") or 0.0,
        query_srid=_get_int(root, "querySrid"),
        mosaic_rule=_get_str(root, "mosaicRule") or "",
        source=_parse_elevation_source(root),
        raw_response=dict(root),
    )


def parse_elevation_profile(root: Mapping[str, Any]) -> ElevationProfile:
    dataset_id = _get_str(root, "datasetId")
    if dataset_id is None:
        raise HonuaSceneError("Elevation profile response is missing datasetId.")
    samples_raw = _get_value(root, "samples")
    samples: list[ElevationProfileSample] = []
    if isinstance(samples_raw, Sequence) and not isinstance(samples_raw, (str, bytes)):
        for sample in samples_raw:
            if not isinstance(sample, Mapping):
                continue
            samples.append(
                ElevationProfileSample(
                    distance_meters=_get_float(sample, "distanceMeters") or 0.0,
                    elevation=_get_float(sample, "elevation"),
                    no_data=_get_bool(sample, "noData") or False,
                )
            )
    layer_id = _get_int(root, "layerId")
    return ElevationProfile(
        dataset_id=dataset_id,
        layer_id=layer_id if layer_id is not None else 0,
        sample_count=_get_int(root, "sampleCount") or len(samples),
        line_length_meters=_get_float(root, "lineLengthMeters") or 0.0,
        line_srid=_get_int(root, "lineSrid") or 4326,
        mosaic_rule=_get_str(root, "mosaicRule") or "",
        is_all_no_data=_get_bool(root, "isAllNoData") or False,
        samples=tuple(samples),
        source=_parse_elevation_source(root),
        raw_response=dict(root),
    )


def _elevation_value_params(
    x: float,
    y: float,
    srid: str | int | None,
    mosaic_rule: str | None,
    extra_params: Params,
) -> dict[str, Any]:
    params: dict[str, Any] = {"x": x, "y": y}
    if srid is not None:
        params["srid"] = srid
    if mosaic_rule is not None:
        params["mosaicRule"] = mosaic_rule
    return _params(params, extra_params)


def _elevation_profile_params(
    line: str,
    sample_count: int | None,
    interval: float | None,
    srid: str | int | None,
    mosaic_rule: str | None,
    extra_params: Params,
) -> dict[str, Any]:
    params: dict[str, Any] = {"line": line}
    if sample_count is not None:
        params["sampleCount"] = sample_count
    if interval is not None:
        params["interval"] = interval
    if srid is not None:
        params["srid"] = srid
    if mosaic_rule is not None:
        params["mosaicRule"] = mosaic_rule
    return _params(params, extra_params)


# ---------------------------------------------------------------------------
# Offline scene-package manifest parsing + validation
# ---------------------------------------------------------------------------


def _parse_package_bounds(root: Any) -> HonuaSceneBounds | None:
    extent = _get_value(root, "extent")
    if isinstance(extent, Mapping):
        return _parse_bounds({"bounds": extent})
    return None


def parse_scene_package_manifest(
    data: str | bytes | Mapping[str, Any],
) -> HonuaScenePackageManifest:
    """Parse a UTF-8 JSON manifest document into the typed model."""
    if isinstance(data, Mapping):
        document: Any = data
    else:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        if not text or not text.strip():
            raise HonuaScenePackageError("Offline scene package manifest JSON is required.")
        try:
            document = json.loads(text)
        except ValueError as exc:
            raise HonuaScenePackageError("Offline scene package manifest JSON was malformed.") from exc

    if not isinstance(document, Mapping):
        raise HonuaScenePackageError("Offline scene package manifest JSON did not contain an object.")

    lod_raw = _get_value(document, "lod")
    lod = None
    if isinstance(lod_raw, Mapping):
        lod = HonuaScenePackageLod(
            min_zoom=_get_int(lod_raw, "minZoom"),
            max_zoom=_get_int(lod_raw, "maxZoom"),
            max_geometric_error_meters=_get_float(lod_raw, "maxGeometricErrorMeters"),
        )

    budget_raw = _get_value(document, "byteBudget")
    byte_budget = None
    if isinstance(budget_raw, Mapping):
        byte_budget = HonuaScenePackageByteBudget(
            max_package_bytes=_get_int(budget_raw, "maxPackageBytes"),
            declared_bytes=_get_int(budget_raw, "declaredBytes"),
        )

    assets_raw = _get_value(document, "assets")
    assets: list[HonuaScenePackageAsset] = []
    if isinstance(assets_raw, Sequence) and not isinstance(assets_raw, (str, bytes)):
        for asset in assets_raw:
            if not isinstance(asset, Mapping):
                continue
            assets.append(
                HonuaScenePackageAsset(
                    key=_get_str(asset, "key"),
                    type=_get_str(asset, "type"),
                    role=_get_str(asset, "role"),
                    path=_get_str(asset, "path"),
                    content_type=_get_str(asset, "contentType"),
                    bytes=_get_int(asset, "bytes"),
                    sha256=_get_str(asset, "sha256"),
                    etag=_get_str(asset, "etag", "eTag"),
                    required=_get_bool(asset, "required") or False,
                )
            )

    return HonuaScenePackageManifest(
        schema_version=_get_str(document, "schemaVersion"),
        package_id=_get_str(document, "packageId"),
        scene_id=_get_str(document, "sceneId"),
        display_name=_get_str(document, "displayName"),
        edition_gate=_get_str(document, "editionGate"),
        server_revision=_get_str(document, "serverRevision"),
        created_at_utc=_parse_datetime(document, "createdAtUtc"),
        stale_after_utc=_parse_datetime(document, "staleAfterUtc"),
        offline_use_expires_at_utc=_parse_datetime(document, "offlineUseExpiresAtUtc"),
        auth_expires_at_utc=_parse_datetime(document, "authExpiresAtUtc"),
        extent=_parse_package_bounds(document),
        lod=lod,
        byte_budget=byte_budget,
        attribution=_parse_attribution(document),
        assets=tuple(assets),
        raw_manifest=dict(document),
    )


_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _is_valid_sha256(sha256: str | None) -> bool:
    if not sha256 or not sha256.strip():
        return False
    value = sha256.strip()
    if _HEX64.match(value):
        return True
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(decoded) == 32


def _is_safe_relative_path(path: str | None) -> bool:
    if not path or not path.strip():
        return False
    if "\\" in path or path.startswith("/"):
        return False
    if "://" in path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    return all(segment not in (".", "..") for segment in segments)


class _IssueSink:
    """Mutable accumulator for validation issues, mirroring the .NET helper set."""

    def __init__(self) -> None:
        self.issues: list[HonuaScenePackageValidationIssue] = []

    def error(self, code: str, message: str, asset_key: str | None = None) -> None:
        self.issues.append(
            HonuaScenePackageValidationIssue(
                code=code,
                message=message,
                severity=HonuaScenePackageValidationSeverity.ERROR,
                asset_key=asset_key,
            )
        )

    def warning(self, code: str, message: str) -> None:
        self.issues.append(
            HonuaScenePackageValidationIssue(
                code=code,
                message=message,
                severity=HonuaScenePackageValidationSeverity.WARNING,
            )
        )


_C = HonuaScenePackageValidationCodes


def _validate_identity(manifest: HonuaScenePackageManifest, sink: _IssueSink) -> bool:
    invalid = False
    if manifest.schema_version != CURRENT_PACKAGE_SCHEMA_VERSION:
        sink.error(_C.UNSUPPORTED_SCHEMA_VERSION, f"Unsupported scene package schema version '{manifest.schema_version or '<missing>'}'.")
        invalid = True
    for value, code, message in (
        (manifest.package_id, _C.MISSING_PACKAGE_ID, "Scene package manifest is missing packageId."),
        (manifest.scene_id, _C.MISSING_SCENE_ID, "Scene package manifest is missing sceneId."),
        (manifest.server_revision, _C.MISSING_SERVER_REVISION, "Scene package manifest is missing serverRevision."),
    ):
        if not (value and value.strip()):
            sink.error(code, message)
            invalid = True
    if not HonuaScenePackageEditionGates.is_supported(manifest.edition_gate):
        sink.error(_C.UNSUPPORTED_EDITION_GATE, f"Unsupported scene package edition gate '{manifest.edition_gate or '<missing>'}'.")
        invalid = True
    return invalid


def _validate_dates(
    manifest: HonuaScenePackageManifest,
    utc_now: datetime,
    sink: _IssueSink,
) -> tuple[bool, bool, bool]:
    """Return ``(invalid, expired, stale)`` for the manifest date fields."""
    invalid = False
    for value, code, message in (
        (manifest.created_at_utc, _C.MISSING_CREATED_AT, "Scene package manifest is missing createdAtUtc."),
        (manifest.stale_after_utc, _C.MISSING_STALE_AFTER, "Scene package manifest is missing staleAfterUtc."),
        (manifest.offline_use_expires_at_utc, _C.MISSING_OFFLINE_USE_EXPIRY, "Scene package manifest is missing offlineUseExpiresAtUtc."),
    ):
        if value is None:
            sink.error(code, message)
            invalid = True

    if (
        manifest.stale_after_utc is not None
        and manifest.offline_use_expires_at_utc is not None
        and manifest.stale_after_utc > manifest.offline_use_expires_at_utc
    ):
        sink.error(_C.INVALID_EXPIRY_ORDER, "staleAfterUtc must be before or equal to offlineUseExpiresAtUtc.")
        invalid = True

    expired = False
    stale = False
    if manifest.offline_use_expires_at_utc is not None and utc_now >= manifest.offline_use_expires_at_utc:
        sink.error(_C.OFFLINE_USE_EXPIRED, "Scene package offline use has expired.")
        expired = True
    elif manifest.stale_after_utc is not None and utc_now >= manifest.stale_after_utc:
        sink.warning(_C.STALE, "Scene package content is stale.")
        stale = True

    if manifest.auth_expires_at_utc is not None and utc_now >= manifest.auth_expires_at_utc:
        sink.warning(_C.AUTH_EXPIRED, "Scene package download or refresh credentials have expired.")

    return invalid, expired, stale


def _validate_extent(extent: HonuaSceneBounds | None, sink: _IssueSink) -> bool:
    if extent is None:
        sink.error(_C.INVALID_EXTENT, "Scene package manifest is missing extent.")
        return True
    invalid = (
        not (-180 <= extent.min_longitude <= 180)
        or not (-180 <= extent.max_longitude <= 180)
        or not (-90 <= extent.min_latitude <= 90)
        or not (-90 <= extent.max_latitude <= 90)
        or extent.min_longitude > extent.max_longitude
        or extent.min_latitude > extent.max_latitude
        or (extent.min_height is not None and extent.max_height is not None and extent.min_height > extent.max_height)
    )
    if invalid:
        sink.error(_C.INVALID_EXTENT, "Scene package extent must be a valid WGS84 bounding box.")
    return invalid


def _validate_lod(lod: HonuaScenePackageLod | None, sink: _IssueSink) -> bool:
    if lod is None:
        sink.error(_C.INVALID_LOD, "Scene package manifest is missing lod.")
        return True
    invalid = (
        lod.min_zoom is None
        or lod.max_zoom is None
        or lod.min_zoom < 0
        or lod.max_zoom < 0
        or lod.min_zoom > lod.max_zoom
        or (lod.max_geometric_error_meters is not None and lod.max_geometric_error_meters < 0)
    )
    if invalid:
        sink.error(_C.INVALID_LOD, "Scene package lod must define a valid zoom range and non-negative geometric error.")
    return invalid


def _validate_byte_budget(manifest: HonuaScenePackageManifest, sink: _IssueSink) -> bool:
    budget = manifest.byte_budget
    if budget is None:
        sink.error(_C.INVALID_BYTE_BUDGET, "Scene package manifest is missing byteBudget.")
        return True
    if (
        budget.max_package_bytes is None
        or budget.declared_bytes is None
        or budget.max_package_bytes <= 0
        or budget.declared_bytes <= 0
    ):
        sink.error(_C.INVALID_BYTE_BUDGET, "Scene package byteBudget must define positive maxPackageBytes and declaredBytes.")
        return True

    max_package_bytes = budget.max_package_bytes
    total_asset_bytes = 0
    asset_bytes_overflow = False
    for asset in manifest.assets:
        if not asset.bytes or asset.bytes <= 0:
            continue
        if asset.bytes > max_package_bytes or total_asset_bytes > max_package_bytes - asset.bytes:
            asset_bytes_overflow = True
            break
        total_asset_bytes += asset.bytes

    if budget.declared_bytes > max_package_bytes or asset_bytes_overflow or total_asset_bytes > max_package_bytes:
        sink.error(_C.OVER_BYTE_BUDGET, "Scene package declared or asset bytes exceed maxPackageBytes.")
        return True
    return False


def _validate_single_asset(
    asset: HonuaScenePackageAsset,
    seen: set[str],
    sink: _IssueSink,
) -> bool:
    invalid = False
    if asset.key is None or not asset.key.strip():
        sink.error(_C.MISSING_REQUIRED_ASSET, "Scene package asset is missing key.", asset.key)
        invalid = True
    elif asset.key.lower() in seen:
        sink.error(_C.DUPLICATE_ASSET_KEY, "Scene package asset key is duplicated.", asset.key)
        invalid = True
    else:
        seen.add(asset.key.lower())

    if not HonuaScenePackageAssetTypes.is_supported(asset.type):
        sink.error(_C.UNSUPPORTED_ASSET_TYPE, f"Unsupported scene package asset type '{asset.type or '<missing>'}'.", asset.key)
        invalid = True
    if not _is_safe_relative_path(asset.path):
        sink.error(_C.INVALID_ASSET_PATH, "Scene package asset path must be package-local and relative.", asset.key)
        invalid = True
    if asset.bytes is None or asset.bytes <= 0:
        sink.error(_C.INVALID_ASSET_BYTES, "Scene package asset bytes must be positive.", asset.key)
        invalid = True
    if not _is_valid_sha256(asset.sha256):
        sink.error(_C.INVALID_ASSET_HASH, "Scene package asset sha256 must be a base16 or base64 SHA-256 digest.", asset.key)
        invalid = True
    return invalid


def _validate_assets(
    manifest: HonuaScenePackageManifest,
    available: set[str] | None,
    sink: _IssueSink,
) -> tuple[bool, bool]:
    """Return ``(invalid, partial)`` for the manifest asset entries."""
    if not manifest.assets:
        sink.error(_C.MISSING_ASSETS, "Scene package manifest has no assets.")
        return True, False

    invalid = False
    partial = False
    seen: set[str] = set()
    has_required_scene_metadata = False
    for asset in manifest.assets:
        invalid |= _validate_single_asset(asset, seen, sink)
        if asset.required and (asset.type or "").lower() == HonuaScenePackageAssetTypes.SCENE_METADATA:
            has_required_scene_metadata = True
        if (
            asset.required
            and available is not None
            and asset.key
            and asset.key.strip()
            and asset.key.lower() not in available
        ):
            sink.error(_C.MISSING_REQUIRED_ASSET, "Required scene package asset is missing from local storage.", asset.key)
            partial = True

    if not has_required_scene_metadata:
        sink.error(_C.MISSING_REQUIRED_SCENE_METADATA, "Scene package manifest must include a required scene-metadata asset.")
        invalid = True

    return invalid, partial


def validate_scene_package_manifest(
    manifest: HonuaScenePackageManifest,
    utc_now: datetime,
    available_asset_keys: Iterable[str] | None = None,
) -> HonuaScenePackageValidationResult:
    """Validate a manifest, mirroring HonuaScenePackageManifestValidator semantics."""
    sink = _IssueSink()
    available = (
        None
        if available_asset_keys is None
        else {key.lower() for key in available_asset_keys if key and key.strip()}
    )

    invalid = _validate_identity(manifest, sink)
    date_invalid, expired, stale = _validate_dates(manifest, utc_now, sink)
    invalid |= date_invalid
    invalid |= _validate_extent(manifest.extent, sink)
    invalid |= _validate_lod(manifest.lod, sink)
    invalid |= _validate_byte_budget(manifest, sink)
    asset_invalid, partial = _validate_assets(manifest, available, sink)
    invalid |= asset_invalid

    if invalid:
        state = HonuaScenePackageState.INVALID
    elif partial:
        state = HonuaScenePackageState.PARTIAL
    elif expired:
        state = HonuaScenePackageState.EXPIRED
    elif stale:
        state = HonuaScenePackageState.STALE
    else:
        state = HonuaScenePackageState.READY

    return HonuaScenePackageValidationResult(state=state, issues=tuple(sink.issues))


# ---------------------------------------------------------------------------
# 3D Tiles tileset traversal + tile content models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HonuaTilesetContent:
    """A single 3D Tiles content reference discovered while walking a tileset.

    The ``uri`` is exactly as authored in the tileset document (relative to the
    document that declared it). ``resolved_path`` is that URI resolved against
    the tileset's own package-relative path, which is the key used for offline
    download and packaging. ``is_tileset`` marks references to nested
    ``tileset.json`` documents (external tilesets) so callers can recurse.
    """

    uri: str
    resolved_path: str
    is_tileset: bool = False


def _is_external_tileset_uri(uri: str) -> bool:
    """Return ``True`` when a content URI points at a nested tileset document."""
    path = urlsplit(uri).path
    return path.lower().endswith(".json")


def _resolve_tileset_relative_path(base_path: str, uri: str) -> str:
    """Resolve a content ``uri`` against the package-relative ``base_path``.

    ``base_path`` is the path of the tileset document that declared ``uri``
    (e.g. ``"tileset.json"`` or ``"sub/tileset.json"``). Absolute URLs and
    rooted paths are returned unchanged; relative URIs (and their query string)
    are normalized against the declaring document's directory using POSIX
    semantics so the result stays a stable package-local key.
    """
    split = urlsplit(uri)
    if split.scheme or split.netloc or uri.startswith("/"):
        return uri
    directory = posixpath.dirname(base_path)
    combined = posixpath.normpath(posixpath.join(directory, split.path)) if split.path else base_path
    return f"{combined}?{split.query}" if split.query else combined


def _walk_tileset_node(
    node: Any,
    base_path: str,
    results: list[HonuaTilesetContent],
    seen: set[str],
) -> None:
    if not isinstance(node, Mapping):
        return
    for content in _node_contents(node):
        uri = _get_str(content, "uri", "url")
        if uri is None:
            continue
        resolved = _resolve_tileset_relative_path(base_path, uri)
        if resolved in seen:
            continue
        seen.add(resolved)
        results.append(
            HonuaTilesetContent(
                uri=uri,
                resolved_path=resolved,
                is_tileset=_is_external_tileset_uri(uri),
            )
        )
    children = _get_value(node, "children")
    if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
        for child in children:
            _walk_tileset_node(child, base_path, results, seen)


def _node_contents(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    contents: list[Mapping[str, Any]] = []
    single = _get_value(node, "content")
    if isinstance(single, Mapping):
        contents.append(single)
    multiple = _get_value(node, "contents")
    if isinstance(multiple, Sequence) and not isinstance(multiple, (str, bytes)):
        contents.extend(item for item in multiple if isinstance(item, Mapping))
    return contents


def enumerate_tileset_contents(
    tileset: Mapping[str, Any],
    *,
    base_path: str = "tileset.json",
) -> tuple[HonuaTilesetContent, ...]:
    """Walk a parsed ``tileset.json`` document and return its content references.

    Traverses the ``root`` node and all ``children`` recursively, collecting the
    ``content``/``contents`` ``uri`` entries. Each reference's ``resolved_path``
    is resolved against ``base_path`` (the package-relative path of this tileset
    document) so the returned keys are stable across the package. Duplicate
    resolved paths are returned once. Nested external tilesets are flagged via
    :attr:`HonuaTilesetContent.is_tileset`; this function does **not** fetch or
    recurse into them -- callers that need the full tile graph download each
    nested tileset and re-enumerate it against its own ``resolved_path``.
    """
    root = _get_value(tileset, "root")
    results: list[HonuaTilesetContent] = []
    _walk_tileset_node(root, base_path, results, set())
    return tuple(results)


# ---------------------------------------------------------------------------
# Offline scene-package build models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HonuaScenePackageBuildAsset:
    """A downloaded asset (tileset, tile content, or metadata) plus its bytes.

    Pairs the manifest :class:`HonuaScenePackageAsset` entry (key, type, path,
    size, SHA-256) with the raw ``content`` so callers can write the bundle to
    disk, a zip, or any offline store.
    """

    asset: HonuaScenePackageAsset
    content: bytes


@dataclass(frozen=True)
class HonuaScenePackageBuildResult:
    """Result of bundling a scene's tileset + tiles into an offline package.

    Combines a generated :class:`HonuaScenePackageManifest` with the downloaded
    asset bytes. The manifest validates (via
    :meth:`HonuaScenePackageManifest.validate`) against the
    ``honua.scene-package.v1`` schema so the produced bundle round-trips through
    the same reader used by offline runtimes.
    """

    manifest: HonuaScenePackageManifest
    assets: tuple[HonuaScenePackageBuildAsset, ...]

    @property
    def total_bytes(self) -> int:
        return sum(len(item.content) for item in self.assets)

    def asset_for(self, key: str) -> HonuaScenePackageBuildAsset | None:
        lowered = key.strip().lower()
        for item in self.assets:
            if item.asset.key and item.asset.key.lower() == lowered:
                return item
        return None


_SCENE_METADATA_KEY = "scene-metadata"
_TILESET_KEY = "tileset"


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _scene_metadata_bytes(scene: HonuaSceneMetadata) -> bytes:
    document = scene.raw_response or {"id": scene.id, "name": scene.name}
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _initial_tileset_queue(tileset_bytes: bytes) -> list[HonuaTilesetContent]:
    try:
        document = json.loads(tileset_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HonuaSceneError("Scene tileset.json was malformed.") from exc
    if not isinstance(document, Mapping):
        raise HonuaSceneError("Scene tileset.json did not contain an object.")
    return list(enumerate_tileset_contents(document, base_path="tileset.json"))


def _tile_asset_type(content: HonuaTilesetContent) -> str:
    if content.is_tileset:
        return HonuaScenePackageAssetTypes.THREE_D_TILESET
    return HonuaScenePackageAssetTypes.THREE_D_TILE_CONTENT


def _tile_asset_key(resolved_path: str) -> str:
    return urlsplit(resolved_path).path or resolved_path


def _tile_build_asset(content: HonuaTilesetContent, payload: bytes) -> HonuaScenePackageBuildAsset:
    path = urlsplit(content.resolved_path).path or content.resolved_path
    return HonuaScenePackageBuildAsset(
        asset=_build_manifest_asset(
            key=_tile_asset_key(content.resolved_path),
            asset_type=_tile_asset_type(content),
            path=path,
            content=payload,
        ),
        content=payload,
    )


def _content_type_for_path(path: str) -> str:
    lowered = urlsplit(path).path.lower()
    if lowered.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


def _build_manifest_asset(
    *,
    key: str,
    asset_type: str,
    path: str,
    content: bytes,
    role: str | None = None,
    required: bool = False,
) -> HonuaScenePackageAsset:
    return HonuaScenePackageAsset(
        key=key,
        type=asset_type,
        role=role,
        path=path,
        content_type=_content_type_for_path(path),
        bytes=len(content),
        sha256=_sha256_hex(content),
        required=required,
    )


def _assemble_scene_package(
    *,
    scene: HonuaSceneMetadata,
    scene_metadata_bytes: bytes,
    tileset_bytes: bytes,
    tile_assets: Sequence[HonuaScenePackageBuildAsset],
    package_id: str,
    edition_gate: str,
    server_revision: str,
    created_at_utc: datetime,
    stale_after_utc: datetime,
    offline_use_expires_at_utc: datetime,
    auth_expires_at_utc: datetime | None,
    max_package_bytes: int | None,
) -> HonuaScenePackageBuildResult:
    metadata_asset = HonuaScenePackageBuildAsset(
        asset=_build_manifest_asset(
            key=_SCENE_METADATA_KEY,
            asset_type=HonuaScenePackageAssetTypes.SCENE_METADATA,
            path="scene.json",
            content=scene_metadata_bytes,
            role="scene-metadata",
            required=True,
        ),
        content=scene_metadata_bytes,
    )
    tileset_asset = HonuaScenePackageBuildAsset(
        asset=_build_manifest_asset(
            key=_TILESET_KEY,
            asset_type=HonuaScenePackageAssetTypes.THREE_D_TILESET,
            path="tileset.json",
            content=tileset_bytes,
            role="primary-tileset",
            required=True,
        ),
        content=tileset_bytes,
    )
    assets: list[HonuaScenePackageBuildAsset] = [metadata_asset, tileset_asset, *tile_assets]

    declared_bytes = sum(len(item.content) for item in assets)
    budget = HonuaScenePackageByteBudget(
        max_package_bytes=max_package_bytes if max_package_bytes is not None else declared_bytes,
        declared_bytes=declared_bytes,
    )
    manifest = HonuaScenePackageManifest(
        schema_version=CURRENT_PACKAGE_SCHEMA_VERSION,
        package_id=package_id,
        scene_id=scene.id,
        display_name=scene.name,
        edition_gate=edition_gate,
        server_revision=server_revision,
        created_at_utc=created_at_utc,
        stale_after_utc=stale_after_utc,
        offline_use_expires_at_utc=offline_use_expires_at_utc,
        auth_expires_at_utc=auth_expires_at_utc,
        extent=scene.bounds,
        lod=HonuaScenePackageLod(min_zoom=0, max_zoom=0),
        byte_budget=budget,
        attribution=scene.attribution,
        assets=tuple(item.asset for item in assets),
    )
    return HonuaScenePackageBuildResult(manifest=manifest, assets=tuple(assets))


_DEFAULT_PACKAGE_TTL_DAYS = 30
_DEFAULT_STALE_FRACTION = 0.5


@dataclass(frozen=True)
class _PackageBuildContext:
    """Resolved, transport-independent inputs for building an offline package."""

    package_id: str
    edition_gate: str
    server_revision: str
    created_at_utc: datetime
    stale_after_utc: datetime
    offline_use_expires_at_utc: datetime
    auth_expires_at_utc: datetime | None
    max_package_bytes: int | None
    max_tilesets: int


def _resolve_package_context(
    scene_id: str,
    *,
    package_id: str | None,
    edition_gate: str,
    server_revision: str | None,
    created_at_utc: datetime | None,
    stale_after_utc: datetime | None,
    offline_use_expires_at_utc: datetime | None,
    auth_expires_at_utc: datetime | None,
    max_package_bytes: int | None,
    max_tilesets: int,
) -> _PackageBuildContext:
    if not HonuaScenePackageEditionGates.is_supported(edition_gate):
        raise ValueError(f"Unsupported scene package edition gate '{edition_gate}'.")
    if max_tilesets <= 0:
        raise ValueError("max_tilesets must be positive.")
    created = created_at_utc or datetime.now(tz=UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    expires = offline_use_expires_at_utc or (created + timedelta(days=_DEFAULT_PACKAGE_TTL_DAYS))
    stale = stale_after_utc or (created + (expires - created) * _DEFAULT_STALE_FRACTION)
    return _PackageBuildContext(
        package_id=package_id or f"pkg_{_require_scene_id(scene_id)}_{int(created.timestamp())}",
        edition_gate=edition_gate,
        server_revision=server_revision or created.strftime("%Y%m%d%H%M%S"),
        created_at_utc=created,
        stale_after_utc=stale,
        offline_use_expires_at_utc=expires,
        auth_expires_at_utc=auth_expires_at_utc,
        max_package_bytes=max_package_bytes,
        max_tilesets=max_tilesets,
    )


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

_DEFAULT_SCENE_ROOT = "/api/scenes"
_DEFAULT_TILESET_ROOT = "/scenes"
_DEFAULT_ELEVATION_ROOT = "/elevation"


def _require_scene_id(scene_id: str) -> str:
    if not scene_id or not scene_id.strip():
        raise ValueError("Scene id is required.")
    return scene_id.strip()


def _require_dataset_id(dataset_id: str) -> str:
    if not dataset_id or not dataset_id.strip():
        raise ValueError("Dataset id is required.")
    return dataset_id.strip()


def _tileset_path(scene_id: str) -> str:
    return f"{_DEFAULT_TILESET_ROOT}/{_encode_path_segment(scene_id)}/tileset.json"


def _scene_asset_path(scene_id: str, asset_path: str) -> str:
    cleaned = asset_path.strip()
    if not cleaned:
        raise ValueError("Scene asset path is required.")
    query = ""
    split = urlsplit(cleaned)
    if split.query:
        query = f"?{split.query}"
        cleaned = split.path
    segments = "/".join(_encode_path_segment(segment) for segment in cleaned.split("/") if segment)
    return f"{_DEFAULT_TILESET_ROOT}/{_encode_path_segment(scene_id)}/{segments}{query}"


class SceneClient(_SyncProtocol):
    """Synchronous Honua scene metadata discovery + render-endpoint resolution.

    Reach this via :meth:`HonuaClient.scenes`. Use it to list scenes, fetch a
    single scene's metadata (tileset/terrain endpoints, 3D extent incl.
    min/max height, suggested camera center, capabilities), and resolve
    render-ready tileset/terrain URLs. This is a data-access client; it does
    not render 3D content.
    """

    root = _DEFAULT_SCENE_ROOT

    def list_scenes(
        self,
        *,
        capabilities: Sequence[str] | None = None,
        include_disabled: bool | None = None,
        response_format: str = "json",
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[HonuaSceneSummary]:
        params = _scene_list_params(capabilities, include_disabled, response_format, extra_params)
        response = self._json("GET", self.root, params=params, timeout=timeout, extra_headers=extra_headers)
        return [parse_scene_summary(item) for item in _enumerate_scene_items(response)]

    def get_scene(
        self,
        scene_id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HonuaSceneMetadata:
        resolved = _require_scene_id(scene_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}"
        response = self._json("GET", path, params={"f": "json"}, timeout=timeout, extra_headers=extra_headers)
        return parse_scene_metadata(response)

    def resolve_scene(
        self,
        scene_id: str,
        *,
        required_capabilities: Sequence[str] | None = None,
        include_terrain: bool = True,
        response_format: str = "json",
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HonuaSceneResolution:
        resolved = _require_scene_id(scene_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}/resolve"
        params = _scene_resolve_params(required_capabilities, include_terrain, response_format, extra_params)
        response = self._json("GET", path, params=params, timeout=timeout, extra_headers=extra_headers)
        resolution = parse_scene_resolution(response, resolved)
        _ensure_capabilities(resolution.scene_id, resolution.capabilities, required_capabilities)
        return resolution

    def get_tileset(
        self,
        scene_id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Fetch a scene's root ``tileset.json`` (3D Tiles) document.

        Returns the parsed JSON document. Use :func:`enumerate_tileset_contents`
        to walk its content references.
        """
        resolved = _require_scene_id(scene_id)
        return self._json(
            "GET", _tileset_path(resolved), timeout=timeout, extra_headers=extra_headers
        )

    def fetch_tile(
        self,
        scene_id: str,
        asset_path: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> BinaryResponse:
        """Fetch a single scene asset (tile content or nested tileset) by path.

        ``asset_path`` is the package-relative path of the asset (e.g.
        ``"tiles/0.b3dm"`` or ``"sub/tileset.json"``), typically a
        :attr:`HonuaTilesetContent.resolved_path` from
        :func:`enumerate_tileset_contents`. Returns the raw bytes plus the
        selected HTTP cache/ETag metadata.
        """
        resolved = _require_scene_id(scene_id)
        return self._binary_response(
            _scene_asset_path(resolved, asset_path), timeout=timeout, extra_headers=extra_headers
        )

    def build_offline_package(
        self,
        scene_id: str,
        *,
        edition_gate: str = HonuaScenePackageEditionGates.COMMUNITY,
        package_id: str | None = None,
        server_revision: str | None = None,
        created_at_utc: datetime | None = None,
        stale_after_utc: datetime | None = None,
        offline_use_expires_at_utc: datetime | None = None,
        auth_expires_at_utc: datetime | None = None,
        max_package_bytes: int | None = None,
        max_tilesets: int = 64,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HonuaScenePackageBuildResult:
        """Bundle a scene's metadata, tileset, and tiles into an offline package.

        Fetches the scene metadata and root ``tileset.json``, walks the tileset
        (recursing into nested external tilesets up to ``max_tilesets``),
        downloads every referenced tile/content asset, and produces a
        ``honua.scene-package.v1`` :class:`HonuaScenePackageManifest` (with
        per-asset SHA-256 + byte sizes) alongside the downloaded bytes. The
        result validates against :meth:`HonuaScenePackageManifest.validate`.
        """
        resolved = _require_scene_id(scene_id)
        context = _resolve_package_context(
            resolved,
            package_id=package_id,
            edition_gate=edition_gate,
            server_revision=server_revision,
            created_at_utc=created_at_utc,
            stale_after_utc=stale_after_utc,
            offline_use_expires_at_utc=offline_use_expires_at_utc,
            auth_expires_at_utc=auth_expires_at_utc,
            max_package_bytes=max_package_bytes,
            max_tilesets=max_tilesets,
        )

        scene = self.get_scene(resolved, timeout=timeout, extra_headers=extra_headers)
        scene_metadata_bytes = _scene_metadata_bytes(scene)

        tileset_response = self.fetch_tile(
            resolved, "tileset.json", timeout=timeout, extra_headers=extra_headers
        )
        tileset_bytes = tileset_response.content

        tile_assets: list[HonuaScenePackageBuildAsset] = []
        seen_paths: set[str] = set()
        pending = _initial_tileset_queue(tileset_bytes)
        processed_tilesets = 1
        while pending:
            content = pending.pop(0)
            if content.resolved_path in seen_paths:
                continue
            seen_paths.add(content.resolved_path)
            response = self.fetch_tile(
                resolved, content.resolved_path, timeout=timeout, extra_headers=extra_headers
            )
            tile_assets.append(_tile_build_asset(content, response.content))
            if content.is_tileset and processed_tilesets < context.max_tilesets:
                processed_tilesets += 1
                pending.extend(
                    enumerate_tileset_contents(
                        json.loads(response.content.decode("utf-8")),
                        base_path=content.resolved_path,
                    )
                )

        return _assemble_scene_package(
            scene=scene,
            scene_metadata_bytes=scene_metadata_bytes,
            tileset_bytes=tileset_bytes,
            tile_assets=tile_assets,
            package_id=context.package_id,
            edition_gate=context.edition_gate,
            server_revision=context.server_revision,
            created_at_utc=context.created_at_utc,
            stale_after_utc=context.stale_after_utc,
            offline_use_expires_at_utc=context.offline_use_expires_at_utc,
            auth_expires_at_utc=context.auth_expires_at_utc,
            max_package_bytes=context.max_package_bytes,
        )


class ElevationClient(_SyncProtocol):
    """Synchronous Honua elevation HTTP API wrapper.

    Reach this via :meth:`HonuaClient.elevation`. Mirrors the server
    ``/elevation/{datasetId}/value`` and ``/elevation/{datasetId}/profile``
    endpoints, returning typed :class:`ElevationValue` /
    :class:`ElevationProfile` models.
    """

    root = _DEFAULT_ELEVATION_ROOT

    def value(
        self,
        dataset_id: str,
        *,
        x: float,
        y: float,
        srid: str | int | None = None,
        mosaic_rule: str | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ElevationValue:
        resolved = _require_dataset_id(dataset_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}/value"
        params = _elevation_value_params(x, y, srid, mosaic_rule, extra_params)
        response = self._json("GET", path, params=params, timeout=timeout, extra_headers=extra_headers)
        return parse_elevation_value(response)

    def profile(
        self,
        dataset_id: str,
        *,
        line: str,
        sample_count: int | None = None,
        interval: float | None = None,
        srid: str | int | None = None,
        mosaic_rule: str | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ElevationProfile:
        resolved = _require_dataset_id(dataset_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}/profile"
        params = _elevation_profile_params(line, sample_count, interval, srid, mosaic_rule, extra_params)
        response = self._json("GET", path, params=params, timeout=timeout, extra_headers=extra_headers)
        return parse_elevation_profile(response)


class AsyncSceneClient(_AsyncProtocol):
    """Async Honua scene metadata discovery + render-endpoint resolution."""

    root = _DEFAULT_SCENE_ROOT

    async def list_scenes(
        self,
        *,
        capabilities: Sequence[str] | None = None,
        include_disabled: bool | None = None,
        response_format: str = "json",
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[HonuaSceneSummary]:
        params = _scene_list_params(capabilities, include_disabled, response_format, extra_params)
        response = await self._json("GET", self.root, params=params, timeout=timeout, extra_headers=extra_headers)
        return [parse_scene_summary(item) for item in _enumerate_scene_items(response)]

    async def get_scene(
        self,
        scene_id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HonuaSceneMetadata:
        resolved = _require_scene_id(scene_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}"
        response = await self._json("GET", path, params={"f": "json"}, timeout=timeout, extra_headers=extra_headers)
        return parse_scene_metadata(response)

    async def resolve_scene(
        self,
        scene_id: str,
        *,
        required_capabilities: Sequence[str] | None = None,
        include_terrain: bool = True,
        response_format: str = "json",
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HonuaSceneResolution:
        resolved = _require_scene_id(scene_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}/resolve"
        params = _scene_resolve_params(required_capabilities, include_terrain, response_format, extra_params)
        response = await self._json("GET", path, params=params, timeout=timeout, extra_headers=extra_headers)
        resolution = parse_scene_resolution(response, resolved)
        _ensure_capabilities(resolution.scene_id, resolution.capabilities, required_capabilities)
        return resolution

    async def get_tileset(
        self,
        scene_id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Fetch a scene's root ``tileset.json`` (3D Tiles) document."""
        resolved = _require_scene_id(scene_id)
        return await self._json(
            "GET", _tileset_path(resolved), timeout=timeout, extra_headers=extra_headers
        )

    async def fetch_tile(
        self,
        scene_id: str,
        asset_path: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> BinaryResponse:
        """Fetch a single scene asset (tile content or nested tileset) by path."""
        resolved = _require_scene_id(scene_id)
        return await self._binary_response(
            _scene_asset_path(resolved, asset_path), timeout=timeout, extra_headers=extra_headers
        )

    async def build_offline_package(
        self,
        scene_id: str,
        *,
        edition_gate: str = HonuaScenePackageEditionGates.COMMUNITY,
        package_id: str | None = None,
        server_revision: str | None = None,
        created_at_utc: datetime | None = None,
        stale_after_utc: datetime | None = None,
        offline_use_expires_at_utc: datetime | None = None,
        auth_expires_at_utc: datetime | None = None,
        max_package_bytes: int | None = None,
        max_tilesets: int = 64,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HonuaScenePackageBuildResult:
        """Bundle a scene's metadata, tileset, and tiles into an offline package.

        Async counterpart of :meth:`SceneClient.build_offline_package`.
        """
        resolved = _require_scene_id(scene_id)
        context = _resolve_package_context(
            resolved,
            package_id=package_id,
            edition_gate=edition_gate,
            server_revision=server_revision,
            created_at_utc=created_at_utc,
            stale_after_utc=stale_after_utc,
            offline_use_expires_at_utc=offline_use_expires_at_utc,
            auth_expires_at_utc=auth_expires_at_utc,
            max_package_bytes=max_package_bytes,
            max_tilesets=max_tilesets,
        )

        scene = await self.get_scene(resolved, timeout=timeout, extra_headers=extra_headers)
        scene_metadata_bytes = _scene_metadata_bytes(scene)

        tileset_response = await self.fetch_tile(
            resolved, "tileset.json", timeout=timeout, extra_headers=extra_headers
        )
        tileset_bytes = tileset_response.content

        tile_assets: list[HonuaScenePackageBuildAsset] = []
        seen_paths: set[str] = set()
        pending = _initial_tileset_queue(tileset_bytes)
        processed_tilesets = 1
        while pending:
            content = pending.pop(0)
            if content.resolved_path in seen_paths:
                continue
            seen_paths.add(content.resolved_path)
            response = await self.fetch_tile(
                resolved, content.resolved_path, timeout=timeout, extra_headers=extra_headers
            )
            tile_assets.append(_tile_build_asset(content, response.content))
            if content.is_tileset and processed_tilesets < context.max_tilesets:
                processed_tilesets += 1
                pending.extend(
                    enumerate_tileset_contents(
                        json.loads(response.content.decode("utf-8")),
                        base_path=content.resolved_path,
                    )
                )

        return _assemble_scene_package(
            scene=scene,
            scene_metadata_bytes=scene_metadata_bytes,
            tileset_bytes=tileset_bytes,
            tile_assets=tile_assets,
            package_id=context.package_id,
            edition_gate=context.edition_gate,
            server_revision=context.server_revision,
            created_at_utc=context.created_at_utc,
            stale_after_utc=context.stale_after_utc,
            offline_use_expires_at_utc=context.offline_use_expires_at_utc,
            auth_expires_at_utc=context.auth_expires_at_utc,
            max_package_bytes=context.max_package_bytes,
        )


class AsyncElevationClient(_AsyncProtocol):
    """Async Honua elevation HTTP API wrapper."""

    root = _DEFAULT_ELEVATION_ROOT

    async def value(
        self,
        dataset_id: str,
        *,
        x: float,
        y: float,
        srid: str | int | None = None,
        mosaic_rule: str | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ElevationValue:
        resolved = _require_dataset_id(dataset_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}/value"
        params = _elevation_value_params(x, y, srid, mosaic_rule, extra_params)
        response = await self._json("GET", path, params=params, timeout=timeout, extra_headers=extra_headers)
        return parse_elevation_value(response)

    async def profile(
        self,
        dataset_id: str,
        *,
        line: str,
        sample_count: int | None = None,
        interval: float | None = None,
        srid: str | int | None = None,
        mosaic_rule: str | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ElevationProfile:
        resolved = _require_dataset_id(dataset_id)
        path = f"{self.root}/{_encode_path_segment(resolved)}/profile"
        params = _elevation_profile_params(line, sample_count, interval, srid, mosaic_rule, extra_params)
        response = await self._json("GET", path, params=params, timeout=timeout, extra_headers=extra_headers)
        return parse_elevation_profile(response)

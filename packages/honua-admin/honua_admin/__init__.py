"""Honua Admin API client and data models.

Install with:  ``pip install honua-admin``
"""

from __future__ import annotations

try:
    from importlib.metadata import version as _meta_version

    __version__: str = _meta_version("honua-admin")
except Exception:  # pragma: no cover -- editable / not-installed fallback
    __version__ = "0.0.0.dev0"

from ._async_client import AsyncHonuaAdminClient
from ._client import HonuaAdminClient
from ._models import (
    AccessPolicyResponse,
    AdminCompatibilityBaseline,
    AdminCompatibilityCheckResult,
    AdminCompatibilityFeatureFlags,
    AdminCompatibilityMetadata,
    AdminCapabilitiesResponse,
    AdminControlPlaneApiCompatibility,
    AdminMetadataSchemaCompatibility,
    AdminVersionResponse,
    ColumnInfo,
    ConnectionTestResult,
    CreateSecureConnectionRequest,
    EncryptionValidationResult,
    KeyRotationResult,
    LayerStyleResponse,
    LayerStyleUpdateRequest,
    ManifestApplyEntry,
    ManifestApplyRequest,
    ManifestApplyResult,
    ManifestApplySummary,
    MapServerSettings,
    MetadataManifest,
    MetadataResource,
    MetadataResourceIdentifier,
    MINIMUM_SUPPORTED_SERVER_VERSION,
    PublishLayerRequest,
    PublishedLayerSummary,
    ResourceMetadata,
    SecureConnectionDetail,
    SecureConnectionSummary,
    ServiceSettingsResponse,
    ServiceSummary,
    TableDiscoveryResponse,
    TableInfo,
    TimeInfoResponse,
    UpdateSecureConnectionRequest,
    MINIMUM_SUPPORTED_CONTROL_PLANE_API_MAJOR,
    MINIMUM_SUPPORTED_CONTROL_PLANE_BASE_PATH,
    MINIMUM_SUPPORTED_SERVER_RELEASE_CHANNEL,
)

__all__ = [
    "__version__",
    "AccessPolicyResponse",
    "AdminCompatibilityBaseline",
    "AdminCompatibilityCheckResult",
    "AdminCompatibilityFeatureFlags",
    "AdminCompatibilityMetadata",
    "AdminCapabilitiesResponse",
    "AdminControlPlaneApiCompatibility",
    "AdminMetadataSchemaCompatibility",
    "AdminVersionResponse",
    "ColumnInfo",
    "ConnectionTestResult",
    "CreateSecureConnectionRequest",
    "EncryptionValidationResult",
    "AsyncHonuaAdminClient",
    "HonuaAdminClient",
    "KeyRotationResult",
    "LayerStyleResponse",
    "LayerStyleUpdateRequest",
    "ManifestApplyEntry",
    "ManifestApplyRequest",
    "ManifestApplyResult",
    "ManifestApplySummary",
    "MapServerSettings",
    "MetadataManifest",
    "MetadataResource",
    "MetadataResourceIdentifier",
    "MINIMUM_SUPPORTED_SERVER_VERSION",
    "MINIMUM_SUPPORTED_CONTROL_PLANE_API_MAJOR",
    "MINIMUM_SUPPORTED_CONTROL_PLANE_BASE_PATH",
    "MINIMUM_SUPPORTED_SERVER_RELEASE_CHANNEL",
    "PublishLayerRequest",
    "PublishedLayerSummary",
    "ResourceMetadata",
    "SecureConnectionDetail",
    "SecureConnectionSummary",
    "ServiceSettingsResponse",
    "ServiceSummary",
    "TableDiscoveryResponse",
    "TableInfo",
    "TimeInfoResponse",
    "UpdateSecureConnectionRequest",
]

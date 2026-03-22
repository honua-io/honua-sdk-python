"""Data models for the Honua Admin API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any

MINIMUM_SUPPORTED_SERVER_VERSION = "2026.3.0"
MINIMUM_SUPPORTED_CONTROL_PLANE_API_MAJOR = 1
MINIMUM_SUPPORTED_CONTROL_PLANE_BASE_PATH = "/api/v1/admin"
MINIMUM_SUPPORTED_SERVER_RELEASE_CHANNEL = "preview"

_RELEASE_CHANNEL_ORDER = {
    "nightly": 0,
    "dev": 1,
    "alpha": 2,
    "preview": 3,
    "beta": 4,
    "rc": 5,
    "stable": 6,
    "lts": 7,
}

_VERSION_COMPONENT_PATTERN = re.compile(r"\d+")


def _to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _snake_keys(d: dict[str, Any]) -> dict[str, Any]:
    """Convert top-level dict keys from camelCase to snake_case."""
    return {_to_snake(k): v for k, v in d.items()}


def _camel_keys(d: dict[str, Any]) -> dict[str, Any]:
    """Convert top-level dict keys from snake_case to camelCase."""
    return {_to_camel(k): v for k, v in d.items()}


def _extract_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Extract only the fields that exist on *cls* from a snake-cased dict."""
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in valid}


def _parse_version_components(version: str | None) -> tuple[int, int, int] | None:
    """Parse a coarse version tuple from semver- or calver-like version strings."""
    if not version:
        return None
    parts = [int(part) for part in _VERSION_COMPONENT_PATTERN.findall(version)]
    if len(parts) < 3:
        return None
    return tuple(parts[:3])


# ---------------------------------------------------------------------------
# Response models (frozen)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServiceSummary:
    service_name: str
    description: str | None
    layer_count: int
    enabled_protocols: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceSummary:
        d = _snake_keys(data)
        d.setdefault("enabled_protocols", [])
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class AccessPolicyResponse:
    allow_anonymous: bool
    allow_anonymous_write: bool
    allowed_roles: list[str]
    allowed_write_roles: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccessPolicyResponse:
        d = _snake_keys(data)
        d.setdefault("allowed_roles", [])
        d.setdefault("allowed_write_roles", [])
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class TimeInfoResponse:
    start_time_field: str | None
    end_time_field: str | None
    track_id_field: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeInfoResponse:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class MapServerSettings:
    max_image_width: int
    max_image_height: int
    default_image_width: int
    default_image_height: int
    default_dpi: int
    default_format: str
    default_transparent: bool
    max_features_per_layer: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MapServerSettings:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class ServiceSettingsResponse:
    service_name: str
    enabled_protocols: list[str]
    available_protocols: list[str]
    access_policy: AccessPolicyResponse | None
    time_info: TimeInfoResponse | None
    map_server: MapServerSettings | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceSettingsResponse:
        d = _snake_keys(data)
        d.setdefault("enabled_protocols", [])
        d.setdefault("available_protocols", [])
        ap = d.get("access_policy")
        ti = d.get("time_info")
        ms = d.get("map_server")
        d["access_policy"] = AccessPolicyResponse.from_dict(ap) if isinstance(ap, dict) else None
        d["time_info"] = TimeInfoResponse.from_dict(ti) if isinstance(ti, dict) else None
        d["map_server"] = MapServerSettings.from_dict(ms) if isinstance(ms, dict) else None
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class SecureConnectionSummary:
    connection_id: str
    name: str
    description: str | None
    host: str
    port: int
    database_name: str
    username: str
    ssl_required: bool
    ssl_mode: str | None
    storage_type: str | None
    is_active: bool
    health_status: str | None
    last_health_check: str | None
    created_at: str | None
    created_by: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecureConnectionSummary:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class SecureConnectionDetail:
    connection_id: str
    name: str
    description: str | None
    host: str
    port: int
    database_name: str
    username: str
    ssl_required: bool
    ssl_mode: str | None
    storage_type: str | None
    is_active: bool
    health_status: str | None
    last_health_check: str | None
    created_at: str | None
    created_by: str | None
    credential_reference: str | None
    encryption_version: int | None
    updated_at: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecureConnectionDetail:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    connection_id: str | None
    connection_name: str | None
    is_healthy: bool
    tested_at: str | None
    message: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionTestResult:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class EncryptionValidationResult:
    is_valid: bool
    current_key_version: int | None
    validated_at: str | None
    message: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EncryptionValidationResult:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class KeyRotationResult:
    previous_key_version: int | None
    new_key_version: int | None
    rotated_at: str | None
    message: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyRotationResult:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class ResourceMetadata:
    id: str | None
    name: str
    namespace: str
    labels: dict[str, str]
    annotations: dict[str, str]
    resource_version: str | None
    generation: int | None
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceMetadata:
        d = _snake_keys(data)
        d.setdefault("id", None)
        d.setdefault("labels", {})
        d.setdefault("annotations", {})
        d.setdefault("resource_version", None)
        d.setdefault("generation", None)
        d.setdefault("created_at", None)
        d.setdefault("updated_at", None)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class MetadataResource:
    api_version: str
    kind: str
    metadata: ResourceMetadata
    spec: dict[str, Any]
    status: dict[str, Any] | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetadataResource:
        d = _snake_keys(data)
        md = d.get("metadata")
        d["metadata"] = ResourceMetadata.from_dict(md) if isinstance(md, dict) else md
        d.setdefault("spec", {})
        d.setdefault("status", None)
        return cls(**_extract_fields(cls, d))

    def to_dict(self) -> dict[str, Any]:
        """Serialise back to camelCase dict for API requests."""
        md = self.metadata
        meta_dict: dict[str, Any] = {
            "name": md.name,
            "namespace": md.namespace,
            "labels": md.labels,
            "annotations": md.annotations,
        }
        if md.id is not None:
            meta_dict["id"] = md.id
        if md.resource_version is not None:
            meta_dict["resourceVersion"] = md.resource_version
        if md.generation is not None:
            meta_dict["generation"] = md.generation
        if md.created_at is not None:
            meta_dict["createdAt"] = md.created_at
        if md.updated_at is not None:
            meta_dict["updatedAt"] = md.updated_at

        result: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": meta_dict,
            "spec": self.spec,
        }
        if self.status is not None:
            result["status"] = self.status
        return result


@dataclass(frozen=True, slots=True)
class MetadataResourceIdentifier:
    kind: str
    namespace: str
    name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetadataResourceIdentifier:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class ManifestApplySummary:
    created: int
    updated: int
    deleted: int
    skipped: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestApplySummary:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class ManifestApplyEntry:
    action: str
    resource: MetadataResourceIdentifier
    message: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestApplyEntry:
        d = _snake_keys(data)
        res = d.get("resource")
        d["resource"] = MetadataResourceIdentifier.from_dict(res) if isinstance(res, dict) else res
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class ManifestApplyResult:
    dry_run: bool
    summary: ManifestApplySummary
    entries: list[ManifestApplyEntry]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestApplyResult:
        d = _snake_keys(data)
        s = d.get("summary")
        d["summary"] = ManifestApplySummary.from_dict(s) if isinstance(s, dict) else s
        raw_entries = d.get("entries", [])
        d["entries"] = [ManifestApplyEntry.from_dict(e) for e in raw_entries]
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class MetadataManifest:
    api_version: str
    generated_at: str | None
    resources: list[MetadataResource]
    drifted_resources: list[MetadataResourceIdentifier]
    manifest_hash: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetadataManifest:
        d = _snake_keys(data)
        raw_res = d.get("resources", [])
        d["resources"] = [MetadataResource.from_dict(r) for r in raw_res]
        raw_drifted = d.get("drifted_resources", [])
        d["drifted_resources"] = [MetadataResourceIdentifier.from_dict(r) for r in raw_drifted]
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class AdminVersionResponse:
    version: str
    metadata_api_version: str
    server_time: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminVersionResponse:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class AdminCapabilitiesResponse:
    metadata_api_versions: list[str] = field(default_factory=list)
    resource_kinds: list[str] = field(default_factory=list)
    manifest_supported: bool = False
    manifest_dry_run_supported: bool = False
    manifest_prune_supported: bool = False
    compatibility: AdminCompatibilityMetadata | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminCapabilitiesResponse:
        d = _snake_keys(data)
        d.setdefault("metadata_api_versions", [])
        d.setdefault("resource_kinds", [])
        d.setdefault("manifest_supported", False)
        d.setdefault("manifest_dry_run_supported", False)
        d.setdefault("manifest_prune_supported", False)
        compatibility = d.get("compatibility")
        d["compatibility"] = (
            AdminCompatibilityMetadata.from_dict(compatibility)
            if isinstance(compatibility, dict)
            else None
        )
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class AdminControlPlaneApiCompatibility:
    major: int = 0
    base_path: str = ""
    deprecated: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminControlPlaneApiCompatibility:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class AdminMetadataSchemaCompatibility:
    version: str
    deprecated: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminMetadataSchemaCompatibility:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class AdminCompatibilityFeatureFlags:
    metadata_resources: bool = False
    manifest_export: bool = False
    manifest_apply: bool = False
    manifest_dry_run: bool = False
    manifest_prune: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminCompatibilityFeatureFlags:
        d = _snake_keys(data)
        d.setdefault("metadata_resources", False)
        d.setdefault("manifest_export", False)
        d.setdefault("manifest_apply", False)
        d.setdefault("manifest_dry_run", False)
        d.setdefault("manifest_prune", False)
        return cls(**_extract_fields(cls, d))

    def supports(self, feature: str) -> bool:
        return bool(getattr(self, _to_snake(feature).replace("-", "_"), False))


@dataclass(frozen=True, slots=True)
class AdminCompatibilityMetadata:
    server_version: str = ""
    release_channel: str = ""
    control_plane_api: AdminControlPlaneApiCompatibility = field(
        default_factory=AdminControlPlaneApiCompatibility
    )
    metadata_schemas: list[AdminMetadataSchemaCompatibility] = field(default_factory=list)
    features: AdminCompatibilityFeatureFlags = field(default_factory=AdminCompatibilityFeatureFlags)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminCompatibilityMetadata:
        d = _snake_keys(data)
        control_plane_api = d.get("control_plane_api")
        metadata_schemas = d.get("metadata_schemas", [])
        features = d.get("features")
        d["control_plane_api"] = (
            AdminControlPlaneApiCompatibility.from_dict(control_plane_api)
            if isinstance(control_plane_api, dict)
            else AdminControlPlaneApiCompatibility(
                major=0,
                base_path="",
                deprecated=False,
            )
        )
        d["metadata_schemas"] = [
            AdminMetadataSchemaCompatibility.from_dict(item)
            for item in metadata_schemas
            if isinstance(item, dict)
        ]
        d["features"] = (
            AdminCompatibilityFeatureFlags.from_dict(features)
            if isinstance(features, dict)
            else AdminCompatibilityFeatureFlags(
                metadata_resources=False,
                manifest_export=False,
                manifest_apply=False,
                manifest_dry_run=False,
                manifest_prune=False,
            )
        )
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class AdminCompatibilityBaseline:
    minimum_server_version: str = MINIMUM_SUPPORTED_SERVER_VERSION
    control_plane_api_major: int = MINIMUM_SUPPORTED_CONTROL_PLANE_API_MAJOR
    base_path: str = MINIMUM_SUPPORTED_CONTROL_PLANE_BASE_PATH
    minimum_release_channel: str = MINIMUM_SUPPORTED_SERVER_RELEASE_CHANNEL


@dataclass(frozen=True, slots=True)
class AdminCompatibilityCheckResult:
    supported: bool
    baseline: AdminCompatibilityBaseline
    compatibility: AdminCompatibilityMetadata | None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def get_release_channel_rank(channel: str | None) -> int | None:
    if channel is None:
        return None
    return _RELEASE_CHANNEL_ORDER.get(channel.lower())


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    max_length: int | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColumnInfo:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class TableInfo:
    schema: str
    table: str
    geometry_column: str | None
    geometry_type: str | None
    srid: int | None
    estimated_rows: int | None
    columns: list[ColumnInfo]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableInfo:
        d = _snake_keys(data)
        raw_cols = d.get("columns", [])
        d["columns"] = [ColumnInfo.from_dict(c) for c in raw_cols]
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class TableDiscoveryResponse:
    tables: list[TableInfo]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableDiscoveryResponse:
        d = _snake_keys(data)
        raw_tables = d.get("tables", [])
        d["tables"] = [TableInfo.from_dict(t) for t in raw_tables]
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class PublishedLayerSummary:
    layer_id: int
    layer_name: str
    schema: str
    table: str
    description: str | None
    geometry_type: str | None
    srid: int | None
    primary_key: str | None
    field_count: int
    enabled: bool
    service_name: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublishedLayerSummary:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


@dataclass(frozen=True, slots=True)
class LayerStyleResponse:
    map_libre_style: dict[str, Any] | None
    drawing_info: dict[str, Any] | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayerStyleResponse:
        d = _snake_keys(data)
        return cls(**_extract_fields(cls, d))


# ---------------------------------------------------------------------------
# Request models (mutable)
# ---------------------------------------------------------------------------


@dataclass
class CreateSecureConnectionRequest:
    name: str
    description: str | None = None
    host: str = ""
    port: int = 5432
    database_name: str = ""
    username: str = ""
    password: str | None = field(default=None, repr=False)
    secret_reference: str | None = None
    secret_type: str | None = None
    ssl_required: bool = False
    ssl_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if val is not None:
                d[_to_camel(f.name)] = val
        return d


@dataclass
class UpdateSecureConnectionRequest:
    description: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    ssl_required: bool | None = None
    ssl_mode: str | None = None
    is_active: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if val is not None:
                d[_to_camel(f.name)] = val
        return d


@dataclass
class PublishLayerRequest:
    schema: str = "public"
    table: str = ""
    layer_name: str | None = None
    description: str | None = None
    geometry_column: str | None = None
    geometry_type: str | None = None
    srid: int | None = None
    primary_key: str | None = None
    fields_list: list[str] | None = None
    service_name: str | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if val is not None:
                key = f.name
                # Map fields_list back to "fields" in the API
                if key == "fields_list":
                    key = "fields"
                d[_to_camel(key)] = val
        return d


@dataclass
class ManifestApplyRequest:
    resources: list[MetadataResource] = field(default_factory=list)
    dry_run: bool = False
    prune: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "resources": [r.to_dict() for r in self.resources],
            "dryRun": self.dry_run,
            "prune": self.prune,
        }


@dataclass
class LayerStyleUpdateRequest:
    map_libre_style: dict[str, Any] | None = None
    drawing_info: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.map_libre_style is not None:
            d["mapLibreStyle"] = self.map_libre_style
        if self.drawing_info is not None:
            d["drawingInfo"] = self.drawing_info
        return d

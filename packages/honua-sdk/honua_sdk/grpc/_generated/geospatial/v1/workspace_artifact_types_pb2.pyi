from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WorkspaceLifecycle(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WORKSPACE_LIFECYCLE_UNSPECIFIED: _ClassVar[WorkspaceLifecycle]
    WORKSPACE_LIFECYCLE_DRAFT: _ClassVar[WorkspaceLifecycle]
    WORKSPACE_LIFECYCLE_ACTIVE: _ClassVar[WorkspaceLifecycle]
    WORKSPACE_LIFECYCLE_PROMOTED: _ClassVar[WorkspaceLifecycle]
    WORKSPACE_LIFECYCLE_RETAINED: _ClassVar[WorkspaceLifecycle]
    WORKSPACE_LIFECYCLE_RELEASED: _ClassVar[WorkspaceLifecycle]
    WORKSPACE_LIFECYCLE_EXPIRED: _ClassVar[WorkspaceLifecycle]

class PromotionStage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PROMOTION_STAGE_UNSPECIFIED: _ClassVar[PromotionStage]
    PROMOTION_STAGE_DRAFT: _ClassVar[PromotionStage]
    PROMOTION_STAGE_REVIEW: _ClassVar[PromotionStage]
    PROMOTION_STAGE_STAGING: _ClassVar[PromotionStage]
    PROMOTION_STAGE_PRODUCTION: _ClassVar[PromotionStage]
    PROMOTION_STAGE_ARCHIVED: _ClassVar[PromotionStage]

class MaterializationState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MATERIALIZATION_STATE_UNSPECIFIED: _ClassVar[MaterializationState]
    MATERIALIZATION_STATE_PENDING: _ClassVar[MaterializationState]
    MATERIALIZATION_STATE_MATERIALIZING: _ClassVar[MaterializationState]
    MATERIALIZATION_STATE_MATERIALIZED: _ClassVar[MaterializationState]
    MATERIALIZATION_STATE_EXPIRED: _ClassVar[MaterializationState]
    MATERIALIZATION_STATE_FAILED: _ClassVar[MaterializationState]
WORKSPACE_LIFECYCLE_UNSPECIFIED: WorkspaceLifecycle
WORKSPACE_LIFECYCLE_DRAFT: WorkspaceLifecycle
WORKSPACE_LIFECYCLE_ACTIVE: WorkspaceLifecycle
WORKSPACE_LIFECYCLE_PROMOTED: WorkspaceLifecycle
WORKSPACE_LIFECYCLE_RETAINED: WorkspaceLifecycle
WORKSPACE_LIFECYCLE_RELEASED: WorkspaceLifecycle
WORKSPACE_LIFECYCLE_EXPIRED: WorkspaceLifecycle
PROMOTION_STAGE_UNSPECIFIED: PromotionStage
PROMOTION_STAGE_DRAFT: PromotionStage
PROMOTION_STAGE_REVIEW: PromotionStage
PROMOTION_STAGE_STAGING: PromotionStage
PROMOTION_STAGE_PRODUCTION: PromotionStage
PROMOTION_STAGE_ARCHIVED: PromotionStage
MATERIALIZATION_STATE_UNSPECIFIED: MaterializationState
MATERIALIZATION_STATE_PENDING: MaterializationState
MATERIALIZATION_STATE_MATERIALIZING: MaterializationState
MATERIALIZATION_STATE_MATERIALIZED: MaterializationState
MATERIALIZATION_STATE_EXPIRED: MaterializationState
MATERIALIZATION_STATE_FAILED: MaterializationState

class WorkspaceRef(_message.Message):
    __slots__ = ("workspace_id", "workspace_revision", "scope_token")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_REVISION_FIELD_NUMBER: _ClassVar[int]
    SCOPE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    workspace_revision: str
    scope_token: str
    def __init__(self, workspace_id: _Optional[str] = ..., workspace_revision: _Optional[str] = ..., scope_token: _Optional[str] = ...) -> None: ...

class RetentionPolicyRef(_message.Message):
    __slots__ = ("retention_policy_id", "retention_policy_revision")
    RETENTION_POLICY_ID_FIELD_NUMBER: _ClassVar[int]
    RETENTION_POLICY_REVISION_FIELD_NUMBER: _ClassVar[int]
    retention_policy_id: str
    retention_policy_revision: str
    def __init__(self, retention_policy_id: _Optional[str] = ..., retention_policy_revision: _Optional[str] = ...) -> None: ...

class QuotaSpec(_message.Message):
    __slots__ = ("max_bytes", "max_artifacts", "soft_ttl_seconds", "hard_ttl_seconds")
    MAX_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    SOFT_TTL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    HARD_TTL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    max_bytes: int
    max_artifacts: int
    soft_ttl_seconds: int
    hard_ttl_seconds: int
    def __init__(self, max_bytes: _Optional[int] = ..., max_artifacts: _Optional[int] = ..., soft_ttl_seconds: _Optional[int] = ..., hard_ttl_seconds: _Optional[int] = ...) -> None: ...

class QuotaUsage(_message.Message):
    __slots__ = ("used_bytes", "used_artifacts", "bytes_available", "artifacts_available")
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    USED_ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    BYTES_AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    used_bytes: int
    used_artifacts: int
    bytes_available: int
    artifacts_available: int
    def __init__(self, used_bytes: _Optional[int] = ..., used_artifacts: _Optional[int] = ..., bytes_available: _Optional[int] = ..., artifacts_available: _Optional[int] = ...) -> None: ...

class RetentionPolicy(_message.Message):
    __slots__ = ("ref", "display_name", "min_retention_seconds", "max_retention_seconds", "immutable_after_publish", "legal_hold", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    REF_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    MIN_RETENTION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    MAX_RETENTION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    IMMUTABLE_AFTER_PUBLISH_FIELD_NUMBER: _ClassVar[int]
    LEGAL_HOLD_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    ref: RetentionPolicyRef
    display_name: str
    min_retention_seconds: int
    max_retention_seconds: int
    immutable_after_publish: bool
    legal_hold: bool
    labels: _containers.ScalarMap[str, str]
    def __init__(self, ref: _Optional[_Union[RetentionPolicyRef, _Mapping]] = ..., display_name: _Optional[str] = ..., min_retention_seconds: _Optional[int] = ..., max_retention_seconds: _Optional[int] = ..., immutable_after_publish: bool = ..., legal_hold: bool = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...

class Workspace(_message.Message):
    __slots__ = ("ref", "lifecycle", "promotion_stage", "quota", "usage", "default_retention", "created_at", "updated_at", "expires_at", "labels", "metadata")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    REF_FIELD_NUMBER: _ClassVar[int]
    LIFECYCLE_FIELD_NUMBER: _ClassVar[int]
    PROMOTION_STAGE_FIELD_NUMBER: _ClassVar[int]
    QUOTA_FIELD_NUMBER: _ClassVar[int]
    USAGE_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_RETENTION_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    ref: WorkspaceRef
    lifecycle: WorkspaceLifecycle
    promotion_stage: PromotionStage
    quota: QuotaSpec
    usage: QuotaUsage
    default_retention: RetentionPolicyRef
    created_at: int
    updated_at: int
    expires_at: int
    labels: _containers.ScalarMap[str, str]
    metadata: _containers.ScalarMap[str, str]
    def __init__(self, ref: _Optional[_Union[WorkspaceRef, _Mapping]] = ..., lifecycle: _Optional[_Union[WorkspaceLifecycle, str]] = ..., promotion_stage: _Optional[_Union[PromotionStage, str]] = ..., quota: _Optional[_Union[QuotaSpec, _Mapping]] = ..., usage: _Optional[_Union[QuotaUsage, _Mapping]] = ..., default_retention: _Optional[_Union[RetentionPolicyRef, _Mapping]] = ..., created_at: _Optional[int] = ..., updated_at: _Optional[int] = ..., expires_at: _Optional[int] = ..., labels: _Optional[_Mapping[str, str]] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

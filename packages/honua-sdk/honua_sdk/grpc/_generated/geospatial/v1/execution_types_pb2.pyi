from honua_sdk.grpc._generated.geospatial.v1 import common_pb2 as _common_pb2
from honua_sdk.grpc._generated.geospatial.v1 import spatial_types_pb2 as _spatial_types_pb2
from honua_sdk.grpc._generated.geospatial.v1 import workspace_artifact_types_pb2 as _workspace_artifact_types_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WorkflowFamily(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WORKFLOW_FAMILY_UNSPECIFIED: _ClassVar[WorkflowFamily]
    WORKFLOW_FAMILY_ANALYZE: _ClassVar[WorkflowFamily]
    WORKFLOW_FAMILY_PUBLISH: _ClassVar[WorkflowFamily]
    WORKFLOW_FAMILY_BUILD: _ClassVar[WorkflowFamily]
    WORKFLOW_FAMILY_DEPLOY: _ClassVar[WorkflowFamily]

class JobState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOB_STATE_UNSPECIFIED: _ClassVar[JobState]
    JOB_STATE_DRAFT: _ClassVar[JobState]
    JOB_STATE_AWAITING_CLARIFICATION: _ClassVar[JobState]
    JOB_STATE_VALIDATED: _ClassVar[JobState]
    JOB_STATE_AWAITING_APPROVAL: _ClassVar[JobState]
    JOB_STATE_RUNNING: _ClassVar[JobState]
    JOB_STATE_COMPLETED: _ClassVar[JobState]
    JOB_STATE_FAILED: _ClassVar[JobState]
    JOB_STATE_CANCELLED: _ClassVar[JobState]

class StageState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STAGE_STATE_UNSPECIFIED: _ClassVar[StageState]
    STAGE_STATE_PENDING: _ClassVar[StageState]
    STAGE_STATE_RUNNING: _ClassVar[StageState]
    STAGE_STATE_COMPLETED: _ClassVar[StageState]
    STAGE_STATE_NEEDS_USER_INPUT: _ClassVar[StageState]
    STAGE_STATE_BLOCKED: _ClassVar[StageState]
    STAGE_STATE_FAILED: _ClassVar[StageState]
    STAGE_STATE_SKIPPED: _ClassVar[StageState]
    STAGE_STATE_CANCELLED: _ClassVar[StageState]

class ErrorCategory(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ERROR_CATEGORY_UNSPECIFIED: _ClassVar[ErrorCategory]
    ERROR_CATEGORY_VALIDATION: _ClassVar[ErrorCategory]
    ERROR_CATEGORY_AUTHORIZATION: _ClassVar[ErrorCategory]
    ERROR_CATEGORY_POLICY: _ClassVar[ErrorCategory]
    ERROR_CATEGORY_EXECUTION: _ClassVar[ErrorCategory]
    ERROR_CATEGORY_ARTIFACT: _ClassVar[ErrorCategory]
    ERROR_CATEGORY_PACKAGING: _ClassVar[ErrorCategory]
    ERROR_CATEGORY_DEPLOYMENT: _ClassVar[ErrorCategory]

class Retryability(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RETRYABILITY_UNSPECIFIED: _ClassVar[Retryability]
    RETRYABILITY_FIX_PLAN_AND_RETRY: _ClassVar[Retryability]
    RETRYABILITY_FIX_DATA_AND_RETRY: _ClassVar[Retryability]
    RETRYABILITY_INSUFFICIENT_QUOTA: _ClassVar[Retryability]
    RETRYABILITY_TRANSIENT_BACKEND_ERROR: _ClassVar[Retryability]
    RETRYABILITY_PERMANENT_FAILURE: _ClassVar[Retryability]

class ArtifactClass(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ARTIFACT_CLASS_UNSPECIFIED: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_SCALAR: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_FEATURE_LAYER: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_TABLE: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_RASTER: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_FILE: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_REPORT: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_MAP: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_APP_BUNDLE: _ClassVar[ArtifactClass]
    ARTIFACT_CLASS_SERVICE_DEFINITION: _ClassVar[ArtifactClass]
WORKFLOW_FAMILY_UNSPECIFIED: WorkflowFamily
WORKFLOW_FAMILY_ANALYZE: WorkflowFamily
WORKFLOW_FAMILY_PUBLISH: WorkflowFamily
WORKFLOW_FAMILY_BUILD: WorkflowFamily
WORKFLOW_FAMILY_DEPLOY: WorkflowFamily
JOB_STATE_UNSPECIFIED: JobState
JOB_STATE_DRAFT: JobState
JOB_STATE_AWAITING_CLARIFICATION: JobState
JOB_STATE_VALIDATED: JobState
JOB_STATE_AWAITING_APPROVAL: JobState
JOB_STATE_RUNNING: JobState
JOB_STATE_COMPLETED: JobState
JOB_STATE_FAILED: JobState
JOB_STATE_CANCELLED: JobState
STAGE_STATE_UNSPECIFIED: StageState
STAGE_STATE_PENDING: StageState
STAGE_STATE_RUNNING: StageState
STAGE_STATE_COMPLETED: StageState
STAGE_STATE_NEEDS_USER_INPUT: StageState
STAGE_STATE_BLOCKED: StageState
STAGE_STATE_FAILED: StageState
STAGE_STATE_SKIPPED: StageState
STAGE_STATE_CANCELLED: StageState
ERROR_CATEGORY_UNSPECIFIED: ErrorCategory
ERROR_CATEGORY_VALIDATION: ErrorCategory
ERROR_CATEGORY_AUTHORIZATION: ErrorCategory
ERROR_CATEGORY_POLICY: ErrorCategory
ERROR_CATEGORY_EXECUTION: ErrorCategory
ERROR_CATEGORY_ARTIFACT: ErrorCategory
ERROR_CATEGORY_PACKAGING: ErrorCategory
ERROR_CATEGORY_DEPLOYMENT: ErrorCategory
RETRYABILITY_UNSPECIFIED: Retryability
RETRYABILITY_FIX_PLAN_AND_RETRY: Retryability
RETRYABILITY_FIX_DATA_AND_RETRY: Retryability
RETRYABILITY_INSUFFICIENT_QUOTA: Retryability
RETRYABILITY_TRANSIENT_BACKEND_ERROR: Retryability
RETRYABILITY_PERMANENT_FAILURE: Retryability
ARTIFACT_CLASS_UNSPECIFIED: ArtifactClass
ARTIFACT_CLASS_SCALAR: ArtifactClass
ARTIFACT_CLASS_FEATURE_LAYER: ArtifactClass
ARTIFACT_CLASS_TABLE: ArtifactClass
ARTIFACT_CLASS_RASTER: ArtifactClass
ARTIFACT_CLASS_FILE: ArtifactClass
ARTIFACT_CLASS_REPORT: ArtifactClass
ARTIFACT_CLASS_MAP: ArtifactClass
ARTIFACT_CLASS_APP_BUNDLE: ArtifactClass
ARTIFACT_CLASS_SERVICE_DEFINITION: ArtifactClass

class ExecutionPlan(_message.Message):
    __slots__ = ("plan_id", "spec_version", "workflow_family", "steps", "expected_outputs")
    PLAN_ID_FIELD_NUMBER: _ClassVar[int]
    SPEC_VERSION_FIELD_NUMBER: _ClassVar[int]
    WORKFLOW_FAMILY_FIELD_NUMBER: _ClassVar[int]
    STEPS_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    plan_id: str
    spec_version: str
    workflow_family: WorkflowFamily
    steps: _containers.RepeatedCompositeFieldContainer[PlanStep]
    expected_outputs: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, plan_id: _Optional[str] = ..., spec_version: _Optional[str] = ..., workflow_family: _Optional[_Union[WorkflowFamily, str]] = ..., steps: _Optional[_Iterable[_Union[PlanStep, _Mapping]]] = ..., expected_outputs: _Optional[_Iterable[str]] = ...) -> None: ...

class PlanStep(_message.Message):
    __slots__ = ("step_id", "kind", "inputs", "dependencies")
    class InputsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: ParameterValue
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[ParameterValue, _Mapping]] = ...) -> None: ...
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    INPUTS_FIELD_NUMBER: _ClassVar[int]
    DEPENDENCIES_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    kind: str
    inputs: _containers.MessageMap[str, ParameterValue]
    dependencies: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, step_id: _Optional[str] = ..., kind: _Optional[str] = ..., inputs: _Optional[_Mapping[str, ParameterValue]] = ..., dependencies: _Optional[_Iterable[str]] = ...) -> None: ...

class ErrorDetail(_message.Message):
    __slots__ = ("code", "message", "details", "category", "phase", "node_id", "retryability", "suggested_action", "severity", "remedy")
    class DetailsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    RETRYABILITY_FIELD_NUMBER: _ClassVar[int]
    SUGGESTED_ACTION_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    REMEDY_FIELD_NUMBER: _ClassVar[int]
    code: int
    message: str
    details: _containers.ScalarMap[str, str]
    category: ErrorCategory
    phase: str
    node_id: str
    retryability: Retryability
    suggested_action: str
    severity: _common_pb2.Severity
    remedy: str
    def __init__(self, code: _Optional[int] = ..., message: _Optional[str] = ..., details: _Optional[_Mapping[str, str]] = ..., category: _Optional[_Union[ErrorCategory, str]] = ..., phase: _Optional[str] = ..., node_id: _Optional[str] = ..., retryability: _Optional[_Union[Retryability, str]] = ..., suggested_action: _Optional[str] = ..., severity: _Optional[_Union[_common_pb2.Severity, str]] = ..., remedy: _Optional[str] = ...) -> None: ...

class ArtifactRef(_message.Message):
    __slots__ = ("artifact_id", "artifact_class", "artifact_version", "producer_ref", "workspace_ref", "retention_policy_ref", "materialization_state", "workspace", "retention", "materialization")
    ARTIFACT_ID_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_CLASS_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_VERSION_FIELD_NUMBER: _ClassVar[int]
    PRODUCER_REF_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_REF_FIELD_NUMBER: _ClassVar[int]
    RETENTION_POLICY_REF_FIELD_NUMBER: _ClassVar[int]
    MATERIALIZATION_STATE_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_FIELD_NUMBER: _ClassVar[int]
    RETENTION_FIELD_NUMBER: _ClassVar[int]
    MATERIALIZATION_FIELD_NUMBER: _ClassVar[int]
    artifact_id: str
    artifact_class: ArtifactClass
    artifact_version: int
    producer_ref: str
    workspace_ref: str
    retention_policy_ref: str
    materialization_state: str
    workspace: _workspace_artifact_types_pb2.WorkspaceRef
    retention: _workspace_artifact_types_pb2.RetentionPolicyRef
    materialization: _workspace_artifact_types_pb2.MaterializationState
    def __init__(self, artifact_id: _Optional[str] = ..., artifact_class: _Optional[_Union[ArtifactClass, str]] = ..., artifact_version: _Optional[int] = ..., producer_ref: _Optional[str] = ..., workspace_ref: _Optional[str] = ..., retention_policy_ref: _Optional[str] = ..., materialization_state: _Optional[str] = ..., workspace: _Optional[_Union[_workspace_artifact_types_pb2.WorkspaceRef, _Mapping]] = ..., retention: _Optional[_Union[_workspace_artifact_types_pb2.RetentionPolicyRef, _Mapping]] = ..., materialization: _Optional[_Union[_workspace_artifact_types_pb2.MaterializationState, str]] = ...) -> None: ...

class EstimatedArtifact(_message.Message):
    __slots__ = ("artifact_class", "estimated_size_bytes", "description")
    ARTIFACT_CLASS_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    artifact_class: ArtifactClass
    estimated_size_bytes: int
    description: str
    def __init__(self, artifact_class: _Optional[_Union[ArtifactClass, str]] = ..., estimated_size_bytes: _Optional[int] = ..., description: _Optional[str] = ...) -> None: ...

class SideEffect(_message.Message):
    __slots__ = ("effect_type", "target", "description")
    EFFECT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    effect_type: str
    target: str
    description: str
    def __init__(self, effect_type: _Optional[str] = ..., target: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...

class CostEstimate(_message.Message):
    __slots__ = ("units", "amount")
    UNITS_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    units: str
    amount: float
    def __init__(self, units: _Optional[str] = ..., amount: _Optional[float] = ...) -> None: ...

class DryRunResult(_message.Message):
    __slots__ = ("estimated_duration_seconds", "estimated_artifacts", "side_effects", "cost_estimate", "estimated_rows", "estimated_bytes", "estimated_duration_ms", "actual_rows", "actual_bytes", "actual_duration_ms")
    ESTIMATED_DURATION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    SIDE_EFFECTS_FIELD_NUMBER: _ClassVar[int]
    COST_ESTIMATE_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_ROWS_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_BYTES_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_ROWS_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    estimated_duration_seconds: int
    estimated_artifacts: _containers.RepeatedCompositeFieldContainer[EstimatedArtifact]
    side_effects: _containers.RepeatedCompositeFieldContainer[SideEffect]
    cost_estimate: CostEstimate
    estimated_rows: int
    estimated_bytes: int
    estimated_duration_ms: float
    actual_rows: int
    actual_bytes: int
    actual_duration_ms: float
    def __init__(self, estimated_duration_seconds: _Optional[int] = ..., estimated_artifacts: _Optional[_Iterable[_Union[EstimatedArtifact, _Mapping]]] = ..., side_effects: _Optional[_Iterable[_Union[SideEffect, _Mapping]]] = ..., cost_estimate: _Optional[_Union[CostEstimate, _Mapping]] = ..., estimated_rows: _Optional[int] = ..., estimated_bytes: _Optional[int] = ..., estimated_duration_ms: _Optional[float] = ..., actual_rows: _Optional[int] = ..., actual_bytes: _Optional[int] = ..., actual_duration_ms: _Optional[float] = ...) -> None: ...

class JobProgress(_message.Message):
    __slots__ = ("job_id", "state", "progress_percent", "current_node_id", "started_at", "updated_at", "message")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_PERCENT_FIELD_NUMBER: _ClassVar[int]
    CURRENT_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    state: JobState
    progress_percent: int
    current_node_id: str
    started_at: int
    updated_at: int
    message: str
    def __init__(self, job_id: _Optional[str] = ..., state: _Optional[_Union[JobState, str]] = ..., progress_percent: _Optional[int] = ..., current_node_id: _Optional[str] = ..., started_at: _Optional[int] = ..., updated_at: _Optional[int] = ..., message: _Optional[str] = ...) -> None: ...

class StageResult(_message.Message):
    __slots__ = ("node_id", "state", "error", "partial_artifacts")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    state: StageState
    error: ErrorDetail
    partial_artifacts: _containers.RepeatedCompositeFieldContainer[ArtifactRef]
    def __init__(self, node_id: _Optional[str] = ..., state: _Optional[_Union[StageState, str]] = ..., error: _Optional[_Union[ErrorDetail, _Mapping]] = ..., partial_artifacts: _Optional[_Iterable[_Union[ArtifactRef, _Mapping]]] = ...) -> None: ...

class PlanValidationIssue(_message.Message):
    __slots__ = ("node_id", "field", "message", "severity")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    FIELD_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    field: str
    message: str
    severity: _common_pb2.Severity
    def __init__(self, node_id: _Optional[str] = ..., field: _Optional[str] = ..., message: _Optional[str] = ..., severity: _Optional[_Union[_common_pb2.Severity, str]] = ...) -> None: ...

class Assumption(_message.Message):
    __slots__ = ("assumption_id", "description", "rationale", "user_confirmed")
    ASSUMPTION_ID_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    RATIONALE_FIELD_NUMBER: _ClassVar[int]
    USER_CONFIRMED_FIELD_NUMBER: _ClassVar[int]
    assumption_id: str
    description: str
    rationale: str
    user_confirmed: bool
    def __init__(self, assumption_id: _Optional[str] = ..., description: _Optional[str] = ..., rationale: _Optional[str] = ..., user_confirmed: bool = ...) -> None: ...

class ProvenanceRecord(_message.Message):
    __slots__ = ("source_dataset_refs", "process_definition_refs", "assumptions", "executed_at", "duration_seconds")
    SOURCE_DATASET_REFS_FIELD_NUMBER: _ClassVar[int]
    PROCESS_DEFINITION_REFS_FIELD_NUMBER: _ClassVar[int]
    ASSUMPTIONS_FIELD_NUMBER: _ClassVar[int]
    EXECUTED_AT_FIELD_NUMBER: _ClassVar[int]
    DURATION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    source_dataset_refs: _containers.RepeatedScalarFieldContainer[str]
    process_definition_refs: _containers.RepeatedScalarFieldContainer[str]
    assumptions: _containers.RepeatedCompositeFieldContainer[Assumption]
    executed_at: int
    duration_seconds: int
    def __init__(self, source_dataset_refs: _Optional[_Iterable[str]] = ..., process_definition_refs: _Optional[_Iterable[str]] = ..., assumptions: _Optional[_Iterable[_Union[Assumption, _Mapping]]] = ..., executed_at: _Optional[int] = ..., duration_seconds: _Optional[int] = ...) -> None: ...

class ParameterValue(_message.Message):
    __slots__ = ("string_value", "int64_value", "double_value", "bool_value", "bytes_value", "list_value", "struct_value", "spatial_filter_value", "spatial_reference_value", "geometry_value", "extent_value", "statistic_value")
    STRING_VALUE_FIELD_NUMBER: _ClassVar[int]
    INT64_VALUE_FIELD_NUMBER: _ClassVar[int]
    DOUBLE_VALUE_FIELD_NUMBER: _ClassVar[int]
    BOOL_VALUE_FIELD_NUMBER: _ClassVar[int]
    BYTES_VALUE_FIELD_NUMBER: _ClassVar[int]
    LIST_VALUE_FIELD_NUMBER: _ClassVar[int]
    STRUCT_VALUE_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_FILTER_VALUE_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_REFERENCE_VALUE_FIELD_NUMBER: _ClassVar[int]
    GEOMETRY_VALUE_FIELD_NUMBER: _ClassVar[int]
    EXTENT_VALUE_FIELD_NUMBER: _ClassVar[int]
    STATISTIC_VALUE_FIELD_NUMBER: _ClassVar[int]
    string_value: str
    int64_value: int
    double_value: float
    bool_value: bool
    bytes_value: bytes
    list_value: ParameterList
    struct_value: ParameterMap
    spatial_filter_value: _spatial_types_pb2.SpatialFilter
    spatial_reference_value: _common_pb2.SpatialReference
    geometry_value: _spatial_types_pb2.Geometry
    extent_value: _common_pb2.Extent
    statistic_value: _common_pb2.StatisticDefinition
    def __init__(self, string_value: _Optional[str] = ..., int64_value: _Optional[int] = ..., double_value: _Optional[float] = ..., bool_value: bool = ..., bytes_value: _Optional[bytes] = ..., list_value: _Optional[_Union[ParameterList, _Mapping]] = ..., struct_value: _Optional[_Union[ParameterMap, _Mapping]] = ..., spatial_filter_value: _Optional[_Union[_spatial_types_pb2.SpatialFilter, _Mapping]] = ..., spatial_reference_value: _Optional[_Union[_common_pb2.SpatialReference, _Mapping]] = ..., geometry_value: _Optional[_Union[_spatial_types_pb2.Geometry, _Mapping]] = ..., extent_value: _Optional[_Union[_common_pb2.Extent, _Mapping]] = ..., statistic_value: _Optional[_Union[_common_pb2.StatisticDefinition, _Mapping]] = ...) -> None: ...

class ParameterList(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedCompositeFieldContainer[ParameterValue]
    def __init__(self, values: _Optional[_Iterable[_Union[ParameterValue, _Mapping]]] = ...) -> None: ...

class ParameterMap(_message.Message):
    __slots__ = ("fields",)
    class FieldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: ParameterValue
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[ParameterValue, _Mapping]] = ...) -> None: ...
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    fields: _containers.MessageMap[str, ParameterValue]
    def __init__(self, fields: _Optional[_Mapping[str, ParameterValue]] = ...) -> None: ...

class ExecutionContext(_message.Message):
    __slots__ = ("workspace_id", "timeout_seconds", "metadata", "workspace")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    timeout_seconds: int
    metadata: _containers.ScalarMap[str, str]
    workspace: _workspace_artifact_types_pb2.WorkspaceRef
    def __init__(self, workspace_id: _Optional[str] = ..., timeout_seconds: _Optional[int] = ..., metadata: _Optional[_Mapping[str, str]] = ..., workspace: _Optional[_Union[_workspace_artifact_types_pb2.WorkspaceRef, _Mapping]] = ...) -> None: ...

class ValidateResponse(_message.Message):
    __slots__ = ("valid", "issues")
    VALID_FIELD_NUMBER: _ClassVar[int]
    ISSUES_FIELD_NUMBER: _ClassVar[int]
    valid: bool
    issues: _containers.RepeatedCompositeFieldContainer[PlanValidationIssue]
    def __init__(self, valid: bool = ..., issues: _Optional[_Iterable[_Union[PlanValidationIssue, _Mapping]]] = ...) -> None: ...

class DryRunResponse(_message.Message):
    __slots__ = ("valid", "issues", "result")
    VALID_FIELD_NUMBER: _ClassVar[int]
    ISSUES_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    valid: bool
    issues: _containers.RepeatedCompositeFieldContainer[PlanValidationIssue]
    result: DryRunResult
    def __init__(self, valid: bool = ..., issues: _Optional[_Iterable[_Union[PlanValidationIssue, _Mapping]]] = ..., result: _Optional[_Union[DryRunResult, _Mapping]] = ...) -> None: ...

class SubmitJobResponse(_message.Message):
    __slots__ = ("job_id", "state")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    state: JobState
    def __init__(self, job_id: _Optional[str] = ..., state: _Optional[_Union[JobState, str]] = ...) -> None: ...

class GetJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class GetJobResponse(_message.Message):
    __slots__ = ("job_id", "state", "progress")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    state: JobState
    progress: JobProgress
    def __init__(self, job_id: _Optional[str] = ..., state: _Optional[_Union[JobState, str]] = ..., progress: _Optional[_Union[JobProgress, _Mapping]] = ...) -> None: ...

class GetJobResultRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class CancelJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class CancelJobResponse(_message.Message):
    __slots__ = ("job_id", "state")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    state: JobState
    def __init__(self, job_id: _Optional[str] = ..., state: _Optional[_Union[JobState, str]] = ...) -> None: ...

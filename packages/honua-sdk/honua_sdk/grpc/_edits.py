"""Domain models and versioned protobuf conversion for native feature edits."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._models import Feature
from ._proto_adapter import _to_proto_geometry

if TYPE_CHECKING:
    from ._generated.geospatial.v1 import common_pb2 as common
    from ._generated.geospatial.v1 import execution_types_pb2 as execution
    from ._generated.geospatial.v1 import feature_service_pb2 as pb2
    from ._generated.geospatial.v1 import spatial_types_pb2 as spatial


@dataclass
class ApplyEditsRequest:
    """Native edit batch; rollback defaults to atomic failure handling.

    ``force_write`` and ``idempotency_key`` retain their geospatial.v1 semantics.
    The client never retries mutations or switches to REST automatically.
    """

    service_id: str = ""
    layer_id: int = 0
    adds: list[Feature] = field(default_factory=list)
    updates: list[Feature] = field(default_factory=list)
    deletes: list[int] = field(default_factory=list)
    rollback_on_failure: bool = True
    force_write: bool = False
    idempotency_key: str = ""


@dataclass
class EditError:
    """Server error detail, including rollback and remediation information."""

    code: int = 0
    message: str = ""
    details: dict[str, str] = field(default_factory=dict)
    category: int = 0
    phase: str = ""
    node_id: str = ""
    retryability: int = 0
    suggested_action: str = ""
    severity: int = 0
    remedy: str = ""


@dataclass
class EditResult:
    """One result in server order; success does not override a batch error."""

    object_id: int = 0
    success: bool = False
    error: EditError | None = None


@dataclass
class ApplyEditsResponse:
    """Native edit results. Inspect both the batch error and per-feature errors."""

    add_results: list[EditResult] = field(default_factory=list)
    update_results: list[EditResult] = field(default_factory=list)
    delete_results: list[EditResult] = field(default_factory=list)
    error: EditError | None = None


def _attribute(value: object) -> common.AttributeValue:
    from ._generated.geospatial.v1 import common_pb2 as common  # noqa: PLC0415 -- optional protobuf dependency

    if value is None:
        return common.AttributeValue(null_value=common.NULL_VALUE)
    if isinstance(value, bool):
        return common.AttributeValue(bool_value=value)
    if isinstance(value, int):
        return common.AttributeValue(int64_value=value)
    if isinstance(value, float):
        return common.AttributeValue(double_value=value)
    if isinstance(value, str):
        return common.AttributeValue(string_value=value)
    if isinstance(value, bytes):
        return common.AttributeValue(bytes_value=value)
    raise TypeError(f"Unsupported native edit attribute type: {type(value).__name__}")


def _feature(feature: Feature) -> spatial.Feature:
    from ._generated.geospatial.v1 import spatial_types_pb2 as spatial  # noqa: PLC0415 -- optional protobuf dependency

    result = spatial.Feature(id=feature.id)
    for key, value in feature.attributes.items():
        result.attributes[key].CopyFrom(_attribute(value))
    if feature.geometry is not None:
        if "spatialReference" in feature.geometry:
            raise ValueError("native edit geometry must use layer coordinates without spatialReference")
        if len(feature.geometry.get("rings", [])) > 1:
            raise ValueError("native edit geometry supports only single-ring polygons")
        geometry, _ = _to_proto_geometry(feature.geometry)
        if geometry.WhichOneof("shape") is None:
            raise ValueError("Unsupported native edit geometry shape")
        result.geometry.CopyFrom(geometry)
    return result


def to_proto_edits(request: ApplyEditsRequest) -> pb2.ApplyEditsRequest:
    from ._generated.geospatial.v1 import feature_service_pb2 as pb2  # noqa: PLC0415 -- optional protobuf dependency

    return pb2.ApplyEditsRequest(
        service_id=request.service_id, layer_id=request.layer_id,
        adds=[_feature(feature) for feature in request.adds],
        updates=[_feature(feature) for feature in request.updates], deletes=request.deletes,
        rollback_on_failure=request.rollback_on_failure, force_write=request.force_write,
        idempotency_key=request.idempotency_key,
    )


def _error(error: execution.ErrorDetail) -> EditError:
    return EditError(
        code=error.code, message=error.message, details=dict(error.details), category=error.category,
        phase=error.phase, node_id=error.node_id, retryability=error.retryability,
        suggested_action=error.suggested_action, severity=error.severity, remedy=error.remedy,
    )


def _result(result: pb2.EditResult) -> EditResult:
    return EditResult(
        object_id=result.object_id, success=result.success,
        error=_error(result.error) if result.HasField("error") else None,
    )


def from_proto_edits(response: pb2.ApplyEditsResponse) -> ApplyEditsResponse:
    return ApplyEditsResponse(
        add_results=[_result(result) for result in response.add_results],
        update_results=[_result(result) for result in response.update_results],
        delete_results=[_result(result) for result in response.delete_results],
        error=_error(response.error) if response.HasField("error") else None,
    )

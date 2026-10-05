from honua_sdk.grpc._generated.geospatial.v1 import common_pb2 as _common_pb2
from honua_sdk.grpc._generated.geospatial.v1 import execution_types_pb2 as _execution_types_pb2
from honua_sdk.grpc._generated.geospatial.v1 import spatial_types_pb2 as _spatial_types_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class QueryFeaturesRequest(_message.Message):
    __slots__ = ("service_id", "layer_id", "where", "object_ids", "out_fields", "return_geometry", "out_sr", "order_by", "return_distinct", "return_count_only", "return_ids_only", "return_extent_only", "out_statistics", "group_by", "geometry_precision", "max_allowable_offset", "spatial_filter", "result_offset_long", "result_record_count_long")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    LAYER_ID_FIELD_NUMBER: _ClassVar[int]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    OBJECT_IDS_FIELD_NUMBER: _ClassVar[int]
    OUT_FIELDS_FIELD_NUMBER: _ClassVar[int]
    RETURN_GEOMETRY_FIELD_NUMBER: _ClassVar[int]
    OUT_SR_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    RETURN_DISTINCT_FIELD_NUMBER: _ClassVar[int]
    RETURN_COUNT_ONLY_FIELD_NUMBER: _ClassVar[int]
    RETURN_IDS_ONLY_FIELD_NUMBER: _ClassVar[int]
    RETURN_EXTENT_ONLY_FIELD_NUMBER: _ClassVar[int]
    OUT_STATISTICS_FIELD_NUMBER: _ClassVar[int]
    GROUP_BY_FIELD_NUMBER: _ClassVar[int]
    GEOMETRY_PRECISION_FIELD_NUMBER: _ClassVar[int]
    MAX_ALLOWABLE_OFFSET_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_FILTER_FIELD_NUMBER: _ClassVar[int]
    RESULT_OFFSET_LONG_FIELD_NUMBER: _ClassVar[int]
    RESULT_RECORD_COUNT_LONG_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    layer_id: int
    where: str
    object_ids: _containers.RepeatedScalarFieldContainer[int]
    out_fields: _containers.RepeatedScalarFieldContainer[str]
    return_geometry: bool
    out_sr: _common_pb2.SpatialReference
    order_by: str
    return_distinct: bool
    return_count_only: bool
    return_ids_only: bool
    return_extent_only: bool
    out_statistics: _containers.RepeatedCompositeFieldContainer[_common_pb2.StatisticDefinition]
    group_by: _containers.RepeatedScalarFieldContainer[str]
    geometry_precision: int
    max_allowable_offset: float
    spatial_filter: _spatial_types_pb2.SpatialFilter
    result_offset_long: int
    result_record_count_long: int
    def __init__(self, service_id: _Optional[str] = ..., layer_id: _Optional[int] = ..., where: _Optional[str] = ..., object_ids: _Optional[_Iterable[int]] = ..., out_fields: _Optional[_Iterable[str]] = ..., return_geometry: bool = ..., out_sr: _Optional[_Union[_common_pb2.SpatialReference, _Mapping]] = ..., order_by: _Optional[str] = ..., return_distinct: bool = ..., return_count_only: bool = ..., return_ids_only: bool = ..., return_extent_only: bool = ..., out_statistics: _Optional[_Iterable[_Union[_common_pb2.StatisticDefinition, _Mapping]]] = ..., group_by: _Optional[_Iterable[str]] = ..., geometry_precision: _Optional[int] = ..., max_allowable_offset: _Optional[float] = ..., spatial_filter: _Optional[_Union[_spatial_types_pb2.SpatialFilter, _Mapping]] = ..., result_offset_long: _Optional[int] = ..., result_record_count_long: _Optional[int] = ...) -> None: ...

class QueryFeaturesResponse(_message.Message):
    __slots__ = ("object_id_field_name", "geometry_type", "spatial_reference", "fields", "features", "exceeded_transfer_limit", "count", "object_ids", "extent")
    OBJECT_ID_FIELD_NAME_FIELD_NUMBER: _ClassVar[int]
    GEOMETRY_TYPE_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_REFERENCE_FIELD_NUMBER: _ClassVar[int]
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    EXCEEDED_TRANSFER_LIMIT_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    OBJECT_IDS_FIELD_NUMBER: _ClassVar[int]
    EXTENT_FIELD_NUMBER: _ClassVar[int]
    object_id_field_name: str
    geometry_type: _common_pb2.GeometryType
    spatial_reference: _common_pb2.SpatialReference
    fields: _containers.RepeatedCompositeFieldContainer[_common_pb2.FieldDefinition]
    features: _containers.RepeatedCompositeFieldContainer[_spatial_types_pb2.Feature]
    exceeded_transfer_limit: bool
    count: int
    object_ids: _containers.RepeatedScalarFieldContainer[int]
    extent: _common_pb2.Extent
    def __init__(self, object_id_field_name: _Optional[str] = ..., geometry_type: _Optional[_Union[_common_pb2.GeometryType, str]] = ..., spatial_reference: _Optional[_Union[_common_pb2.SpatialReference, _Mapping]] = ..., fields: _Optional[_Iterable[_Union[_common_pb2.FieldDefinition, _Mapping]]] = ..., features: _Optional[_Iterable[_Union[_spatial_types_pb2.Feature, _Mapping]]] = ..., exceeded_transfer_limit: bool = ..., count: _Optional[int] = ..., object_ids: _Optional[_Iterable[int]] = ..., extent: _Optional[_Union[_common_pb2.Extent, _Mapping]] = ...) -> None: ...

class FeaturePage(_message.Message):
    __slots__ = ("object_id_field_name", "geometry_type", "spatial_reference", "fields", "features", "is_last_page")
    OBJECT_ID_FIELD_NAME_FIELD_NUMBER: _ClassVar[int]
    GEOMETRY_TYPE_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_REFERENCE_FIELD_NUMBER: _ClassVar[int]
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    IS_LAST_PAGE_FIELD_NUMBER: _ClassVar[int]
    object_id_field_name: str
    geometry_type: _common_pb2.GeometryType
    spatial_reference: _common_pb2.SpatialReference
    fields: _containers.RepeatedCompositeFieldContainer[_common_pb2.FieldDefinition]
    features: _containers.RepeatedCompositeFieldContainer[_spatial_types_pb2.Feature]
    is_last_page: bool
    def __init__(self, object_id_field_name: _Optional[str] = ..., geometry_type: _Optional[_Union[_common_pb2.GeometryType, str]] = ..., spatial_reference: _Optional[_Union[_common_pb2.SpatialReference, _Mapping]] = ..., fields: _Optional[_Iterable[_Union[_common_pb2.FieldDefinition, _Mapping]]] = ..., features: _Optional[_Iterable[_Union[_spatial_types_pb2.Feature, _Mapping]]] = ..., is_last_page: bool = ...) -> None: ...

class ApplyEditsRequest(_message.Message):
    __slots__ = ("service_id", "layer_id", "adds", "updates", "deletes", "rollback_on_failure", "force_write", "idempotency_key")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    LAYER_ID_FIELD_NUMBER: _ClassVar[int]
    ADDS_FIELD_NUMBER: _ClassVar[int]
    UPDATES_FIELD_NUMBER: _ClassVar[int]
    DELETES_FIELD_NUMBER: _ClassVar[int]
    ROLLBACK_ON_FAILURE_FIELD_NUMBER: _ClassVar[int]
    FORCE_WRITE_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    layer_id: int
    adds: _containers.RepeatedCompositeFieldContainer[_spatial_types_pb2.Feature]
    updates: _containers.RepeatedCompositeFieldContainer[_spatial_types_pb2.Feature]
    deletes: _containers.RepeatedScalarFieldContainer[int]
    rollback_on_failure: bool
    force_write: bool
    idempotency_key: str
    def __init__(self, service_id: _Optional[str] = ..., layer_id: _Optional[int] = ..., adds: _Optional[_Iterable[_Union[_spatial_types_pb2.Feature, _Mapping]]] = ..., updates: _Optional[_Iterable[_Union[_spatial_types_pb2.Feature, _Mapping]]] = ..., deletes: _Optional[_Iterable[int]] = ..., rollback_on_failure: bool = ..., force_write: bool = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class ApplyEditsResponse(_message.Message):
    __slots__ = ("add_results", "update_results", "delete_results", "error")
    ADD_RESULTS_FIELD_NUMBER: _ClassVar[int]
    UPDATE_RESULTS_FIELD_NUMBER: _ClassVar[int]
    DELETE_RESULTS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    add_results: _containers.RepeatedCompositeFieldContainer[EditResult]
    update_results: _containers.RepeatedCompositeFieldContainer[EditResult]
    delete_results: _containers.RepeatedCompositeFieldContainer[EditResult]
    error: _execution_types_pb2.ErrorDetail
    def __init__(self, add_results: _Optional[_Iterable[_Union[EditResult, _Mapping]]] = ..., update_results: _Optional[_Iterable[_Union[EditResult, _Mapping]]] = ..., delete_results: _Optional[_Iterable[_Union[EditResult, _Mapping]]] = ..., error: _Optional[_Union[_execution_types_pb2.ErrorDetail, _Mapping]] = ...) -> None: ...

class EditResult(_message.Message):
    __slots__ = ("object_id", "success", "error")
    OBJECT_ID_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    object_id: int
    success: bool
    error: _execution_types_pb2.ErrorDetail
    def __init__(self, object_id: _Optional[int] = ..., success: bool = ..., error: _Optional[_Union[_execution_types_pb2.ErrorDetail, _Mapping]] = ...) -> None: ...

from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class NullValue(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NULL_VALUE: _ClassVar[NullValue]

class FieldType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FIELD_TYPE_UNSPECIFIED: _ClassVar[FieldType]
    FIELD_TYPE_STRING: _ClassVar[FieldType]
    FIELD_TYPE_INTEGER: _ClassVar[FieldType]
    FIELD_TYPE_BIG_INTEGER: _ClassVar[FieldType]
    FIELD_TYPE_DOUBLE: _ClassVar[FieldType]
    FIELD_TYPE_FLOAT: _ClassVar[FieldType]
    FIELD_TYPE_BOOLEAN: _ClassVar[FieldType]
    FIELD_TYPE_DATE_TIME: _ClassVar[FieldType]
    FIELD_TYPE_DATE: _ClassVar[FieldType]
    FIELD_TYPE_TIME: _ClassVar[FieldType]
    FIELD_TYPE_GEOMETRY: _ClassVar[FieldType]
    FIELD_TYPE_JSON: _ClassVar[FieldType]
    FIELD_TYPE_BINARY: _ClassVar[FieldType]
    FIELD_TYPE_UUID: _ClassVar[FieldType]

class GeometryType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GEOMETRY_TYPE_UNSPECIFIED: _ClassVar[GeometryType]
    GEOMETRY_TYPE_POINT: _ClassVar[GeometryType]
    GEOMETRY_TYPE_MULTI_POINT: _ClassVar[GeometryType]
    GEOMETRY_TYPE_LINE_STRING: _ClassVar[GeometryType]
    GEOMETRY_TYPE_MULTI_LINE_STRING: _ClassVar[GeometryType]
    GEOMETRY_TYPE_POLYGON: _ClassVar[GeometryType]
    GEOMETRY_TYPE_MULTI_POLYGON: _ClassVar[GeometryType]
    GEOMETRY_TYPE_GEOMETRY_COLLECTION: _ClassVar[GeometryType]
    GEOMETRY_TYPE_NONE: _ClassVar[GeometryType]

class SpatialRelationship(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SPATIAL_RELATIONSHIP_UNSPECIFIED: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_INTERSECTS: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_WITHIN: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_CONTAINS: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_ENVELOPE_INTERSECTS: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_CROSSES: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_TOUCHES: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_OVERLAPS: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_DISJOINT: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_EQUALS: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_WITHIN_DISTANCE: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_BEYOND_DISTANCE: _ClassVar[SpatialRelationship]
    SPATIAL_RELATIONSHIP_NEAREST_NEIGHBOR: _ClassVar[SpatialRelationship]

class DistanceUnit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DISTANCE_UNIT_UNSPECIFIED: _ClassVar[DistanceUnit]
    DISTANCE_UNIT_METERS: _ClassVar[DistanceUnit]
    DISTANCE_UNIT_FEET: _ClassVar[DistanceUnit]
    DISTANCE_UNIT_KILOMETERS: _ClassVar[DistanceUnit]
    DISTANCE_UNIT_MILES: _ClassVar[DistanceUnit]

class StatisticType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STATISTIC_TYPE_UNSPECIFIED: _ClassVar[StatisticType]
    STATISTIC_TYPE_COUNT: _ClassVar[StatisticType]
    STATISTIC_TYPE_SUM: _ClassVar[StatisticType]
    STATISTIC_TYPE_MIN: _ClassVar[StatisticType]
    STATISTIC_TYPE_MAX: _ClassVar[StatisticType]
    STATISTIC_TYPE_AVG: _ClassVar[StatisticType]
    STATISTIC_TYPE_STDDEV: _ClassVar[StatisticType]
    STATISTIC_TYPE_VAR: _ClassVar[StatisticType]

class Severity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SEVERITY_UNSPECIFIED: _ClassVar[Severity]
    SEVERITY_INFO: _ClassVar[Severity]
    SEVERITY_WARNING: _ClassVar[Severity]
    SEVERITY_ERROR: _ClassVar[Severity]
NULL_VALUE: NullValue
FIELD_TYPE_UNSPECIFIED: FieldType
FIELD_TYPE_STRING: FieldType
FIELD_TYPE_INTEGER: FieldType
FIELD_TYPE_BIG_INTEGER: FieldType
FIELD_TYPE_DOUBLE: FieldType
FIELD_TYPE_FLOAT: FieldType
FIELD_TYPE_BOOLEAN: FieldType
FIELD_TYPE_DATE_TIME: FieldType
FIELD_TYPE_DATE: FieldType
FIELD_TYPE_TIME: FieldType
FIELD_TYPE_GEOMETRY: FieldType
FIELD_TYPE_JSON: FieldType
FIELD_TYPE_BINARY: FieldType
FIELD_TYPE_UUID: FieldType
GEOMETRY_TYPE_UNSPECIFIED: GeometryType
GEOMETRY_TYPE_POINT: GeometryType
GEOMETRY_TYPE_MULTI_POINT: GeometryType
GEOMETRY_TYPE_LINE_STRING: GeometryType
GEOMETRY_TYPE_MULTI_LINE_STRING: GeometryType
GEOMETRY_TYPE_POLYGON: GeometryType
GEOMETRY_TYPE_MULTI_POLYGON: GeometryType
GEOMETRY_TYPE_GEOMETRY_COLLECTION: GeometryType
GEOMETRY_TYPE_NONE: GeometryType
SPATIAL_RELATIONSHIP_UNSPECIFIED: SpatialRelationship
SPATIAL_RELATIONSHIP_INTERSECTS: SpatialRelationship
SPATIAL_RELATIONSHIP_WITHIN: SpatialRelationship
SPATIAL_RELATIONSHIP_CONTAINS: SpatialRelationship
SPATIAL_RELATIONSHIP_ENVELOPE_INTERSECTS: SpatialRelationship
SPATIAL_RELATIONSHIP_CROSSES: SpatialRelationship
SPATIAL_RELATIONSHIP_TOUCHES: SpatialRelationship
SPATIAL_RELATIONSHIP_OVERLAPS: SpatialRelationship
SPATIAL_RELATIONSHIP_DISJOINT: SpatialRelationship
SPATIAL_RELATIONSHIP_EQUALS: SpatialRelationship
SPATIAL_RELATIONSHIP_WITHIN_DISTANCE: SpatialRelationship
SPATIAL_RELATIONSHIP_BEYOND_DISTANCE: SpatialRelationship
SPATIAL_RELATIONSHIP_NEAREST_NEIGHBOR: SpatialRelationship
DISTANCE_UNIT_UNSPECIFIED: DistanceUnit
DISTANCE_UNIT_METERS: DistanceUnit
DISTANCE_UNIT_FEET: DistanceUnit
DISTANCE_UNIT_KILOMETERS: DistanceUnit
DISTANCE_UNIT_MILES: DistanceUnit
STATISTIC_TYPE_UNSPECIFIED: StatisticType
STATISTIC_TYPE_COUNT: StatisticType
STATISTIC_TYPE_SUM: StatisticType
STATISTIC_TYPE_MIN: StatisticType
STATISTIC_TYPE_MAX: StatisticType
STATISTIC_TYPE_AVG: StatisticType
STATISTIC_TYPE_STDDEV: StatisticType
STATISTIC_TYPE_VAR: StatisticType
SEVERITY_UNSPECIFIED: Severity
SEVERITY_INFO: Severity
SEVERITY_WARNING: Severity
SEVERITY_ERROR: Severity

class AttributeValue(_message.Message):
    __slots__ = ("string_value", "int32_value", "int64_value", "double_value", "float_value", "bool_value", "datetime_value", "bytes_value", "null_value")
    STRING_VALUE_FIELD_NUMBER: _ClassVar[int]
    INT32_VALUE_FIELD_NUMBER: _ClassVar[int]
    INT64_VALUE_FIELD_NUMBER: _ClassVar[int]
    DOUBLE_VALUE_FIELD_NUMBER: _ClassVar[int]
    FLOAT_VALUE_FIELD_NUMBER: _ClassVar[int]
    BOOL_VALUE_FIELD_NUMBER: _ClassVar[int]
    DATETIME_VALUE_FIELD_NUMBER: _ClassVar[int]
    BYTES_VALUE_FIELD_NUMBER: _ClassVar[int]
    NULL_VALUE_FIELD_NUMBER: _ClassVar[int]
    string_value: str
    int32_value: int
    int64_value: int
    double_value: float
    float_value: float
    bool_value: bool
    datetime_value: int
    bytes_value: bytes
    null_value: NullValue
    def __init__(self, string_value: _Optional[str] = ..., int32_value: _Optional[int] = ..., int64_value: _Optional[int] = ..., double_value: _Optional[float] = ..., float_value: _Optional[float] = ..., bool_value: bool = ..., datetime_value: _Optional[int] = ..., bytes_value: _Optional[bytes] = ..., null_value: _Optional[_Union[NullValue, str]] = ...) -> None: ...

class SpatialReference(_message.Message):
    __slots__ = ("wkid", "latest_wkid", "wkt")
    WKID_FIELD_NUMBER: _ClassVar[int]
    LATEST_WKID_FIELD_NUMBER: _ClassVar[int]
    WKT_FIELD_NUMBER: _ClassVar[int]
    wkid: int
    latest_wkid: int
    wkt: str
    def __init__(self, wkid: _Optional[int] = ..., latest_wkid: _Optional[int] = ..., wkt: _Optional[str] = ...) -> None: ...

class FieldDefinition(_message.Message):
    __slots__ = ("name", "field_type", "length", "nullable", "alias")
    NAME_FIELD_NUMBER: _ClassVar[int]
    FIELD_TYPE_FIELD_NUMBER: _ClassVar[int]
    LENGTH_FIELD_NUMBER: _ClassVar[int]
    NULLABLE_FIELD_NUMBER: _ClassVar[int]
    ALIAS_FIELD_NUMBER: _ClassVar[int]
    name: str
    field_type: FieldType
    length: int
    nullable: bool
    alias: str
    def __init__(self, name: _Optional[str] = ..., field_type: _Optional[_Union[FieldType, str]] = ..., length: _Optional[int] = ..., nullable: bool = ..., alias: _Optional[str] = ...) -> None: ...

class StatisticDefinition(_message.Message):
    __slots__ = ("on_statistic_field", "statistic_type", "out_statistic_field_name")
    ON_STATISTIC_FIELD_FIELD_NUMBER: _ClassVar[int]
    STATISTIC_TYPE_FIELD_NUMBER: _ClassVar[int]
    OUT_STATISTIC_FIELD_NAME_FIELD_NUMBER: _ClassVar[int]
    on_statistic_field: str
    statistic_type: StatisticType
    out_statistic_field_name: str
    def __init__(self, on_statistic_field: _Optional[str] = ..., statistic_type: _Optional[_Union[StatisticType, str]] = ..., out_statistic_field_name: _Optional[str] = ...) -> None: ...

class Extent(_message.Message):
    __slots__ = ("xmin", "ymin", "xmax", "ymax", "spatial_reference")
    XMIN_FIELD_NUMBER: _ClassVar[int]
    YMIN_FIELD_NUMBER: _ClassVar[int]
    XMAX_FIELD_NUMBER: _ClassVar[int]
    YMAX_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_REFERENCE_FIELD_NUMBER: _ClassVar[int]
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    spatial_reference: SpatialReference
    def __init__(self, xmin: _Optional[float] = ..., ymin: _Optional[float] = ..., xmax: _Optional[float] = ..., ymax: _Optional[float] = ..., spatial_reference: _Optional[_Union[SpatialReference, _Mapping]] = ...) -> None: ...

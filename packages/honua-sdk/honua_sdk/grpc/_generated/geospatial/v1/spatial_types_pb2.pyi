from honua_sdk.grpc._generated.geospatial.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Geometry(_message.Message):
    __slots__ = ("point", "multi_point", "polyline", "polygon", "multi_polygon")
    POINT_FIELD_NUMBER: _ClassVar[int]
    MULTI_POINT_FIELD_NUMBER: _ClassVar[int]
    POLYLINE_FIELD_NUMBER: _ClassVar[int]
    POLYGON_FIELD_NUMBER: _ClassVar[int]
    MULTI_POLYGON_FIELD_NUMBER: _ClassVar[int]
    point: PointGeometry
    multi_point: MultiPointGeometry
    polyline: PolylineGeometry
    polygon: PolygonGeometry
    multi_polygon: MultiPolygonGeometry
    def __init__(self, point: _Optional[_Union[PointGeometry, _Mapping]] = ..., multi_point: _Optional[_Union[MultiPointGeometry, _Mapping]] = ..., polyline: _Optional[_Union[PolylineGeometry, _Mapping]] = ..., polygon: _Optional[_Union[PolygonGeometry, _Mapping]] = ..., multi_polygon: _Optional[_Union[MultiPolygonGeometry, _Mapping]] = ...) -> None: ...

class PointGeometry(_message.Message):
    __slots__ = ("x", "y", "z", "m")
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    Z_FIELD_NUMBER: _ClassVar[int]
    M_FIELD_NUMBER: _ClassVar[int]
    x: float
    y: float
    z: float
    m: float
    def __init__(self, x: _Optional[float] = ..., y: _Optional[float] = ..., z: _Optional[float] = ..., m: _Optional[float] = ...) -> None: ...

class MultiPointGeometry(_message.Message):
    __slots__ = ("points",)
    POINTS_FIELD_NUMBER: _ClassVar[int]
    points: _containers.RepeatedCompositeFieldContainer[PointGeometry]
    def __init__(self, points: _Optional[_Iterable[_Union[PointGeometry, _Mapping]]] = ...) -> None: ...

class Coordinate(_message.Message):
    __slots__ = ("x", "y", "z", "m")
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    Z_FIELD_NUMBER: _ClassVar[int]
    M_FIELD_NUMBER: _ClassVar[int]
    x: float
    y: float
    z: float
    m: float
    def __init__(self, x: _Optional[float] = ..., y: _Optional[float] = ..., z: _Optional[float] = ..., m: _Optional[float] = ...) -> None: ...

class CoordinateSequence(_message.Message):
    __slots__ = ("coords",)
    COORDS_FIELD_NUMBER: _ClassVar[int]
    coords: _containers.RepeatedCompositeFieldContainer[Coordinate]
    def __init__(self, coords: _Optional[_Iterable[_Union[Coordinate, _Mapping]]] = ...) -> None: ...

class PolylineGeometry(_message.Message):
    __slots__ = ("paths",)
    PATHS_FIELD_NUMBER: _ClassVar[int]
    paths: _containers.RepeatedCompositeFieldContainer[CoordinateSequence]
    def __init__(self, paths: _Optional[_Iterable[_Union[CoordinateSequence, _Mapping]]] = ...) -> None: ...

class PolygonGeometry(_message.Message):
    __slots__ = ("rings",)
    RINGS_FIELD_NUMBER: _ClassVar[int]
    rings: _containers.RepeatedCompositeFieldContainer[CoordinateSequence]
    def __init__(self, rings: _Optional[_Iterable[_Union[CoordinateSequence, _Mapping]]] = ...) -> None: ...

class MultiPolygonGeometry(_message.Message):
    __slots__ = ("polygons",)
    POLYGONS_FIELD_NUMBER: _ClassVar[int]
    polygons: _containers.RepeatedCompositeFieldContainer[PolygonGeometry]
    def __init__(self, polygons: _Optional[_Iterable[_Union[PolygonGeometry, _Mapping]]] = ...) -> None: ...

class SpatialFilter(_message.Message):
    __slots__ = ("geometry", "spatial_relationship", "spatial_reference", "distance", "distance_unit", "nearest_count", "return_distance")
    GEOMETRY_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_RELATIONSHIP_FIELD_NUMBER: _ClassVar[int]
    SPATIAL_REFERENCE_FIELD_NUMBER: _ClassVar[int]
    DISTANCE_FIELD_NUMBER: _ClassVar[int]
    DISTANCE_UNIT_FIELD_NUMBER: _ClassVar[int]
    NEAREST_COUNT_FIELD_NUMBER: _ClassVar[int]
    RETURN_DISTANCE_FIELD_NUMBER: _ClassVar[int]
    geometry: Geometry
    spatial_relationship: _common_pb2.SpatialRelationship
    spatial_reference: _common_pb2.SpatialReference
    distance: float
    distance_unit: _common_pb2.DistanceUnit
    nearest_count: int
    return_distance: bool
    def __init__(self, geometry: _Optional[_Union[Geometry, _Mapping]] = ..., spatial_relationship: _Optional[_Union[_common_pb2.SpatialRelationship, str]] = ..., spatial_reference: _Optional[_Union[_common_pb2.SpatialReference, _Mapping]] = ..., distance: _Optional[float] = ..., distance_unit: _Optional[_Union[_common_pb2.DistanceUnit, str]] = ..., nearest_count: _Optional[int] = ..., return_distance: bool = ...) -> None: ...

class Feature(_message.Message):
    __slots__ = ("id", "attributes", "geometry")
    class AttributesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: _common_pb2.AttributeValue
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[_common_pb2.AttributeValue, _Mapping]] = ...) -> None: ...
    ID_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    GEOMETRY_FIELD_NUMBER: _ClassVar[int]
    id: int
    attributes: _containers.MessageMap[str, _common_pb2.AttributeValue]
    geometry: Geometry
    def __init__(self, id: _Optional[int] = ..., attributes: _Optional[_Mapping[str, _common_pb2.AttributeValue]] = ..., geometry: _Optional[_Union[Geometry, _Mapping]] = ...) -> None: ...

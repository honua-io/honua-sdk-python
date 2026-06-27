"""Bidirectional conversion between domain models and proto messages."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from honua_sdk.grpc._generated.honua.v1 import feature_service_pb2 as pb2

from . import _models as models


def to_proto_request(request: models.QueryFeaturesRequest) -> pb2.QueryFeaturesRequest:
    """Convert domain request to proto message."""
    from honua_sdk.grpc._generated.honua.v1 import feature_service_pb2 as pb2

    msg = pb2.QueryFeaturesRequest()
    msg.service_id = request.service_id
    msg.layer_id = request.layer_id
    msg.where = request.where
    msg.return_geometry = request.return_geometry

    if request.object_ids:
        msg.object_ids.extend(request.object_ids)
    if request.out_fields:
        msg.out_fields.extend(request.out_fields)
    if request.out_sr:
        msg.out_sr.wkid = request.out_sr.wkid
        msg.out_sr.latest_wkid = request.out_sr.latest_wkid
        msg.out_sr.wkt = request.out_sr.wkt
    msg.result_offset = request.result_offset
    msg.result_record_count = request.result_record_count
    if request.order_by:
        msg.order_by = request.order_by
    msg.return_distinct = request.return_distinct
    msg.return_count_only = request.return_count_only
    msg.return_ids_only = request.return_ids_only
    msg.return_extent_only = request.return_extent_only
    if request.out_statistics:
        for stat in request.out_statistics:
            s = pb2.StatisticDefinition()
            s.on_statistic_field = stat.on_statistic_field
            s.statistic_type = stat.statistic_type.value  # type: ignore[assignment]
            s.out_statistic_field_name = stat.out_statistic_field_name
            msg.out_statistics.append(s)
    if request.group_by:
        msg.group_by.extend(request.group_by)
    msg.geometry_precision = request.geometry_precision
    msg.max_allowable_offset = request.max_allowable_offset

    if request.spatial_filter:
        sf = request.spatial_filter
        msg.spatial_filter.spatial_relationship = sf.spatial_relationship.value  # type: ignore[assignment]
        msg.spatial_filter.distance = sf.distance
        msg.spatial_filter.distance_unit = sf.distance_unit.value  # type: ignore[assignment]
        msg.spatial_filter.nearest_count = sf.nearest_count
        msg.spatial_filter.return_distance = sf.return_distance
        geometry_spatial_reference: pb2.SpatialReference | None = None
        if sf.spatial_reference:
            msg.spatial_filter.spatial_reference.wkid = sf.spatial_reference.wkid
            msg.spatial_filter.spatial_reference.latest_wkid = sf.spatial_reference.latest_wkid
            msg.spatial_filter.spatial_reference.wkt = sf.spatial_reference.wkt
        if sf.geometry:
            proto_geometry, geometry_spatial_reference = _to_proto_geometry(sf.geometry)
            msg.spatial_filter.geometry.CopyFrom(proto_geometry)
        if not sf.spatial_reference and geometry_spatial_reference:
            msg.spatial_filter.spatial_reference.CopyFrom(geometry_spatial_reference)

    return msg


def from_proto_response(response: pb2.QueryFeaturesResponse) -> models.QueryFeaturesResponse:
    """Convert proto response to domain model."""
    return models.QueryFeaturesResponse(
        object_id_field_name=response.object_id_field_name,
        geometry_type=_safe_enum(
            models.GeometryType,
            response.geometry_type,
            models.GeometryType.UNSPECIFIED,
        ),
        spatial_reference=_convert_spatial_reference(response.spatial_reference)
        if response.HasField("spatial_reference")
        else None,
        fields=[_convert_field(f) for f in response.fields],
        features=[_convert_feature(f) for f in response.features],
        exceeded_transfer_limit=response.exceeded_transfer_limit,
        count=response.count,
        object_ids=[int(oid) for oid in response.object_ids],
        extent=_convert_extent(response.extent) if response.HasField("extent") else None,
    )


def from_proto_page(page: pb2.FeaturePage) -> models.FeaturePage:
    """Convert a streaming FeaturePage proto to domain model."""
    return models.FeaturePage(
        object_id_field_name=page.object_id_field_name,
        geometry_type=_safe_enum(
            models.GeometryType,
            page.geometry_type,
            models.GeometryType.UNSPECIFIED,
        ),
        spatial_reference=_convert_spatial_reference(page.spatial_reference)
        if page.HasField("spatial_reference")
        else None,
        fields=[_convert_field(f) for f in page.fields],
        features=[_convert_feature(f) for f in page.features],
        is_last_page=page.is_last_page,
    )


def _convert_spatial_reference(sr: Any) -> models.SpatialReference:
    return models.SpatialReference(wkid=sr.wkid, latest_wkid=sr.latest_wkid, wkt=sr.wkt)


def _convert_extent(ext: Any) -> models.Extent:
    sr = (
        _convert_spatial_reference(ext.spatial_reference)
        if ext.HasField("spatial_reference")
        else None
    )
    return models.Extent(
        xmin=ext.xmin, ymin=ext.ymin, xmax=ext.xmax, ymax=ext.ymax, spatial_reference=sr
    )


def _convert_field(f: Any) -> models.FieldDefinition:
    return models.FieldDefinition(
        name=f.name,
        field_type=_safe_enum(
            models.FieldType,
            f.field_type,
            models.FieldType.UNSPECIFIED,
        ),
        length=f.length,
        nullable=f.nullable,
    )


def _safe_enum(enum_type: Any, value: int, fallback: Any) -> Any:
    try:
        return enum_type(value)
    except ValueError:
        return fallback


def _convert_feature(f: Any) -> models.Feature:
    attributes: dict[str, Any] = {}
    for key, attr in f.attributes.items():
        attributes[key] = _convert_attribute(attr)

    geometry = _convert_geometry(f.geometry) if f.HasField("geometry") else None

    return models.Feature(id=f.id, attributes=attributes, geometry=geometry)


def _convert_attribute(attr: Any) -> Any:  # noqa: PLR0911 -- proto oneof dispatch
    """Convert a proto AttributeValue to a Python value."""
    which = attr.WhichOneof("value")
    if which == "string_value":
        return attr.string_value
    elif which == "int32_value":
        return attr.int32_value
    elif which == "int64_value":
        return attr.int64_value
    elif which == "double_value":
        return attr.double_value
    elif which == "float_value":
        return attr.float_value
    elif which == "bool_value":
        return attr.bool_value
    elif which == "datetime_value":
        return attr.datetime_value  # UTC milliseconds since epoch
    elif which == "bytes_value":
        return bytes(attr.bytes_value)
    elif which == "null_value":
        return None
    return None


def _array_vertex(c: Any) -> list[Any]:
    """Build an Esri-JSON coordinate array for a proto coordinate.

    Esri JSON never uses ``null`` placeholders inside coordinate arrays. A
    vertex is ``[x, y]``; ``[x, y, z]`` when only Z is present; ``[x, y, m]``
    when only M is present; and ``[x, y, z, m]`` when both are present. The
    geometry-level ``hasZ``/``hasM`` flags (set by :func:`_with_zm_flags`)
    disambiguate a trailing third ordinate.
    """
    vertex: list[Any] = [c.x, c.y]
    if c.HasField("z"):
        vertex.append(c.z)
        if c.HasField("m"):
            vertex.append(c.m)
    elif c.HasField("m"):
        vertex.append(c.m)
    return vertex


def _with_zm_flags(result: dict[str, Any], *, has_z: bool, has_m: bool) -> dict[str, Any]:
    """Annotate a geometry dict with ``hasZ``/``hasM`` so a consumer can tell
    whether a third coordinate ordinate is Z or M."""
    if has_z:
        result["hasZ"] = True
    if has_m:
        result["hasM"] = True
    return result


def _convert_geometry(geom: Any) -> dict[str, Any] | None:  # noqa: PLR0912 -- proto oneof + per-shape conversion
    """Convert a proto Geometry to Esri JSON dict."""
    which = geom.WhichOneof("shape")
    if which == "point":
        p = geom.point
        result: dict[str, Any] = {"x": p.x, "y": p.y}
        if p.HasField("z"):
            result["z"] = p.z
        if p.HasField("m"):
            result["m"] = p.m
        return result
    elif which == "multi_point":
        mp = geom.multi_point
        points = []
        has_z = has_m = False
        for p in mp.points:
            points.append(_array_vertex(p))
            has_z = has_z or p.HasField("z")
            has_m = has_m or p.HasField("m")
        return _with_zm_flags({"points": points}, has_z=has_z, has_m=has_m)
    elif which == "polyline":
        pl = geom.polyline
        paths = []
        has_z = has_m = False
        for path in pl.paths:
            coords_list: list[list[Any]] = []
            for c in path.coords:
                coords_list.append(_array_vertex(c))
                has_z = has_z or c.HasField("z")
                has_m = has_m or c.HasField("m")
            paths.append(coords_list)
        return _with_zm_flags({"paths": paths}, has_z=has_z, has_m=has_m)
    elif which == "polygon":
        pg = geom.polygon
        rings = []
        has_z = has_m = False
        for ring in pg.rings:
            coords_list = []
            for c in ring.coords:
                coords_list.append(_array_vertex(c))
                has_z = has_z or c.HasField("z")
                has_m = has_m or c.HasField("m")
            rings.append(coords_list)
        return _with_zm_flags({"rings": rings}, has_z=has_z, has_m=has_m)
    elif which == "multi_polygon":
        mpg = geom.multi_polygon
        rings = []
        has_z = has_m = False
        for poly in mpg.polygons:
            for ring in poly.rings:
                coords_list = []
                for c in ring.coords:
                    coords_list.append(_array_vertex(c))
                    has_z = has_z or c.HasField("z")
                    has_m = has_m or c.HasField("m")
                rings.append(coords_list)
        return _with_zm_flags({"rings": rings}, has_z=has_z, has_m=has_m)
    return None


def _to_proto_geometry(geom: dict[str, Any]) -> tuple[Any, pb2.SpatialReference | None]:
    """Convert an Esri JSON geometry dict to a proto Geometry message."""
    from honua_sdk.grpc._generated.honua.v1 import feature_service_pb2 as pb2

    msg = pb2.Geometry()
    spatial_reference = _extract_spatial_reference(geom, pb2)
    has_z_hint = bool(geom.get("hasZ"))
    has_m_hint = bool(geom.get("hasM"))

    if "x" in geom and "y" in geom:
        point = pb2.PointGeometry(x=geom["x"], y=geom["y"])
        if "z" in geom:
            point.z = geom["z"]
        if "m" in geom:
            point.m = geom["m"]
        msg.point.CopyFrom(point)
    elif "xmin" in geom and "ymin" in geom and "xmax" in geom and "ymax" in geom:
        ring = pb2.CoordinateSequence(coords=[
            pb2.Coordinate(x=geom["xmin"], y=geom["ymin"]),
            pb2.Coordinate(x=geom["xmax"], y=geom["ymin"]),
            pb2.Coordinate(x=geom["xmax"], y=geom["ymax"]),
            pb2.Coordinate(x=geom["xmin"], y=geom["ymax"]),
            pb2.Coordinate(x=geom["xmin"], y=geom["ymin"]),
        ])
        msg.polygon.CopyFrom(pb2.PolygonGeometry(rings=[ring]))
    elif "points" in geom:
        points = []
        for pt in geom["points"]:
            p = pb2.PointGeometry(x=pt[0], y=pt[1])
            _set_coordinate_ordinates(
                p,
                pt,
                has_z_hint=has_z_hint,
                has_m_hint=has_m_hint,
            )
            points.append(p)
        msg.multi_point.CopyFrom(pb2.MultiPointGeometry(points=points))
    elif "paths" in geom:
        paths = []
        for path in geom["paths"]:
            coords = [
                _to_proto_coordinate(c, pb2, has_z_hint=has_z_hint, has_m_hint=has_m_hint)
                for c in path
            ]
            paths.append(pb2.CoordinateSequence(coords=coords))
        msg.polyline.CopyFrom(pb2.PolylineGeometry(paths=paths))
    elif "rings" in geom:
        rings = []
        for ring in geom["rings"]:
            coords = [
                _to_proto_coordinate(c, pb2, has_z_hint=has_z_hint, has_m_hint=has_m_hint)
                for c in ring
            ]
            rings.append(pb2.CoordinateSequence(coords=coords))
        msg.polygon.CopyFrom(pb2.PolygonGeometry(rings=rings))

    return msg, spatial_reference


def _set_coordinate_ordinates(
    target: Any,
    values: list[Any],
    *,
    has_z_hint: bool,
    has_m_hint: bool,
) -> None:
    if len(values) <= 2:
        return

    third = values[2]
    fourth = values[3] if len(values) > 3 else None

    if len(values) > 3:
        if third is not None:
            target.z = third
        if fourth is not None:
            target.m = fourth
        return

    if third is None:
        return

    if has_m_hint and not has_z_hint:
        target.m = third
    else:
        target.z = third


def _to_proto_coordinate(
    values: list[Any],
    pb2_module: Any,
    *,
    has_z_hint: bool = False,
    has_m_hint: bool = False,
) -> Any:
    coordinate = pb2_module.Coordinate(x=values[0], y=values[1])
    _set_coordinate_ordinates(
        coordinate,
        values,
        has_z_hint=has_z_hint,
        has_m_hint=has_m_hint,
    )
    return coordinate


def _extract_spatial_reference(geom: dict[str, Any], pb2_module: Any) -> pb2.SpatialReference | None:
    spatial_reference = geom.get("spatialReference")
    if not isinstance(spatial_reference, dict):
        return None

    sr = pb2_module.SpatialReference()
    wkid = spatial_reference.get("wkid")
    latest_wkid = spatial_reference.get("latestWkid")
    wkt = spatial_reference.get("wkt")

    if isinstance(wkid, int):
        sr.wkid = wkid
    if isinstance(latest_wkid, int):
        sr.latest_wkid = latest_wkid
    if isinstance(wkt, str):
        sr.wkt = wkt

    if sr.wkid == 0 and sr.latest_wkid == 0 and not sr.wkt:
        return None

    return cast("pb2.SpatialReference", sr)

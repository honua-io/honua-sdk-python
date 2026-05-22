"""``arcpy.analysis`` shim -- 15 functions (6 mapped, 9 stubbed).

The mapped functions dispatch through ``honua_sdk.protocols.OgcProcessesClient``
to honua-server's geometry / analytics processes. The remaining 9 raise
:class:`~honua_arcpy._errors.HonuaArcpyUnsupportedError` with the relevant
honua-server tracking ticket.
"""

from __future__ import annotations

from typing import Any

from .._dispatch import dispatch_process, raise_unsupported


def Buffer(
    in_features: Any,
    out_feature_class: Any,
    buffer_distance_or_field: Any,
    line_side: Any = None,
    line_end_type: Any = None,
    dissolve_option: Any = None,
    dissolve_field: Any = None,
    method: Any = None,
) -> Any:
    return dispatch_process(
        "analysis.Buffer",
        in_features=in_features,
        out_feature_class=out_feature_class,
        buffer_distance_or_field=buffer_distance_or_field,
        line_side=line_side,
        line_end_type=line_end_type,
        dissolve_option=dissolve_option,
        dissolve_field=dissolve_field,
        method=method,
    )


def Clip(
    in_features: Any,
    clip_features: Any,
    out_feature_class: Any,
    cluster_tolerance: Any = None,
) -> Any:
    return dispatch_process(
        "analysis.Clip",
        in_features=in_features,
        clip_features=clip_features,
        out_feature_class=out_feature_class,
        cluster_tolerance=cluster_tolerance,
    )


def Intersect(
    in_features: Any,
    out_feature_class: Any,
    join_attributes: Any = None,
    cluster_tolerance: Any = None,
    output_type: Any = None,
) -> Any:
    return dispatch_process(
        "analysis.Intersect",
        in_features=in_features,
        out_feature_class=out_feature_class,
        join_attributes=join_attributes,
        cluster_tolerance=cluster_tolerance,
        output_type=output_type,
    )


def Union(
    in_features: Any,
    out_feature_class: Any,
    join_attributes: Any = None,
    cluster_tolerance: Any = None,
    gaps: Any = None,
) -> Any:
    return dispatch_process(
        "analysis.Union",
        in_features=in_features,
        out_feature_class=out_feature_class,
        join_attributes=join_attributes,
        cluster_tolerance=cluster_tolerance,
        gaps=gaps,
    )


def Erase(
    in_features: Any,
    erase_features: Any,
    out_feature_class: Any,
    cluster_tolerance: Any = None,
) -> Any:
    return dispatch_process(
        "analysis.Erase",
        in_features=in_features,
        erase_features=erase_features,
        out_feature_class=out_feature_class,
        cluster_tolerance=cluster_tolerance,
    )


def SpatialJoin(
    target_features: Any,
    join_features: Any,
    out_feature_class: Any,
    join_operation: Any = None,
    join_type: Any = None,
    field_mapping: Any = None,
    match_option: Any = None,
    search_radius: Any = None,
    distance_field_name: Any = None,
    match_fields: Any = None,
) -> Any:
    return dispatch_process(
        "analysis.SpatialJoin",
        target_features=target_features,
        join_features=join_features,
        out_feature_class=out_feature_class,
        join_operation=join_operation,
        join_type=join_type,
        field_mapping=field_mapping,
        match_option=match_option,
        search_radius=search_radius,
        distance_field_name=distance_field_name,
        match_fields=match_fields,
    )


def NearestNeighbor(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.NearestNeighbor")


def Near(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Near")


def TabulateIntersection(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.TabulateIntersection")


def MultipleRingBuffer(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.MultipleRingBuffer")


def PointDistance(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.PointDistance")


def SummarizeWithin(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.SummarizeWithin")


def SymmetricalDifference(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.SymmetricalDifference")


def Update(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Update")


def Identity(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Identity")


__all__ = [
    "Buffer",
    "Clip",
    "Intersect",
    "Union",
    "Erase",
    "SpatialJoin",
    "NearestNeighbor",
    "Near",
    "TabulateIntersection",
    "MultipleRingBuffer",
    "PointDistance",
    "SummarizeWithin",
    "SymmetricalDifference",
    "Update",
    "Identity",
]

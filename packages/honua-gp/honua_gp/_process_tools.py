"""Projection adapters: arcpy GP tool signatures -> honua-server process inputs.

Audit pass 8 downgraded every process-backed analysis/management entry to a
stub because the shim emitted an arcpy-style ``input_features`` / ``result``
payload while honua-server's ``BuiltInProcessCatalog`` expects either raw WKB
geometries (the ``geometry.*`` family -- single-geometry, not feature-class
shaped) or ``layerId``-addressed references (the ``analytics.*`` /
``generalization.*`` / ``data-management.*`` / ``conversion.feature-project``
families).

This module supplies the projection that re-promotes the **layer-aware**
tools. Each adapter:

1. Accepts the arcpy-style positional/keyword parameters.
2. Translates the input feature class / layer alias to a numeric ``layerId``
   (via :func:`honua_gp._resolve.resolve_layer_id`) and maps the remaining
   arcpy parameters onto the process's typed input names.
3. Submits the process as an async OGC API Processes job and polls it to a
   terminal state (:func:`honua_gp._process_jobs.submit_and_wait`).
4. Binds the named output to the job's real result -- the inline FeatureLayer
   collection honua-server returns -- and returns an arcpy-style
   :class:`Result`. Reads of that name (GetCount, cursors) are served from the
   bound result; a name whose job never succeeded has no binding and fails to
   resolve.

The ``geometry.*`` single-WKB operations (Clip / Intersect / Union / Erase)
have **no** layer-aware catalog counterpart, so they stay honest stubs; see
``honua_gp.analysis`` for those.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._audit import _redact_value, _shape_of, record_call
from ._compat import FunctionEntry, anchor_for, entry_for
from ._errors import (
    ExecuteError,
    HonuaGpConfigurationError,
    HonuaGpResolveError,
)
from ._output_artifact import read_output_artifact
from ._process_jobs import JobOutcome, submit_and_wait
from ._resolve import resolve_layer_id
from ._session import HonuaSession, LayerAlias, get_session


@dataclass(frozen=True)
class Result:
    """arcpy ``Result``-shaped return value for a completed GP tool.

    Real ``arcpy`` tools return a ``Result`` whose ``[0]`` (and ``str(...)``)
    is the output dataset path and whose ``.status`` is ``4`` (succeeded). The
    shim mirrors the subset of that surface customer scripts actually use:
    indexing ``result[0]`` for the output name, ``str(result)`` for the path,
    ``int(result)`` / ``result.status`` for the GP status code, and
    ``result.job_id`` / ``result.outputs`` for the underlying Honua job.
    """

    output: str
    job_id: str
    status: int = 4  # arcpy esriJobSucceeded
    outputs: Mapping[str, Any] | None = None

    def __str__(self) -> str:
        return self.output

    def __int__(self) -> int:
        return self.status

    def __getitem__(self, index: int) -> Any:
        # arcpy's Result.getOutput(i); index 0 is the output dataset.
        if index == 0:
            return self.output
        raise IndexError(f"Result has no output at index {index}.")

    def getOutput(self, index: int) -> Any:  # noqa: N802 -- arcpy API name.
        return self[index]


def _bound(entry: FunctionEntry, args: Sequence[Any], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Bind positional + keyword args to the manifest's arcpy parameter order.

    Uses the full ``arcpy_params`` signature (output + non-input params
    included) so positional binding matches real arcpy, not just the
    ``param_map`` subset that the server-catalog contract validates.
    """

    ordered = list(entry.arcpy_params) or list(entry.param_map.keys())
    bound: dict[str, Any] = {}
    for index, value in enumerate(args):
        if index < len(ordered):
            bound[ordered[index]] = value
        else:
            bound[f"arg_{index + 1}"] = value
    bound.update(kwargs)
    return bound


def _parse_linear_distance(value: Any) -> tuple[float, str]:
    """Coerce an arcpy linear-distance argument into a (value, unit) pair.

    arcpy accepts both a number (``25``) and a ``"25 Meters"`` linear-unit
    string. honua-server's ``analytics.buffer-aggregate`` takes a numeric
    ``distance`` plus a ``unit`` enum, so the shim splits the string form into
    a value + unit. Only the unit families honua-server accepts
    (meters/kilometers/feet/miles) are mapped; anything else raises so the
    caller is not silently given a wrong-unit buffer.
    """

    if isinstance(value, bool):
        raise HonuaGpConfigurationError(f"Buffer distance {value!r} is not a number.")
    if isinstance(value, (int, float)):
        return float(value), "meters"
    if not isinstance(value, str) or not value.strip():
        raise HonuaGpConfigurationError(
            f"Buffer distance {value!r} is not a number or an arcpy linear-unit string."
        )
    parts = value.split()
    try:
        magnitude = float(parts[0])
    except ValueError as exc:
        raise HonuaGpConfigurationError(
            f"Buffer distance {value!r} does not start with a number."
        ) from exc
    unit_token = parts[1].lower() if len(parts) > 1 else "meters"
    unit_map = {
        "meters": "meters", "meter": "meters",
        "kilometers": "kilometers", "kilometer": "kilometers",
        "feet": "feet", "foot": "feet",
        "miles": "miles", "mile": "miles",
    }
    unit = unit_map.get(unit_token)
    if unit is None:
        raise HonuaGpConfigurationError(
            f"Buffer linear unit {unit_token!r} is not supported; honua-server's "
            "analytics.buffer-aggregate accepts meters, kilometers, feet, or miles."
        )
    return magnitude, unit


def _csv_fields(value: Any) -> str | None:
    """Normalize an arcpy field-list argument into a comma-separated string."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


@dataclass
class _ProjectedCall:
    """Result of projecting bound arcpy args onto a process payload."""

    inputs: dict[str, Any]
    output_name: str | None = None


def _reserve_output(name: Any, *, session: HonuaSession, projected: _ProjectedCall) -> None:
    """Reserve the GP tool's named output ahead of job submission.

    Mirrors arcpy's fail-fast duplicate-output check (``env.overwriteOutput``)
    so a call that would collide with an existing alias never submits a job
    at all -- but, unlike the old behaviour, this does **not** publish a
    usable alias yet. The name is only bound to a real backing artifact by
    :func:`_bind_output` once the job has actually succeeded; until then a
    ``MakeFeatureLayer`` / ``GetCount`` / cursor / GP call against this name
    keeps its prior alias if it had one, and otherwise fails to resolve --
    never an imaginary dataset or the workspace's layer 0.
    """

    if not isinstance(name, str) or not name:
        return
    if not session.overwrite_output and session.get_layer(name) is not None:
        raise HonuaGpConfigurationError(
            f"Layer alias {name!r} already exists; set arcpy.env.overwriteOutput = True to replace."
        )
    projected.output_name = name


def _mark_requested_output(bound: Mapping[str, Any], session: HonuaSession) -> None:
    """Keep a requested output name with no prior alias unresolvable until its job succeeds."""

    name = bound.get("out_feature_class") or bound.get("out_dataset")
    if isinstance(name, str) and name and session.get_layer(name) is None:
        session.mark_unbound_output(
            name,
            f"{name!r} is the output of a GP tool whose job has not completed successfully, "
            "so it is not bound to any dataset.",
        )


def _bind_output(
    qualified: str,
    output_name: str | None,
    *,
    session: HonuaSession,
    outcome: JobOutcome,
    compat_anchor: str | None,
) -> None:
    """Bind the reserved output name to the job's real result on success.

    Validates the FeatureLayer output the terminal-success job returned
    (:func:`honua_gp._output_artifact.read_output_artifact`) and only then
    registers the alias, so ``Result[0]`` / ``getOutput(0)`` / ``str(result)``
    and every later read of that name use that result. A missing or
    unreadable output is a typed :class:`ExecuteError`, never a successful
    ``Result``.
    """

    artifact = read_output_artifact(
        outcome.results,
        function=qualified,
        job_id=outcome.job_id,
        compat_anchor=compat_anchor,
    )
    if not isinstance(output_name, str) or not output_name:
        return
    session.register_layer(
        LayerAlias(name=output_name, source=artifact.source, kind="gp-output", output=artifact)
    )


# ---------------------------------------------------------------------------
# Parameter-semantics validation
#
# Every ``arcpy_params`` entry the projector does not translate into a
# process input is a parameter the customer's script *thinks* is doing
# something. Silently accepting a nondefault value there means the tool ran
# with different semantics than requested without telling anyone. These
# helpers reject any such value up front (before layer resolution / job
# submission) unless it is the arcpy default the shim already implements.
# ---------------------------------------------------------------------------


def _reject_nondefault_token(tool: str, param: str, value: Any, *default_tokens: str, reason: str) -> None:
    if value is None:
        return
    if isinstance(value, str) and value.strip().upper() in default_tokens:
        return
    raise HonuaGpConfigurationError(
        f"{tool} {param}={value!r} is not supported by the shim; {reason}"
    )


def _reject_if_set(tool: str, param: str, value: Any, *, reason: str) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    if isinstance(value, (list, tuple, dict)) and len(value) == 0:
        return
    raise HonuaGpConfigurationError(
        f"{tool} {param}={value!r} is not supported by the shim; {reason}"
    )


def _reject_nondefault_flag(
    tool: str, param: str, value: Any, *, default: bool, true_token: str, false_token: str, reason: str
) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        is_default = value == default
    elif isinstance(value, str):
        token = value.strip().upper()
        if token == true_token:
            is_default = default is True
        elif token == false_token:
            is_default = default is False
        else:
            is_default = False
    else:
        is_default = False
    if not is_default:
        raise HonuaGpConfigurationError(
            f"{tool} {param}={value!r} is not supported by the shim; {reason}"
        )


def _validate_buffer_options(bound: Mapping[str, Any]) -> None:
    _reject_nondefault_token(
        "analysis.Buffer", "line_side", bound.get("line_side"), "FULL",
        reason="honua-server's analytics.buffer-aggregate always buffers symmetrically; "
        "LEFT/RIGHT/OUTSIDE_ONLY are not modelled.",
    )
    _reject_nondefault_token(
        "analysis.Buffer", "line_end_type", bound.get("line_end_type"), "ROUND",
        reason="honua-server always emits round buffer ends; FLAT is not modelled.",
    )
    _reject_nondefault_token(
        "analysis.Buffer", "method", bound.get("method"), "PLANAR",
        reason="honua-server's buffer process is planar-only; GEODESIC is not modelled.",
    )


def _validate_spatial_join_options(bound: Mapping[str, Any]) -> None:
    _reject_nondefault_token(
        "analysis.SpatialJoin", "join_operation", bound.get("join_operation"), "JOIN_ONE_TO_ONE",
        reason="honua-server's analytics.spatial-join always emits one output row per join match; "
        "JOIN_ONE_TO_MANY cardinality is not modelled.",
    )
    _reject_nondefault_token(
        "analysis.SpatialJoin", "join_type", bound.get("join_type"), "KEEP_ALL",
        reason="honua-server's analytics.spatial-join does not drop unmatched target features; "
        "KEEP_COMMON is not modelled.",
    )
    _reject_if_set(
        "analysis.SpatialJoin", "field_mapping", bound.get("field_mapping"),
        reason="custom field mapping/merge rules are not modelled by analytics.spatial-join.",
    )
    _reject_if_set(
        "analysis.SpatialJoin", "distance_field_name", bound.get("distance_field_name"),
        reason="the join distance is not written back as an output field by analytics.spatial-join.",
    )


def _validate_dissolve_options(bound: Mapping[str, Any]) -> None:
    _reject_if_set(
        "management.Dissolve", "statistics_fields", bound.get("statistics_fields"),
        reason="per-group statistics aggregation is not modelled by generalization.dissolve.",
    )
    _reject_nondefault_flag(
        "management.Dissolve", "multi_part", bound.get("multi_part"),
        default=True, true_token="MULTI_PART", false_token="SINGLE_PART",
        reason="honua-server's generalization.dissolve always emits multi-part output; "
        "SINGLE_PART is not modelled.",
    )
    _reject_nondefault_flag(
        "management.Dissolve", "unsplit_lines", bound.get("unsplit_lines"),
        default=False, true_token="UNSPLIT_LINES", false_token="DISSOLVE_LINES",
        reason="line-unsplitting is not modelled by generalization.dissolve.",
    )


def _validate_project_options(bound: Mapping[str, Any]) -> None:
    _reject_if_set(
        "management.Project", "transform_method", bound.get("transform_method"),
        reason="geographic (datum) transformations are not modelled by conversion.feature-project.",
    )
    _reject_if_set(
        "management.Project", "in_coor_system", bound.get("in_coor_system"),
        reason="overriding the input spatial reference is not modelled by conversion.feature-project.",
    )
    _reject_nondefault_flag(
        "management.Project", "preserve_shape", bound.get("preserve_shape"),
        default=False, true_token="PRESERVE_SHAPE", false_token="NO_PRESERVE_SHAPE",
        reason="shape-preserving transformation is not modelled by conversion.feature-project.",
    )
    _reject_if_set(
        "management.Project", "max_deviation", bound.get("max_deviation"),
        reason="shape-preservation deviation tolerance is not modelled by conversion.feature-project.",
    )
    _reject_nondefault_flag(
        "management.Project", "vertical", bound.get("vertical"),
        default=False, true_token="VERTICAL", false_token="NO_VERTICAL",
        reason="vertical (Z-value) transformation is not modelled by conversion.feature-project.",
    )


# ---------------------------------------------------------------------------
# Selection and environment semantics
#
# A MakeFeatureLayer / SelectLayerByAttribute selection on an input layer and
# arcpy.env settings that change the output are semantics the caller expects
# the tool to honour. Forward a selection where the process can filter that
# input; reject everything else before submission.
# ---------------------------------------------------------------------------

_UNAPPLIED_ENVIRONMENT = ("extent", "XYTolerance", "XYResolution")


def _validate_environment(qualified: str, session: HonuaSession) -> None:
    # Project takes its output coordinate system from out_coor_system, as arcpy does.
    if qualified != "management.Project" and session.output_coordinate_system is not None:
        raise HonuaGpConfigurationError(
            f"{qualified} does not apply arcpy.env.outputCoordinateSystem="
            f"{session.output_coordinate_system!r}; honua-server returns the output in the "
            "input layer's spatial reference. Clear the environment setting."
        )
    names = [*_UNAPPLIED_ENVIRONMENT]
    if qualified == "management.Project":
        names.append("geographicTransformations")
    for name in names:
        value = session.extra_env_options.get(name)
        if value is not None and value != "":
            raise HonuaGpConfigurationError(
                f"{qualified} does not apply arcpy.env.{name}={value!r}; honua-server's process "
                "has no equivalent input. Clear the environment setting."
            )


def _selection_where(
    value: Any,
    *,
    session: HonuaSession,
    tool: str,
    param: str,
    filterable: bool = True,
) -> str | None:
    """Return the selection an input layer alias carries, if any.

    ``filterable=False`` marks an input the process cannot filter; a selection
    there is rejected instead of running the tool on every feature.
    """

    alias = session.get_layer(value) if isinstance(value, str) else None
    where = alias.where if alias is not None else None
    if not where:
        return None
    if not filterable:
        raise HonuaGpConfigurationError(
            f"{tool} {param}={value!r} has the selection {where!r}, but honua-server's process "
            "cannot filter that input, so the tool would run on every feature. Clear the selection first."
        )
    return where


def _combine_where(*clauses: Any) -> str | None:
    parts = [clause for clause in clauses if isinstance(clause, str) and clause.strip()]
    if len(parts) <= 1:
        return parts[0] if parts else None
    return " AND ".join(f"({part})" for part in parts)


# ---------------------------------------------------------------------------
# Per-tool projections (arcpy signature -> process inputs)
# ---------------------------------------------------------------------------


def _project_buffer(bound: Mapping[str, Any], *, session: HonuaSession, projected: _ProjectedCall) -> None:
    _validate_buffer_options(bound)
    layer_id = resolve_layer_id(bound.get("in_features"), session=session)
    distance, unit = _parse_linear_distance(bound.get("buffer_distance_or_field"))
    inputs: dict[str, Any] = {"layerId": layer_id, "distance": distance, "unit": unit}
    # arcpy dissolve_option ALL/LIST -> dissolve=true; NONE -> dissolve=false.
    dissolve_option = bound.get("dissolve_option")
    if dissolve_option is not None:
        inputs["dissolve"] = str(dissolve_option).upper() != "NONE"
    if bound.get("dissolve_field"):
        inputs["groupByFields"] = _csv_fields(bound.get("dissolve_field"))
    where = _combine_where(
        _selection_where(bound.get("in_features"), session=session, tool="analysis.Buffer", param="in_features"),
        bound.get("where_clause"),
    )
    if where:
        inputs["where"] = where
    projected.inputs = inputs
    _reserve_output(bound.get("out_feature_class"), session=session, projected=projected)


def _project_spatial_join(bound: Mapping[str, Any], *, session: HonuaSession, projected: _ProjectedCall) -> None:
    _validate_spatial_join_options(bound)
    layer_id = resolve_layer_id(bound.get("target_features"), session=session)
    join_id = resolve_layer_id(bound.get("join_features"), session=session)
    inputs: dict[str, Any] = {"layerId": layer_id, "joinLayerId": join_id}
    # Map arcpy match_option vocabulary onto honua-server's predicate enum.
    match_option = bound.get("match_option")
    if match_option is not None:
        predicate, distance = _match_option_to_predicate(match_option, bound.get("search_radius"))
        inputs["predicate"] = predicate
        if distance is not None:
            inputs["distance"] = distance
    _selection_where(
        bound.get("join_features"), session=session, tool="analysis.SpatialJoin", param="join_features",
        filterable=False,
    )
    where = _combine_where(
        _selection_where(
            bound.get("target_features"), session=session, tool="analysis.SpatialJoin", param="target_features"
        ),
        bound.get("where_clause"),
    )
    if where:
        inputs["where"] = where
    projected.inputs = inputs
    _reserve_output(bound.get("out_feature_class"), session=session, projected=projected)


def _match_option_to_predicate(match_option: Any, search_radius: Any) -> tuple[str, float | None]:
    token = str(match_option).upper()
    mapping = {
        "INTERSECT": ("intersects", None),
        "CONTAINS": ("contains", None),
        "WITHIN": ("within", None),
        "WITHIN_A_DISTANCE": ("dwithin", None),
        "CLOSEST": ("dwithin", None),
    }
    if token not in mapping:
        raise HonuaGpConfigurationError(
            f"SpatialJoin match_option {match_option!r} has no honua-server "
            "predicate equivalent; supported: INTERSECT, CONTAINS, WITHIN, "
            "WITHIN_A_DISTANCE."
        )
    predicate, _ = mapping[token]
    distance: float | None = None
    if predicate == "dwithin":
        distance, _unit = _parse_linear_distance(search_radius) if search_radius is not None else (None, None)
        if distance is None:
            raise HonuaGpConfigurationError(
                "SpatialJoin match_option=WITHIN_A_DISTANCE requires a "
                "search_radius (e.g. '100 Meters')."
            )
    return predicate, distance


def _project_dissolve(bound: Mapping[str, Any], *, session: HonuaSession, projected: _ProjectedCall) -> None:
    _validate_dissolve_options(bound)
    layer_id = resolve_layer_id(bound.get("in_features"), session=session)
    inputs: dict[str, Any] = {"layerId": layer_id}
    group_fields = _csv_fields(bound.get("dissolve_field"))
    if group_fields:
        inputs["groupByFields"] = group_fields
    where = _combine_where(
        _selection_where(bound.get("in_features"), session=session, tool="management.Dissolve", param="in_features"),
        bound.get("where_clause"),
    )
    if where:
        inputs["where"] = where
    projected.inputs = inputs
    _reserve_output(bound.get("out_feature_class"), session=session, projected=projected)


def _project_project(bound: Mapping[str, Any], *, session: HonuaSession, projected: _ProjectedCall) -> None:
    _validate_project_options(bound)
    layer_id = resolve_layer_id(bound.get("in_dataset"), session=session)
    target = bound.get("out_coor_system")
    target_srid = _coerce_srid(target)
    _selection_where(
        bound.get("in_dataset"), session=session, tool="management.Project", param="in_dataset", filterable=False
    )
    projected.inputs = {"layerId": layer_id, "targetSrid": target_srid}
    _reserve_output(bound.get("out_dataset"), session=session, projected=projected)


def _coerce_srid(value: Any) -> int:
    """Coerce an arcpy spatial-reference argument into an integer SRID.

    arcpy's ``out_coor_system`` is usually an EPSG/WKID int (``4326``) or a
    numeric string. honua-server's ``conversion.feature-project`` takes a
    plain ``targetSrid`` integer, so the shim accepts the int / numeric-string
    forms and rejects opaque ``arcpy.SpatialReference`` objects with a clear
    message instead of POSTing an unparseable value.
    """

    if isinstance(value, bool):
        raise HonuaGpConfigurationError("Project out_coor_system must be an EPSG/WKID code, not a bool.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    factory_code = getattr(value, "factoryCode", None)
    if isinstance(factory_code, int):
        return factory_code
    raise HonuaGpConfigurationError(
        f"Project out_coor_system {value!r} must be an EPSG/WKID code "
        "(integer or numeric string); arcpy.SpatialReference objects are not "
        "resolvable by the shim. Pass the WKID directly (e.g. 4326)."
    )


# Projection registry: manifest name -> (projector).
_PROJECTORS = {
    "analysis.Buffer": _project_buffer,
    "analysis.SpatialJoin": _project_spatial_join,
    "management.Dissolve": _project_dissolve,
    "management.Project": _project_project,
}


def run_layer_process(qualified: str, *args: Any, **kwargs: Any) -> Result:
    """Project, submit, poll, and return an arcpy ``Result`` for a GP tool.

    This is the entry point every promoted process-backed shim calls. It owns
    the full lifecycle under a single audit ``record_call`` so each tool
    invocation -- success or failure -- writes exactly one JSONL line with the
    real ``error_kind``.
    """

    entry = entry_for(qualified)
    if entry is None or entry.backend != "process":
        raise HonuaGpConfigurationError(
            f"{qualified} is not a process-backed manifest entry."
        )
    projector = _PROJECTORS.get(qualified)
    if projector is None:  # pragma: no cover -- registry / manifest drift guard.
        raise HonuaGpConfigurationError(f"No projection adapter registered for {qualified}.")

    session = get_session()
    bound = _bound(entry, args, kwargs)
    anchor = anchor_for(qualified)

    with record_call(qualified, args=args, kwargs=kwargs, writer=session.audit_writer()) as record:
        projected = _ProjectedCall(inputs={})
        try:
            _mark_requested_output(bound, session)
            _validate_environment(qualified, session)
            projector(bound, session=session, projected=projected)
            processes = session.processes_client()
            outcome: JobOutcome = submit_and_wait(
                processes,
                entry.process_id or "",
                projected.inputs,
                function=qualified,
                compat_anchor=anchor,
            )
            # Only bind the reserved output name to a session alias once the
            # job has actually succeeded and produced a real artifact -- a
            # failure/timeout above never reaches here, so no alias is ever
            # published for a dataset that does not exist (and a prior alias
            # under the same name, if any, is left untouched).
            _bind_output(qualified, projected.output_name, session=session, outcome=outcome, compat_anchor=anchor)
        except (ExecuteError, HonuaGpConfigurationError, HonuaGpResolveError):
            raise
        except Exception as exc:  # honua_sdk transport errors -- wrap, keep cause.
            raise ExecuteError(
                f"{qualified} failed: {exc}",
                function=qualified,
                error_kind=exc.__class__.__name__,
                compat_anchor=anchor,
                cause=exc,
            ) from exc

        output_name = projected.output_name or ""
        record["process_id"] = entry.process_id
        # Record the projected process inputs (the actual payload POSTed to the
        # server's OGC execute endpoint) so the eval harness can diff the
        # dispatch/parameter-translation against a golden fingerprint. This is
        # deterministic across the stub and a live server -- the projection is
        # transport-independent -- so a regression that maps an arcpy argument
        # to the wrong process input is caught in BOTH modes, not just when a
        # real server happens to reject the malformed payload. Redacted with
        # the same heuristics as args/kwargs; the typed inputs (layerId,
        # distance, unit, predicate, targetSrid) carry no secrets.
        record["process_inputs"] = _redact_value(dict(projected.inputs), context="process_inputs")
        record["job_id"] = outcome.job_id
        record["job_status"] = outcome.status
        record["result_shape"] = _shape_of({"output": output_name, "jobId": outcome.job_id})
        return Result(
            output=output_name,
            job_id=outcome.job_id,
            outputs=outcome.results,
        )


__all__ = ["Result", "run_layer_process"]

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
4. Registers the named output as a session layer alias (so a later GP call can
   reference it) and returns an arcpy-style :class:`Result`.

The ``geometry.*`` single-WKB operations (Clip / Intersect / Union / Erase)
have **no** layer-aware catalog counterpart, so they stay honest stubs; see
``honua_gp.analysis`` for those.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ._audit import _shape_of, record_call
from ._compat import FunctionEntry, anchor_for, entry_for
from ._errors import (
    ExecuteError,
    HonuaGpConfigurationError,
    HonuaGpResolveError,
)
from ._process_jobs import JobOutcome, submit_and_wait
from ._resolve import resolve_layer_id, resolve_or_register_output
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
    prior_alias: LayerAlias | None = None
    alias_registered: bool = False
    extra_record: dict[str, Any] = field(default_factory=dict)


def _register_output(name: Any, *, session: HonuaSession, projected: _ProjectedCall) -> None:
    """Register the GP tool's named output as a session alias.

    Mirrors arcpy's "the tool creates the output dataset" contract: a later
    ``MakeFeatureLayer`` / ``GetCount`` / cursor against the output name then
    resolves through the alias. Honours ``env.overwriteOutput`` via
    :func:`resolve_or_register_output`, and records the prior alias so a failed
    job can roll the registration back.
    """

    if not isinstance(name, str) or not name:
        return
    projected.output_name = name
    projected.prior_alias = session.get_layer(name)
    resolve_or_register_output(name, session=session)
    projected.alias_registered = True


def _rollback_output(session: HonuaSession, projected: _ProjectedCall) -> None:
    if not projected.alias_registered or projected.output_name is None:
        return
    with session._lock:  # noqa: SLF001 -- intentional cross-module rollback under the same lock.
        if projected.prior_alias is None:
            session._layers.pop(projected.output_name, None)  # noqa: SLF001
        else:
            session._layers[projected.output_name] = projected.prior_alias  # noqa: SLF001


# ---------------------------------------------------------------------------
# Per-tool projections (arcpy signature -> process inputs)
# ---------------------------------------------------------------------------


def _project_buffer(bound: Mapping[str, Any], *, session: HonuaSession, projected: _ProjectedCall) -> None:
    layer_id = resolve_layer_id(bound.get("in_features"), session=session)
    distance, unit = _parse_linear_distance(bound.get("buffer_distance_or_field"))
    inputs: dict[str, Any] = {"layerId": layer_id, "distance": distance, "unit": unit}
    # arcpy dissolve_option ALL/LIST -> dissolve=true; NONE -> dissolve=false.
    dissolve_option = bound.get("dissolve_option")
    if dissolve_option is not None:
        inputs["dissolve"] = str(dissolve_option).upper() != "NONE"
    if bound.get("dissolve_field"):
        inputs["groupByFields"] = _csv_fields(bound.get("dissolve_field"))
    if bound.get("where_clause"):
        inputs["where"] = bound.get("where_clause")
    projected.inputs = inputs
    _register_output(bound.get("out_feature_class"), session=session, projected=projected)


def _project_spatial_join(bound: Mapping[str, Any], *, session: HonuaSession, projected: _ProjectedCall) -> None:
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
    if bound.get("where_clause"):
        inputs["where"] = bound.get("where_clause")
    projected.inputs = inputs
    _register_output(bound.get("out_feature_class"), session=session, projected=projected)


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
    layer_id = resolve_layer_id(bound.get("in_features"), session=session)
    inputs: dict[str, Any] = {"layerId": layer_id}
    group_fields = _csv_fields(bound.get("dissolve_field"))
    if group_fields:
        inputs["groupByFields"] = group_fields
    if bound.get("where_clause"):
        inputs["where"] = bound.get("where_clause")
    projected.inputs = inputs
    _register_output(bound.get("out_feature_class"), session=session, projected=projected)


def _project_project(bound: Mapping[str, Any], *, session: HonuaSession, projected: _ProjectedCall) -> None:
    layer_id = resolve_layer_id(bound.get("in_dataset"), session=session)
    target = bound.get("out_coor_system")
    target_srid = _coerce_srid(target)
    projected.inputs = {"layerId": layer_id, "targetSrid": target_srid}
    _register_output(bound.get("out_dataset"), session=session, projected=projected)


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
            projector(bound, session=session, projected=projected)
            processes = session.processes_client()
            outcome: JobOutcome = submit_and_wait(
                processes,
                entry.process_id or "",
                projected.inputs,
                function=qualified,
                compat_anchor=anchor,
            )
        except (ExecuteError, HonuaGpConfigurationError, HonuaGpResolveError):
            _rollback_output(session, projected)
            raise
        except Exception as exc:  # honua_sdk transport errors -- wrap, keep cause.
            _rollback_output(session, projected)
            raise ExecuteError(
                f"{qualified} failed: {exc}",
                function=qualified,
                error_kind=exc.__class__.__name__,
                compat_anchor=anchor,
                cause=exc,
            ) from exc

        output_name = projected.output_name or ""
        record["process_id"] = entry.process_id
        record["job_id"] = outcome.job_id
        record["job_status"] = outcome.status
        record["result_shape"] = _shape_of({"output": output_name, "jobId": outcome.job_id})
        return Result(
            output=output_name,
            job_id=outcome.job_id,
            outputs=outcome.results,
        )


__all__ = ["Result", "run_layer_process"]

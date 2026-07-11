"""Raster/surface (Spatial-Analyst) GP tool dispatch.

honua-server's raster and surface processes (``surface.slope``,
``raster.reproject``, ``raster.zonal-statistics``, ...) are executed
out-of-process by the heavyweight GDAL worker. Unlike the layer-aware vector
processes handled by :mod:`honua_gp._process_tools`, **none** of the raster ids
are allow-listed for a direct ``POST .../processes/{id}/execution`` -- a direct
call 404s. The only way to invoke one is wrapped as a single ``geoprocess``
step inside the canonical ``honua-geoprocessing`` process's ``plan`` input.

This module owns that wrapping + submit/poll/consume lifecycle for the
``backend="raster"`` manifest entries surfaced under ``honua_gp.sa.*``. It:

1. Builds the flat raster-process ``inputs`` bag from ``honua_sdk``'s public
   :class:`~honua_sdk.geoprocessing.RasterReference` /
   :class:`~honua_sdk.geoprocessing.LayerReference` input model (per-tool
   input assembly lives in :mod:`honua_gp.sa`).
2. Wraps it as a single-step canonical plan (the same shape
   :meth:`honua_sdk.geoprocessing.HonuaGeoprocessing.submit_raster_process`
   builds -- confirmed against ``OgcProcessesExecutionSubmissionTests``).
3. Submits + polls the async OGC API Processes job through the **same**
   transport the vector tools use (``session.processes_client()`` +
   :func:`honua_gp._process_jobs.submit_and_wait`); no new HTTP path.
4. Routes the terminal results document by output kind (via
   ``honua_sdk``'s :func:`~honua_sdk.geoprocessing.results_kind` /
   :meth:`~honua_sdk.geoprocessing.HonuaGeoprocessing.consume_result`):
   ``Table``/``Scalar`` outputs are returned as parsed JSON directly;
   ``Raster``/``FeatureLayer`` outputs are returned as a lazy
   :class:`RasterResult` handle so the optional ``raster`` / ``geopandas``
   extras are only imported when the caller actually converts.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from honua_sdk.geoprocessing import (
    CANONICAL_PROCESS_ID,
    LayerReference,
    RasterReference,
    results_kind,
)

from ._audit import _shape_of, record_call
from ._compat import anchor_for, entry_for
from ._errors import (
    ExecuteError,
    HonuaGpConfigurationError,
)
from ._process_jobs import JobOutcome, submit_and_wait
from ._session import get_session

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd
    import xarray


# ---------------------------------------------------------------------------
# Input coercion helpers (build the flat raster-process ``inputs`` bag)
# ---------------------------------------------------------------------------


def as_raster_reference(value: Any) -> RasterReference:
    """Coerce ``value`` into a :class:`honua_sdk.geoprocessing.RasterReference`.

    Accepts a :class:`RasterReference` (returned unchanged) or raw GeoTIFF
    ``bytes`` (wrapped via :meth:`RasterReference.from_geotiff_bytes`). Catalog
    raster-layer / registered-raster ids are intentionally *not* coerced from a
    bare string -- the two id kinds are ambiguous -- so callers pass
    ``RasterReference.from_layer_id(...)`` / ``.from_raster_id(...)`` explicitly.
    """
    if isinstance(value, RasterReference):
        return value
    if isinstance(value, (bytes, bytearray)):
        return RasterReference.from_geotiff_bytes(bytes(value))
    raise HonuaGpConfigurationError(
        "Raster input must be a honua_gp.RasterReference (use "
        "RasterReference.from_layer_id / .from_raster_id / .from_geotiff_bytes) "
        f"or raw GeoTIFF bytes; got {type(value).__name__}."
    )


def _feature_collection_of(value: Any) -> Mapping[str, Any]:
    """Return an inline GeoJSON ``FeatureCollection`` from ``value``.

    Accepts a GeoJSON ``FeatureCollection`` mapping or an inline-GeoJSON
    :class:`honua_sdk.geoprocessing.LayerReference`
    (``LayerReference.from_geojson(...)``). Query-result / layer-id references
    are rejected: the raster worker reads inline zone/point geometry today.
    """
    if isinstance(value, LayerReference):
        if value.kind != "inlineGeoJson" or value.inline_geojson is None:
            raise HonuaGpConfigurationError(
                "Only inline-GeoJSON LayerReference "
                "(LayerReference.from_geojson(...)) is accepted here; layer-resolved "
                "references are deferred server-side."
            )
        return value.inline_geojson
    if isinstance(value, Mapping) and value.get("type") == "FeatureCollection":
        return value
    raise HonuaGpConfigurationError(
        "Expected a GeoJSON FeatureCollection mapping or an inline-GeoJSON "
        f"LayerReference; got {type(value).__name__}."
    )


def encode_feature_collection(value: Any) -> str:
    """Base64-encode a GeoJSON ``FeatureCollection`` (the ``zones`` / ``points`` wire shape).

    honua-server's raster worker reads zone polygons and interpolation points as
    a base64-encoded compact GeoJSON ``FeatureCollection`` (confirmed via
    ``GdalJobInputReader.TryGetBase64Input``); this mirrors ``honua_sdk``'s
    ``_zone_inputs`` encoding.
    """
    collection = _feature_collection_of(value)
    payload = json.dumps(collection, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def encode_source_list(values: Sequence[Any]) -> str:
    """Encode a list of source rasters into the ``'|'``-separated ``sources`` input.

    honua-server's ``raster.mosaic`` / ``raster.map-algebra`` read a
    ``'|'``-separated list of base64-encoded GeoTIFFs. Only inline
    ``source``-kind references (raw bytes or
    ``RasterReference.from_geotiff_bytes``) can join the list -- ``layerId`` /
    ``rasterId`` references are not resolvable into the multi-source string --
    so they are rejected with a clear message.
    """
    if not isinstance(values, (list, tuple)) or len(values) < 2:
        raise HonuaGpConfigurationError(
            "This tool requires two or more input rasters as a list."
        )
    encoded: list[str] = []
    for value in values:
        reference = as_raster_reference(value)
        if reference.kind != "source" or not reference.source_base64:
            raise HonuaGpConfigurationError(
                "Multi-raster inputs (Mosaic / RasterCalculator) require inline "
                "GeoTIFF bytes for each raster; layerId/rasterId references are not "
                "resolvable into the '|'-separated 'sources' input. Pass raw bytes or "
                "RasterReference.from_geotiff_bytes(...)."
            )
        encoded.append(reference.source_base64)
    return "|".join(encoded)


def _stringify(value: Any) -> str:
    """Coerce a scalar parameter to its canonical string form (mirrors honua_sdk)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def raster_inputs(
    raster: RasterReference,
    *,
    zones: Any | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the flat single-source raster-process ``inputs`` bag.

    ``raster.to_inputs()`` supplies the ``source`` / ``layerId`` / ``rasterId``
    carrier; ``zones`` (when supplied) is base64-encoded under ``zones``; and
    the remaining ``parameters`` are string-canonicalized. ``None`` parameter
    values are dropped so unset optional kwargs never reach the server.
    """
    inputs: dict[str, Any] = dict(raster.to_inputs())
    if zones is not None:
        inputs["zones"] = encode_feature_collection(zones)
    merge_parameters(inputs, parameters)
    return inputs


def merge_parameters(inputs: dict[str, Any], parameters: Mapping[str, Any] | None) -> None:
    """String-canonicalize and merge ``parameters`` into a process ``inputs`` bag.

    ``None`` values are dropped so unset optional kwargs never reach the server;
    non-string scalars are canonicalized (``bool`` -> ``"true"``/``"false"``,
    else ``str``). Mutates ``inputs`` in place.
    """
    if not parameters:
        return
    for key, value in parameters.items():
        if value is None:
            continue
        inputs[key] = value if isinstance(value, str) else _stringify(value)


def named_parameters(param_map: Mapping[str, str], **kwargs: Any) -> dict[str, Any]:
    """Translate arcpy-keyword kwargs into server-input keys via ``param_map``.

    Drops ``None`` values (unset optional kwargs). Used by :mod:`honua_gp.sa` to
    map its confident named kwargs (``z_factor`` -> ``zFactor``, ...) onto the
    server's process-input names before merging a generic ``**parameters``
    passthrough.
    """
    out: dict[str, Any] = {}
    for arcpy_key, server_key in param_map.items():
        value = kwargs.get(arcpy_key)
        if value is not None:
            out[server_key] = value
    return out


# ---------------------------------------------------------------------------
# Plan wrapping (single ``geoprocess`` step in the canonical plan)
# ---------------------------------------------------------------------------


def _default_plan_id(process_id: str) -> str:
    return f"raster-{process_id}-{uuid.uuid4().hex[:12]}"


def wrap_raster_plan(process_id: str, inputs: Mapping[str, Any], plan_id: str) -> dict[str, Any]:
    """Wrap a raster-process invocation as a single-step canonical plan.

    Mirrors ``honua_sdk.geoprocessing._raster_plan`` -- the shape
    ``honua-geoprocessing`` accepts for a one-off raster step (a ``planId`` plus
    one ``geoprocess`` step naming the raster ``processId`` and its ``inputs``).
    """
    return {
        "planId": plan_id,
        "steps": [
            {
                "stepId": "s1",
                "kind": "geoprocess",
                "processId": process_id,
                "inputs": dict(inputs),
            }
        ],
    }


# ---------------------------------------------------------------------------
# Result handle (lazy, extra-gated conversion)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RasterResult:
    """Handle over a raster/surface GP tool's terminal results document.

    Raster-output tools (Slope, Hillshade, ...) and the FeatureLayer-output
    Contour tool return this instead of eagerly materializing the output, so the
    optional ``raster`` (rasterio/rioxarray/xarray) and ``geopandas`` extras are
    imported only when a caller actually converts:

    * :meth:`consume` -- kind-routed conversion (``Raster`` -> xarray,
      ``FeatureLayer`` -> GeoDataFrame) via ``honua_sdk``'s ``consume_result``.
    * :meth:`to_xarray` / :attr:`raster_bytes` -- raster-output accessors.
    * :meth:`to_geodataframe` -- FeatureLayer-output accessor (Contour).

    ``results`` is the raw OGC ``/results`` document; ``job_id`` /
    ``process_id`` / ``kind`` identify the underlying job and declared output.
    """

    results: Mapping[str, Any]
    job_id: str
    process_id: str
    kind: str | None = None

    def _consumer(self) -> Any:
        from honua_sdk.geoprocessing import HonuaGeoprocessing

        return HonuaGeoprocessing(get_session().client())

    def consume(self) -> Any:
        """Materialize the output as the Python object matching its kind."""
        return self._consumer().consume_result(self.results)

    def to_xarray(self) -> "xarray.DataArray":
        """Return the raster output as an :class:`xarray.DataArray` (``raster`` extra)."""
        return self._consumer().result_to_xarray(self.results)

    def to_geodataframe(self) -> "gpd.GeoDataFrame":
        """Return the FeatureLayer output as a GeoDataFrame (``geopandas`` extra)."""
        return self._consumer()._result_geodataframe(self.results)  # noqa: SLF001

    @property
    def raster_bytes(self) -> bytes:
        """Return the raw GeoTIFF bytes of the raster output."""
        return self._consumer().result_raster_bytes(self.results)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

# Output kinds returned as parsed JSON (list/dict) rather than a RasterResult.
_JSON_RESULT_KINDS = frozenset({"Table", "Scalar"})


def run_raster_process(
    qualified: str,
    inputs: Mapping[str, Any],
    *,
    plan_id: str | None = None,
) -> Any:
    """Submit a raster/surface process (auto-wrapped as a plan) and consume it.

    ``inputs`` is the flat raster-process input bag (built per-tool in
    :mod:`honua_gp.sa`). Returns the parsed JSON value for ``Table``/``Scalar``
    outputs (e.g. ZonalStatisticsAsTable's per-zone list) or a lazy
    :class:`RasterResult` for ``Raster``/``FeatureLayer`` outputs. Raises
    :class:`~honua_gp._errors.ExecuteError` on job failure / transport error,
    writing exactly one audit line per call.
    """
    entry = entry_for(qualified)
    if entry is None or entry.backend != "raster":
        raise HonuaGpConfigurationError(
            f"{qualified} is not a raster-backed manifest entry."
        )
    process_id = entry.process_id or ""
    session = get_session()
    anchor = anchor_for(qualified)
    effective_plan_id = plan_id or _default_plan_id(process_id)
    plan = wrap_raster_plan(process_id, inputs, effective_plan_id)

    with record_call(qualified, args=(), kwargs={}, writer=session.audit_writer()) as record:
        # Record dispatch metadata but never the raster payload itself: the
        # ``inputs`` bag can carry multi-megabyte base64 GeoTIFF bytes, so only
        # the (secret-free) input KEYS are audited.
        record["process_id"] = process_id
        record["plan_id"] = effective_plan_id
        record["process_input_keys"] = sorted(str(key) for key in inputs)
        try:
            processes = session.processes_client()
            outcome: JobOutcome = submit_and_wait(
                processes,
                CANONICAL_PROCESS_ID,
                {"plan": plan},
                function=qualified,
                compat_anchor=anchor,
            )
        except (ExecuteError, HonuaGpConfigurationError):
            raise
        except Exception as exc:  # honua_sdk transport errors -- wrap, keep cause.
            raise ExecuteError(
                f"{qualified} failed: {exc}",
                function=qualified,
                error_kind=exc.__class__.__name__,
                compat_anchor=anchor,
                cause=exc,
            ) from exc

        record["job_id"] = outcome.job_id
        record["job_status"] = outcome.status
        results = outcome.results or {}
        kind = results_kind(results)
        record["result_kind"] = kind
        value = _consume(qualified, process_id, results, kind, outcome, anchor)
        record["result_shape"] = _shape_of(
            value.results if isinstance(value, RasterResult) else value
        )
        return value


def _consume(
    qualified: str,
    process_id: str,
    results: Mapping[str, Any],
    kind: str | None,
    outcome: JobOutcome,
    anchor: str,
) -> Any:
    """Route a terminal results document to JSON (Table/Scalar) or a handle."""
    if kind in _JSON_RESULT_KINDS:
        try:
            return _consume_json(results)
        except (ExecuteError, HonuaGpConfigurationError):
            raise
        except Exception as exc:  # decode/transport error consuming a JSON output.
            raise ExecuteError(
                f"{qualified} failed to read its {kind} output: {exc}",
                function=qualified,
                error_kind=exc.__class__.__name__,
                compat_anchor=anchor,
                cause=exc,
            ) from exc
    return RasterResult(
        results=results,
        job_id=outcome.job_id,
        process_id=process_id,
        kind=kind,
    )


def _consume_json(results: Mapping[str, Any]) -> Any:
    """Parse a ``Table``/``Scalar`` output's JSON value from a results document.

    Inline values (a ``data:`` URI, a raw JSON string, or an already-parsed
    ``dict``/``list``) are decoded **without** constructing a
    :class:`~honua_sdk.HonuaClient`: the GDAL worker publishes Table/Scalar
    artifacts as inline ``data:`` URIs (``GdalDataUri.Build``), so the common
    path needs no data client and works when only ``processes_client=`` is
    configured. Only a fetchable ``http(s)`` ``href`` falls back to the
    SDK's client-backed ``consume_result`` (which requires a data client).
    """
    member = _member_for_json(results)
    if member is not None:
        found, value = _decode_inline_json(member)
        if found:
            return value
    # Non-inline (fetchable-href) output: delegate to the SDK's client-backed
    # consumption, which fetches through the bound client (base URL + auth).
    from honua_sdk.geoprocessing import HonuaGeoprocessing

    return HonuaGeoprocessing(get_session().client()).consume_result(results)


def _member_for_json(results: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the results document's primary JSON-bearing output member.

    The document may itself be the member (carries ``kind``/``value``/``href``)
    or an outputs map keyed by output id whose first such member holds the
    payload. Mirrors the SDK's member selection without depending on its
    private selectors.
    """
    keys = ("kind", "value", "href")
    if any(key in results for key in keys):
        return results
    for member in results.values():
        if isinstance(member, Mapping) and any(key in member for key in keys):
            return member
    return None


def _decode_inline_json(member: Mapping[str, Any]) -> tuple[bool, Any]:
    """Decode a member's inline JSON payload; ``(False, None)`` if only fetchable."""
    value = member.get("value")
    if isinstance(value, (dict, list)):
        return True, value
    if isinstance(value, str):
        data = _inline_json_bytes(value)
        if data is not None:
            return True, json.loads(data)
    href = member.get("href")
    if isinstance(href, str) and href.startswith("data:"):
        data = _data_uri_bytes(href)
        if data is not None:
            return True, json.loads(data)
    return False, None


def _inline_json_bytes(value: str) -> bytes | None:
    """Return JSON bytes from a ``data:`` URI or a raw JSON string, else ``None``."""
    if value.startswith("data:"):
        return _data_uri_bytes(value)
    stripped = value.strip()
    if stripped[:1] in ("{", "["):
        return value.encode("utf-8")
    return None


def _data_uri_bytes(uri: str) -> bytes | None:
    """Decode a ``data:`` URI to bytes (base64 or percent-encoded payload)."""
    if not uri.startswith("data:"):
        return None
    header, _, data = uri.partition(",")
    if ";base64" in header:
        return base64.b64decode(data, validate=True)
    from urllib.parse import unquote

    return unquote(data).encode("utf-8")


__all__ = [
    "RasterResult",
    "as_raster_reference",
    "encode_feature_collection",
    "encode_source_list",
    "merge_parameters",
    "named_parameters",
    "raster_inputs",
    "run_raster_process",
    "wrap_raster_plan",
]

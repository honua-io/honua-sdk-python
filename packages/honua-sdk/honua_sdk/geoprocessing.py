"""First-class geoprocessing (GP) clients for Honua Server.

Honua exposes geoprocessing through **OGC API Processes**. On the reconciled
server (honua-server #1228 / #1185) a process execution is:

* ``POST /ogc/processes/processes/{processId}/execution`` with a
  ``{"inputs": {...}}`` body -> returns ``201 Created`` with an OGC
  ``StatusInfo`` document (and a ``Location`` header pointing at the job),
* status polled on ``GET /ogc/processes/jobs/{jobId}``,
* results fetched from ``GET /ogc/processes/jobs/{jobId}/results`` once the job
  reaches a terminal status (a document-mode outputs map).

Two process shapes are addressable:

* **Namespaced catalog processes** (``geometry.*``, ``conversion.*``,
  ``analytics.*``, ``generalization.*``, ...): each declares its own ``inputs``
  bag. Feature-collection-in / feature-collection-out vector processes take an
  inline GeoJSON ``FeatureCollection`` plus process parameters; single-geometry
  primitives take a base64/WKT geometry plus a ``srid``. Reach the layer-scope
  path with :meth:`HonuaGeoprocessing.execute` (submit + poll-to-terminal +
  fetch results) or :meth:`HonuaGeoprocessing.submit` (async submit returning a
  pollable :class:`GeoprocessingJob`).
* **The canonical ``honua-geoprocessing`` process**: accepts a ``plan`` input —
  a multi-step analysis plan (a DAG of process-node steps with input bindings).
  This is how multi-step geoprocessing is expressed *today* over the OGC
  Processes surface; submit it with :meth:`HonuaGeoprocessing.execute_plan`.

.. note::

   Catalog-*layer-id* input was deferred server-side, so this client supports
   **inline FeatureCollection** input now; it does not build catalog-layer-ref
   input. For a durable, authored multi-node workflow (the replacement for the
   dropped GeoETL pipeline endpoints) see :mod:`honua_sdk.workflow`.

Both the synchronous (:class:`HonuaGeoprocessing`) and asynchronous
(:class:`AsyncHonuaGeoprocessing`) clients are provided with full parity and
reuse the bound :class:`~honua_sdk.client.HonuaClient` /
:class:`~honua_sdk.async_client.AsyncHonuaClient` transport.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, TypeGuard, cast
from urllib.parse import parse_qsl, unquote, urlsplit

from ._client_protocol import SupportsAsyncRequest, SupportsSyncRequest
from ._http import _encode_path_segment
from .errors import HonuaError

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd
    import rasterio
    import xarray

JsonObject = dict[str, Any]
LayerReferenceKind = Literal["inlineGeoJson", "queryResult"]
RasterReferenceKind = Literal["source", "layerId", "rasterId"]

#: Canonical process id that accepts a multi-step analysis ``plan`` input.
CANONICAL_PROCESS_ID = "honua-geoprocessing"

#: OGC job statuses that are terminal (no further transition will occur).
TERMINAL_JOB_STATUSES: frozenset[str] = frozenset({"successful", "failed", "dismissed"})
_LOGGER = logging.getLogger("honua_sdk.geoprocessing")
_MAX_POLL_INTERVAL = 10.0

#: Namespaced catalog process ids that execute at *layer scope* (feature
#: collection in / out) and are projected through OGC API Processes today.
#: Mirrors the reconciled server's
#: ``ProcessMigrationEvidenceClassifier.FirstSliceAutomatedVectorProcessIds``.
LAYER_SCOPE_PROCESS_IDS: frozenset[str] = frozenset(
    {
        "geometry.buffer",
        "geometry.clip",
        "geometry.intersect",
        "geometry.project",
        "geometry.simplify",
        "geometry.snap",
        "geometry.dissolve",
        "geometry.make-valid",
        "geometry.union",
        "geometry.difference",
        "geometry.area",
        "geometry.length",
        "geometry.centroid",
        "geometry.convex-hull",
        "analytics.buffer-aggregate",
        "analytics.spatial-join",
        "analytics.density",
        "analytics.cluster",
        "conversion.feature-project",
        "generalization.simplify-layer",
        "generalization.dissolve",
    }
)

#: Raster / surface process ids handled by the GDAL worker. Unlike the vector
#: ids above, **none** of these are allow-listed for direct
#: ``POST .../processes/{processId}/execution`` on the reconciled server
#: (``ProcessMigrationEvidenceClassifier.FirstSliceAutomatedVectorProcessIds``
#: only lists vector/geometry ids) — a direct call 404s with ``no-such-process``.
#: The only way to invoke one is wrapped as a single ``geoprocess`` step inside
#: the canonical ``honua-geoprocessing`` ``plan`` input; the
#: :meth:`~HonuaGeoprocessing.submit_raster_process` /
#: :meth:`~HonuaGeoprocessing.execute_raster_process` helpers do that wrapping
#: transparently.
RASTER_SCOPE_PROCESS_IDS: frozenset[str] = frozenset(
    {
        "surface.slope",
        "surface.aspect",
        "surface.hillshade",
        "surface.contour",
        "surface.viewshed",
        "surface.roughness",
        "surface.rugosity-tpi",
        "surface.rugosity-tri",
        "raster.clip",
        "raster.mosaic",
        "raster.reclassify",
        "raster.reproject",
        "raster.resample",
        "raster.map-algebra",
        "raster.spectral-index",
        "raster.statistics",
        "raster.histogram",
        "raster.interpolate-idw",
        "raster.interpolate-kriging",
        "raster.zonal-statistics",
    }
)


class GeoprocessingJobError(HonuaError):
    """Raised when a geoprocessing job reaches a non-successful terminal state."""

    def __init__(self, job: "GeoprocessingJob") -> None:
        self.job = job
        message = job.message or f"Geoprocessing job {job.job_id!r} ended with status {job.status!r}."
        super().__init__(message)


@dataclass(frozen=True)
class LayerReference:
    """A reference to the input feature collection a vector GP process runs on.

    Exactly one carrier is populated according to :attr:`kind`. Use the
    classmethod constructors rather than building this by hand:

    * :meth:`from_geojson` -- an inline GeoJSON ``FeatureCollection`` (the
      supported input shape today).
    * :meth:`from_query_result` -- a previously materialized query-result id.

    Catalog-layer-id input was deferred server-side and is intentionally not
    modelled here.
    """

    kind: LayerReferenceKind
    inline_geojson: Mapping[str, Any] | None = None
    query_result_id: str | None = None
    where: str | None = None

    @classmethod
    def from_geojson(cls, feature_collection: Mapping[str, Any]) -> "LayerReference":
        """Build a reference from an inline GeoJSON ``FeatureCollection``."""
        return cls(kind="inlineGeoJson", inline_geojson=feature_collection)

    @classmethod
    def from_query_result(cls, query_result_id: str, *, where: str | None = None) -> "LayerReference":
        """Build a reference to a previously materialized query-result id."""
        return cls(kind="queryResult", query_result_id=str(query_result_id), where=where)

    def to_inputs(self) -> JsonObject:
        """Project this reference onto the OGC Processes ``inputs`` keys.

        The server's vector executor reads ``inputGeoJson`` (an inline
        FeatureCollection serialized as a string) or ``queryResultId`` (plus an
        optional ``where`` filter) from the canonical step-input bag.
        """
        inputs: JsonObject = {}
        if self.kind == "inlineGeoJson":
            if self.inline_geojson is None:
                raise ValueError("inlineGeoJson layer reference requires a feature collection.")
            inputs["inputGeoJson"] = json.dumps(self.inline_geojson, separators=(",", ":"))
        elif self.kind == "queryResult":
            if not self.query_result_id:
                raise ValueError("queryResult layer reference requires a query-result id.")
            inputs["queryResultId"] = self.query_result_id
        else:  # pragma: no cover - guarded by the Literal type
            raise ValueError(f"Unknown layer reference kind: {self.kind!r}")
        if self.where:
            inputs["where"] = self.where
        return inputs


@dataclass(frozen=True)
class RasterReference:
    """A reference to the raster a raster/surface GP process runs on.

    A raster input reaches the GDAL worker as **one flat string parameter** in
    the process ``inputs`` bag; exactly one carrier is populated according to
    :attr:`kind`. Use the classmethod constructors rather than building this by
    hand:

    * :meth:`from_geotiff_bytes` -- inline GeoTIFF bytes, base64-encoded and
      emitted as ``source`` (this is literally what the GDAL worker reads at
      execution time).
    * :meth:`from_layer_id` -- a catalog raster layer id, emitted as ``layerId``
      (resolved server-side into a ``source`` before the job reaches the worker).
    * :meth:`from_raster_id` -- a registered raster id, emitted as ``rasterId``
      (same server-side pre-resolution as ``layerId``).

    The three carriers are mutually exclusive; exactly one must be populated.
    """

    kind: RasterReferenceKind
    source_base64: str | None = None
    layer_id: str | None = None
    raster_id: str | None = None

    def __post_init__(self) -> None:
        populated = [
            name
            for name, value in (
                ("source_base64", self.source_base64),
                ("layer_id", self.layer_id),
                ("raster_id", self.raster_id),
            )
            if value is not None
        ]
        if len(populated) != 1:
            raise ValueError(
                "RasterReference requires exactly one of source_base64/layer_id/raster_id "
                f"to be populated; got {populated!r}. Use the classmethod constructors."
            )

    @classmethod
    def from_geotiff_bytes(cls, data: bytes) -> "RasterReference":
        """Build a reference from inline GeoTIFF ``data`` (base64-encoded ``source``)."""
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("from_geotiff_bytes expects GeoTIFF bytes.")
        encoded = base64.b64encode(bytes(data)).decode("ascii")
        return cls(kind="source", source_base64=encoded)

    @classmethod
    def from_layer_id(cls, layer_id: str) -> "RasterReference":
        """Build a reference to a catalog raster layer id (emitted as ``layerId``)."""
        return cls(kind="layerId", layer_id=str(layer_id))

    @classmethod
    def from_raster_id(cls, raster_id: str) -> "RasterReference":
        """Build a reference to a registered raster id (emitted as ``rasterId``)."""
        return cls(kind="rasterId", raster_id=str(raster_id))

    def to_inputs(self) -> JsonObject:
        """Project this reference onto its single OGC Processes ``inputs`` key.

        The GDAL worker reads ``source`` (inline base64 GeoTIFF); ``layerId`` /
        ``rasterId`` are resolved into a ``source`` server-side before the job
        reaches the worker.
        """
        if self.kind == "source":
            if not self.source_base64:
                raise ValueError("source raster reference requires base64-encoded GeoTIFF bytes.")
            return {"source": self.source_base64}
        if self.kind == "layerId":
            if not self.layer_id:
                raise ValueError("layerId raster reference requires a catalog raster layer id.")
            return {"layerId": self.layer_id}
        if self.kind == "rasterId":
            if not self.raster_id:
                raise ValueError("rasterId raster reference requires a registered raster id.")
            return {"rasterId": self.raster_id}
        raise ValueError(f"Unknown raster reference kind: {self.kind!r}")  # pragma: no cover


@dataclass(frozen=True)
class GeoprocessingJob:
    """A typed view over an OGC API Processes ``StatusInfo`` document."""

    job_id: str
    status: str
    process_id: str | None = None
    message: str | None = None
    progress: int | None = None
    created: str | None = None
    updated: str | None = None
    links: tuple[Mapping[str, Any], ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_status_info(cls, payload: Mapping[str, Any]) -> "GeoprocessingJob":
        """Parse a ``StatusInfo`` (or job-results error) document."""
        links_raw = payload.get("links")
        links: tuple[Mapping[str, Any], ...] = (
            tuple(link for link in links_raw if isinstance(link, Mapping))
            if isinstance(links_raw, list)
            else ()
        )
        job_id = payload.get("jobID") or payload.get("jobId") or ""
        return cls(
            job_id=str(job_id),
            status=str(payload.get("status") or ""),
            process_id=payload.get("processID") or payload.get("processId"),
            message=payload.get("message"),
            progress=payload.get("progress") if isinstance(payload.get("progress"), int) else None,
            created=payload.get("created"),
            updated=payload.get("updated"),
            links=links,
            raw=dict(payload),
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the job has reached a terminal status."""
        return self.status in TERMINAL_JOB_STATUSES

    @property
    def succeeded(self) -> bool:
        """Whether the job finished successfully."""
        return self.status == "successful"


def _execute_payload(inputs: Mapping[str, Any], *, response_mode: str | None) -> JsonObject:
    payload: JsonObject = {"inputs": dict(inputs)}
    if response_mode is not None:
        payload["response"] = response_mode
    return payload


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _layer_inputs(reference: LayerReference, parameters: Mapping[str, Any] | None) -> JsonObject:
    inputs = reference.to_inputs()
    if parameters:
        for key, value in parameters.items():
            # The server canonicalizes non-string inputs to strings; pass
            # booleans/numbers through as JSON-friendly strings for clarity.
            inputs[key] = value if isinstance(value, str) else _stringify(value)
    return inputs


def _plan_inputs(plan: Mapping[str, Any]) -> JsonObject:
    """Wrap an analysis plan into the canonical process ``inputs`` bag."""
    return {"plan": dict(plan)}


def _zone_inputs(zones: LayerReference) -> JsonObject:
    """Project a zone-polygon layer onto the ``zones`` raster-process input.

    ``raster.zonal-statistics`` reads its zone polygons as a **base64-encoded
    GeoJSON ``FeatureCollection``** under the flat ``zones`` parameter (confirmed
    via ``GdalRasterZonalStatisticsJobExecutor`` ->
    ``GdalJobInputReader.TryGetBase64Input(parameters, "zones", ...)``). This is
    a *different* wire shape from a vector process's ``inputGeoJson`` (raw JSON
    string), so zones are encoded here rather than via ``LayerReference.to_inputs``.
    Layer-resolved zones (``zonesLayerId``) are deferred server-side, so only an
    inline-GeoJSON :class:`LayerReference` is accepted.
    """
    if zones.kind != "inlineGeoJson" or zones.inline_geojson is None:
        raise ValueError(
            "zones must be an inline-GeoJSON LayerReference "
            "(LayerReference.from_geojson(...)); layer-resolved zones are deferred server-side."
        )
    payload = json.dumps(zones.inline_geojson, separators=(",", ":")).encode("utf-8")
    return {"zones": base64.b64encode(payload).decode("ascii")}


def _raster_process_inputs(
    raster: RasterReference,
    zones: LayerReference | None,
    parameters: Mapping[str, Any] | None,
) -> JsonObject:
    """Build the flat raster-process ``inputs`` bag (raster + zones + parameters)."""
    inputs: JsonObject = dict(raster.to_inputs())
    if zones is not None:
        inputs.update(_zone_inputs(zones))
    if parameters:
        for key, value in parameters.items():
            inputs[key] = value if isinstance(value, str) else _stringify(value)
    return inputs


def _raster_plan(process_id: str, inputs: Mapping[str, Any], plan_id: str) -> JsonObject:
    """Wrap a raster-process invocation as a single-step canonical plan.

    Raster/surface process ids 404 on direct execution, so they are submitted as
    one ``geoprocess`` step inside the ``honua-geoprocessing`` process's ``plan``
    input (shape confirmed against
    ``OgcProcessesExecutionSubmissionTests``).
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


def _default_plan_id(process_id: str) -> str:
    """Generate a reasonable, unique ``planId`` for an auto-wrapped raster step."""
    return f"raster-{process_id}-{uuid.uuid4().hex[:12]}"


def _data_uri_bytes(uri: str) -> bytes | None:
    """Decode a ``data:`` URI to bytes, or ``None`` when ``uri`` is not a data URI.

    Handles both ``;base64`` and plain (percent-encoded) payloads. Honua's GDAL
    worker publishes scalar/table/vector artifacts as
    ``data:<content-type>;base64,<payload>`` (see ``GdalDataUri.Build``).
    """
    if not uri.startswith("data:"):
        return None
    header, _, data = uri.partition(",")
    if ";base64" in header:
        try:
            return base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HonuaError(f"Output data URI is not valid base64: {exc}") from exc
    return unquote(data).encode("utf-8")


def _output_json_bytes(member: Mapping[str, Any]) -> bytes | None:
    """Return the JSON payload bytes carried inline by an output ``member``.

    Reads an inline ``value`` (a ``data:`` URI or a raw JSON string) or a
    ``data:`` ``href``. Returns ``None`` when the payload is only reachable via a
    fetchable (``http(s)``) ``href`` -- the caller fetches that through the bound
    client so base URL, auth, and retry policy apply -- or is carried as a raw
    (non-string) ``value`` the caller can use as-is.
    """
    value = member.get("value")
    if isinstance(value, str):
        decoded = _data_uri_bytes(value)
        if decoded is not None:
            return decoded
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            return value.encode("utf-8")
        return None
    href = member.get("href")
    if isinstance(href, str) and href:
        return _data_uri_bytes(href)
    return None


def _output_members(results: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Yield candidate output members from a results document.

    Handles the same shape variability the other selectors do: the document may
    itself be a member, an outputs map keyed by output id, or an outputs map
    whose members wrap the real payload under a ``value`` key.
    """
    members: list[Mapping[str, Any]] = []
    if _looks_output_member(results):
        members.append(results)
    for member in results.values():
        if isinstance(member, Mapping):
            if _looks_output_member(member):
                members.append(member)
            wrapped = member.get("value")
            if isinstance(wrapped, Mapping) and _looks_output_member(wrapped):
                members.append(wrapped)
    return tuple(members)


def _looks_output_member(value: Any) -> bool:
    """Whether ``value`` looks like an OGC results output member (carries ``kind``)."""
    return isinstance(value, Mapping) and "kind" in value


def _primary_output_member(results: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the first output member carrying a ``kind`` field, if any."""
    members = _output_members(results)
    return members[0] if members else None


def results_kind(results: Mapping[str, Any]) -> str | None:
    """Return the ``kind`` of a results document's primary output, if declared.

    Reads ``outputs.*.kind`` (one of Honua's ``ArtifactKind`` values --
    ``Raster``, ``FeatureLayer``, ``Table``, ``Scalar``) from the OGC Processes
    results document returned by ``GET /ogc/processes/jobs/{id}/results``,
    tolerating the same document-shape variability the raster/feature selectors
    handle (bare member, outputs map, or ``value``-wrapped member). Returns
    ``None`` when no output declares a ``kind`` (for example a bare pass-through
    ``FeatureCollection``), in which case consumption falls back to sniffing.
    """
    member = _primary_output_member(results)
    if member is None:
        return None
    kind = member.get("kind")
    return kind if isinstance(kind, str) else None


def _is_feature_collection(value: Any) -> TypeGuard[Mapping[str, Any]]:
    """Whether ``value`` looks like a GeoJSON ``FeatureCollection``."""
    return (
        isinstance(value, Mapping)
        and value.get("type") == "FeatureCollection"
        and isinstance(value.get("features"), list)
    )


def _feature_collection_from_results(results: Mapping[str, Any]) -> JsonObject:
    """Select the FeatureCollection output from an OGC Processes results document.

    :meth:`HonuaGeoprocessing.results` returns the document-mode outputs map
    fetched from ``GET /ogc/processes/jobs/{id}/results`` -- not a bare
    FeatureCollection. The output is keyed by output id and, depending on
    server response mode, the FeatureCollection may be:

    * the whole document (a bare ``FeatureCollection`` passed through),
    * an outputs map with a single FeatureCollection-valued member, or
    * an OGC ``raw``/``value`` wrapped member where the FeatureCollection sits
      under a ``value`` key.

    The first FeatureCollection found is returned. A :class:`HonuaError` is
    raised when no FeatureCollection output is present so the failure is clear
    rather than yielding an empty GeoDataFrame.
    """
    if _is_feature_collection(results):
        return cast(JsonObject, dict(results))

    for member in results.values():
        if _is_feature_collection(member):
            return cast(JsonObject, dict(member))
        if isinstance(member, Mapping):
            wrapped = member.get("value")
            if _is_feature_collection(wrapped):
                return cast(JsonObject, dict(wrapped))

    raise HonuaError(
        "Geoprocessing results document does not contain a FeatureCollection output; "
        f"got output keys {sorted(results)!r}. "
        "execute_dataframe requires a feature-collection-out process."
    )


def _feature_collection_from_output(results: Mapping[str, Any]) -> JsonObject | None:
    """Best-effort, pure attempt to find a FeatureCollection in a results document.

    Tries the declared-kind output member's JSON payload first (the
    ``FeatureLayer`` shape published as a base64/``data:`` URI -- see
    :func:`_output_json_bytes` -- for example ``surface.contour``'s output),
    then falls back to :func:`_feature_collection_from_results` (the plain
    inline-FeatureCollection vector-process shape). Returns ``None`` rather than
    raising when neither is found, so a caller can decide what to do next (fetch
    a live href, fall back to another kind, ...) -- and, notably, without
    needing geopandas: this is pure selection logic only, no conversion.
    """
    member = _primary_output_member(results)
    if member is not None:
        data = _output_json_bytes(member)
        if data is not None:
            parsed = json.loads(data)
            if _is_feature_collection(parsed):
                return cast(JsonObject, parsed)
    try:
        return _feature_collection_from_results(results)
    except HonuaError:
        return None


def _async_prefer_header(respond_async: bool) -> dict[str, str] | None:
    return {"Prefer": "respond-async"} if respond_async else None


def _job_id_from_location(location: str | None) -> str | None:
    """Extract a job id from an OGC Processes ``Location`` header.

    The execution response points the ``Location`` header at the created job
    (``.../ogc/processes/jobs/{jobId}``); the job id is its last path segment.
    Returns ``None`` when the header is absent or carries no usable segment.
    """
    if not location:
        return None
    path = urlsplit(location).path.rstrip("/")
    if not path:
        return None
    segment = path.rsplit("/", 1)[-1]
    return unquote(segment) or None


def _job_from_response(response: Any) -> GeoprocessingJob:
    """Build a :class:`GeoprocessingJob` from an execution HTTP response.

    The OGC ``StatusInfo`` body is the primary source for the job id, but a
    ``201 Created`` with an empty body (or a synchronous execution that returns
    no ``jobID``) still identifies the job via the ``Location`` header. Fall
    back to parsing that header so the job stays pollable/dismissable.
    """
    body = response.json() if response.content else {}
    if not isinstance(body, Mapping):
        body = {}
    job = GeoprocessingJob.from_status_info(body)
    if not job.job_id:
        location_id = _job_id_from_location(response.headers.get("Location"))
        if location_id:
            job = replace(job, job_id=location_id)
    return job


def _processes_path(root: str) -> str:
    return f"{root}/processes"


def _process_path(root: str, process_id: str) -> str:
    return f"{root}/processes/{_encode_path_segment(process_id)}"


def _execution_path(root: str, process_id: str) -> str:
    return f"{_process_path(root, process_id)}/execution"


def _job_path(root: str, job_id: str) -> str:
    return f"{root}/jobs/{_encode_path_segment(job_id)}"


def _job_results_path(root: str, job_id: str) -> str:
    return f"{_job_path(root, job_id)}/results"


def _initial_poll_delay(poll_interval: float) -> float:
    return min(max(0.0, poll_interval), _MAX_POLL_INTERVAL)


def _next_poll_delay(current: float) -> float:
    if current <= 0.0:
        return 0.0
    return min(current * 2.0, _MAX_POLL_INTERVAL)


def _href_path_and_params(href: str) -> tuple[str, dict[str, str]]:
    """Split a (possibly absolute) ``href`` into a request path and query params.

    By-reference raster outputs point at a result on the same Honua host; only
    the path + query are forwarded so the bound client's base URL, auth, and
    retry policy apply (the host/scheme are taken from the client).
    """
    parsed = urlsplit(href)
    path = parsed.path or href
    return path, dict(parse_qsl(parsed.query, keep_blank_values=True))


class HonuaGeoprocessing:
    """Synchronous geoprocessing client built on OGC API Processes."""

    root = "/ogc/processes"

    def __init__(self, client: SupportsSyncRequest) -> None:
        self.client = client

    # -- discovery ---------------------------------------------------------

    def processes(self) -> JsonObject:
        """List the available processes."""
        return self.client._request_json("GET", _processes_path(self.root))

    def describe(self, process_id: str) -> JsonObject:
        """Describe one process (inputs, outputs, job-control options)."""
        return self.client._request_json("GET", _process_path(self.root, process_id))

    # -- raw execution -----------------------------------------------------

    def submit_inputs(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        response_mode: str | None = "document",
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a process with an explicit ``inputs`` bag and return the job.

        This is the lowest-level submit. The layer helpers
        (:meth:`submit` / :meth:`execute`), the single-geometry helper
        (:meth:`submit_geometry`), and the plan helper (:meth:`submit_plan`)
        build on top of it.
        """
        payload = _execute_payload(inputs, response_mode=response_mode)
        response = self.client._request(
            "POST",
            _execution_path(self.root, process_id),
            json_body=payload,
            headers=_async_prefer_header(respond_async),
        )
        return _job_from_response(response)

    def submit_raw(
        self,
        process_id: str,
        body: Mapping[str, Any],
        *,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a pre-built OGC execute body (``{"inputs": ...}`` and friends).

        Use this when you already have a complete execution body -- for example
        the codemod's translated ``{"inputs", "outputs", "metadata"}`` payload --
        and want it forwarded verbatim rather than rebuilt from keyword inputs.
        """
        response = self.client._request(
            "POST",
            _execution_path(self.root, process_id),
            json_body=dict(body),
            headers=_async_prefer_header(respond_async),
        )
        return _job_from_response(response)

    # -- single-geometry primitive ----------------------------------------

    def submit_geometry(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a single-geometry primitive process (one geometry in/out).

        A thin alias over :meth:`submit_inputs` that documents intent: callers
        pass the primitive inputs (for example a base64-WKB geometry plus
        ``srid``) rather than a layer reference.
        """
        return self.submit_inputs(process_id, inputs, respond_async=respond_async)

    def execute_geometry(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a single-geometry primitive to completion and return results."""
        job = self.submit_geometry(process_id, inputs)
        terminal = self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return self.results(terminal.job_id)

    # -- layer-ref-in -> layer-out ----------------------------------------

    def submit(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a vector layer-scope process and return the (pending) job.

        ``layer`` is a :class:`LayerReference` (inline GeoJSON FeatureCollection
        or query result); ``parameters`` carries the process-specific options
        (for example ``{"distance": 100}`` for ``geometry.buffer`` or
        ``{"targetSrid": 3857}`` for ``conversion.feature-project``).
        """
        inputs = _layer_inputs(layer, parameters)
        return self.submit_inputs(process_id, inputs, respond_async=respond_async)

    def execute(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a vector layer-scope process to completion and return the output.

        Submits the process (async job-style), polls to a terminal state, and
        returns the ``/results`` document. Raises :class:`GeoprocessingJobError`
        when the job fails, unless ``raise_on_failure`` is ``False``.
        """
        job = self.submit(process_id, layer, parameters=parameters)
        terminal = self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return self.results(terminal.job_id)

    def execute_dataframe(
        self,
        process_id: str,
        gdf: "gpd.GeoDataFrame",
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> "gpd.GeoDataFrame":
        """Run a vector process over a GeoDataFrame and return a GeoDataFrame.

        Convenience wrapper that converts ``gdf`` to an inline GeoJSON
        FeatureCollection, runs :meth:`execute`, and parses the output
        FeatureCollection back to a GeoDataFrame. Requires the ``geopandas``
        extra.
        """
        from .geopandas import geodataframe_to_geojson, ogc_features_to_geodataframe

        source_crs = gdf.crs
        layer = LayerReference.from_geojson(geodataframe_to_geojson(gdf))
        result = self.execute(
            process_id,
            layer,
            parameters=parameters,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        out = ogc_features_to_geodataframe(_feature_collection_from_results(result))
        # The result rides back as GeoJSON/WGS84; reapply the caller's source CRS
        # so a projected-in / projected-out round-trip preserves coordinates.
        if source_crs is not None and out.crs is not None:
            out = out.to_crs(source_crs)
        return out

    # -- raster result interop --------------------------------------------

    def result_raster_bytes(self, results: Mapping[str, Any]) -> bytes:
        """Return the GeoTIFF bytes of a results document's raster output.

        Selects the raster output (see
        :func:`honua_sdk.raster.find_raster_output`), decoding an inline base64
        ``value`` or fetching a by-reference ``href`` through the bound client
        (so base URL, auth, and retry policy apply). Raises
        :class:`~honua_sdk.errors.HonuaError` when no usable raster output is
        present.
        """
        from .raster import find_raster_output, inline_raster_bytes, raster_href

        member = find_raster_output(results)
        inline = inline_raster_bytes(member)
        if inline is not None:
            return inline
        href = raster_href(member)
        if href:
            # honua-server publishes rasters as a ``data:`` URI in ``href``
            # (GdalDataUri.Build), so decode that inline rather than fetching.
            data_uri = _data_uri_bytes(href)
            if data_uri is not None:
                return data_uri
            path, params = _href_path_and_params(href)
            return self.client._request("GET", path, params=params).content
        raise HonuaError("Raster output has neither an inline value nor an href to fetch.")

    def result_to_rasterio(self, results: Mapping[str, Any]) -> "rasterio.io.DatasetReader":
        """Open a results document's raster output as a :mod:`rasterio` dataset.

        Requires the ``raster`` extra (``pip install honua-sdk[raster]``).
        """
        from .raster import open_geotiff

        return open_geotiff(self.result_raster_bytes(results))

    def result_to_xarray(self, results: Mapping[str, Any]) -> "xarray.DataArray":
        """Convert a results document's raster output to an :class:`xarray.DataArray`.

        Requires the ``raster`` extra (``pip install honua-sdk[raster]``).
        """
        from .raster import geotiff_to_xarray

        return geotiff_to_xarray(self.result_raster_bytes(results))

    def execute_raster(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> "xarray.DataArray":
        """Run a raster-producing process and return the output as an xarray array.

        Convenience wrapper that runs :meth:`execute` and converts the raster
        output via :meth:`result_to_xarray`. Requires the ``raster`` extra.
        """
        result = self.execute(
            process_id,
            layer,
            parameters=parameters,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        return self.result_to_xarray(result)

    # -- raster-ref-in (surface/raster tools) -----------------------------

    def submit_raster_process(
        self,
        process_id: str,
        raster: RasterReference,
        *,
        zones: LayerReference | None = None,
        parameters: Mapping[str, Any] | None = None,
        plan_id: str | None = None,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a raster/surface process and return the (pending) job.

        ``raster`` is a :class:`RasterReference` (inline GeoTIFF ``source`` or a
        server-resolved ``layerId`` / ``rasterId``); ``zones`` is an optional
        inline-GeoJSON :class:`LayerReference` of zone polygons for
        ``raster.zonal-statistics``; ``parameters`` carries process options (for
        example ``{"units": "degrees"}`` for ``surface.slope``).

        Because every raster/surface process id 404s on direct execution, the
        call is transparently auto-wrapped as a single ``geoprocess`` step inside
        the canonical ``honua-geoprocessing`` ``plan`` and submitted through the
        existing plan machinery. Pass ``plan_id`` to override the generated id.
        """
        inputs = _raster_process_inputs(raster, zones, parameters)
        plan = _raster_plan(process_id, inputs, plan_id or _default_plan_id(process_id))
        return self.submit_plan(plan, respond_async=respond_async)

    def execute_raster_process(
        self,
        process_id: str,
        raster: RasterReference,
        *,
        zones: LayerReference | None = None,
        parameters: Mapping[str, Any] | None = None,
        plan_id: str | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a raster/surface process to completion and return the results document.

        Same ergonomics as :meth:`execute` for vector processes: submits (as an
        auto-wrapped single-step plan), polls to a terminal state, and returns
        the ``/results`` document. The output ``kind`` varies by tool (``Raster``
        for most, ``FeatureLayer`` for ``surface.contour``, ``Table`` for
        ``raster.zonal-statistics``, ``Scalar`` for
        ``raster.statistics``/``raster.histogram``); pass the returned document to
        :meth:`consume_result` to get the corresponding Python object without
        knowing the kind in advance.
        """
        inputs = _raster_process_inputs(raster, zones, parameters)
        plan = _raster_plan(process_id, inputs, plan_id or _default_plan_id(process_id))
        return self.execute_plan(
            plan,
            poll_interval=poll_interval,
            timeout=timeout,
            raise_on_failure=raise_on_failure,
        )

    # -- kind-routed result consumption -----------------------------------

    def _result_json_value(self, results: Mapping[str, Any]) -> Any:
        """Parse a ``Table``/``Scalar`` output's JSON value from a results document."""
        member = _primary_output_member(results) or results
        data = _output_json_bytes(member)
        if data is None:
            href = member.get("href")
            if isinstance(href, str) and href and not href.startswith("data:"):
                path, params = _href_path_and_params(href)
                data = self.client._request("GET", path, params=params).content
        if data is None:
            value = member.get("value")
            if isinstance(value, (dict, list)):
                return value
            raise HonuaError("Table/Scalar output has no decodable JSON payload.")
        return json.loads(data)

    def _result_feature_collection(self, results: Mapping[str, Any]) -> JsonObject:
        """Select a results document's FeatureCollection output.

        Pure selection plus, only when the pure attempt comes up empty, a live
        ``href`` fetch through the bound client -- no geopandas needed.
        :meth:`_result_geodataframe` is the thin geopandas-dependent conversion
        built on top of this.
        """
        found = _feature_collection_from_output(results)
        if found is not None:
            return found
        member = _primary_output_member(results)
        href = member.get("href") if member is not None else None
        if isinstance(href, str) and href and not href.startswith("data:"):
            path, params = _href_path_and_params(href)
            parsed = json.loads(self.client._request("GET", path, params=params).content)
            if _is_feature_collection(parsed):
                return cast(JsonObject, parsed)
        raise HonuaError(
            "Geoprocessing results document does not contain a FeatureCollection output; "
            f"got output keys {sorted(results)!r}."
        )

    def _result_geodataframe(self, results: Mapping[str, Any]) -> "gpd.GeoDataFrame":
        """Parse a ``FeatureLayer`` output to a GeoDataFrame (requires geopandas)."""
        from .geopandas import ogc_features_to_geodataframe

        return ogc_features_to_geodataframe(self._result_feature_collection(results))

    def consume_result(self, results: Mapping[str, Any]) -> Any:
        """Route a results document to the Python object matching its output kind.

        * ``Raster`` -> :class:`xarray.DataArray` (via :meth:`result_to_xarray`).
        * ``FeatureLayer`` -> a :class:`geopandas.GeoDataFrame`.
        * ``Table`` / ``Scalar`` -> the parsed JSON value (``dict`` / ``list``).
        * undeclared kind -> sniffed, in priority order: raster, then feature
          collection (via the pure :func:`_feature_collection_from_output`, so
          geopandas is only touched once a FeatureCollection payload is actually
          found), then a plain JSON value.

        Lets a caller consume :meth:`execute_raster_process` output without
        knowing in advance which kind a given ``process_id`` produces (xarray for
        ``surface.slope``, a GeoDataFrame for ``surface.contour``, a list-of-dicts
        for ``raster.zonal-statistics``). Raster/feature routing requires the
        corresponding optional extra (``raster`` / ``geopandas``).
        """
        kind = results_kind(results)
        if kind == "Raster":
            return self.result_to_xarray(results)
        if kind == "FeatureLayer":
            return self._result_geodataframe(results)
        if kind in ("Table", "Scalar"):
            return self._result_json_value(results)
        if kind is not None:
            raise HonuaError(f"Unsupported results kind {kind!r}.")
        from .raster import find_raster_output

        try:
            find_raster_output(results)
        except HonuaError:
            pass
        else:
            return self.result_to_xarray(results)
        if _feature_collection_from_output(results) is not None:
            return self._result_geodataframe(results)
        return self._result_json_value(results)

    # -- canonical multi-step plan ----------------------------------------

    def submit_plan(self, plan: Mapping[str, Any], *, respond_async: bool = True) -> GeoprocessingJob:
        """Submit a multi-step analysis ``plan`` to the canonical process.

        ``plan`` is the analysis-plan document (``{"planId", "steps", ...}``)
        understood by the ``honua-geoprocessing`` canonical process; each step
        names a ``kind`` (``geoprocess`` / ``queryFeatures`` / ...), an optional
        ``processId``, string ``inputs``, and ``dependsOn`` edges.
        """
        return self.submit_inputs(CANONICAL_PROCESS_ID, _plan_inputs(plan), respond_async=respond_async)

    def execute_plan(
        self,
        plan: Mapping[str, Any],
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Submit a multi-step plan to completion and return the results."""
        job = self.submit_plan(plan)
        terminal = self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return self.results(terminal.job_id)

    # -- job lifecycle -----------------------------------------------------

    def job(self, job_id: str) -> GeoprocessingJob:
        """Get the current status for a job."""
        payload = self.client._request_json("GET", _job_path(self.root, job_id))
        return GeoprocessingJob.from_status_info(payload)

    def results(self, job_id: str) -> JsonObject:
        """Fetch the results document for a (successful) job."""
        return self.client._request_json("GET", _job_results_path(self.root, job_id))

    def jobs(self) -> JsonObject:
        """List submitted jobs."""
        return self.client._request_json("GET", f"{self.root}/jobs")

    def dismiss(self, job_id: str) -> None:
        """Dismiss (cancel/forget) a job."""
        self.client._request_json("DELETE", _job_path(self.root, job_id))

    def _safe_dismiss(self, job_id: str) -> None:
        """Best-effort :meth:`dismiss`; never raises (cleanup-only path)."""
        if not job_id:
            return
        try:
            self.dismiss(job_id)
        except Exception:
            _LOGGER.debug(
                "Failed to dismiss geoprocessing job %r during cleanup.",
                job_id,
                exc_info=True,
            )

    def wait(
        self,
        job: GeoprocessingJob | str,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> GeoprocessingJob:
        """Poll a job until it reaches a terminal status (or ``timeout``).

        On timeout the pending server job is best-effort dismissed before the
        :class:`TimeoutError` propagates so it is not left orphaned.
        """
        job_id = job.job_id if isinstance(job, GeoprocessingJob) else str(job)
        current = job if isinstance(job, GeoprocessingJob) else self.job(job_id)
        deadline = None if timeout is None else time.monotonic() + timeout
        poll_delay = _initial_poll_delay(poll_interval)
        while not current.is_terminal:
            sleep_delay = poll_delay
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._safe_dismiss(job_id)
                    raise TimeoutError(
                        f"Geoprocessing job {job_id!r} did not reach a terminal status within {timeout}s "
                        f"(last status: {current.status!r})."
                    )
                sleep_delay = min(sleep_delay, remaining)
            time.sleep(sleep_delay)
            current = self.job(job_id)
            poll_delay = _next_poll_delay(poll_delay)
        return current


class AsyncHonuaGeoprocessing:
    """Asynchronous geoprocessing client built on OGC API Processes."""

    root = "/ogc/processes"

    def __init__(self, client: SupportsAsyncRequest) -> None:
        self.client = client

    # -- discovery ---------------------------------------------------------

    async def processes(self) -> JsonObject:
        """List the available processes."""
        return await self.client._request_json("GET", _processes_path(self.root))

    async def describe(self, process_id: str) -> JsonObject:
        """Describe one process (inputs, outputs, job-control options)."""
        return await self.client._request_json("GET", _process_path(self.root, process_id))

    # -- raw execution -----------------------------------------------------

    async def submit_inputs(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        response_mode: str | None = "document",
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a process with an explicit ``inputs`` bag and return the job."""
        payload = _execute_payload(inputs, response_mode=response_mode)
        response = await self.client._request(
            "POST",
            _execution_path(self.root, process_id),
            json_body=payload,
            headers=_async_prefer_header(respond_async),
        )
        return _job_from_response(response)

    async def submit_raw(
        self,
        process_id: str,
        body: Mapping[str, Any],
        *,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a pre-built OGC execute body (``{"inputs": ...}`` and friends)."""
        response = await self.client._request(
            "POST",
            _execution_path(self.root, process_id),
            json_body=dict(body),
            headers=_async_prefer_header(respond_async),
        )
        return _job_from_response(response)

    # -- single-geometry primitive ----------------------------------------

    async def submit_geometry(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a single-geometry primitive process (one geometry in/out)."""
        return await self.submit_inputs(process_id, inputs, respond_async=respond_async)

    async def execute_geometry(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a single-geometry primitive to completion and return results."""
        job = await self.submit_geometry(process_id, inputs)
        terminal = await self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return await self.results(terminal.job_id)

    # -- layer-ref-in -> layer-out ----------------------------------------

    async def submit(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a vector layer-scope process and return the (pending) job."""
        inputs = _layer_inputs(layer, parameters)
        return await self.submit_inputs(process_id, inputs, respond_async=respond_async)

    async def execute(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a vector layer-scope process to completion and return the output."""
        job = await self.submit(process_id, layer, parameters=parameters)
        terminal = await self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return await self.results(terminal.job_id)

    async def execute_dataframe(
        self,
        process_id: str,
        gdf: "gpd.GeoDataFrame",
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> "gpd.GeoDataFrame":
        """Run a vector process over a GeoDataFrame and return a GeoDataFrame."""
        from .geopandas import geodataframe_to_geojson, ogc_features_to_geodataframe

        source_crs = gdf.crs
        layer = LayerReference.from_geojson(geodataframe_to_geojson(gdf))
        result = await self.execute(
            process_id,
            layer,
            parameters=parameters,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        out = ogc_features_to_geodataframe(_feature_collection_from_results(result))
        # The result rides back as GeoJSON/WGS84; reapply the caller's source CRS
        # so a projected-in / projected-out round-trip preserves coordinates.
        if source_crs is not None and out.crs is not None:
            out = out.to_crs(source_crs)
        return out

    # -- raster result interop --------------------------------------------

    async def result_raster_bytes(self, results: Mapping[str, Any]) -> bytes:
        """Return the GeoTIFF bytes of a results document's raster output."""
        from .raster import find_raster_output, inline_raster_bytes, raster_href

        member = find_raster_output(results)
        inline = inline_raster_bytes(member)
        if inline is not None:
            return inline
        href = raster_href(member)
        if href:
            # honua-server publishes rasters as a ``data:`` URI in ``href``
            # (GdalDataUri.Build), so decode that inline rather than fetching.
            data_uri = _data_uri_bytes(href)
            if data_uri is not None:
                return data_uri
            path, params = _href_path_and_params(href)
            response = await self.client._request("GET", path, params=params)
            return response.content
        raise HonuaError("Raster output has neither an inline value nor an href to fetch.")

    async def result_to_rasterio(self, results: Mapping[str, Any]) -> "rasterio.io.DatasetReader":
        """Open a results document's raster output as a :mod:`rasterio` dataset.

        Requires the ``raster`` extra (``pip install honua-sdk[raster]``).
        """
        from .raster import open_geotiff

        return open_geotiff(await self.result_raster_bytes(results))

    async def result_to_xarray(self, results: Mapping[str, Any]) -> "xarray.DataArray":
        """Convert a results document's raster output to an :class:`xarray.DataArray`.

        Requires the ``raster`` extra (``pip install honua-sdk[raster]``).
        """
        from .raster import geotiff_to_xarray

        return geotiff_to_xarray(await self.result_raster_bytes(results))

    async def execute_raster(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> "xarray.DataArray":
        """Run a raster-producing process and return the output as an xarray array.

        Convenience wrapper that runs :meth:`execute` and converts the raster
        output via :meth:`result_to_xarray`. Requires the ``raster`` extra.
        """
        result = await self.execute(
            process_id,
            layer,
            parameters=parameters,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        return await self.result_to_xarray(result)

    # -- raster-ref-in (surface/raster tools) -----------------------------

    async def submit_raster_process(
        self,
        process_id: str,
        raster: RasterReference,
        *,
        zones: LayerReference | None = None,
        parameters: Mapping[str, Any] | None = None,
        plan_id: str | None = None,
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a raster/surface process and return the (pending) job.

        Async twin of :meth:`HonuaGeoprocessing.submit_raster_process`; the call
        is transparently auto-wrapped as a single ``geoprocess`` step inside the
        canonical ``honua-geoprocessing`` ``plan`` (raster ids 404 on direct
        execution).
        """
        inputs = _raster_process_inputs(raster, zones, parameters)
        plan = _raster_plan(process_id, inputs, plan_id or _default_plan_id(process_id))
        return await self.submit_plan(plan, respond_async=respond_async)

    async def execute_raster_process(
        self,
        process_id: str,
        raster: RasterReference,
        *,
        zones: LayerReference | None = None,
        parameters: Mapping[str, Any] | None = None,
        plan_id: str | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a raster/surface process to completion and return the results document.

        Async twin of :meth:`HonuaGeoprocessing.execute_raster_process`. Pass the
        returned document to :meth:`consume_result` to get the corresponding
        Python object for whatever ``kind`` the tool produced.
        """
        inputs = _raster_process_inputs(raster, zones, parameters)
        plan = _raster_plan(process_id, inputs, plan_id or _default_plan_id(process_id))
        return await self.execute_plan(
            plan,
            poll_interval=poll_interval,
            timeout=timeout,
            raise_on_failure=raise_on_failure,
        )

    # -- kind-routed result consumption -----------------------------------

    async def _result_json_value(self, results: Mapping[str, Any]) -> Any:
        """Parse a ``Table``/``Scalar`` output's JSON value from a results document."""
        member = _primary_output_member(results) or results
        data = _output_json_bytes(member)
        if data is None:
            href = member.get("href")
            if isinstance(href, str) and href and not href.startswith("data:"):
                path, params = _href_path_and_params(href)
                response = await self.client._request("GET", path, params=params)
                data = response.content
        if data is None:
            value = member.get("value")
            if isinstance(value, (dict, list)):
                return value
            raise HonuaError("Table/Scalar output has no decodable JSON payload.")
        return json.loads(data)

    async def _result_feature_collection(self, results: Mapping[str, Any]) -> JsonObject:
        """Select a results document's FeatureCollection output.

        Pure selection plus, only when the pure attempt comes up empty, a live
        ``href`` fetch through the bound client -- no geopandas needed.
        :meth:`_result_geodataframe` is the thin geopandas-dependent conversion
        built on top of this.
        """
        found = _feature_collection_from_output(results)
        if found is not None:
            return found
        member = _primary_output_member(results)
        href = member.get("href") if member is not None else None
        if isinstance(href, str) and href and not href.startswith("data:"):
            path, params = _href_path_and_params(href)
            response = await self.client._request("GET", path, params=params)
            parsed = json.loads(response.content)
            if _is_feature_collection(parsed):
                return cast(JsonObject, parsed)
        raise HonuaError(
            "Geoprocessing results document does not contain a FeatureCollection output; "
            f"got output keys {sorted(results)!r}."
        )

    async def _result_geodataframe(self, results: Mapping[str, Any]) -> "gpd.GeoDataFrame":
        """Parse a ``FeatureLayer`` output to a GeoDataFrame (requires geopandas)."""
        from .geopandas import ogc_features_to_geodataframe

        return ogc_features_to_geodataframe(await self._result_feature_collection(results))

    async def consume_result(self, results: Mapping[str, Any]) -> Any:
        """Route a results document to the Python object matching its output kind.

        Async twin of :meth:`HonuaGeoprocessing.consume_result`: ``Raster`` ->
        :class:`xarray.DataArray`, ``FeatureLayer`` -> GeoDataFrame,
        ``Table``/``Scalar`` -> parsed JSON, undeclared kind -> sniffed (raster,
        then feature collection via the pure :func:`_feature_collection_from_output`,
        then a plain JSON value).
        """
        kind = results_kind(results)
        if kind == "Raster":
            return await self.result_to_xarray(results)
        if kind == "FeatureLayer":
            return await self._result_geodataframe(results)
        if kind in ("Table", "Scalar"):
            return await self._result_json_value(results)
        if kind is not None:
            raise HonuaError(f"Unsupported results kind {kind!r}.")
        from .raster import find_raster_output

        try:
            find_raster_output(results)
        except HonuaError:
            pass
        else:
            return await self.result_to_xarray(results)
        if _feature_collection_from_output(results) is not None:
            return await self._result_geodataframe(results)
        return await self._result_json_value(results)

    # -- canonical multi-step plan ----------------------------------------

    async def submit_plan(self, plan: Mapping[str, Any], *, respond_async: bool = True) -> GeoprocessingJob:
        """Submit a multi-step analysis ``plan`` to the canonical process."""
        return await self.submit_inputs(
            CANONICAL_PROCESS_ID, _plan_inputs(plan), respond_async=respond_async
        )

    async def execute_plan(
        self,
        plan: Mapping[str, Any],
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Submit a multi-step plan to completion and return the results."""
        job = await self.submit_plan(plan)
        terminal = await self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return await self.results(terminal.job_id)

    # -- job lifecycle -----------------------------------------------------

    async def job(self, job_id: str) -> GeoprocessingJob:
        """Get the current status for a job."""
        payload = await self.client._request_json("GET", _job_path(self.root, job_id))
        return GeoprocessingJob.from_status_info(payload)

    async def results(self, job_id: str) -> JsonObject:
        """Fetch the results document for a (successful) job."""
        return await self.client._request_json("GET", _job_results_path(self.root, job_id))

    async def jobs(self) -> JsonObject:
        """List submitted jobs."""
        return await self.client._request_json("GET", f"{self.root}/jobs")

    async def dismiss(self, job_id: str) -> None:
        """Dismiss (cancel/forget) a job."""
        await self.client._request_json("DELETE", _job_path(self.root, job_id))

    async def _safe_dismiss(self, job_id: str) -> None:
        """Best-effort :meth:`dismiss`; never raises (cleanup-only path)."""
        if not job_id:
            return
        try:
            await self.dismiss(job_id)
        except Exception:
            _LOGGER.debug(
                "Failed to dismiss geoprocessing job %r during cleanup.",
                job_id,
                exc_info=True,
            )

    async def wait(
        self,
        job: GeoprocessingJob | str,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> GeoprocessingJob:
        """Poll a job until it reaches a terminal status (or ``timeout``).

        On timeout — or when the awaiting task is cancelled — the pending server
        job is best-effort dismissed before the exception propagates so it is
        not left orphaned.
        """
        import asyncio

        job_id = job.job_id if isinstance(job, GeoprocessingJob) else str(job)
        current = job if isinstance(job, GeoprocessingJob) else await self.job(job_id)
        deadline = None if timeout is None else time.monotonic() + timeout
        poll_delay = _initial_poll_delay(poll_interval)
        try:
            while not current.is_terminal:
                sleep_delay = poll_delay
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        await self._safe_dismiss(job_id)
                        raise TimeoutError(
                            f"Geoprocessing job {job_id!r} did not reach a terminal status within {timeout}s "
                            f"(last status: {current.status!r})."
                        )
                    sleep_delay = min(sleep_delay, remaining)
                await asyncio.sleep(sleep_delay)
                current = await self.job(job_id)
                poll_delay = _next_poll_delay(poll_delay)
        except asyncio.CancelledError:
            await self._safe_dismiss(job_id)
            raise
        return current

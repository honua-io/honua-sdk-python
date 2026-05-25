"""First-class geoprocessing (GP) clients for Honua Server.

Honua exposes geoprocessing through OGC API Processes. There are two shapes:

* **Layer-scope execution** (the canonical ergonomic path): a process takes an
  *input layer reference* -- a catalog layer id, an inline GeoJSON
  ``FeatureCollection``, or a stored query result -- streams the features,
  applies the operation across the whole collection (carrying attributes
  through), and produces an *output layer / artifact* (a GeoJSON
  ``FeatureCollection``). Reach it with :meth:`HonuaGeoprocessing.execute_layer`
  (submit + poll to terminal) or :meth:`HonuaGeoprocessing.submit_layer`
  (async submit returning a pollable :class:`GeoprocessingJob`).

* **Single-geometry primitive** (lower level): one geometry in, one geometry
  out, addressed through :meth:`HonuaGeoprocessing.execute`.

Both the synchronous (:class:`HonuaGeoprocessing`) and asynchronous
(:class:`AsyncHonuaGeoprocessing`) clients mirror the OGC API Processes wire
contract used by :class:`honua_sdk.protocols.OgcProcessesClient`: execution is
``POST /ogc/processes/processes/{processId}/execution`` with a
``{"inputs": {...}}`` body, status is polled on
``/ogc/processes/jobs/{jobId}``, and results are fetched from
``/ogc/processes/jobs/{jobId}/results``.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from ._http import _encode_path_segment
from .errors import HonuaError

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

JsonObject = dict[str, Any]
LayerReferenceKind = Literal["inlineGeoJson", "layerId", "queryResult"]

#: OGC job statuses that are terminal (no further transition will occur).
TERMINAL_JOB_STATUSES: frozenset[str] = frozenset({"successful", "failed", "dismissed"})

#: Process ids that execute at *layer scope* (feature-collection in/out) today.
#: These mirror ``LayerGeometryJobExecutor.HandledProcessIds`` server-side.
LAYER_SCOPE_PROCESS_IDS: frozenset[str] = frozenset(
    {
        "generalization.simplify-layer",
        "conversion.feature-project",
        "geometry.make-valid",
        "geometry.difference",
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
    """A reference to the input feature collection a layer-scope GP process runs on.

    Exactly one of the carriers is populated according to :attr:`kind`. Use the
    classmethod constructors rather than building this by hand:

    * :meth:`from_geojson` -- an inline GeoJSON ``FeatureCollection``.
    * :meth:`from_layer` -- a catalog layer id (optionally SQL-filtered).
    * :meth:`from_query_result` -- a previously materialized query result id.
    """

    kind: LayerReferenceKind
    inline_geojson: Mapping[str, Any] | None = None
    layer_id: str | None = None
    query_result_id: str | None = None
    where: str | None = None

    @classmethod
    def from_geojson(cls, feature_collection: Mapping[str, Any]) -> "LayerReference":
        """Build a reference from an inline GeoJSON ``FeatureCollection``."""
        return cls(kind="inlineGeoJson", inline_geojson=feature_collection)

    @classmethod
    def from_layer(cls, layer_id: str, *, where: str | None = None) -> "LayerReference":
        """Build a reference to a catalog layer id, optionally SQL-filtered."""
        return cls(kind="layerId", layer_id=str(layer_id), where=where)

    @classmethod
    def from_query_result(cls, query_result_id: str, *, where: str | None = None) -> "LayerReference":
        """Build a reference to a previously materialized query-result id."""
        return cls(kind="queryResult", query_result_id=str(query_result_id), where=where)

    def to_inputs(self) -> JsonObject:
        """Project this reference onto the OGC Processes ``inputs`` keys.

        The server's layer-scope executor reads ``inputGeoJson`` (an inline
        FeatureCollection serialized as a string), ``layerId``, ``queryResultId``,
        and an optional ``where`` filter from the canonical step-input bag.
        """
        import json

        inputs: JsonObject = {}
        if self.kind == "inlineGeoJson":
            if self.inline_geojson is None:
                raise ValueError("inlineGeoJson layer reference requires a feature collection.")
            inputs["inputGeoJson"] = json.dumps(self.inline_geojson, separators=(",", ":"))
        elif self.kind == "layerId":
            if not self.layer_id:
                raise ValueError("layerId layer reference requires a layer id.")
            inputs["layerId"] = self.layer_id
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


def _layer_inputs(reference: LayerReference, parameters: Mapping[str, Any] | None) -> JsonObject:
    inputs = reference.to_inputs()
    if parameters:
        for key, value in parameters.items():
            # OGC inputs for non-canonical processes are stringified server-side;
            # pass booleans/numbers through as JSON-friendly strings for clarity.
            inputs[key] = value if isinstance(value, str) else _stringify(value)
    return inputs


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _async_prefer_header(respond_async: bool) -> dict[str, str] | None:
    return {"Prefer": "respond-async"} if respond_async else None


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


class HonuaGeoprocessing:
    """Synchronous geoprocessing client built on OGC API Processes."""

    root = "/ogc/processes"

    def __init__(self, client: Any) -> None:
        self.client = client

    # -- discovery ---------------------------------------------------------

    def processes(self) -> JsonObject:
        """List the available processes."""
        return self.client._request_json("GET", _processes_path(self.root))

    def describe(self, process_id: str) -> JsonObject:
        """Describe one process (inputs, outputs, job-control options)."""
        return self.client._request_json("GET", _process_path(self.root, process_id))

    # -- raw execution -----------------------------------------------------

    def execute(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        response_mode: str | None = "document",
        respond_async: bool = False,
    ) -> GeoprocessingJob:
        """Submit a process with an explicit ``inputs`` bag and return the job.

        This is the lowest-level submit. Layer-scope helpers
        (:meth:`submit_layer` / :meth:`execute_layer`) and the single-geometry
        helper (:meth:`execute_geometry`) build on top of it.
        """
        payload = _execute_payload(inputs, response_mode=response_mode)
        response = self.client._request(
            "POST",
            _execution_path(self.root, process_id),
            json_body=payload,
            headers=_async_prefer_header(respond_async),
        )
        body = response.json() if response.content else {}
        if not isinstance(body, Mapping):
            body = {}
        return GeoprocessingJob.from_status_info(body)

    def execute_geometry(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        response_mode: str | None = "document",
        respond_async: bool = False,
    ) -> GeoprocessingJob:
        """Submit a single-geometry primitive process (one geometry in/out).

        A thin alias over :meth:`execute` that documents intent: callers pass
        the primitive inputs (for example a base64-WKB geometry plus ``srid``)
        rather than a layer reference.
        """
        return self.execute(
            process_id,
            inputs,
            response_mode=response_mode,
            respond_async=respond_async,
        )

    def submit_raw(
        self,
        process_id: str,
        body: Mapping[str, Any],
        *,
        respond_async: bool = False,
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
        result = response.json() if response.content else {}
        if not isinstance(result, Mapping):
            result = {}
        return GeoprocessingJob.from_status_info(result)

    # -- layer-ref-in -> layer-out ----------------------------------------

    def submit_layer(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        response_mode: str | None = "document",
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a layer-scope process and return the (likely pending) job.

        ``layer`` is a :class:`LayerReference` (catalog layer id, inline GeoJSON
        FeatureCollection, or query result); ``parameters`` carries the
        process-specific options (for example ``{"tolerance": 10}`` for
        ``generalization.simplify-layer`` or ``{"targetSrid": 3857}`` for
        ``conversion.feature-project``).
        """
        inputs = _layer_inputs(layer, parameters)
        return self.execute(
            process_id,
            inputs,
            response_mode=response_mode,
            respond_async=respond_async,
        )

    def execute_layer(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a layer-scope process to completion and return the output layer.

        Submits the process (async job-style), polls to a terminal state, and
        returns the ``/results`` document -- a GeoJSON ``FeatureCollection`` (the
        output layer / artifact). Raises :class:`GeoprocessingJobError` when the
        job fails, unless ``raise_on_failure`` is ``False``.
        """
        job = self.submit_layer(process_id, layer, parameters=parameters, respond_async=True)
        terminal = self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return self.results(terminal.job_id)

    def execute_layer_dataframe(
        self,
        process_id: str,
        gdf: "gpd.GeoDataFrame",
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> "gpd.GeoDataFrame":
        """Run a layer-scope process over a GeoDataFrame and return a GeoDataFrame.

        Convenience wrapper that converts ``gdf`` to inline GeoJSON, runs
        :meth:`execute_layer`, and parses the output FeatureCollection back to a
        GeoDataFrame. Requires the ``geopandas`` extra.
        """
        from .geopandas import geodataframe_to_geojson, ogc_features_to_geodataframe

        layer = LayerReference.from_geojson(geodataframe_to_geojson(gdf))
        result = self.execute_layer(
            process_id,
            layer,
            parameters=parameters,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        return ogc_features_to_geodataframe(result)

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

    def wait(
        self,
        job: GeoprocessingJob | str,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> GeoprocessingJob:
        """Poll a job until it reaches a terminal status (or ``timeout``)."""
        job_id = job.job_id if isinstance(job, GeoprocessingJob) else str(job)
        current = job if isinstance(job, GeoprocessingJob) else self.job(job_id)
        deadline = None if timeout is None else time.monotonic() + timeout
        while not current.is_terminal:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Geoprocessing job {job_id!r} did not reach a terminal status within {timeout}s "
                    f"(last status: {current.status!r})."
                )
            time.sleep(max(0.0, poll_interval))
            current = self.job(job_id)
        return current


class AsyncHonuaGeoprocessing:
    """Asynchronous geoprocessing client built on OGC API Processes."""

    root = "/ogc/processes"

    def __init__(self, client: Any) -> None:
        self.client = client

    # -- discovery ---------------------------------------------------------

    async def processes(self) -> JsonObject:
        """List the available processes."""
        return await self.client._request_json("GET", _processes_path(self.root))

    async def describe(self, process_id: str) -> JsonObject:
        """Describe one process (inputs, outputs, job-control options)."""
        return await self.client._request_json("GET", _process_path(self.root, process_id))

    # -- raw execution -----------------------------------------------------

    async def execute(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        response_mode: str | None = "document",
        respond_async: bool = False,
    ) -> GeoprocessingJob:
        """Submit a process with an explicit ``inputs`` bag and return the job."""
        payload = _execute_payload(inputs, response_mode=response_mode)
        response = await self.client._request(
            "POST",
            _execution_path(self.root, process_id),
            json_body=payload,
            headers=_async_prefer_header(respond_async),
        )
        body = response.json() if response.content else {}
        if not isinstance(body, Mapping):
            body = {}
        return GeoprocessingJob.from_status_info(body)

    async def execute_geometry(
        self,
        process_id: str,
        inputs: Mapping[str, Any],
        *,
        response_mode: str | None = "document",
        respond_async: bool = False,
    ) -> GeoprocessingJob:
        """Submit a single-geometry primitive process (one geometry in/out)."""
        return await self.execute(
            process_id,
            inputs,
            response_mode=response_mode,
            respond_async=respond_async,
        )

    async def submit_raw(
        self,
        process_id: str,
        body: Mapping[str, Any],
        *,
        respond_async: bool = False,
    ) -> GeoprocessingJob:
        """Submit a pre-built OGC execute body (``{"inputs": ...}`` and friends)."""
        response = await self.client._request(
            "POST",
            _execution_path(self.root, process_id),
            json_body=dict(body),
            headers=_async_prefer_header(respond_async),
        )
        result = response.json() if response.content else {}
        if not isinstance(result, Mapping):
            result = {}
        return GeoprocessingJob.from_status_info(result)

    # -- layer-ref-in -> layer-out ----------------------------------------

    async def submit_layer(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        response_mode: str | None = "document",
        respond_async: bool = True,
    ) -> GeoprocessingJob:
        """Submit a layer-scope process and return the (likely pending) job."""
        inputs = _layer_inputs(layer, parameters)
        return await self.execute(
            process_id,
            inputs,
            response_mode=response_mode,
            respond_async=respond_async,
        )

    async def execute_layer(
        self,
        process_id: str,
        layer: LayerReference,
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> JsonObject:
        """Run a layer-scope process to completion and return the output layer."""
        job = await self.submit_layer(process_id, layer, parameters=parameters, respond_async=True)
        terminal = await self.wait(job, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise GeoprocessingJobError(terminal)
        return await self.results(terminal.job_id)

    async def execute_layer_dataframe(
        self,
        process_id: str,
        gdf: "gpd.GeoDataFrame",
        *,
        parameters: Mapping[str, Any] | None = None,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> "gpd.GeoDataFrame":
        """Run a layer-scope process over a GeoDataFrame and return a GeoDataFrame."""
        from .geopandas import geodataframe_to_geojson, ogc_features_to_geodataframe

        layer = LayerReference.from_geojson(geodataframe_to_geojson(gdf))
        result = await self.execute_layer(
            process_id,
            layer,
            parameters=parameters,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        return ogc_features_to_geodataframe(result)

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

    async def wait(
        self,
        job: GeoprocessingJob | str,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> GeoprocessingJob:
        """Poll a job until it reaches a terminal status (or ``timeout``)."""
        import asyncio

        job_id = job.job_id if isinstance(job, GeoprocessingJob) else str(job)
        current = job if isinstance(job, GeoprocessingJob) else await self.job(job_id)
        deadline = None if timeout is None else time.monotonic() + timeout
        while not current.is_terminal:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Geoprocessing job {job_id!r} did not reach a terminal status within {timeout}s "
                    f"(last status: {current.status!r})."
                )
            await asyncio.sleep(max(0.0, poll_interval))
            current = await self.job(job_id)
        return current

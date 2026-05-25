"""GeoETL pipeline clients for Honua Server.

Honua's GeoETL feature lets you author *pipeline definitions* -- an ordered
chain of stages (``source`` -> ``transform``\\* -> ``sink``) -- and run them on a
durable job substrate. This module mirrors the server wire contract under
``/api/v{version}/admin/geoetl/pipelines``:

* CRUD on definitions (create / get / list / update / delete),
* ``run`` and ``dry-run`` (submit an execution, returns ``202 Accepted``),
* execution status (list / get), pollable to a terminal state.

A :class:`PipelineDefinition` models the stage chain as typed Python objects:
:class:`SourceStage` / :class:`TransformStage` / :class:`SinkStage`, each wrapping
a connector/transform ``type`` discriminator plus a string ``options`` map. The
``type`` and ``options`` are passed through to the server, which validates the
stage chain, so unknown connector/transform types are accepted by the client and
rejected (with advisories) by the server -- keeping the SDK forward-compatible.

Both :class:`HonuaEtl` (sync) and :class:`AsyncHonuaEtl` (async) are provided.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ._http import _encode_path_segment
from .errors import HonuaError

JsonObject = dict[str, Any]
StageKind = Literal["source", "transform", "sink"]

#: GeoETL execution statuses that are terminal.
TERMINAL_EXECUTION_STATUSES: frozenset[str] = frozenset({"Succeeded", "Failed", "Cancelled"})

_DEFAULT_API_VERSION = "1.0"


class PipelineExecutionError(HonuaError):
    """Raised when a pipeline execution reaches a non-successful terminal state."""

    def __init__(self, execution: "PipelineExecution") -> None:
        self.execution = execution
        message = (
            execution.error_message
            or f"Pipeline execution {execution.id!r} ended with status {execution.status!r}."
        )
        super().__init__(message)


@dataclass(frozen=True)
class ConnectorConfig:
    """A source/sink connector configuration (a ``type`` plus string options)."""

    type: str
    options: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {"type": self.type, "options": {str(k): str(v) for k, v in self.options.items()}}


@dataclass(frozen=True)
class TransformConfig:
    """A transform configuration (a ``type`` plus string options)."""

    type: str
    options: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {"type": self.type, "options": {str(k): str(v) for k, v in self.options.items()}}


@dataclass(frozen=True)
class PipelineStage:
    """One stage in a pipeline definition.

    Use the :class:`SourceStage`, :class:`TransformStage`, and :class:`SinkStage`
    constructors rather than building this directly.
    """

    kind: StageKind
    connector: ConnectorConfig | None = None
    transform: TransformConfig | None = None

    def to_dict(self) -> JsonObject:
        stage: JsonObject = {"kind": self.kind}
        if self.connector is not None:
            stage["connector"] = self.connector.to_dict()
        if self.transform is not None:
            stage["transform"] = self.transform.to_dict()
        return stage

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PipelineStage":
        connector = payload.get("connector")
        transform = payload.get("transform")
        return cls(
            kind=str(payload.get("kind") or ""),  # type: ignore[arg-type]
            connector=(
                ConnectorConfig(
                    type=str(connector.get("type") or ""),
                    options={str(k): str(v) for k, v in (connector.get("options") or {}).items()},
                )
                if isinstance(connector, Mapping)
                else None
            ),
            transform=(
                TransformConfig(
                    type=str(transform.get("type") or ""),
                    options={str(k): str(v) for k, v in (transform.get("options") or {}).items()},
                )
                if isinstance(transform, Mapping)
                else None
            ),
        )


def SourceStage(connector_type: str, options: Mapping[str, str] | None = None) -> PipelineStage:
    """Build a ``source`` stage (for example ``geojson`` / ``csv`` / ``shapefile``)."""
    return PipelineStage(kind="source", connector=ConnectorConfig(connector_type, options or {}))


def TransformStage(transform_type: str, options: Mapping[str, str] | None = None) -> PipelineStage:
    """Build a ``transform`` stage (for example ``reproject`` / ``clip`` / ``dedup``)."""
    return PipelineStage(kind="transform", transform=TransformConfig(transform_type, options or {}))


def SinkStage(connector_type: str, options: Mapping[str, str] | None = None) -> PipelineStage:
    """Build a ``sink`` stage (for example ``honua-layer`` / ``geojson-file``)."""
    return PipelineStage(kind="sink", connector=ConnectorConfig(connector_type, options or {}))


@dataclass(frozen=True)
class PipelineDefinition:
    """A GeoETL pipeline definition (source -> transform\\* -> sink chain)."""

    name: str
    stages: Sequence[PipelineStage]
    description: str | None = None
    schema_version: int = 1
    # Server-assigned fields, populated when read back.
    id: str | None = None
    version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    advisories: tuple[str, ...] = ()

    def to_request(self) -> JsonObject:
        """Build the create/update request body."""
        body: JsonObject = {
            "schema_version": self.schema_version,
            "name": self.name,
            "stages": [stage.to_dict() for stage in self.stages],
        }
        if self.description is not None:
            body["description"] = self.description
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PipelineDefinition":
        stages_raw = payload.get("stages")
        stages = (
            [PipelineStage.from_dict(stage) for stage in stages_raw if isinstance(stage, Mapping)]
            if isinstance(stages_raw, list)
            else []
        )
        advisories_raw = payload.get("advisories")
        advisories = (
            tuple(str(item) for item in advisories_raw) if isinstance(advisories_raw, list) else ()
        )
        return cls(
            name=str(payload.get("name") or ""),
            stages=stages,
            description=payload.get("description"),
            schema_version=int(payload.get("schema_version") or 1),
            id=payload.get("id"),
            version=payload.get("version") if isinstance(payload.get("version"), int) else None,
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            advisories=advisories,
        )


@dataclass(frozen=True)
class PipelineExecution:
    """A GeoETL pipeline execution record."""

    id: str
    pipeline_id: str
    status: str
    pipeline_version: int | None = None
    execution_job_id: str | None = None
    is_dry_run: bool = False
    features_read: int = 0
    features_written: int = 0
    features_quarantined: int = 0
    batch_id: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PipelineExecution":
        return cls(
            id=str(payload.get("id") or ""),
            pipeline_id=str(payload.get("pipeline_id") or ""),
            status=str(payload.get("status") or ""),
            pipeline_version=(
                payload.get("pipeline_version")
                if isinstance(payload.get("pipeline_version"), int)
                else None
            ),
            execution_job_id=payload.get("execution_job_id"),
            is_dry_run=bool(payload.get("is_dry_run", False)),
            features_read=int(payload.get("features_read") or 0),
            features_written=int(payload.get("features_written") or 0),
            features_quarantined=int(payload.get("features_quarantined") or 0),
            batch_id=payload.get("batch_id"),
            error_message=payload.get("error_message"),
            created_at=payload.get("created_at"),
            completed_at=payload.get("completed_at"),
            raw=dict(payload),
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the execution has reached a terminal status."""
        return self.status in TERMINAL_EXECUTION_STATUSES

    @property
    def succeeded(self) -> bool:
        """Whether the execution finished successfully."""
        return self.status == "Succeeded"


def _pipelines_root(api_version: str) -> str:
    return f"/api/v{api_version}/admin/geoetl/pipelines"


def _pipeline_path(api_version: str, pipeline_id: str) -> str:
    return f"{_pipelines_root(api_version)}/{_encode_path_segment(pipeline_id)}"


def _executions_path(api_version: str, pipeline_id: str) -> str:
    return f"{_pipeline_path(api_version, pipeline_id)}/executions"


def _execution_path(api_version: str, pipeline_id: str, execution_id: str) -> str:
    return f"{_executions_path(api_version, pipeline_id)}/{_encode_path_segment(execution_id)}"


def _unwrap_data(payload: Mapping[str, Any]) -> JsonObject:
    """Unwrap the ``ApiResponse<T>`` ``{"success", "data", ...}`` envelope."""
    if isinstance(payload, Mapping) and "data" in payload and isinstance(payload.get("data"), Mapping):
        return dict(payload["data"])
    return dict(payload)


def _executions_from(payload: Mapping[str, Any]) -> list[JsonObject]:
    data = _unwrap_data(payload)
    executions = data.get("executions")
    if isinstance(executions, list):
        return [item for item in executions if isinstance(item, Mapping)]
    return []


def _pipelines_from(payload: Mapping[str, Any]) -> list[JsonObject]:
    data = _unwrap_data(payload)
    pipelines = data.get("pipelines")
    if isinstance(pipelines, list):
        return [item for item in pipelines if isinstance(item, Mapping)]
    return []


class HonuaEtl:
    """Synchronous GeoETL pipeline client."""

    def __init__(self, client: Any, *, api_version: str = _DEFAULT_API_VERSION) -> None:
        self.client = client
        self.api_version = api_version

    # -- definitions -------------------------------------------------------

    def create(self, definition: PipelineDefinition) -> PipelineDefinition:
        """Create a pipeline definition; returns it with server-assigned fields."""
        payload = self.client._request_json(
            "POST", _pipelines_root(self.api_version), json_body=definition.to_request()
        )
        return PipelineDefinition.from_dict(_unwrap_data(payload))

    def get(self, pipeline_id: str) -> PipelineDefinition:
        """Get one pipeline definition by id."""
        payload = self.client._request_json("GET", _pipeline_path(self.api_version, pipeline_id))
        return PipelineDefinition.from_dict(_unwrap_data(payload))

    def list(self) -> list[PipelineDefinition]:
        """List all pipeline definitions."""
        payload = self.client._request_json("GET", _pipelines_root(self.api_version))
        return [PipelineDefinition.from_dict(item) for item in _pipelines_from(payload)]

    def update(self, pipeline_id: str, definition: PipelineDefinition) -> PipelineDefinition:
        """Replace a pipeline definition."""
        payload = self.client._request_json(
            "PUT", _pipeline_path(self.api_version, pipeline_id), json_body=definition.to_request()
        )
        return PipelineDefinition.from_dict(_unwrap_data(payload))

    def delete(self, pipeline_id: str) -> None:
        """Delete a pipeline definition."""
        self.client._request_json("DELETE", _pipeline_path(self.api_version, pipeline_id))

    # -- execution ---------------------------------------------------------

    def run(self, pipeline_id: str) -> PipelineExecution:
        """Submit a pipeline run through the durable substrate."""
        payload = self.client._request_json("POST", f"{_pipeline_path(self.api_version, pipeline_id)}/run")
        return PipelineExecution.from_dict(_unwrap_data(payload))

    def dry_run(self, pipeline_id: str) -> PipelineExecution:
        """Submit a pipeline dry run (writes to the null-preview sink)."""
        payload = self.client._request_json(
            "POST", f"{_pipeline_path(self.api_version, pipeline_id)}/dry-run"
        )
        return PipelineExecution.from_dict(_unwrap_data(payload))

    def executions(self, pipeline_id: str) -> list[PipelineExecution]:
        """List executions for a pipeline."""
        payload = self.client._request_json("GET", _executions_path(self.api_version, pipeline_id))
        return [PipelineExecution.from_dict(item) for item in _executions_from(payload)]

    def execution(self, pipeline_id: str, execution_id: str) -> PipelineExecution:
        """Get a single pipeline execution."""
        payload = self.client._request_json(
            "GET", _execution_path(self.api_version, pipeline_id, execution_id)
        )
        return PipelineExecution.from_dict(_unwrap_data(payload))

    def wait(
        self,
        pipeline_id: str,
        execution: PipelineExecution | str,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> PipelineExecution:
        """Poll an execution until it reaches a terminal status (or ``timeout``)."""
        execution_id = execution.id if isinstance(execution, PipelineExecution) else str(execution)
        current = (
            execution
            if isinstance(execution, PipelineExecution)
            else self.execution(pipeline_id, execution_id)
        )
        deadline = None if timeout is None else time.monotonic() + timeout
        while not current.is_terminal:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Pipeline execution {execution_id!r} did not reach a terminal status within "
                    f"{timeout}s (last status: {current.status!r})."
                )
            time.sleep(max(0.0, poll_interval))
            current = self.execution(pipeline_id, execution_id)
        return current

    def run_to_completion(
        self,
        pipeline_id: str,
        *,
        dry_run: bool = False,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> PipelineExecution:
        """Submit a run (or dry run) and poll it to a terminal status."""
        started = self.dry_run(pipeline_id) if dry_run else self.run(pipeline_id)
        terminal = self.wait(pipeline_id, started, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise PipelineExecutionError(terminal)
        return terminal


class AsyncHonuaEtl:
    """Asynchronous GeoETL pipeline client."""

    def __init__(self, client: Any, *, api_version: str = _DEFAULT_API_VERSION) -> None:
        self.client = client
        self.api_version = api_version

    # -- definitions -------------------------------------------------------

    async def create(self, definition: PipelineDefinition) -> PipelineDefinition:
        """Create a pipeline definition; returns it with server-assigned fields."""
        payload = await self.client._request_json(
            "POST", _pipelines_root(self.api_version), json_body=definition.to_request()
        )
        return PipelineDefinition.from_dict(_unwrap_data(payload))

    async def get(self, pipeline_id: str) -> PipelineDefinition:
        """Get one pipeline definition by id."""
        payload = await self.client._request_json("GET", _pipeline_path(self.api_version, pipeline_id))
        return PipelineDefinition.from_dict(_unwrap_data(payload))

    async def list(self) -> list[PipelineDefinition]:
        """List all pipeline definitions."""
        payload = await self.client._request_json("GET", _pipelines_root(self.api_version))
        return [PipelineDefinition.from_dict(item) for item in _pipelines_from(payload)]

    async def update(self, pipeline_id: str, definition: PipelineDefinition) -> PipelineDefinition:
        """Replace a pipeline definition."""
        payload = await self.client._request_json(
            "PUT", _pipeline_path(self.api_version, pipeline_id), json_body=definition.to_request()
        )
        return PipelineDefinition.from_dict(_unwrap_data(payload))

    async def delete(self, pipeline_id: str) -> None:
        """Delete a pipeline definition."""
        await self.client._request_json("DELETE", _pipeline_path(self.api_version, pipeline_id))

    # -- execution ---------------------------------------------------------

    async def run(self, pipeline_id: str) -> PipelineExecution:
        """Submit a pipeline run through the durable substrate."""
        payload = await self.client._request_json(
            "POST", f"{_pipeline_path(self.api_version, pipeline_id)}/run"
        )
        return PipelineExecution.from_dict(_unwrap_data(payload))

    async def dry_run(self, pipeline_id: str) -> PipelineExecution:
        """Submit a pipeline dry run (writes to the null-preview sink)."""
        payload = await self.client._request_json(
            "POST", f"{_pipeline_path(self.api_version, pipeline_id)}/dry-run"
        )
        return PipelineExecution.from_dict(_unwrap_data(payload))

    async def executions(self, pipeline_id: str) -> list[PipelineExecution]:
        """List executions for a pipeline."""
        payload = await self.client._request_json("GET", _executions_path(self.api_version, pipeline_id))
        return [PipelineExecution.from_dict(item) for item in _executions_from(payload)]

    async def execution(self, pipeline_id: str, execution_id: str) -> PipelineExecution:
        """Get a single pipeline execution."""
        payload = await self.client._request_json(
            "GET", _execution_path(self.api_version, pipeline_id, execution_id)
        )
        return PipelineExecution.from_dict(_unwrap_data(payload))

    async def wait(
        self,
        pipeline_id: str,
        execution: PipelineExecution | str,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
    ) -> PipelineExecution:
        """Poll an execution until it reaches a terminal status (or ``timeout``)."""
        import asyncio

        execution_id = execution.id if isinstance(execution, PipelineExecution) else str(execution)
        current = (
            execution
            if isinstance(execution, PipelineExecution)
            else await self.execution(pipeline_id, execution_id)
        )
        deadline = None if timeout is None else time.monotonic() + timeout
        while not current.is_terminal:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Pipeline execution {execution_id!r} did not reach a terminal status within "
                    f"{timeout}s (last status: {current.status!r})."
                )
            await asyncio.sleep(max(0.0, poll_interval))
            current = await self.execution(pipeline_id, execution_id)
        return current

    async def run_to_completion(
        self,
        pipeline_id: str,
        *,
        dry_run: bool = False,
        poll_interval: float = 0.5,
        timeout: float | None = 120.0,
        raise_on_failure: bool = True,
    ) -> PipelineExecution:
        """Submit a run (or dry run) and poll it to a terminal status."""
        started = await (self.dry_run(pipeline_id) if dry_run else self.run(pipeline_id))
        terminal = await self.wait(pipeline_id, started, poll_interval=poll_interval, timeout=timeout)
        if raise_on_failure and not terminal.succeeded:
            raise PipelineExecutionError(terminal)
        return terminal

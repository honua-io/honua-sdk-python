"""Workflow authoring + publication clients for Honua Server.

The reconciled honua-server exposes a **durable, authored multi-node workflow**
surface over HTTP under ``/api/v1/console`` (honua-server
``Features/WorkflowPackages``). This is the replacement for the dropped GeoETL
pipeline endpoints: instead of an imperative ``/admin/geoetl/pipelines`` API,
authors persist a Workflow *Draft* (a DAG of registry nodes), snapshot it into
an immutable *version*, validate / dry-run it, then *publish* the version to a
run target (a durable job template, a schedule, or a process-style endpoint) and
*run* the resulting publication.

The endpoints this client targets (all under ``/api/v1/console`` and gated by
admin authorization on the server):

* ``GET  /workflow-node-registry`` -- the server-owned node registry snapshot,
* ``GET  /workflow-node-registry/{nodeTypeId}`` -- one node definition,
* ``GET  /workflow-packages`` -- list Workflow Drafts,
* ``POST /workflow-packages`` -- create/replace a Workflow Draft,
* ``GET  /workflow-packages/{packageId}`` -- get a Workflow Draft,
* ``PUT  /workflow-packages/{packageId}`` -- replace a Workflow Draft,
* ``GET  /workflow-packages/{packageId}/versions`` -- list immutable versions,
* ``POST /workflow-packages/{packageId}/versions`` -- snapshot a new version,
* ``GET  /workflow-packages/{packageId}/versions/{version}`` -- get a version,
* ``POST /workflow-packages/{packageId}/versions/{version}/validate`` -- validate,
* ``POST /workflow-packages/{packageId}/versions/{version}/dry-run`` -- dry-run,
* ``POST /workflow-packages/{packageId}/versions/{version}/publish`` -- publish,
* ``GET  /workflow-publications`` -- list publications,
* ``POST /workflow-publications/{publicationId}/runs`` -- start a run.

Every successful response is the server's ``ApiResponse<T>`` envelope
(``{"success", "data", "message", "timestamp"}``); the methods here unwrap and
return the ``data`` payload as a JSON mapping. Workflow graphs, validation
results, publications, and run results are returned as their server JSON shapes
(camelCase records) rather than re-modelled as Python dataclasses, mirroring the
pragmatic JSON-in/JSON-out style of :mod:`honua_sdk.geoprocessing`.

.. note::

   Starting a run returns a :class:`WorkflowPublicationRunResult`-shaped payload
   carrying a ``jobId`` (job/process-endpoint targets) or ``workflowRunId``
   (schedule targets). Run *status* is then polled on the server's admin
   jobs/operations surface (``/api/v1/admin/jobs/{jobId}`` or
   ``/api/v1/admin/operations/{workflowRunId}``); the workflow feature itself
   exposes no run-status GET endpoint, so this client does not fabricate one.

For ad-hoc, *un-authored* multi-step geoprocessing, chain process executions or
submit an analysis ``plan`` to the canonical process via
:mod:`honua_sdk.geoprocessing` instead.

The ``workflow-packages`` route segment and the ``packageId`` field are server
wire names and are sent unchanged; the Python names say Workflow and Draft.

Both the synchronous (:class:`HonuaWorkflow`) and asynchronous
(:class:`AsyncHonuaWorkflow`) clients are provided with full parity and reuse
the bound :class:`~honua_sdk.client.HonuaClient` /
:class:`~honua_sdk.async_client.AsyncHonuaClient` transport.
"""

from __future__ import annotations

import functools
import inspect
import warnings
from collections.abc import Callable, Mapping
from typing import Any, ParamSpec, TypeVar, cast

from ._client_protocol import SupportsAsyncRequest, SupportsSyncRequest
from ._http import _encode_path_segment

JsonObject = dict[str, Any]

#: Workflow graph schema version emitted by the reconciled server graphs.
WORKFLOW_SCHEMA_VERSION = "workflow-package.v1"

_RENAMED_CONSTANTS = {"WORKFLOW_PACKAGE_SCHEMA_VERSION": "WORKFLOW_SCHEMA_VERSION"}

_P = ParamSpec("_P")
_R = TypeVar("_R")


_RENAMED_MESSAGE = "{old} is deprecated; use {new}. It is removed in the next minor release."


def _warn_renamed(old: str, new: str) -> None:
    warnings.warn(_RENAMED_MESSAGE.format(old=old, new=new), DeprecationWarning, stacklevel=3)


def __getattr__(name: str) -> Any:
    replacement = _RENAMED_CONSTANTS.get(name)
    if replacement is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    _warn_renamed(name, replacement)
    return globals()[replacement]


def _rename_package_id(kwargs: dict[str, Any]) -> None:
    if "package_id" not in kwargs:
        return
    if "workflow_id" in kwargs:
        raise TypeError("pass workflow_id or the deprecated package_id, not both")
    message = _RENAMED_MESSAGE.format(old="package_id=", new="workflow_id=")
    warnings.warn(message, DeprecationWarning, stacklevel=3)
    kwargs["workflow_id"] = kwargs.pop("package_id")


def _accepts_package_id(method: Callable[_P, _R]) -> Callable[_P, _R]:
    """Route the deprecated ``package_id=`` keyword to ``workflow_id=``."""
    if inspect.iscoroutinefunction(method):

        @functools.wraps(method)
        async def forward_async(*args: Any, **kwargs: Any) -> Any:
            _rename_package_id(kwargs)
            return await method(*args, **kwargs)

        return cast("Callable[_P, _R]", forward_async)

    @functools.wraps(method)
    def forward(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        _rename_package_id(kwargs)
        return method(*args, **kwargs)

    return forward


#: Publication targets accepted by ``POST .../publish`` (mirrors the server
#: ``WorkflowPublicationTarget`` enum).
PUBLICATION_TARGET_JOB = "Job"
PUBLICATION_TARGET_SCHEDULE = "Schedule"
PUBLICATION_TARGET_PROCESS_ENDPOINT = "ProcessEndpoint"


def _unwrap(payload: Mapping[str, Any]) -> JsonObject:
    """Return the ``data`` payload from an ``ApiResponse`` envelope.

    The reconciled server wraps every successful body in
    ``{"success", "data", "message", "timestamp"}``. When the envelope shape is
    present the inner ``data`` mapping is returned; otherwise the payload is
    returned unchanged so callers still see whatever the server sent.
    """
    if "data" in payload:
        data = payload["data"]
        if isinstance(data, Mapping):
            return dict(data)
        return {"data": data}
    return dict(payload)


def _save_draft_body(
    *,
    name: str,
    graph: Mapping[str, Any],
    workflow_id: str | None,
    description: str | None,
    namespace: str | None,
    metadata: Mapping[str, str] | None,
) -> JsonObject:
    body: JsonObject = {"name": name, "graph": dict(graph)}
    if workflow_id is not None:
        body["packageId"] = workflow_id
    if description is not None:
        body["description"] = description
    if namespace is not None:
        body["namespace"] = namespace
    if metadata is not None:
        body["metadata"] = dict(metadata)
    return body


def _publish_body(
    *,
    target: str,
    publication_id: str | None,
    process_id: str | None,
    schedule: Mapping[str, Any] | None,
    enabled: bool,
) -> JsonObject:
    body: JsonObject = {"target": target, "enabled": enabled}
    if publication_id is not None:
        body["publicationId"] = publication_id
    if process_id is not None:
        body["processId"] = process_id
    if schedule is not None:
        body["schedule"] = dict(schedule)
    return body


def _run_body(
    *,
    idempotency_key: str | None,
    parameters: Mapping[str, str] | None,
) -> JsonObject:
    body: JsonObject = {}
    if idempotency_key is not None:
        body["idempotencyKey"] = idempotency_key
    if parameters is not None:
        body["parameters"] = dict(parameters)
    return body


_ROOT = "/api/v1/console"


def _node_registry_path() -> str:
    return f"{_ROOT}/workflow-node-registry"


def _node_path(node_type_id: str) -> str:
    return f"{_ROOT}/workflow-node-registry/{_encode_path_segment(node_type_id)}"


def _drafts_path() -> str:
    return f"{_ROOT}/workflow-packages"


def _draft_path(workflow_id: str) -> str:
    return f"{_drafts_path()}/{_encode_path_segment(workflow_id)}"


def _versions_path(workflow_id: str) -> str:
    return f"{_draft_path(workflow_id)}/versions"


def _version_path(workflow_id: str, version: int) -> str:
    return f"{_versions_path(workflow_id)}/{int(version)}"


def _version_action_path(workflow_id: str, version: int, action: str) -> str:
    return f"{_version_path(workflow_id, version)}/{action}"


def _publications_path() -> str:
    return f"{_ROOT}/workflow-publications"


def _publication_runs_path(publication_id: str) -> str:
    return f"{_publications_path()}/{_encode_path_segment(publication_id)}/runs"


class HonuaWorkflow:
    """Synchronous Workflow authoring + publication client."""

    root = _ROOT

    def __init__(self, client: SupportsSyncRequest) -> None:
        self.client = client

    # -- node registry -----------------------------------------------------

    def node_registry(self) -> JsonObject:
        """Get the server-owned workflow node registry snapshot."""
        return _unwrap(self.client._request_json("GET", _node_registry_path()))

    def node(self, node_type_id: str) -> JsonObject:
        """Get one workflow node definition from the registry."""
        return _unwrap(self.client._request_json("GET", _node_path(node_type_id)))

    # -- drafts ------------------------------------------------------------

    def drafts(self) -> JsonObject:
        """List Workflow Drafts."""
        return _unwrap(self.client._request_json("GET", _drafts_path()))

    def draft(self, workflow_id: str) -> JsonObject:
        """Get one Workflow Draft."""
        return _unwrap(self.client._request_json("GET", _draft_path(workflow_id)))

    def save_draft(
        self,
        name: str,
        graph: Mapping[str, Any],
        *,
        workflow_id: str | None = None,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Create or replace a Workflow Draft.

        ``graph`` is the workflow DAG (``{"nodes", "edges", ...}``) understood by
        the server. Omit ``workflow_id`` to create a new Draft; pass it to replace
        an existing one (see :meth:`update_draft` for the PUT variant).
        """
        body = _save_draft_body(
            name=name,
            graph=graph,
            workflow_id=workflow_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(self.client._request_json("POST", _drafts_path(), json_body=body))

    def update_draft(
        self,
        workflow_id: str,
        name: str,
        graph: Mapping[str, Any],
        *,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Replace an existing Workflow Draft (PUT)."""
        body = _save_draft_body(
            name=name,
            graph=graph,
            workflow_id=workflow_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(self.client._request_json("PUT", _draft_path(workflow_id), json_body=body))

    def packages(self) -> JsonObject:
        """Deprecated alias of :meth:`drafts`."""
        _warn_renamed("packages()", "drafts()")
        return self.drafts()

    def package(self, package_id: str) -> JsonObject:
        """Deprecated alias of :meth:`draft`."""
        _warn_renamed("package()", "draft()")
        return self.draft(package_id)

    def save_package(
        self,
        name: str,
        graph: Mapping[str, Any],
        *,
        package_id: str | None = None,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Deprecated alias of :meth:`save_draft`."""
        _warn_renamed("save_package()", "save_draft()")
        return self.save_draft(
            name,
            graph,
            workflow_id=package_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )

    def update_package(
        self,
        package_id: str,
        name: str,
        graph: Mapping[str, Any],
        *,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Deprecated alias of :meth:`update_draft`."""
        _warn_renamed("update_package()", "update_draft()")
        return self.update_draft(
            package_id, name, graph, description=description, namespace=namespace, metadata=metadata
        )

    # -- immutable versions ------------------------------------------------

    @_accepts_package_id
    def versions(self, workflow_id: str) -> JsonObject:
        """List immutable Versions of a Workflow."""
        return _unwrap(self.client._request_json("GET", _versions_path(workflow_id)))

    @_accepts_package_id
    def create_version(self, workflow_id: str) -> JsonObject:
        """Snapshot the current Workflow Draft into a new immutable Version."""
        return _unwrap(self.client._request_json("POST", _versions_path(workflow_id)))

    @_accepts_package_id
    def version(self, workflow_id: str, version: int) -> JsonObject:
        """Get one immutable Workflow Version."""
        return _unwrap(self.client._request_json("GET", _version_path(workflow_id, version)))

    @_accepts_package_id
    def validate_version(self, workflow_id: str, version: int) -> JsonObject:
        """Validate a Workflow Version and return the validation result."""
        return _unwrap(
            self.client._request_json("POST", _version_action_path(workflow_id, version, "validate"))
        )

    @_accepts_package_id
    def dry_run_version(self, workflow_id: str, version: int) -> JsonObject:
        """Dry-run a Workflow Version and return the preview result."""
        return _unwrap(
            self.client._request_json("POST", _version_action_path(workflow_id, version, "dry-run"))
        )

    @_accepts_package_id
    def publish_version(
        self,
        workflow_id: str,
        version: int,
        *,
        target: str,
        publication_id: str | None = None,
        process_id: str | None = None,
        schedule: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> JsonObject:
        """Publish a Workflow Version to a run target and return the publication.

        ``target`` is one of :data:`PUBLICATION_TARGET_JOB`,
        :data:`PUBLICATION_TARGET_SCHEDULE`, or
        :data:`PUBLICATION_TARGET_PROCESS_ENDPOINT`. Pass ``process_id`` for a
        process-endpoint target and ``schedule`` (``{"cronExpression", ...}``)
        for a schedule target.
        """
        body = _publish_body(
            target=target,
            publication_id=publication_id,
            process_id=process_id,
            schedule=schedule,
            enabled=enabled,
        )
        return _unwrap(
            self.client._request_json(
                "POST", _version_action_path(workflow_id, version, "publish"), json_body=body
            )
        )

    # -- publications + runs -----------------------------------------------

    def publications(self) -> JsonObject:
        """List Workflow publications."""
        return _unwrap(self.client._request_json("GET", _publications_path()))

    def run(
        self,
        publication_id: str,
        *,
        idempotency_key: str | None = None,
        parameters: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Start a run from a publication and return the run result.

        The result carries a ``jobId`` (job / process-endpoint targets) or a
        ``workflowRunId`` (schedule targets). Run status is then polled on the
        admin jobs/operations surface; this client does not poll it.
        """
        body = _run_body(idempotency_key=idempotency_key, parameters=parameters)
        return _unwrap(
            self.client._request_json("POST", _publication_runs_path(publication_id), json_body=body)
        )


class AsyncHonuaWorkflow:
    """Asynchronous Workflow authoring + publication client."""

    root = _ROOT

    def __init__(self, client: SupportsAsyncRequest) -> None:
        self.client = client

    # -- node registry -----------------------------------------------------

    async def node_registry(self) -> JsonObject:
        """Get the server-owned workflow node registry snapshot."""
        return _unwrap(await self.client._request_json("GET", _node_registry_path()))

    async def node(self, node_type_id: str) -> JsonObject:
        """Get one workflow node definition from the registry."""
        return _unwrap(await self.client._request_json("GET", _node_path(node_type_id)))

    # -- drafts ------------------------------------------------------------

    async def drafts(self) -> JsonObject:
        """List Workflow Drafts."""
        return _unwrap(await self.client._request_json("GET", _drafts_path()))

    async def draft(self, workflow_id: str) -> JsonObject:
        """Get one Workflow Draft."""
        return _unwrap(await self.client._request_json("GET", _draft_path(workflow_id)))

    async def save_draft(
        self,
        name: str,
        graph: Mapping[str, Any],
        *,
        workflow_id: str | None = None,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Create or replace a Workflow Draft.

        ``graph`` is the workflow DAG (``{"nodes", "edges", ...}``) understood by
        the server. Omit ``workflow_id`` to create a new Draft; pass it to replace
        an existing one (see :meth:`update_draft` for the PUT variant).
        """
        body = _save_draft_body(
            name=name,
            graph=graph,
            workflow_id=workflow_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(await self.client._request_json("POST", _drafts_path(), json_body=body))

    async def update_draft(
        self,
        workflow_id: str,
        name: str,
        graph: Mapping[str, Any],
        *,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Replace an existing Workflow Draft (PUT)."""
        body = _save_draft_body(
            name=name,
            graph=graph,
            workflow_id=workflow_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(await self.client._request_json("PUT", _draft_path(workflow_id), json_body=body))

    async def packages(self) -> JsonObject:
        """Deprecated alias of :meth:`drafts`."""
        _warn_renamed("packages()", "drafts()")
        return await self.drafts()

    async def package(self, package_id: str) -> JsonObject:
        """Deprecated alias of :meth:`draft`."""
        _warn_renamed("package()", "draft()")
        return await self.draft(package_id)

    async def save_package(
        self,
        name: str,
        graph: Mapping[str, Any],
        *,
        package_id: str | None = None,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Deprecated alias of :meth:`save_draft`."""
        _warn_renamed("save_package()", "save_draft()")
        return await self.save_draft(
            name,
            graph,
            workflow_id=package_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )

    async def update_package(
        self,
        package_id: str,
        name: str,
        graph: Mapping[str, Any],
        *,
        description: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Deprecated alias of :meth:`update_draft`."""
        _warn_renamed("update_package()", "update_draft()")
        return await self.update_draft(
            package_id, name, graph, description=description, namespace=namespace, metadata=metadata
        )

    # -- immutable versions ------------------------------------------------

    @_accepts_package_id
    async def versions(self, workflow_id: str) -> JsonObject:
        """List immutable Versions of a Workflow."""
        return _unwrap(await self.client._request_json("GET", _versions_path(workflow_id)))

    @_accepts_package_id
    async def create_version(self, workflow_id: str) -> JsonObject:
        """Snapshot the current Workflow Draft into a new immutable Version."""
        return _unwrap(await self.client._request_json("POST", _versions_path(workflow_id)))

    @_accepts_package_id
    async def version(self, workflow_id: str, version: int) -> JsonObject:
        """Get one immutable Workflow Version."""
        return _unwrap(await self.client._request_json("GET", _version_path(workflow_id, version)))

    @_accepts_package_id
    async def validate_version(self, workflow_id: str, version: int) -> JsonObject:
        """Validate a Workflow Version and return the validation result."""
        return _unwrap(
            await self.client._request_json("POST", _version_action_path(workflow_id, version, "validate"))
        )

    @_accepts_package_id
    async def dry_run_version(self, workflow_id: str, version: int) -> JsonObject:
        """Dry-run a Workflow Version and return the preview result."""
        return _unwrap(
            await self.client._request_json("POST", _version_action_path(workflow_id, version, "dry-run"))
        )

    @_accepts_package_id
    async def publish_version(
        self,
        workflow_id: str,
        version: int,
        *,
        target: str,
        publication_id: str | None = None,
        process_id: str | None = None,
        schedule: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> JsonObject:
        """Publish a Workflow Version to a run target and return the publication.

        ``target`` is one of :data:`PUBLICATION_TARGET_JOB`,
        :data:`PUBLICATION_TARGET_SCHEDULE`, or
        :data:`PUBLICATION_TARGET_PROCESS_ENDPOINT`. Pass ``process_id`` for a
        process-endpoint target and ``schedule`` (``{"cronExpression", ...}``)
        for a schedule target.
        """
        body = _publish_body(
            target=target,
            publication_id=publication_id,
            process_id=process_id,
            schedule=schedule,
            enabled=enabled,
        )
        return _unwrap(
            await self.client._request_json(
                "POST", _version_action_path(workflow_id, version, "publish"), json_body=body
            )
        )

    # -- publications + runs -----------------------------------------------

    async def publications(self) -> JsonObject:
        """List Workflow publications."""
        return _unwrap(await self.client._request_json("GET", _publications_path()))

    async def run(
        self,
        publication_id: str,
        *,
        idempotency_key: str | None = None,
        parameters: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Start a run from a publication and return the run result."""
        body = _run_body(idempotency_key=idempotency_key, parameters=parameters)
        return _unwrap(
            await self.client._request_json(
                "POST", _publication_runs_path(publication_id), json_body=body
            )
        )

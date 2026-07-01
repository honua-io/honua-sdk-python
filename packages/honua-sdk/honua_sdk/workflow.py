"""Workflow package authoring + publication clients for Honua Server.

The reconciled honua-server exposes a **durable, authored multi-node workflow**
surface over HTTP under ``/api/v1/console`` (honua-server
``Features/WorkflowPackages``). This is the replacement for the dropped GeoETL
pipeline endpoints: instead of an imperative ``/admin/geoetl/pipelines`` API,
authors persist a workflow *package* (a DAG of registry nodes), snapshot it into
an immutable *version*, validate / dry-run it, then *publish* the version to a
run target (a durable job template, a schedule, or a process-style endpoint) and
*run* the resulting publication.

The endpoints this client targets (all under ``/api/v1/console`` and gated by
admin authorization on the server):

* ``GET  /workflow-node-registry`` -- the server-owned node registry snapshot,
* ``GET  /workflow-node-registry/{nodeTypeId}`` -- one node definition,
* ``GET  /workflow-packages`` -- list package drafts,
* ``POST /workflow-packages`` -- create/replace a package draft,
* ``GET  /workflow-packages/{packageId}`` -- get a package draft,
* ``PUT  /workflow-packages/{packageId}`` -- replace a package draft,
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

Both the synchronous (:class:`HonuaWorkflow`) and asynchronous
(:class:`AsyncHonuaWorkflow`) clients are provided with full parity and reuse
the bound :class:`~honua_sdk.client.HonuaClient` /
:class:`~honua_sdk.async_client.AsyncHonuaClient` transport.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._client_protocol import SupportsAsyncRequest, SupportsSyncRequest
from ._http import _encode_path_segment

JsonObject = dict[str, Any]

#: Workflow package schema version emitted by the reconciled server graphs.
WORKFLOW_PACKAGE_SCHEMA_VERSION = "workflow-package.v1"

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


def _save_package_body(
    *,
    name: str,
    graph: Mapping[str, Any],
    package_id: str | None,
    description: str | None,
    namespace: str | None,
    metadata: Mapping[str, str] | None,
) -> JsonObject:
    body: JsonObject = {"name": name, "graph": dict(graph)}
    if package_id is not None:
        body["packageId"] = package_id
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


def _packages_path() -> str:
    return f"{_ROOT}/workflow-packages"


def _package_path(package_id: str) -> str:
    return f"{_ROOT}/workflow-packages/{_encode_path_segment(package_id)}"


def _versions_path(package_id: str) -> str:
    return f"{_package_path(package_id)}/versions"


def _version_path(package_id: str, version: int) -> str:
    return f"{_versions_path(package_id)}/{int(version)}"


def _version_action_path(package_id: str, version: int, action: str) -> str:
    return f"{_version_path(package_id, version)}/{action}"


def _publications_path() -> str:
    return f"{_ROOT}/workflow-publications"


def _publication_runs_path(publication_id: str) -> str:
    return f"{_publications_path()}/{_encode_path_segment(publication_id)}/runs"


class HonuaWorkflow:
    """Synchronous workflow package authoring + publication client."""

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

    # -- package drafts ----------------------------------------------------

    def packages(self) -> JsonObject:
        """List workflow package drafts."""
        return _unwrap(self.client._request_json("GET", _packages_path()))

    def package(self, package_id: str) -> JsonObject:
        """Get a workflow package draft."""
        return _unwrap(self.client._request_json("GET", _package_path(package_id)))

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
        """Create or replace a workflow package draft.

        ``graph`` is the workflow DAG (``{"nodes", "edges", ...}``) understood by
        the server. Omit ``package_id`` to create a new draft; pass it to replace
        an existing one (see :meth:`update_package` for the PUT variant).
        """
        body = _save_package_body(
            name=name,
            graph=graph,
            package_id=package_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(self.client._request_json("POST", _packages_path(), json_body=body))

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
        """Replace an existing workflow package draft (PUT)."""
        body = _save_package_body(
            name=name,
            graph=graph,
            package_id=package_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(self.client._request_json("PUT", _package_path(package_id), json_body=body))

    # -- immutable versions ------------------------------------------------

    def versions(self, package_id: str) -> JsonObject:
        """List immutable versions of a package."""
        return _unwrap(self.client._request_json("GET", _versions_path(package_id)))

    def create_version(self, package_id: str) -> JsonObject:
        """Snapshot the current package draft into a new immutable version."""
        return _unwrap(self.client._request_json("POST", _versions_path(package_id)))

    def version(self, package_id: str, version: int) -> JsonObject:
        """Get one immutable package version."""
        return _unwrap(self.client._request_json("GET", _version_path(package_id, version)))

    def validate_version(self, package_id: str, version: int) -> JsonObject:
        """Validate a package version and return the validation result."""
        return _unwrap(
            self.client._request_json("POST", _version_action_path(package_id, version, "validate"))
        )

    def dry_run_version(self, package_id: str, version: int) -> JsonObject:
        """Dry-run a package version and return the preview result."""
        return _unwrap(
            self.client._request_json("POST", _version_action_path(package_id, version, "dry-run"))
        )

    def publish_version(
        self,
        package_id: str,
        version: int,
        *,
        target: str,
        publication_id: str | None = None,
        process_id: str | None = None,
        schedule: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> JsonObject:
        """Publish a package version to a run target and return the publication.

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
                "POST", _version_action_path(package_id, version, "publish"), json_body=body
            )
        )

    # -- publications + runs -----------------------------------------------

    def publications(self) -> JsonObject:
        """List workflow package publications."""
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
    """Asynchronous workflow package authoring + publication client."""

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

    # -- package drafts ----------------------------------------------------

    async def packages(self) -> JsonObject:
        """List workflow package drafts."""
        return _unwrap(await self.client._request_json("GET", _packages_path()))

    async def package(self, package_id: str) -> JsonObject:
        """Get a workflow package draft."""
        return _unwrap(await self.client._request_json("GET", _package_path(package_id)))

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
        """Create or replace a workflow package draft."""
        body = _save_package_body(
            name=name,
            graph=graph,
            package_id=package_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(await self.client._request_json("POST", _packages_path(), json_body=body))

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
        """Replace an existing workflow package draft (PUT)."""
        body = _save_package_body(
            name=name,
            graph=graph,
            package_id=package_id,
            description=description,
            namespace=namespace,
            metadata=metadata,
        )
        return _unwrap(
            await self.client._request_json("PUT", _package_path(package_id), json_body=body)
        )

    # -- immutable versions ------------------------------------------------

    async def versions(self, package_id: str) -> JsonObject:
        """List immutable versions of a package."""
        return _unwrap(await self.client._request_json("GET", _versions_path(package_id)))

    async def create_version(self, package_id: str) -> JsonObject:
        """Snapshot the current package draft into a new immutable version."""
        return _unwrap(await self.client._request_json("POST", _versions_path(package_id)))

    async def version(self, package_id: str, version: int) -> JsonObject:
        """Get one immutable package version."""
        return _unwrap(await self.client._request_json("GET", _version_path(package_id, version)))

    async def validate_version(self, package_id: str, version: int) -> JsonObject:
        """Validate a package version and return the validation result."""
        return _unwrap(
            await self.client._request_json(
                "POST", _version_action_path(package_id, version, "validate")
            )
        )

    async def dry_run_version(self, package_id: str, version: int) -> JsonObject:
        """Dry-run a package version and return the preview result."""
        return _unwrap(
            await self.client._request_json(
                "POST", _version_action_path(package_id, version, "dry-run")
            )
        )

    async def publish_version(
        self,
        package_id: str,
        version: int,
        *,
        target: str,
        publication_id: str | None = None,
        process_id: str | None = None,
        schedule: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> JsonObject:
        """Publish a package version to a run target and return the publication."""
        body = _publish_body(
            target=target,
            publication_id=publication_id,
            process_id=process_id,
            schedule=schedule,
            enabled=enabled,
        )
        return _unwrap(
            await self.client._request_json(
                "POST", _version_action_path(package_id, version, "publish"), json_body=body
            )
        )

    # -- publications + runs -----------------------------------------------

    async def publications(self) -> JsonObject:
        """List workflow package publications."""
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

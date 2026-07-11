"""Stub Honua transport used by eval scripts when no live server is available.

The stub is intentionally minimal: it responds to ``OgcProcessesClient.execute``
with a fake job acceptance and stubs ``Source.iter_features`` /
``Source.apply_edits`` against a tiny in-memory feature list. The goal is to
exercise the shim's dispatch pipeline -- audit logging, parameter binding,
client routing -- without depending on honua-server.

The stub mirrors the real :class:`honua_sdk.HonuaClient.source` contract:
it accepts a ``SourceDescriptor`` or mapping and rejects bare strings with
``TypeError``, so anything that works against the stub also works against the
real SDK.

Set ``HONUA_GP_EVAL_USE_STUB=0`` to bypass the stub (useful when running
against a real Honua deployment).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _StubApplyEditsResult:
    adds: list[dict[str, Any]] = field(default_factory=list)
    updates: list[dict[str, Any]] = field(default_factory=list)
    deletes: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adds": list(self.adds),
            "updates": list(self.updates),
            "deletes": list(self.deletes),
        }


@dataclass
class _StubFeature:
    attributes: dict[str, Any]
    geometry: dict[str, Any] | None = None


@dataclass
class _StubResult:
    features: list[_StubFeature]


class _StubSource:
    def __init__(self, name: str) -> None:
        self.name = name
        self._features = [
            _StubFeature(attributes={"OBJECTID": 1, "STATUS": "OPEN", "name": f"{name}/A"}),
            _StubFeature(attributes={"OBJECTID": 2, "STATUS": "CLOSED", "name": f"{name}/B"}),
            _StubFeature(attributes={"OBJECTID": 3, "STATUS": "OPEN", "name": f"{name}/C"}),
        ]

    def query(self, where: str | None = None, **_: Any) -> _StubResult:
        if not where:
            return _StubResult(features=list(self._features))
        # The stub does not parse SQL; it returns everything but allows callers
        # to count features under a where clause for audit-line coverage.
        return _StubResult(features=list(self._features))

    def iter_features(self, where: str | None = None, **_: Any) -> Any:
        for feature in self.query(where=where).features:
            yield feature

    def apply_edits(
        self,
        *,
        adds: list[dict[str, Any]] | None = None,
        updates: list[dict[str, Any]] | None = None,
        deletes: list[Any] | None = None,
    ) -> _StubApplyEditsResult:
        return _StubApplyEditsResult(
            adds=list(adds or []),
            updates=list(updates or []),
            deletes=list(deletes or []),
        )


class _StubProcessesClient:
    """Stub OGC API Processes client that models the async job lifecycle.

    honua-server runs every built-in geoprocessing operation as an
    asynchronous job: ``execute`` returns a ``201`` StatusInfo with a
    ``jobID`` + ``accepted`` status, the job transitions through ``running``
    to ``successful``, and ``/results`` returns a document. The shim's
    submit-and-poll helper drives exactly that contract, so the stub mirrors
    it -- ``execute`` returns a fresh ``jobID``, the first poll resolves to
    ``successful``, and ``job_results`` returns a synthetic results document.

    ``calls`` exposes the original ``(process_id, payload)`` pairs as both the
    legacy dict shape (``{"process_id", "payload"}``) via ``raw_calls`` and the
    tuple shape used by the newer tests.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raw_calls: list[dict[str, Any]] = []
        self._next_job = 0

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((process_id, payload))
        self.raw_calls.append({"process_id": process_id, "payload": payload})
        self._next_job += 1
        return {
            "processID": process_id,
            "jobID": f"stub-job-{self._next_job}",
            "status": "accepted",
        }

    def job(self, job_id: str) -> dict[str, Any]:
        return {"jobID": job_id, "status": "successful"}

    def job_results(self, job_id: str) -> dict[str, Any]:
        return {"jobID": job_id, "outputs": {"result": {"href": f"honua://jobs/{job_id}/result"}}}

    def dismiss_job(self, job_id: str) -> None:
        return None


class _StubFeatureServerNotFoundError(Exception):
    """Mirrors a honua-server 404 for an unknown service/layer id."""


class _StubFeatureServer:
    """Stub ``honua_sdk.protocols.GeoServicesFeatureServerClient`` wrapper.

    Backs ``management.Describe`` / ``management.ListFields`` in eval scripts
    and tests. ``schema(layer_id)`` mirrors the real client's contract --
    ``LayerSchema.from_metadata(layer_metadata(layer_id))`` -- against a tiny
    canned catalog instead of an HTTP round trip, so the schema-introspection
    shims exercise the same parsing path (``honua_sdk.models.LayerSchema``)
    that a live honua-server response would.
    """

    _CATALOG: dict[tuple[str, int], dict[str, Any]] = {
        ("legacy", 0): {
            "id": 0,
            "name": "segments",
            "objectIdField": "OBJECTID",
            "geometryType": "esriGeometryPolyline",
            "spatialReference": {"wkid": 4326, "latestWkid": 4326},
            "fields": [
                {
                    "name": "OBJECTID",
                    "type": "esriFieldTypeOID",
                    "alias": "OBJECTID",
                    "nullable": False,
                    "editable": False,
                },
                {
                    "name": "STATUS",
                    "type": "esriFieldTypeString",
                    "alias": "Status",
                    "length": 20,
                    "nullable": True,
                },
                {
                    "name": "LENGTH_KM",
                    "type": "esriFieldTypeDouble",
                    "alias": "Length (km)",
                    "nullable": True,
                },
                {
                    "name": "SHAPE",
                    "type": "esriFieldTypeGeometry",
                    "alias": "SHAPE",
                    "nullable": True,
                },
            ],
        },
        ("transport", 0): {
            "id": 0,
            "name": "roads",
            "objectIdField": "OBJECTID",
            "geometryType": "esriGeometryPolyline",
            "spatialReference": {"wkid": 4326, "latestWkid": 4326},
            "fields": [
                {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "OBJECTID", "nullable": False},
                {
                    "name": "STATUS",
                    "type": "esriFieldTypeString",
                    "alias": "Status",
                    "length": 10,
                    "nullable": True,
                },
                {"name": "name", "type": "esriFieldTypeString", "alias": "Name", "length": 50, "nullable": True},
            ],
        },
    }

    def __init__(self, service_id: str) -> None:
        self.service_id = service_id

    def layer_metadata(self, layer_id: int, **_: Any) -> dict[str, Any]:
        key = (self.service_id, layer_id)
        payload = self._CATALOG.get(key)
        if payload is None:
            raise _StubFeatureServerNotFoundError(
                f"layer {layer_id} not found on service {self.service_id!r}"
            )
        return dict(payload)

    def schema(self, layer_id: int, **_: Any) -> Any:
        from honua_sdk.models import LayerSchema

        return LayerSchema.from_metadata(self.layer_metadata(layer_id))


class _StubAdminClient:
    """Lightweight admin stub.

    The supported ``arcpy.management`` admin entries are now stubbed (see
    ``honua_gp._compat``) because :class:`honua_admin.HonuaAdminClient`
    does not expose per-layer schema mutation. This stub keeps a tiny event
    log so tests that exercise unrelated admin flows can still observe calls.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def apply_manifest(self, request: Any) -> Any:
        payload = getattr(request, "to_dict", lambda: {"entries": getattr(request, "entries", [])})()
        self.events.append({"kind": "apply_manifest", "request": payload})
        return _Resp({"applied": payload})


@dataclass
class _Resp:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class StubHonuaClient:
    """Stand-in for ``honua_sdk.HonuaClient`` used in eval/test scenarios.

    ``source()`` mirrors the real SDK contract: it accepts a
    ``SourceDescriptor`` instance or a mapping and rejects bare strings with
    ``TypeError``.
    """

    def __init__(self) -> None:
        self._processes = _StubProcessesClient()

    def source(self, descriptor: Any) -> _StubSource:
        if isinstance(descriptor, Mapping):
            name = str(descriptor.get("id") or descriptor.get("source") or "")
        elif hasattr(descriptor, "id"):
            name = str(descriptor.id or "")
        else:
            raise TypeError("descriptor must be a SourceDescriptor or mapping.")
        if not name:
            name = "stub-source"
        return _StubSource(name)

    def ogc_processes(self) -> _StubProcessesClient:
        return self._processes

    def feature_server(self, service_id: str) -> _StubFeatureServer:
        return _StubFeatureServer(service_id)


def install_stub() -> None:
    """Configure ``honua_gp`` with stub clients."""

    import honua_gp

    client = StubHonuaClient()
    admin = _StubAdminClient()
    honua_gp.configure(client=client, admin_client=admin)


def stub_active() -> bool:
    return os.environ.get("HONUA_GP_EVAL_USE_STUB", "1") == "1"

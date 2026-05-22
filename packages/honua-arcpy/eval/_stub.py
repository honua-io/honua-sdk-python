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

Set ``HONUA_ARCPY_EVAL_USE_STUB=0`` to bypass the stub (useful when running
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
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"process_id": process_id, "payload": payload})
        return {
            "processID": process_id,
            "status": "accepted",
            "inputs": payload.get("inputs", {}),
            "outputs": payload.get("outputs", {}),
        }


class _StubAdminClient:
    """Lightweight admin stub.

    The supported ``arcpy.management`` admin entries are now stubbed (see
    ``honua_arcpy._compat``) because :class:`honua_admin.HonuaAdminClient`
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
            name = str(getattr(descriptor, "id") or "")
        else:
            raise TypeError("descriptor must be a SourceDescriptor or mapping.")
        if not name:
            name = "stub-source"
        return _StubSource(name)

    def ogc_processes(self) -> _StubProcessesClient:
        return self._processes


def install_stub() -> None:
    """Configure ``honua_arcpy`` with stub clients."""

    import honua_arcpy

    client = StubHonuaClient()
    admin = _StubAdminClient()
    honua_arcpy.configure(client=client, admin_client=admin)


def stub_active() -> bool:
    return os.environ.get("HONUA_ARCPY_EVAL_USE_STUB", "1") == "1"

"""Resolve arcpy paths into Honua-friendly source identifiers.

Real customer scripts pass paths like ``r"C:\\GIS\\parcels.gdb\\Parcels"``,
``"in_memory\\layer1"``, ArcSDE connection strings, or
``arcpy.env.workspace``-relative names. The shim cannot magically know what
the corresponding Honua resource ID is, so we provide:

* A documented ``HONUA_ARCPY_PATH_MAP`` env-var override (JSON object).
* A ``honua://`` URI shape that maps directly to a ``SourceLocator``.
* Pass-through for plain identifiers (treated as service-relative names).

When a path cannot be classified we still return the input string so that
process payloads remain testable; resolution failures only raise when an
upstream call demands a concrete ``SourceDescriptor`` we cannot synthesize.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from ._errors import HonuaArcpyResolveError
from ._session import HonuaSession, LayerAlias, get_session

_HONUA_URI = re.compile(r"^honua://(?P<rest>.+)$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_GDB_RE = re.compile(r"\.gdb([\\/]|$)", re.IGNORECASE)
_SDE_RE = re.compile(r"\.sde([\\/]|$)", re.IGNORECASE)
_IN_MEMORY_PREFIXES = ("in_memory", "memory", "in_memory\\", "in_memory/")


@dataclass(frozen=True)
class ResolvedSource:
    """Resolved arcpy path."""

    source: str
    kind: str  # "honua-uri" | "in-memory" | "workspace-relative" | "absolute" | "alias"
    workspace: str | None = None
    layer: str | None = None
    raw: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "workspace": self.workspace,
            "layer": self.layer,
            "raw": self.raw,
        }


def _path_map() -> dict[str, str]:
    raw = os.environ.get("HONUA_ARCPY_PATH_MAP")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def resolve(path: Any, *, session: HonuaSession | None = None) -> ResolvedSource:
    """Resolve an arcpy path / layer-name into a Honua source string."""

    if path is None:
        raise HonuaArcpyResolveError("None", hint="Path / layer name must not be None.")

    session = session or get_session()
    if not isinstance(path, str):
        return ResolvedSource(source=str(path), kind="passthrough", raw=str(path))

    raw = path

    # 1. Alias registered via MakeFeatureLayer / MakeTableView.
    alias = session.get_layer(path)
    if alias is not None:
        return ResolvedSource(
            source=alias.source,
            kind="alias",
            workspace=alias.workspace,
            layer=alias.name,
            raw=raw,
        )

    # 2. Explicit honua:// URI.
    match = _HONUA_URI.match(path)
    if match is not None:
        return ResolvedSource(source=path, kind="honua-uri", raw=raw)

    # 3. HONUA_ARCPY_PATH_MAP override.
    overrides = _path_map()
    if path in overrides:
        return ResolvedSource(source=overrides[path], kind="honua-uri", raw=raw)

    # 4. in_memory / memory layer.
    lowered = path.lower()
    if lowered.startswith(_IN_MEMORY_PREFIXES):
        tail = path.split("/")[-1].split("\\")[-1]
        return ResolvedSource(source=f"in_memory:{tail}", kind="in-memory", raw=raw)

    # 5. Absolute Windows / POSIX path.
    if _WINDOWS_ABSOLUTE.match(path) or path.startswith("/") or path.startswith("\\\\"):
        normalized = path.replace("\\", "/")
        layer = normalized.rsplit("/", 1)[-1]
        workspace_match = _GDB_RE.search(normalized) or _SDE_RE.search(normalized)
        workspace = None
        if workspace_match is not None:
            workspace_end = workspace_match.end(0)
            workspace = normalized[: workspace_end - 1].rsplit("/", 1)[-1]
        return ResolvedSource(
            source=layer,
            kind="absolute",
            workspace=workspace or session.workspace,
            layer=layer,
            raw=raw,
        )

    # 6. Fall back to workspace-relative name.
    return ResolvedSource(
        source=path,
        kind="workspace-relative",
        workspace=session.workspace,
        layer=path,
        raw=raw,
    )


def resolve_or_register_output(path: Any, *, session: HonuaSession | None = None) -> ResolvedSource:
    """Resolve an output path and, if it's a string, register an alias.

    Output paths from arcpy calls are typically created by the call itself.
    The shim mirrors that by registering a layer alias so subsequent calls
    can reuse the same name without re-resolving against the workspace.

    Unlike input resolution, output registration does NOT short-circuit on an
    existing alias: an output path that collides with a prior registration is
    a duplicate-output condition. :meth:`HonuaSession.register_layer` then
    raises :class:`HonuaArcpyConfigurationError` unless ``env.overwriteOutput``
    is true -- bubble that error so the second process call does not silently
    overwrite a protected output.
    """

    session = session or get_session()
    resolved = resolve(path, session=session)
    if resolved.kind != "honua-uri" and isinstance(path, str):
        alias = LayerAlias(
            name=path,
            source=resolved.source,
            workspace=resolved.workspace or session.workspace,
        )
        session.register_layer(alias)
    return resolved


def descriptor_mapping(
    resolved: ResolvedSource,
    *,
    session: HonuaSession | None = None,
) -> dict[str, Any]:
    """Project a :class:`ResolvedSource` onto a :class:`SourceDescriptor` mapping.

    ``HonuaClient.source(...)`` requires a ``SourceDescriptor`` or mapping;
    raw strings raise ``TypeError`` from the SDK coercion path. This helper
    converts the shim's resolved source (a string + workspace hint) into a
    mapping the real SDK accepts. It is best-effort: customers with non-
    trivial paths should declare them in ``HONUA_ARCPY_PATH_MAP``.
    """

    session = session or get_session()
    source = resolved.source
    workspace = resolved.workspace or session.workspace

    service_id: str | None = None
    layer_id: int | None = None

    if source.startswith("honua://services/"):
        rest = source[len("honua://services/") :]
        parts = [part for part in rest.split("/") if part]
        if parts:
            service_id = parts[0]
        if len(parts) >= 2:
            try:
                layer_id = int(parts[1])
            except ValueError as exc:
                raise HonuaArcpyResolveError(
                    source,
                    hint=(
                        "honua://services URIs must use a numeric layer id "
                        "(for example honua://services/transport/0); layer "
                        "name lookup is not implemented by the shim."
                    ),
                ) from exc
            if layer_id < 0:
                raise HonuaArcpyResolveError(
                    source,
                    hint="honua://services URIs must use a non-negative numeric layer id.",
                )
    elif isinstance(workspace, str) and workspace.startswith("honua://services/"):
        ws_parts = [part for part in workspace[len("honua://services/") :].split("/") if part]
        if ws_parts:
            service_id = ws_parts[0]
        layer_id = 0
    else:
        service_id = source
        layer_id = 0

    locator: dict[str, Any] = {}
    if service_id is not None:
        locator["serviceId"] = service_id
    if layer_id is not None:
        locator["layerId"] = layer_id

    return {
        "id": resolved.source,
        "protocol": "geoservices-feature-service",
        "locator": locator,
    }


def resolve_layer_id(path: Any, *, session: HonuaSession | None = None) -> int:
    """Project an arcpy path / layer alias onto a honua-server ``layerId``.

    honua-server's layer-aware geoprocessing operations
    (``analytics.spatial-join``, ``generalization.dissolve``,
    ``conversion.feature-project``, ``data-management.*``) address their input
    by a numeric ``layerId``, not by an arcpy feature-class path. This helper
    reuses :func:`resolve` + :func:`descriptor_mapping` so a single source of
    truth (alias map, ``honua://`` URIs, ``HONUA_ARCPY_PATH_MAP``) drives both
    the source-facade descriptor and the process ``layerId``.

    The ``layerId`` is taken from the resolved descriptor's ``locator.layerId``.
    ``descriptor_mapping`` defaults unrecognized paths to ``layerId=0``; a
    ``honua://services/<svc>/<n>`` URI yields ``<n>``. A non-integer or negative
    layer id raises :class:`HonuaArcpyResolveError` so the caller surfaces the
    gap arcpy-style instead of POSTing an invalid process payload.
    """

    session = session or get_session()
    resolved = resolve(path, session=session)
    descriptor = descriptor_mapping(resolved, session=session)
    layer_id = descriptor.get("locator", {}).get("layerId")
    if not isinstance(layer_id, int) or isinstance(layer_id, bool) or layer_id < 0:
        raise HonuaArcpyResolveError(
            str(path),
            hint=(
                "Layer-aware geoprocessing requires a numeric layer id. Point "
                "the input at a honua://services/<service>/<layerId> URI (or a "
                "HONUA_ARCPY_PATH_MAP entry that resolves to one) so the shim "
                "can address the honua-server process by layerId."
            ),
        )
    return layer_id


__all__ = [
    "ResolvedSource",
    "descriptor_mapping",
    "resolve",
    "resolve_layer_id",
    "resolve_or_register_output",
]

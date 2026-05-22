"""Central dispatcher.

Every shim function calls :func:`dispatch_process`, :func:`dispatch_admin`,
or builds its own audit-wrapped call against the session. The dispatcher:

1. Looks up the manifest entry.
2. Routes to the configured backend.
3. Records an audit JSONL line (success and failure).
4. Wraps internal exceptions into the ``ExecuteError`` hierarchy so
   ``except arcpy.ExecuteError:`` keeps working.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from ._audit import _shape_of, record_call
from ._compat import COMPAT, FunctionEntry, anchor_for
from ._errors import (
    ExecuteError,
    HonuaArcpyConfigurationError,
    HonuaArcpyResolveError,
    HonuaArcpyUnsupportedError,
)
from ._resolve import resolve, resolve_or_register_output
from ._session import HonuaSession, get_session

LOGGER = logging.getLogger("honua_arcpy.dispatch")


def _entry_or_raise(qualified_name: str) -> FunctionEntry:
    entry = COMPAT.get(qualified_name)
    if entry is None:
        raise HonuaArcpyUnsupportedError(
            qualified_name,
            compat_anchor=anchor_for(qualified_name),
            replacement_hint="Function is not registered in the compatibility manifest.",
        )
    return entry


def raise_unsupported(
    qualified_name: str,
    *,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    replacement_hint: str | None = None,
    tracking: str | None = None,
    compat_anchor: str | None = None,
) -> None:
    """Raise ``HonuaArcpyUnsupportedError`` and record an audit line.

    Stubs and partial-mode rejects (e.g. ``SelectLayerByAttribute`` with
    ``selection_type=SWITCH_SELECTION``) route through this helper so the
    JSONL audit stream stays complete: every shim call -- including the
    ones the shim immediately refuses -- writes one line with
    ``status="error"`` and a meaningful ``error_kind``.

    Explicit ``replacement_hint`` / ``tracking`` / ``compat_anchor``
    overrides take precedence over the manifest values so callers can
    scope the error to a specific function variant (e.g.
    ``SWITCH_SELECTION``) without claiming the whole function is
    unsupported and without breaking the matrix anchor URL.
    """

    entry = COMPAT.get(qualified_name)
    if entry is None or entry.backend != "not_implemented":
        effective_hint = replacement_hint or "Function is not registered in the compatibility manifest."
        effective_tracking = tracking
    else:
        effective_hint = replacement_hint if replacement_hint is not None else entry.replacement_hint
        effective_tracking = tracking if tracking is not None else entry.tracking
    effective_anchor = compat_anchor or anchor_for(qualified_name)

    error = HonuaArcpyUnsupportedError(
        qualified_name,
        compat_anchor=effective_anchor,
        replacement_hint=effective_hint,
        tracking=effective_tracking,
    )

    writer = None
    try:
        writer = get_session().audit_writer()
    except Exception:
        # Audit is observability; never let a session-bootstrap failure
        # mask the underlying unsupported-call signal.
        writer = None

    if writer is None:
        raise error
    with record_call(qualified_name, args=args, kwargs=kwargs or {}, writer=writer):
        raise error


def bind_arguments(
    qualified_name: str,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    *,
    entry: FunctionEntry | None = None,
) -> dict[str, Any]:
    """Bind positional + keyword args to arcpy parameter names from the manifest."""

    entry = entry or _entry_or_raise(qualified_name)
    ordered_params = list(entry.param_map.keys())
    bound: dict[str, Any] = {}

    for index, value in enumerate(args):
        if index < len(ordered_params):
            bound[ordered_params[index]] = value
        else:
            bound[f"arg_{index + 1}"] = value

    for key, value in kwargs.items():
        bound[key] = value
    return bound


def _project_to_process_inputs(
    entry: FunctionEntry,
    bound: Mapping[str, Any],
    *,
    session: HonuaSession,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Project bound arcpy args into process inputs / outputs / metadata."""

    inputs: dict[str, Any] = {}
    outputs: dict[str, Any] = {}
    metadata: dict[str, Any] = {}

    for arcpy_name, value in bound.items():
        if value is None:
            continue
        process_name = entry.param_map.get(arcpy_name, arcpy_name)
        if arcpy_name in entry.output_params:
            resolved = resolve_or_register_output(value, session=session)
            outputs[process_name] = resolved.source
            continue
        if arcpy_name in entry.source_params:
            inputs[process_name] = _resolve_source_value(value, session=session)
            continue
        # Non-source parameters (dissolve_option, expression, CRS strings,
        # numeric thresholds, etc.) pass through untouched. Routing them
        # through ``resolve()`` would let a HONUA_ARCPY_PATH_MAP entry that
        # collides with a literal like ``"ALL"`` silently rewrite the value
        # before the process executor sees it.
        inputs[process_name] = value

    if session.output_coordinate_system is not None:
        metadata["outputCoordinateSystem"] = session.output_coordinate_system
    if session.workspace is not None:
        metadata["workspace"] = session.workspace
    if session.overwrite_output:
        metadata["overwriteOutput"] = True
    if session.parallel_processing_factor is not None:
        metadata["parallelProcessingFactor"] = session.parallel_processing_factor

    return inputs, outputs, metadata


def _resolve_source_value(value: Any, *, session: HonuaSession) -> Any:
    """Resolve a source-valued parameter, descending into list / tuple inputs.

    Single string inputs (e.g. ``Buffer.in_features="roads"``) are routed
    through :func:`resolve` exactly as before. Sequence inputs (e.g.
    ``Intersect.in_features=["roads", "parcels"]``) have each string element
    resolved individually so ``HONUA_ARCPY_PATH_MAP`` overrides apply inside
    multi-input parameters.
    """

    if isinstance(value, str):
        return resolve(value, session=session).source
    if isinstance(value, (list, tuple)):
        resolved_elements: list[Any] = []
        for element in value:
            if isinstance(element, str):
                resolved_elements.append(resolve(element, session=session).source)
            else:
                resolved_elements.append(element)
        return type(value)(resolved_elements) if isinstance(value, tuple) else resolved_elements
    return value


def dispatch_process(
    qualified_name: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run a shim function whose backend is ``process``."""

    entry = _entry_or_raise(qualified_name)
    if entry.backend != "process":
        raise HonuaArcpyConfigurationError(
            f"dispatch_process invoked for {qualified_name} (backend={entry.backend})."
        )
    session = get_session()
    bound = bind_arguments(qualified_name, args, kwargs, entry=entry)

    with record_call(qualified_name, args=args, kwargs=kwargs, writer=session.audit_writer()) as record:
        try:
            inputs, outputs, metadata = _project_to_process_inputs(entry, bound, session=session)
            payload: dict[str, Any] = {"inputs": inputs}
            if outputs:
                payload["outputs"] = outputs
            if metadata:
                payload["metadata"] = {"honuaArcpy": metadata}
            processes = session.processes_client()
            result = processes.execute(entry.process_id, payload)
        except ExecuteError:
            raise
        except Exception as exc:  # honua_sdk transport errors -- wrap, keep cause.
            kind = exc.__class__.__name__
            LOGGER.warning("honua_arcpy.%s failed via process %s: %s", qualified_name, entry.process_id, exc)
            raise ExecuteError(
                f"{qualified_name} failed: {exc}",
                function=qualified_name,
                error_kind=kind,
                compat_anchor=anchor_for(qualified_name),
                cause=exc,
            ) from exc
        record["result_shape"] = _shape_of(result)
        record["process_id"] = entry.process_id
        record["payload_keys"] = sorted(payload.keys())
        return result


def dispatch_admin(
    qualified_name: str,
    callable_factory: Callable[[Any, dict[str, Any]], Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run a shim function whose backend is ``admin``.

    ``callable_factory`` is invoked with ``(admin_client, bound_args)`` and
    is expected to perform the underlying admin call. The factory pattern
    keeps the manifest-defined parameter mapping in one place (this module)
    while letting each function pick the right admin endpoint.
    """

    entry = _entry_or_raise(qualified_name)
    if entry.backend != "admin":
        raise HonuaArcpyConfigurationError(
            f"dispatch_admin invoked for {qualified_name} (backend={entry.backend})."
        )
    session = get_session()
    bound = bind_arguments(qualified_name, args, kwargs, entry=entry)
    with record_call(qualified_name, args=args, kwargs=kwargs, writer=session.audit_writer()) as record:
        try:
            admin = session.admin_client()
            result = callable_factory(admin, bound)
        except ExecuteError:
            raise
        except Exception as exc:
            kind = exc.__class__.__name__
            LOGGER.warning("honua_arcpy.%s failed via admin client: %s", qualified_name, exc)
            raise ExecuteError(
                f"{qualified_name} failed: {exc}",
                function=qualified_name,
                error_kind=kind,
                compat_anchor=anchor_for(qualified_name),
                cause=exc,
            ) from exc
        record["result_shape"] = _shape_of(result)
        return result


@contextmanager
def dispatch_source(
    qualified_name: str,
    *args: Any,
    **kwargs: Any,
) -> Iterator[tuple[FunctionEntry, dict[str, Any], dict[str, Any]]]:
    """Yield ``(entry, bound, record)`` for ``backend=source`` callers.

    Cursor classes need full control over the iteration / commit lifecycle,
    so the dispatcher just supplies bound arguments + the audit record.
    """

    entry = _entry_or_raise(qualified_name)
    if entry.backend != "source":
        raise HonuaArcpyConfigurationError(
            f"dispatch_source invoked for {qualified_name} (backend={entry.backend})."
        )
    session = get_session()
    bound = bind_arguments(qualified_name, args, kwargs, entry=entry)
    with record_call(qualified_name, args=args, kwargs=kwargs, writer=session.audit_writer()) as record:
        try:
            yield entry, bound, record
        except ExecuteError:
            raise
        except HonuaArcpyResolveError:
            raise
        except Exception as exc:
            kind = exc.__class__.__name__
            LOGGER.warning("honua_arcpy.%s failed via source client: %s", qualified_name, exc)
            raise ExecuteError(
                f"{qualified_name} failed: {exc}",
                function=qualified_name,
                error_kind=kind,
                compat_anchor=anchor_for(qualified_name),
                cause=exc,
            ) from exc


def dispatch_session(
    qualified_name: str,
    handler: Callable[[HonuaSession, dict[str, Any]], Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run a shim function whose backend is ``session``."""

    entry = _entry_or_raise(qualified_name)
    if entry.backend != "session":
        raise HonuaArcpyConfigurationError(
            f"dispatch_session invoked for {qualified_name} (backend={entry.backend})."
        )
    session = get_session()
    bound = bind_arguments(qualified_name, args, kwargs, entry=entry)
    with record_call(qualified_name, args=args, kwargs=kwargs, writer=session.audit_writer()) as record:
        result = handler(session, bound)
        record["result_shape"] = _shape_of(result)
        return result


__all__ = [
    "bind_arguments",
    "dispatch_admin",
    "dispatch_process",
    "dispatch_session",
    "dispatch_source",
    "raise_unsupported",
]


def _signature_of(callable_obj: Callable[..., Any]) -> inspect.Signature:
    return inspect.signature(callable_obj)

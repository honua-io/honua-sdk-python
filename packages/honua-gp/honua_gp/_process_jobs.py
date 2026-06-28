"""OGC API Processes job submit-and-poll helper.

honua-server's ``BuiltInProcessCatalog`` operations all execute as
**asynchronous jobs**: ``POST .../execution`` returns a ``201 Created`` with an
``OgcStatusInfo`` body (``{"jobID": ..., "status": "accepted"}``) rather than an
inline result. The arcpy idiom is synchronous -- ``arcpy.analysis.Buffer(...)``
returns a ``Result`` whose ``[0]`` is the output path -- so every promoted
process-backed shim must submit the job, poll ``/jobs/{id}`` until it reaches a
terminal state, and surface the outcome arcpy-style.

This module owns that submit/poll loop. It is deliberately transport-agnostic:
it only calls the four methods every ``OgcProcessesClient`` exposes
(``execute`` / ``job`` / ``job_results``) plus the optional ``dismiss_job`` for
cleanup, so the faked transports used in the test-suite drive the exact same
code path the real ``honua_sdk.protocols.OgcProcessesClient`` does.

OGC job status vocabulary (from honua-server's
``OgcProcessesConversionHelpers.ToOgcStatus``):

* ``accepted`` / ``running`` -- non-terminal, keep polling.
* ``successful`` -- terminal success; results are fetched from ``/results``.
* ``failed`` -- terminal failure; raise ``ExecuteError``.
* ``dismissed`` -- terminal cancellation; raise ``ExecuteError``.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._errors import ExecuteError

# Terminal OGC job states. ``successful`` is the only non-error terminal state.
_TERMINAL_OK = "successful"
_TERMINAL_ERROR = {"failed", "dismissed"}
_TERMINAL = {_TERMINAL_OK, *_TERMINAL_ERROR}

# Default polling envelope. These mirror a conservative arcpy "wait for the GP
# tool to finish" loop; callers can override per-tool when a process is known to
# be long-running.
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class JobOutcome:
    """Result of a completed OGC API Processes job.

    ``status_info`` is the final ``/jobs/{id}`` document (or the execute
    response when it was already terminal); ``results`` is the
    ``/jobs/{id}/results`` document for a successful job (``None`` when the
    transport returned no results body).
    """

    job_id: str
    status: str
    status_info: Mapping[str, Any]
    results: Mapping[str, Any] | None


def _job_id(payload: Mapping[str, Any]) -> str | None:
    """Extract the job id from a StatusInfo body.

    honua-server serializes the id as ``jobID`` (OGC StatusInfo schema). We
    also accept ``jobId`` / ``id`` defensively so a transport that normalizes
    casing still works.
    """

    for key in ("jobID", "jobId", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _status(payload: Mapping[str, Any]) -> str:
    status = payload.get("status")
    return status.lower() if isinstance(status, str) else ""


def submit_and_wait(
    processes: Any,
    process_id: str,
    inputs: Mapping[str, Any],
    *,
    function: str,
    compat_anchor: str | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    sleep: Any = time.sleep,
) -> JobOutcome:
    """Submit ``process_id`` and block until the job reaches a terminal state.

    The execution body follows the OGC API Processes ``execute`` schema:
    ``{"inputs": {...}}`` keyed by the process's typed input names. The server
    accepts only ``inputs`` at the top level (``OgcExecuteRequest``), so we do
    not wrap outputs/metadata here -- the layer-aware processes return a new
    artifact addressed by the results document.

    Raises :class:`~honua_gp._errors.ExecuteError` when the job fails, is
    dismissed, or the poll loop exceeds ``timeout``.
    """

    response = processes.execute(process_id, {"inputs": dict(inputs)})
    if not isinstance(response, Mapping):
        raise ExecuteError(
            f"{function} failed: process {process_id} returned a non-mapping execution response.",
            function=function,
            error_kind="protocol",
            compat_anchor=compat_anchor,
        )

    job_id = _job_id(response)
    status = _status(response)

    # Some transports return the terminal status inline on the execute response
    # (a fast/synchronous job). Honour that before entering the poll loop.
    if status in _TERMINAL:
        return _finalize(processes, process_id, job_id, status, response, function, compat_anchor)

    if job_id is None:
        raise ExecuteError(
            f"{function} failed: process {process_id} accepted the job but returned no jobID.",
            function=function,
            error_kind="protocol",
            compat_anchor=compat_anchor,
        )

    deadline = time.monotonic() + timeout
    status_info: Mapping[str, Any] = response
    while True:
        if time.monotonic() >= deadline:
            # Best-effort cleanup so a timed-out job does not linger; never let
            # a dismiss failure mask the timeout itself.
            _try_dismiss(processes, job_id)
            raise ExecuteError(
                f"{function} timed out after {timeout:g}s waiting for process "
                f"{process_id} job {job_id} (last status: {status or 'unknown'}).",
                function=function,
                error_kind="timeout",
                compat_anchor=compat_anchor,
            )
        sleep(poll_interval)
        polled = processes.job(job_id)
        if not isinstance(polled, Mapping):
            raise ExecuteError(
                f"{function} failed: job poll for {job_id} returned a non-mapping response.",
                function=function,
                error_kind="protocol",
                compat_anchor=compat_anchor,
            )
        status_info = polled
        status = _status(polled)
        if status in _TERMINAL:
            return _finalize(processes, process_id, job_id, status, status_info, function, compat_anchor)


def _finalize(
    processes: Any,
    process_id: str,
    job_id: str | None,
    status: str,
    status_info: Mapping[str, Any],
    function: str,
    compat_anchor: str | None,
) -> JobOutcome:
    if status in _TERMINAL_ERROR:
        message = status_info.get("message")
        detail = f": {message}" if isinstance(message, str) and message else ""
        raise ExecuteError(
            f"{function} failed: process {process_id} job {job_id or '<unknown>'} ended {status}{detail}.",
            function=function,
            error_kind=status,
            compat_anchor=compat_anchor,
        )

    results: Mapping[str, Any] | None = None
    if job_id is not None:
        fetched = processes.job_results(job_id)
        if isinstance(fetched, Mapping):
            results = fetched
    return JobOutcome(
        job_id=job_id or "",
        status=status,
        status_info=status_info,
        results=results,
    )


def _try_dismiss(processes: Any, job_id: str) -> None:
    dismiss = getattr(processes, "dismiss_job", None)
    if dismiss is None:
        return
    with contextlib.suppress(Exception):  # cleanup is best-effort.
        dismiss(job_id)


__all__ = [
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "JobOutcome",
    "submit_and_wait",
]

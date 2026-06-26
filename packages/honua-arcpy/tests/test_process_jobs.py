"""Unit tests for the OGC API Processes submit-and-poll helper."""

from __future__ import annotations

import pytest

from honua_arcpy._errors import ExecuteError
from honua_arcpy._process_jobs import submit_and_wait


class _Transport:
    def __init__(self, statuses: list[str], *, with_job_id: bool = True) -> None:
        self._statuses = statuses
        self._index = 0
        self._with_job_id = with_job_id
        self.executed: list[tuple[str, dict]] = []
        self.polled: list[str] = []
        self.results_for: list[str] = []
        self.dismissed: list[str] = []

    def execute(self, process_id: str, payload: dict) -> dict:
        self.executed.append((process_id, payload))
        body: dict = {"processID": process_id, "status": self._statuses[0]}
        if self._with_job_id:
            body["jobID"] = "j-1"
        return body

    def job(self, job_id: str) -> dict:
        self.polled.append(job_id)
        self._index += 1
        status = self._statuses[min(self._index, len(self._statuses) - 1)]
        return {"jobID": job_id, "status": status, "message": "kaput" if status == "failed" else None}

    def job_results(self, job_id: str) -> dict:
        self.results_for.append(job_id)
        return {"jobID": job_id, "outputs": {"result": 1}}

    def dismiss_job(self, job_id: str) -> None:
        self.dismissed.append(job_id)


def _no_sleep(_seconds: float) -> None:
    return None


def test_submit_and_wait_polls_to_success_and_fetches_results() -> None:
    transport = _Transport(["accepted", "running", "successful"])
    outcome = submit_and_wait(
        transport, "p.test", {"layerId": 1}, function="test.tool", sleep=_no_sleep
    )
    assert outcome.status == "successful"
    assert outcome.job_id == "j-1"
    assert outcome.results == {"jobID": "j-1", "outputs": {"result": 1}}
    assert transport.executed == [("p.test", {"inputs": {"layerId": 1}})]
    assert transport.polled == ["j-1", "j-1"]
    assert transport.results_for == ["j-1"]


def test_submit_and_wait_inline_terminal_skips_polling() -> None:
    transport = _Transport(["successful"])
    outcome = submit_and_wait(
        transport, "p.test", {}, function="test.tool", sleep=_no_sleep
    )
    assert outcome.status == "successful"
    assert transport.polled == []  # already terminal on the execute response


def test_submit_and_wait_failed_raises_execute_error() -> None:
    transport = _Transport(["accepted", "failed"])
    with pytest.raises(ExecuteError) as info:
        submit_and_wait(transport, "p.test", {}, function="test.tool", sleep=_no_sleep)
    assert info.value.error_kind == "failed"
    assert "kaput" in str(info.value)


def test_submit_and_wait_dismissed_raises_execute_error() -> None:
    transport = _Transport(["accepted", "dismissed"])
    with pytest.raises(ExecuteError) as info:
        submit_and_wait(transport, "p.test", {}, function="test.tool", sleep=_no_sleep)
    assert info.value.error_kind == "dismissed"


def test_submit_and_wait_timeout_dismisses_and_raises() -> None:
    transport = _Transport(["accepted", "running"])
    with pytest.raises(ExecuteError) as info:
        submit_and_wait(
            transport, "p.test", {}, function="test.tool", timeout=0.0, sleep=_no_sleep
        )
    assert info.value.error_kind == "timeout"
    # Best-effort cleanup dismissed the lingering job.
    assert transport.dismissed == ["j-1"]


def test_submit_and_wait_missing_job_id_raises() -> None:
    transport = _Transport(["accepted"], with_job_id=False)
    with pytest.raises(ExecuteError) as info:
        submit_and_wait(transport, "p.test", {}, function="test.tool", sleep=_no_sleep)
    assert info.value.error_kind == "protocol"

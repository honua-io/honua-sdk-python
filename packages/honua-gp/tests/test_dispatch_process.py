"""Process-backed dispatch: stub routing, audit JSONL, exception surface.

The shim does NOT yet implement the arcpy -> honua-server projection
adapter (see ``test_compat_manifest.py::test_process_backed_entries_match_honua_server_catalog``),
so every analysis.* and management.* entry that previously dispatched
through ``dispatch_process`` now routes through ``raise_unsupported``
instead. The tests below pin the new contract -- the dispatcher itself
is exercised through a private test-only manifest entry so future
process-backed entries can be re-added with confidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import honua_gp
from honua_gp._compat import COMPAT, FunctionEntry
from honua_gp._dispatch import dispatch_process


class _CapturingProcessesClient:
    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.response = response or {"processID": "_test.echo", "status": "accepted"}

    def execute(self, process_id: str, payload: dict) -> dict:
        self.calls.append((process_id, payload))
        return self.response


def _audit_lines(audit_root: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(audit_root.glob("audit-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Downgraded entries: every previously process-backed analysis / management
# function now raises HonuaGpUnsupportedError + writes one audit line.
# ---------------------------------------------------------------------------


# Overlay tools (Clip/Intersect/Union/Erase) only have single-WKB
# geometry.* counterparts, not layer-aware ones, so they stay stubs. Delete
# stays a stub because arcpy.Delete removes a dataset while honua-server's
# delete-features only deletes filtered features inside a layer.
_DOWNGRADED = [
    ("analysis.Clip", lambda: honua_gp.analysis.Clip("roads", "study", "clip")),
    ("analysis.Intersect", lambda: honua_gp.analysis.Intersect(["roads", "parcels"], "out")),
    ("analysis.Union", lambda: honua_gp.analysis.Union(["a", "b"], "out")),
    ("analysis.Erase", lambda: honua_gp.analysis.Erase("roads", "water", "out")),
    ("management.Delete", lambda: honua_gp.management.Delete("a")),
]


@pytest.mark.parametrize("qualified,invoke", _DOWNGRADED, ids=[name for name, _ in _DOWNGRADED])
def test_downgraded_process_entries_raise_unsupported(
    _isolated_audit_dir: Path, qualified: str, invoke,
) -> None:
    """The overlay tools (Clip/Intersect/Union/Erase) have no layer-aware
    honua-server process -- only single-WKB ``geometry.*`` ops -- and Delete
    has different semantics from delete-features, so each must stay an honest
    stub that raises ``HonuaGpUnsupportedError`` and writes a JSONL audit
    line with ``status="error"`` / ``error_kind="unsupported"`` plus a
    tracking ticket."""

    with pytest.raises(honua_gp.HonuaGpUnsupportedError) as info:
        invoke()
    err = info.value
    assert err.function == qualified
    assert err.tracking and err.tracking.startswith("honua-server#")
    assert err.replacement_hint, f"{qualified} stub must carry a replacement hint"

    lines = _audit_lines(_isolated_audit_dir)
    refused = [r for r in lines if r["function"] == qualified]
    assert refused, f"{qualified} refusal was not audited"
    assert refused[-1]["status"] == "error"
    assert refused[-1]["error_kind"] == "unsupported"


# ---------------------------------------------------------------------------
# Dispatcher exercise via a private test-only manifest entry. Keeps the
# overwrite / rollback / failure-wrapping invariants covered without
# claiming false compatibility for production shim entries.
# ---------------------------------------------------------------------------


_TEST_ENTRY_NAME = "_test.process_echo"
_TEST_ENTRY = FunctionEntry(
    backend="process",
    status="supported",
    process_id="_test.echo",
    notes="Test-only manifest entry. Never exposed to customers.",
    param_map={
        "in_features": "input_features",
        "out_feature_class": "result",
        "distance": "distance",
        "extra": "extra",
    },
    output_params=("out_feature_class",),
    source_params=("in_features",),
)


@pytest.fixture
def _registered_test_entry():
    """Register the test-only process entry in COMPAT for the duration of the
    test. The contract test in ``test_compat_manifest.py`` only checks
    *real* entries (it walks the snapshot keys); a private entry whose
    ``process_id`` is not in the snapshot would fail that guard, which is
    why we register / unregister inside this fixture."""

    COMPAT[_TEST_ENTRY_NAME] = _TEST_ENTRY
    try:
        yield _TEST_ENTRY_NAME
    finally:
        COMPAT.pop(_TEST_ENTRY_NAME, None)


def test_dispatch_process_emits_payload_and_audit(
    _isolated_audit_dir: Path, _registered_test_entry: str,
) -> None:
    proc = _CapturingProcessesClient()
    honua_gp.configure(processes_client=proc)
    dispatch_process(
        _registered_test_entry,
        in_features="roads",
        out_feature_class="out",
        distance="5 Meters",
    )

    assert proc.calls == [(
        "_test.echo",
        {
            "inputs": {"input_features": "roads", "distance": "5 Meters"},
            "outputs": {"result": "out"},
        },
    )]
    lines = _audit_lines(_isolated_audit_dir)
    assert len(lines) == 1
    record = lines[0]
    assert record["function"] == _registered_test_entry
    assert record["status"] == "ok"
    assert record["process_id"] == "_test.echo"


def test_dispatch_process_failure_wraps_in_execute_error(
    _isolated_audit_dir: Path, _registered_test_entry: str,
) -> None:
    class _FailingProcessClient:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    honua_gp.configure(processes_client=_FailingProcessClient())
    with pytest.raises(honua_gp.ExecuteError) as info:
        dispatch_process(
            _registered_test_entry,
            in_features="a", out_feature_class="b", distance=1,
        )
    err = info.value
    assert err.function == _registered_test_entry
    assert err.error_kind == "RuntimeError"
    assert "compatibility-matrix" in (err.compat_anchor or "")

    lines = _audit_lines(_isolated_audit_dir)
    assert lines[0]["status"] == "error"
    assert lines[0]["error_kind"] == "RuntimeError"


def test_dispatch_process_skips_none_kwargs(
    _isolated_audit_dir: Path, _registered_test_entry: str,
) -> None:
    proc = _CapturingProcessesClient()
    honua_gp.configure(processes_client=proc)
    dispatch_process(
        _registered_test_entry,
        in_features="roads",
        out_feature_class="out",
        distance="5 Meters",
        extra=None,
    )
    payload = proc.calls[0][1]
    assert "extra" not in payload["inputs"]


def test_dispatch_process_overwrite_output_guard_prevents_duplicate_output(
    _isolated_audit_dir: Path, _registered_test_entry: str,
) -> None:
    """Two dispatch_process calls to the same output must fail when
    overwriteOutput=False."""

    proc = _CapturingProcessesClient()
    honua_gp.configure(processes_client=proc)
    honua_gp.env.overwriteOutput = False

    dispatch_process(_registered_test_entry, in_features="roads", out_feature_class="out", distance=1)
    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        dispatch_process(_registered_test_entry, in_features="roads", out_feature_class="out", distance=2)
    assert len(proc.calls) == 1


def test_dispatch_process_overwrite_output_true_allows_replace(
    _isolated_audit_dir: Path, _registered_test_entry: str,
) -> None:
    proc = _CapturingProcessesClient()
    honua_gp.configure(processes_client=proc)
    honua_gp.env.overwriteOutput = True

    dispatch_process(_registered_test_entry, in_features="roads", out_feature_class="out", distance=1)
    dispatch_process(_registered_test_entry, in_features="roads", out_feature_class="out", distance=2)
    assert len(proc.calls) == 2


def test_dispatch_process_failed_call_rolls_back_output_alias(
    _isolated_audit_dir: Path, _registered_test_entry: str,
) -> None:
    """A failed process call must not leave its output alias behind so
    retries are not blocked by the duplicate-output guard."""

    class _FailingProcessClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def execute(self, process_id: str, payload: dict) -> dict:
            self.calls.append((process_id, payload))
            raise RuntimeError("backend boom")

    proc = _FailingProcessClient()
    honua_gp.configure(processes_client=proc)
    honua_gp.env.overwriteOutput = False

    with pytest.raises(honua_gp.ExecuteError):
        dispatch_process(_registered_test_entry, in_features="roads", out_feature_class="out", distance=1)

    assert honua_gp.get_session().get_layer("out") is None

    working = _CapturingProcessesClient()
    honua_gp.configure(processes_client=working)
    dispatch_process(_registered_test_entry, in_features="roads", out_feature_class="out", distance=2)
    assert len(working.calls) == 1
    assert honua_gp.get_session().get_layer("out") is not None


def test_dispatch_process_failed_call_restores_prior_output_alias_under_overwrite(
    _isolated_audit_dir: Path, _registered_test_entry: str,
) -> None:
    class _FailingProcessClient:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("backend boom")

    working = _CapturingProcessesClient()
    honua_gp.configure(processes_client=working)
    honua_gp.env.overwriteOutput = True
    dispatch_process(_registered_test_entry, in_features="roads", out_feature_class="out", distance=1)
    first_alias = honua_gp.get_session().get_layer("out")
    assert first_alias is not None
    first_alias_source = first_alias.source

    honua_gp.configure(processes_client=_FailingProcessClient())
    with pytest.raises(honua_gp.ExecuteError):
        dispatch_process(_registered_test_entry, in_features="highways", out_feature_class="out", distance=2)

    restored = honua_gp.get_session().get_layer("out")
    assert restored is not None
    assert restored.source == first_alias_source


def test_dispatch_process_path_map_applies_to_list_inputs(
    _isolated_audit_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    _registered_test_entry: str,
) -> None:
    """Verify HONUA_GP_PATH_MAP rewrites string elements of list-valued
    source params. The test-only entry declares ``in_features`` as a
    source param so the dispatcher's list-walking path is exercised."""

    monkeypatch.setenv(
        "HONUA_GP_PATH_MAP",
        '{"roads": "honua://services/transport/0", "parcels": "honua://services/land/1"}',
    )
    proc = _CapturingProcessesClient()
    honua_gp.configure(processes_client=proc)

    dispatch_process(
        _registered_test_entry,
        in_features=["roads", "parcels"],
        out_feature_class="joined",
        distance=1,
    )

    payload = proc.calls[0][1]
    assert payload["inputs"]["input_features"] == [
        "honua://services/transport/0",
        "honua://services/land/1",
    ]


def test_dispatch_process_path_map_does_not_rewrite_non_source_params(
    _isolated_audit_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    _registered_test_entry: str,
) -> None:
    """HONUA_GP_PATH_MAP entries must NOT rewrite non-source string
    params -- a path-map alias that collides with an arcpy literal must
    not silently corrupt the process payload."""

    monkeypatch.setenv(
        "HONUA_GP_PATH_MAP",
        '{"roads": "honua://services/transport/0",'
        ' "ALL": "honua://services/policy/all"}',
    )
    proc = _CapturingProcessesClient()
    honua_gp.configure(processes_client=proc)

    dispatch_process(
        _registered_test_entry,
        in_features="roads",
        out_feature_class="out",
        distance="5 Meters",
        extra="ALL",
    )

    payload = proc.calls[0][1]
    assert payload["inputs"]["input_features"] == "honua://services/transport/0"
    # ``extra`` is not declared as a source param in the test entry, so
    # the path-map alias for "ALL" must not rewrite it.
    assert payload["inputs"]["extra"] == "ALL"
    assert payload["inputs"]["distance"] == "5 Meters"


def test_stub_raises_unsupported_with_anchor_and_hint() -> None:
    with pytest.raises(honua_gp.HonuaGpUnsupportedError) as info:
        honua_gp.analysis.Near("points", "roads")
    err = info.value
    assert err.function == "analysis.Near"
    assert "compatibility-matrix" in (err.compat_anchor or "")
    assert err.replacement_hint and "Source.query" in err.replacement_hint
    assert err.tracking and err.tracking.startswith("honua-server#")

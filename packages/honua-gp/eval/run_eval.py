"""Golden eval harness for the honua-gp compatibility shim.

The harness runs every ``eval/scripts/*.py`` in a subprocess and grades it on
three independent layers, from weakest to strongest:

1. **Plumbing** (every mode): exit code, audit-JSONL line count, and a required
   ``stdout`` marker. This only proves the script ran without crashing and
   emitted its audit stream -- it does NOT prove the shim sent the right thing
   or parsed the right thing back.

2. **Request value diff** (every mode): the projected process id + typed inputs
   the shim POSTs to honua-server, captured from the ``process_inputs`` audit
   field. This is deterministic across the stub transport and a live server
   (the projection is transport-independent), so a dispatch /
   parameter-translation regression -- an arcpy argument mapped to the wrong
   process input -- is caught even under the stub, which the canned-response
   stub could never catch on its own.

3. **Response value diff** (live mode only): the values the shim parsed back
   from a REAL, seeded honua-server (buffered geometry type + feature count,
   row counts), captured from the per-script sidecar written by
   ``eval/_emit.py``. The stub only returns a canned ``href``, so this layer is
   graded only when ``HONUA_GP_EVAL_USE_STUB=0`` and a live ``HONUA_BASE_URL``
   is configured.

Honest scope: stub mode grades layers 1-2 (dispatch plumbing + request
fingerprint). Live mode adds layer 3 (round-trip correctness against a real
Honua server). Neither layer verifies ArcGIS Pro output parity -- that requires
a licensed arcpy run and is out of scope here (tracked separately). See
``docs/golden-eval.md``.

Run from the package root::

    python eval/run_eval.py --output-json eval-results.json --output-junit eval-results.xml

Re-capture (bless) the golden value oracles after an intentional change::

    # request fingerprints (stub is enough -- projection is transport-independent)
    python eval/run_eval.py --update-golden
    # response fingerprints (requires a live, seeded honua-server)
    HONUA_GP_EVAL_USE_STUB=0 HONUA_BASE_URL=... python eval/run_eval.py --update-golden

Set ``HONUA_GP_EVAL_USE_STUB=1`` to force the stub transport even when
``HONUA_BASE_URL`` is configured.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree as ET


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT_DIR = PACKAGE_ROOT / "eval" / "scripts"
DEFAULT_GOLDEN_DIR = PACKAGE_ROOT / "eval" / "golden"
DEFAULT_PASS_RATE = 0.70


@dataclass(frozen=True)
class ScriptResult:
    name: str
    status: str  # "pass" | "fail" | "skip"
    duration_ms: float
    exit_code: int
    audit_lines: int
    stdout: str
    stderr: str
    expected_failure: bool = False
    golden: dict[str, Any] | None = None
    reason: str | None = None
    checks: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "durationMs": self.duration_ms,
            "exitCode": self.exit_code,
            "auditLines": self.audit_lines,
            "expectedFailure": self.expected_failure,
            "checks": self.checks,
            "reason": self.reason,
        }


@dataclass
class EvalSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    pass_rate: float = 0.0
    results: list[ScriptResult] = field(default_factory=list)
    pass_threshold: float = DEFAULT_PASS_RATE
    supported_total: int = 0
    supported_passed: int = 0
    supported_pass_rate: float = 0.0
    live_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "passRate": self.pass_rate,
            "passThreshold": self.pass_threshold,
            "supportedTotal": self.supported_total,
            "supportedPassed": self.supported_passed,
            "supportedPassRate": self.supported_pass_rate,
            "liveMode": self.live_mode,
            "results": [result.to_dict() for result in self.results],
        }


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------


def live_values_available() -> bool:
    """True when the run talks to a real server (so response values are real).

    Mirrors ``eval/_stub.stub_active``: the stub transport is the default, and
    a run only produces real response values when ``HONUA_GP_EVAL_USE_STUB`` is
    explicitly ``0`` AND a ``HONUA_BASE_URL`` is configured.
    """

    if os.environ.get("HONUA_GP_EVAL_USE_STUB", "1") == "1":
        return False
    return bool(os.environ.get("HONUA_BASE_URL"))


# ---------------------------------------------------------------------------
# Golden schema (v2 with v1 back-compat)
# ---------------------------------------------------------------------------


def _golden_for(script: Path, golden_dir: Path) -> dict[str, Any] | None:
    target = golden_dir / f"{script.stem}.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _plumbing(golden: dict[str, Any] | None) -> dict[str, Any]:
    """Return the plumbing block, tolerating the legacy flat v1 shape."""

    if not golden:
        return {}
    plumbing = golden.get("plumbing")
    if isinstance(plumbing, dict):
        return plumbing
    # v1: audit_lines / stdout_contains sat at the top level.
    legacy: dict[str, Any] = {}
    for key in ("audit_lines", "stdout_contains"):
        if key in golden:
            legacy[key] = golden[key]
    return legacy


def _golden_is_expected_failure(script: Path, golden: dict[str, Any] | None) -> bool:
    if golden is not None and isinstance(golden.get("expected_failure"), bool):
        return golden["expected_failure"]
    return "expected_failure" in script.stem


# ---------------------------------------------------------------------------
# Captured value oracles
# ---------------------------------------------------------------------------


def _capture_request(audit_root: Path, script: Path) -> list[dict[str, Any]]:
    """Extract the process-dispatch request fingerprint(s) from the audit stream.

    Every process-backed shim call records one audit line carrying
    ``process_id`` and ``process_inputs`` (the projected OGC ``inputs`` payload
    the shim POSTs). Returned in call order so multi-op scripts (e.g.
    buffer-then-dissolve) fingerprint each step. Non-process scripts return an
    empty list.
    """

    audit_dir = audit_root / script.stem
    requests: list[dict[str, Any]] = []
    if not audit_dir.exists():
        return requests
    for file in sorted(audit_dir.glob("audit-*.jsonl")):
        for line in file.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "process_id" in record and "process_inputs" in record:
                requests.append(
                    {
                        "function": record.get("function"),
                        "process_id": record.get("process_id"),
                        "inputs": record.get("process_inputs"),
                    }
                )
    return requests


def _capture_response(result_dir: Path, script: Path) -> dict[str, Any] | None:
    sidecar = result_dir / f"{script.stem}.json"
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _normalize(value: Any) -> Any:
    """Canonicalize for structural comparison (dict key order, list of dicts)."""

    return json.loads(json.dumps(value, sort_keys=True))


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------


def _run_script(
    script: Path,
    *,
    audit_root: Path,
    result_dir: Path,
    timeout: float,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str, float]:
    audit_dir = audit_root / script.stem
    audit_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HONUA_GP_AUDIT_DIR"] = str(audit_dir)
    # Per-script response sidecar directory (read back for the live value diff).
    env["HONUA_GP_EVAL_RESULT_DIR"] = str(result_dir)
    env.setdefault("HONUA_GP_EVAL_USE_STUB", "1")
    # ``_build_pythonpath`` preserves the existing PYTHONPATH and appends the
    # sibling-package extras (only when not already present). Assigning
    # unconditionally is required: an earlier ``env.setdefault(...)`` would
    # leave a host-provided PYTHONPATH untouched and eval scripts could fail
    # to import honua_gp / honua_sdk / honua_admin.
    env["PYTHONPATH"] = _build_pythonpath(env.get("PYTHONPATH", ""))
    if extra_env:
        env.update(extra_env)
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    duration = (time.perf_counter() - start) * 1000.0
    return proc.returncode, proc.stdout, proc.stderr, duration


def _build_pythonpath(existing: str) -> str:
    workspace_root = PACKAGE_ROOT.parent.parent
    extras = [
        str(PACKAGE_ROOT),
        str(workspace_root / "packages" / "honua-sdk"),
        str(workspace_root / "packages" / "honua-admin"),
    ]
    parts = [part for part in existing.split(os.pathsep) if part]
    for extra in extras:
        if extra not in parts:
            parts.append(extra)
    return os.pathsep.join(parts)


def _count_audit_lines(audit_root: Path, script: Path) -> int:
    audit_dir = audit_root / script.stem
    if not audit_dir.exists():
        return 0
    total = 0
    for file in audit_dir.glob("audit-*.jsonl"):
        total += sum(1 for _ in file.open(encoding="utf-8"))
    return total


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def _grade(
    script: Path,
    *,
    exit_code: int,
    audit_lines: int,
    golden: dict[str, Any] | None,
    stdout: str,
    stderr: str,
    request_actual: list[dict[str, Any]],
    response_actual: dict[str, Any] | None,
    live_mode: bool,
) -> tuple[str, bool, str | None, dict[str, str]]:
    """Grade one script across plumbing + request + response layers."""

    expected_failure = _golden_is_expected_failure(script, golden)
    plumbing = _plumbing(golden)
    checks: dict[str, str] = {}

    # --- Layer 0: exit code -------------------------------------------------
    if exit_code != 0:
        tail = stderr.strip().splitlines()[-1] if stderr.strip() else f"exit {exit_code}"
        checks["exit"] = "fail"
        return "fail", expected_failure, f"exited {exit_code}: {tail}", checks
    checks["exit"] = "pass"

    # --- Layer 1: plumbing (marker + audit line count) ----------------------
    marker = plumbing.get("stdout_contains")
    if isinstance(marker, str) and marker and marker not in stdout:
        checks["plumbing"] = "fail"
        prefix = "expected_failure script " if expected_failure else ""
        return "fail", expected_failure, f"{prefix}missing stdout marker: {marker!r}", checks
    expected_audit = plumbing.get("audit_lines")
    if isinstance(expected_audit, int) and expected_audit != audit_lines:
        checks["plumbing"] = "fail"
        prefix = "expected_failure " if expected_failure else ""
        return (
            "fail",
            expected_failure,
            f"{prefix}audit line count mismatch: expected {expected_audit}, got {audit_lines}",
            checks,
        )
    checks["plumbing"] = "pass"

    if expected_failure:
        # expected_failure scripts catch HonuaGpUnsupportedError and exit 0;
        # they have no request/response oracle to diff.
        return "pass", True, "caught expected unsupported error", checks

    # --- Layer 2: request fingerprint (both modes) --------------------------
    golden_request = golden.get("request") if golden else None
    if golden_request is not None:
        if _normalize(request_actual) != _normalize(golden_request):
            checks["request"] = "fail"
            return (
                "fail",
                False,
                "request fingerprint mismatch (dispatch/parameter mapping regression); "
                f"expected {json.dumps(golden_request, sort_keys=True)}, "
                f"got {json.dumps(request_actual, sort_keys=True)}",
                checks,
            )
        checks["request"] = "pass"

    # --- Layer 3: response fingerprint (live mode only) ---------------------
    golden_response = golden.get("response") if golden else None
    if golden_response is not None:
        if not live_mode:
            checks["response"] = "skip(stub)"
        elif response_actual is None:
            checks["response"] = "fail"
            return (
                "fail",
                False,
                "live response fingerprint missing (script emitted no sidecar)",
                checks,
            )
        elif _normalize(response_actual) != _normalize(golden_response):
            checks["response"] = "fail"
            return (
                "fail",
                False,
                "response value mismatch (server round-trip / response parsing regression); "
                f"expected {json.dumps(golden_response, sort_keys=True)}, "
                f"got {json.dumps(response_actual, sort_keys=True)}",
                checks,
            )
        else:
            checks["response"] = "pass"
    elif live_mode and golden is not None and not expected_failure:
        # Live run, supported script, but no response oracle recorded yet.
        checks["response"] = "unblessed"

    return "pass", False, None, checks


def _update_golden(
    script: Path,
    golden_dir: Path,
    golden: dict[str, Any] | None,
    *,
    request_actual: list[dict[str, Any]],
    response_actual: dict[str, Any] | None,
    live_mode: bool,
) -> None:
    """Re-capture (bless) the request/response oracles into the golden file.

    Request fingerprints are written in any mode (transport-independent).
    Response fingerprints are written ONLY in live mode -- the stub's canned
    ``href`` carries no real values and must never be frozen as an oracle.
    """

    document = dict(golden) if golden else {}
    document.setdefault("schema_version", 2)
    if request_actual:
        document["request"] = request_actual
    if live_mode and response_actual is not None:
        document["response"] = response_actual
    target = golden_dir / f"{script.stem}.json"
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(
    script_dir: Path,
    *,
    golden_dir: Path,
    audit_root: Path,
    timeout: float,
    pass_threshold: float,
    update_golden: bool = False,
) -> EvalSummary:
    scripts = sorted(p for p in script_dir.glob("*.py") if not p.name.startswith("_"))
    live_mode = live_values_available()
    summary = EvalSummary(total=len(scripts), pass_threshold=pass_threshold, live_mode=live_mode)
    result_root = Path(tempfile.mkdtemp(prefix="honua-gp-eval-results-"))
    for script in scripts:
        result_dir = result_root / script.stem
        result_dir.mkdir(parents=True, exist_ok=True)
        try:
            exit_code, stdout, stderr, duration_ms = _run_script(
                script,
                audit_root=audit_root,
                result_dir=result_dir,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            summary.results.append(
                ScriptResult(
                    name=script.name,
                    status="fail",
                    duration_ms=timeout * 1000.0,
                    exit_code=-1,
                    audit_lines=0,
                    stdout="",
                    stderr=str(exc),
                    reason=f"timeout after {timeout:.0f}s",
                )
            )
            summary.failed += 1
            continue
        audit_lines = _count_audit_lines(audit_root, script)
        golden = _golden_for(script, golden_dir)
        request_actual = _capture_request(audit_root, script)
        response_actual = _capture_response(result_dir, script)

        if update_golden:
            _update_golden(
                script,
                golden_dir,
                golden,
                request_actual=request_actual,
                response_actual=response_actual,
                live_mode=live_mode,
            )
            golden = _golden_for(script, golden_dir)

        status, expected_failure, reason, checks = _grade(
            script,
            exit_code=exit_code,
            audit_lines=audit_lines,
            golden=golden,
            stdout=stdout,
            stderr=stderr,
            request_actual=request_actual,
            response_actual=response_actual,
            live_mode=live_mode,
        )
        result = ScriptResult(
            name=script.name,
            status=status,
            duration_ms=duration_ms,
            exit_code=exit_code,
            audit_lines=audit_lines,
            stdout=stdout,
            stderr=stderr,
            expected_failure=expected_failure,
            golden=golden,
            reason=reason,
            checks=checks,
        )
        summary.results.append(result)
        if status == "pass":
            summary.passed += 1
        elif status == "skip":
            summary.skipped += 1
        else:
            summary.failed += 1
    runnable = summary.total - summary.skipped
    summary.pass_rate = (summary.passed / runnable) if runnable else 0.0
    # Track the supported-surface pass rate separately so live smoke can fail
    # fast when any non-expected_failure script regresses, even if the overall
    # pass rate stays above the headline threshold (the expected_failure block
    # is large enough to mask total supported-surface collapse otherwise).
    supported_results = [r for r in summary.results if not r.expected_failure and r.status != "skip"]
    summary.supported_total = len(supported_results)
    summary.supported_passed = sum(1 for r in supported_results if r.status == "pass")
    summary.supported_pass_rate = (
        summary.supported_passed / summary.supported_total
    ) if summary.supported_total else 0.0
    return summary


def write_json(summary: EvalSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_junit(summary: EvalSummary, path: Path) -> None:
    root = ET.Element(
        "testsuite",
        attrib={
            "name": "honua-gp.eval",
            "tests": str(summary.total),
            "failures": str(summary.failed),
            "skipped": str(summary.skipped),
        },
    )
    for result in summary.results:
        case = ET.SubElement(
            root,
            "testcase",
            attrib={
                "classname": "honua_gp.eval",
                "name": result.name,
                "time": f"{result.duration_ms / 1000.0:.3f}",
            },
        )
        if result.status == "fail":
            failure = ET.SubElement(case, "failure", attrib={"message": result.reason or "eval script failed"})
            failure.text = result.stderr or result.stdout
        elif result.status == "skip":
            ET.SubElement(case, "skipped", attrib={"message": result.reason or "skipped"})
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_step_summary(summary: EvalSummary, path: Path | None) -> None:
    if path is None:
        return
    mode = "live (real honua-server)" if summary.live_mode else "stub (dispatch plumbing only)"
    lines: list[str] = []
    lines.append("# honua-gp eval results")
    lines.append("")
    lines.append(f"Mode: **{mode}**")
    lines.append(
        f"Pass rate: **{summary.pass_rate:.0%}** ({summary.passed} / {max(summary.total - summary.skipped, 1)})"
    )
    lines.append(f"Threshold: {summary.pass_threshold:.0%}")
    lines.append("")
    lines.append("| Script | Status | Checks | Audit lines | Latency (ms) | Notes |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for result in summary.results:
        notes = result.reason or ""
        check_str = ", ".join(f"{k}:{v}" for k, v in result.checks.items())
        lines.append(
            f"| {result.name} | {result.status} | {check_str} | {result.audit_lines} | {result.duration_ms:.0f} | {notes} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the honua-gp compatibility eval suite.")
    parser.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPT_DIR, help="Directory of eval scripts.")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_DIR, help="Directory of golden reference values.")
    parser.add_argument(
        "--audit-root",
        type=Path,
        default=PACKAGE_ROOT / "eval" / ".audit",
        help="Directory used for per-script audit JSONL output.",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output-json", type=Path, default=PACKAGE_ROOT / "eval-results.json")
    parser.add_argument("--output-junit", type=Path, default=PACKAGE_ROOT / "eval-results.xml")
    parser.add_argument(
        "--step-summary",
        type=Path,
        default=Path(os.environ.get("GITHUB_STEP_SUMMARY")) if os.environ.get("GITHUB_STEP_SUMMARY") else None,
    )
    parser.add_argument("--pass-threshold", type=float, default=DEFAULT_PASS_RATE)
    parser.add_argument(
        "--require-supported-pass-rate",
        type=float,
        default=0.0,
        help=(
            "Independent gate that requires the non-expected_failure pass rate "
            "to be at least this value. Defaults to 0.0 (off) so stub-mode runs "
            "are unchanged. Live smoke runs set this to 1.0 so a regression on "
            "any supported script fails the run even if the expected_failure "
            "block keeps the headline pass rate above --pass-threshold."
        ),
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help=(
            "Re-capture (bless) the request/response value oracles into the "
            "golden files instead of grading against them. Request fingerprints "
            "are written in any mode; response fingerprints only in live mode "
            "(HONUA_GP_EVAL_USE_STUB=0 + HONUA_BASE_URL). Review the diff before "
            "committing."
        ),
    )
    parser.add_argument(
        "--fail-under",
        action="store_true",
        default=True,
        help="Exit non-zero when the pass rate is below the threshold (default: enabled).",
    )
    parser.add_argument(
        "--no-fail-under",
        dest="fail_under",
        action="store_false",
        help="Do not fail when the pass rate is below the threshold (useful for local exploration).",
    )
    args = parser.parse_args(argv)

    summary = run(
        args.scripts,
        golden_dir=args.golden,
        audit_root=args.audit_root,
        timeout=args.timeout,
        pass_threshold=args.pass_threshold,
        update_golden=args.update_golden,
    )
    write_json(summary, args.output_json)
    write_junit(summary, args.output_junit)
    write_step_summary(summary, args.step_summary)

    mode = "live" if summary.live_mode else "stub"
    sys.stdout.write(
        f"honua-gp eval [{mode}]: {summary.passed}/{summary.total} passed ({summary.pass_rate:.0%}); "
        f"threshold {args.pass_threshold:.0%}; "
        f"supported {summary.supported_passed}/{summary.supported_total} "
        f"({summary.supported_pass_rate:.0%}); "
        f"supported-required {args.require_supported_pass_rate:.0%}\n"
    )
    # Name the failures on stdout. The aggregate pass-rate line alone makes a
    # red CI lane undiagnosable from the job log -- the script names and their
    # reasons otherwise only exist in --output-json.
    for result in summary.results:
        if result.status == "fail":
            scope = "expected_failure" if result.expected_failure else "supported"
            sys.stdout.write(
                f"honua-gp eval: FAIL [{scope}] {result.name}: {result.reason or 'no reason recorded'}\n"
            )
    if args.update_golden:
        sys.stdout.write("honua-gp eval: golden value oracles updated; review the diff before committing.\n")
        return 0
    if args.fail_under and summary.pass_rate + 1e-9 < args.pass_threshold:
        return 1
    if (
        args.require_supported_pass_rate > 0.0
        and summary.supported_pass_rate + 1e-9 < args.require_supported_pass_rate
    ):
        sys.stdout.write(
            "honua-gp eval: supported-surface pass rate "
            f"{summary.supported_pass_rate:.0%} is below required "
            f"{args.require_supported_pass_rate:.0%}\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

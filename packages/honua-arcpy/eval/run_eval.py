"""Pass-rate harness for the honua-arcpy eval suite.

The harness:

* Walks ``eval/scripts/*.py`` and executes each script in a subprocess.
* Wires a stub Honua transport (or the real ``HONUA_BASE_URL`` when set) so
  scripts run without an ArcGIS Pro license.
* Records exit code, audit-JSONL shape, and (optionally) a golden-output
  digest match.
* Writes ``eval-results.json`` (machine-readable) and ``eval-results.xml``
  (JUnit) plus a workflow-summary table.

Run from the package root::

    python eval/run_eval.py --output-json eval-results.json --output-junit eval-results.xml

Set ``HONUA_ARCPY_EVAL_USE_STUB=1`` to force the stub transport even when
``HONUA_BASE_URL`` is configured.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "durationMs": self.duration_ms,
            "exitCode": self.exit_code,
            "auditLines": self.audit_lines,
            "expectedFailure": self.expected_failure,
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
            "results": [result.to_dict() for result in self.results],
        }


def _golden_for(script: Path, golden_dir: Path) -> dict[str, Any] | None:
    target = golden_dir / f"{script.stem}.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _run_script(
    script: Path,
    *,
    audit_root: Path,
    timeout: float,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str, float]:
    audit_dir = audit_root / script.stem
    audit_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HONUA_ARCPY_AUDIT_DIR"] = str(audit_dir)
    env.setdefault("HONUA_ARCPY_EVAL_USE_STUB", "1")
    # ``_build_pythonpath`` preserves the existing PYTHONPATH and appends the
    # sibling-package extras (only when not already present). Assigning
    # unconditionally is required: an earlier ``env.setdefault(...)`` would
    # leave a host-provided PYTHONPATH untouched and eval scripts could fail
    # to import honua_arcpy / honua_sdk / honua_admin.
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


def _classify(
    script: Path,
    *,
    exit_code: int,
    audit_lines: int,
    golden: dict[str, Any] | None,
    stdout: str,
    stderr: str,
) -> tuple[str, bool, str | None]:
    expected_failure = "expected_failure" in script.stem
    if expected_failure:
        # expected_failure scripts catch HonuaArcpyUnsupportedError, print the
        # caught function name, and exit 0. The pass signal is the marker.
        if exit_code != 0:
            tail = stderr.strip().splitlines()[-1] if stderr.strip() else f"exit {exit_code}"
            return "fail", True, f"expected_failure script exited {exit_code}: {tail}"
        if golden is not None:
            marker = golden.get("stdout_contains")
            if isinstance(marker, str) and marker and marker not in stdout:
                return "fail", True, f"expected_failure script missing marker {marker!r}"
            # expected_failure scripts still write audit JSONL (the stub
            # records the refused call with status=error). Honour the golden
            # audit_lines count so a regression that loses the refusal-time
            # audit shows up as an eval failure instead of slipping through
            # the expected_failure branch.
            expected_audit = golden.get("audit_lines")
            if isinstance(expected_audit, int) and expected_audit != audit_lines:
                return (
                    "fail",
                    True,
                    f"expected_failure audit line count mismatch: expected {expected_audit}, got {audit_lines}",
                )
        return "pass", True, "caught expected unsupported error"

    if exit_code != 0:
        return "fail", False, stderr.strip().splitlines()[-1] if stderr.strip() else f"exit {exit_code}"

    if golden is not None:
        expected_audit = golden.get("audit_lines")
        if isinstance(expected_audit, int) and expected_audit != audit_lines:
            return (
                "fail",
                False,
                f"audit line count mismatch: expected {expected_audit}, got {audit_lines}",
            )
        required_marker = golden.get("stdout_contains")
        if isinstance(required_marker, str) and required_marker and required_marker not in stdout:
            return "fail", False, f"stdout missing marker: {required_marker!r}"

    return "pass", False, None


def run(
    script_dir: Path,
    *,
    golden_dir: Path,
    audit_root: Path,
    timeout: float,
    pass_threshold: float,
) -> EvalSummary:
    scripts = sorted(p for p in script_dir.glob("*.py") if not p.name.startswith("_"))
    summary = EvalSummary(total=len(scripts), pass_threshold=pass_threshold)
    for script in scripts:
        try:
            exit_code, stdout, stderr, duration_ms = _run_script(
                script,
                audit_root=audit_root,
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
        status, expected_failure, reason = _classify(
            script,
            exit_code=exit_code,
            audit_lines=audit_lines,
            golden=golden,
            stdout=stdout,
            stderr=stderr,
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
            "name": "honua-arcpy.eval",
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
                "classname": "honua_arcpy.eval",
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
    lines: list[str] = []
    lines.append("# honua-arcpy eval results")
    lines.append("")
    lines.append(
        f"Pass rate: **{summary.pass_rate:.0%}** ({summary.passed} / {max(summary.total - summary.skipped, 1)})"
    )
    lines.append(f"Threshold: {summary.pass_threshold:.0%}")
    lines.append("")
    lines.append("| Script | Status | Audit lines | Latency (ms) | Notes |")
    lines.append("| --- | --- | --- | --- | --- |")
    for result in summary.results:
        notes = result.reason or ""
        lines.append(
            f"| {result.name} | {result.status} | {result.audit_lines} | {result.duration_ms:.0f} | {notes} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the honua-arcpy compatibility eval suite.")
    parser.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPT_DIR, help="Directory of eval scripts.")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_DIR, help="Directory of golden reference outputs.")
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
    )
    write_json(summary, args.output_json)
    write_junit(summary, args.output_junit)
    write_step_summary(summary, args.step_summary)

    sys.stdout.write(
        f"honua-arcpy eval: {summary.passed}/{summary.total} passed ({summary.pass_rate:.0%}); "
        f"threshold {args.pass_threshold:.0%}; "
        f"supported {summary.supported_passed}/{summary.supported_total} "
        f"({summary.supported_pass_rate:.0%}); "
        f"supported-required {args.require_supported_pass_rate:.0%}\n"
    )
    if args.fail_under and summary.pass_rate + 1e-9 < args.pass_threshold:
        return 1
    if (
        args.require_supported_pass_rate > 0.0
        and summary.supported_pass_rate + 1e-9 < args.require_supported_pass_rate
    ):
        sys.stdout.write(
            "honua-arcpy eval: supported-surface pass rate "
            f"{summary.supported_pass_rate:.0%} is below required "
            f"{args.require_supported_pass_rate:.0%}\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

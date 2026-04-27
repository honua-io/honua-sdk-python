"""Run the shared staging smoke probes against an installed honua-sdk build."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

from _smoke_harness import (
    SmokeConfigError,
    load_smoke_config_from_env,
    render_smoke_summary,
    run_smoke_suite,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-path",
        default="release-smoke-results.json",
        help="Where to write the machine-readable smoke results JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_smoke_config_from_env()
    except SmokeConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    config = replace(config, results_path=Path(args.results_path))

    report = run_smoke_suite(config)
    report_path = report.write()

    sys.stdout.write(render_smoke_summary(report))
    sys.stdout.write(f"Wrote smoke results to {report_path}\n")
    return 0 if report.overall_status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

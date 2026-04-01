"""CLI entrypoint for the geospatial ETL demo."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from honua_sdk import HonuaClient

from examples.geospatial_etl.workflow import (
    DEFAULT_BASE_URL,
    DEFAULT_LAYER_ID,
    DEFAULT_SERVICE_ID,
    run_workflow,
)

EXAMPLE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_PATH = EXAMPLE_DIR / "data" / "demo_sites.csv"
DEFAULT_OUTPUT_DIR = EXAMPLE_DIR / "output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Honua geospatial ETL demo against a writable FeatureServer layer."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("HONUA_BASE_URL", DEFAULT_BASE_URL),
        help=f"Honua base URL (default: {DEFAULT_BASE_URL} or HONUA_BASE_URL).",
    )
    parser.add_argument(
        "--service-id",
        default=DEFAULT_SERVICE_ID,
        help=f"Target service id (default: {DEFAULT_SERVICE_ID}).",
    )
    parser.add_argument(
        "--layer-id",
        type=int,
        default=DEFAULT_LAYER_ID,
        help=f"Target layer id (default: {DEFAULT_LAYER_ID}).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Input CSV path (default: {DEFAULT_INPUT_PATH}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for demo artifacts (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("HONUA_API_KEY"),
        help="Optional API key for non-anonymous environments (defaults to HONUA_API_KEY).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    with HonuaClient(args.base_url, api_key=args.api_key) as client:
        result = run_workflow(
            client,
            base_url=args.base_url,
            service_id=args.service_id,
            layer_id=args.layer_id,
            input_path=args.input,
            output_dir=args.output_dir,
        )

    print(
        f"Extracted {result.validation.source_row_count} source rows from "
        f"{Path(args.input).resolve()}"
    )
    print(
        f"Validated {result.validation.valid_count} rows and rejected "
        f"{result.validation.rejected_count}"
    )
    if result.pre_load is not None:
        print(
            f"Queried {result.pre_load.feature_count} demo-owned target features before load "
            f"({result.pre_load.target_crs})"
        )

    if result.plan is not None:
        print(f"Planned {result.plan.add_count} adds and {result.plan.update_count} updates")

    apply_status = result.apply_edits_result.get("status")
    if apply_status == "success":
        print(
            f"apply_edits succeeded with "
            f"{result.apply_edits_result.get('successful_edits', 0)} successful edits"
        )
    elif apply_status == "skipped" and result.apply_edits_result.get("reason") == "all_rows_rejected":
        print("apply_edits was skipped because every source row was rejected during validation")
    elif apply_status == "http_error":
        print(
            "apply_edits failed: "
            f"{result.apply_edits_result.get('status_code')} "
            f"{result.apply_edits_result.get('message')}"
        )

    if result.post_load is not None:
        print(f"Queried {result.post_load.feature_count} demo-owned target features after load")
    elif result.error_summary is not None and result.error_stage != "apply_edits":
        print(
            f"{_format_stage_name(result.error_stage)} failed: "
            f"{result.error_summary.get('status_code')} {result.error_summary.get('message')}"
        )

    print(f"Summary artifact: {result.summary_path}")
    if result.preview_path is not None:
        print(f"Preview artifact: {result.preview_path}")

    return result.exit_code


def _format_stage_name(stage: str | None) -> str:
    if stage == "pre_load_query":
        return "Pre-load query"
    if stage == "post_load_query":
        return "Post-load query"
    return "Workflow stage"


if __name__ == "__main__":
    raise SystemExit(main())

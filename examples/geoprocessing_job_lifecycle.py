"""Submit one registered OGC process and wait for its bounded result.

This example deliberately accepts the process id and input object from the
caller. Process input schemas are server-defined; inventing a universal buffer
payload here would make the example look portable when it is not.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from typing import Any

import httpx

from honua_sdk import HonuaClient


def run_job(
    base_url: str,
    process_id: str,
    inputs: Mapping[str, Any],
    *,
    api_key: str | None = None,
    poll_interval: float = 0.5,
    deadline_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Submit, wait, and fetch results for one registered process.

    ``deadline_seconds`` bounds polling. The SDK performs a best-effort
    dismiss when that wait expires. An operator-triggered cancellation should
    call ``client.geoprocessing().dismiss(job_id)`` explicitly.
    """

    options: dict[str, Any] = {"api_key": api_key, "timeout": 10.0}
    if transport is not None:
        options["transport"] = transport

    with HonuaClient(base_url, **options) as client:
        geoprocessing = client.geoprocessing()
        submitted = geoprocessing.submit_inputs(process_id, dict(inputs))
        terminal = geoprocessing.wait(
            submitted,
            poll_interval=poll_interval,
            timeout=deadline_seconds,
        )
        return geoprocessing.results(terminal.job_id)


def _object_json(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--inputs-json must decode to a JSON object")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit a registered Honua OGC process and collect its result.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("HONUA_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--api-key", default=os.environ.get("HONUA_API_KEY"))
    parser.add_argument("--process-id", required=True)
    parser.add_argument("--inputs-json", required=True, type=_object_json)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--deadline-seconds", type=float, default=30.0)
    args = parser.parse_args()

    result = run_job(
        args.base_url,
        args.process_id,
        args.inputs_json,
        api_key=args.api_key,
        poll_interval=args.poll_interval,
        deadline_seconds=args.deadline_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

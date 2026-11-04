"""Publication jobs hand distributions to each other by artifact name; a mismatch only shows on a release."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "publish-python-sdk.yml"


def _artifact_steps(action: str) -> list[dict[str, Any]]:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return [
        step["with"]
        for job in jobs.values()
        for step in job.get("steps", [])
        if step.get("uses", "").startswith(f"actions/{action}@") and "-dist-" in step.get("with", {}).get("name", "")
    ]


def test_every_downloaded_distribution_has_a_matching_upload() -> None:
    uploaded = {step["name"] for step in _artifact_steps("upload-artifact")}
    downloaded = {step["name"] for step in _artifact_steps("download-artifact")}

    assert uploaded == {"honua-sdk-dist-${{ github.run_id }}", "honua-admin-dist-${{ github.run_id }}"}
    assert downloaded <= uploaded


def test_distribution_artifacts_survive_a_rerun_of_failed_jobs() -> None:
    steps = _artifact_steps("upload-artifact") + _artifact_steps("download-artifact")

    assert all("run_attempt" not in step["name"] for step in steps)
    assert all(step.get("overwrite") is True for step in _artifact_steps("upload-artifact"))

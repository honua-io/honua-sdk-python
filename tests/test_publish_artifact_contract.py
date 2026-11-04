"""Publication jobs hand distributions to each other by artifact name; a mismatch only shows on a release."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "publish-python-sdk.yml"
PACKAGES = ("honua-sdk", "honua-admin")
DIST_NAME = "{package}-dist-${{{{ github.run_id }}}}"
CONSUMER_JOBS = (
    "preflight-{package}-pypi",
    "publish-{package}",
    "verify-{package}-pypi",
    "attach-{package}-release",
    "attest-{package}",
)


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _artifact_names(job: dict[str, Any], action: str) -> list[str]:
    return [
        step["with"]["name"] for step in job.get("steps", []) if step.get("uses", "").startswith(f"actions/{action}@")
    ]


def _artifact_steps(action: str) -> list[dict[str, Any]]:
    return [
        step["with"]
        for job in _jobs().values()
        for step in job.get("steps", [])
        if step.get("uses", "").startswith(f"actions/{action}@")
    ]


@pytest.mark.parametrize("package", PACKAGES)
def test_only_the_package_build_uploads_its_distribution(package: str) -> None:
    name = DIST_NAME.format(package=package)
    producers = [key for key, job in _jobs().items() if name in _artifact_names(job, "upload-artifact")]

    assert producers == [f"build-{package}"]


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("consumer", CONSUMER_JOBS)
def test_each_consumer_downloads_its_own_package_distribution(package: str, consumer: str) -> None:
    job = _jobs()[consumer.format(package=package)]

    assert _artifact_names(job, "download-artifact") == [DIST_NAME.format(package=package)]


def test_distribution_artifacts_survive_a_rerun_of_failed_jobs() -> None:
    steps = _artifact_steps("upload-artifact") + _artifact_steps("download-artifact")

    assert all("run_attempt" not in step["name"] for step in steps)
    assert all(step.get("overwrite") is True for step in _artifact_steps("upload-artifact"))

from __future__ import annotations

import json
from pathlib import Path
import tomllib

import pytest

from scripts.resolve_publish_targets import plan_publish
from tests.test_release_please_config import _job_block
from tests.test_resolve_publish_targets import SHA, OTHER_SHA, VERSIONS, SDK_TAG, ADMIN_TAG


ROOT = Path(__file__).resolve().parents[1]
GP_TAG = "python-gp-v0.1.0"


def test_gp_release_selects_only_the_exact_tagged_commit() -> None:
    plan = plan_publish(
        event_name="workflow_run", release_sha=SHA, versions=VERSIONS,
        tag_commits={SDK_TAG: OTHER_SHA, ADMIN_TAG: OTHER_SHA, GP_TAG: SHA},
        release_is_trunk_ancestor=True,
    )
    assert plan.selected == ("gp",)
    assert plan.publish is True


@pytest.mark.parametrize("tag_commit", [None, OTHER_SHA])
def test_manual_gp_publication_rejects_missing_or_moved_tag(tag_commit: str | None) -> None:
    with pytest.raises(ValueError, match="python-gp-v"):
        plan_publish(
            event_name="workflow_dispatch", release_sha=SHA, versions=VERSIONS,
            tag_commits={GP_TAG: tag_commit}, release_is_trunk_ancestor=True,
            requested_package="honua-gp", dry_run=False, release_tag=GP_TAG,
            workflow_ref="refs/heads/trunk",
        )


def test_manual_gp_publication_accepts_only_its_own_release() -> None:
    plan = plan_publish(
        event_name="workflow_dispatch", release_sha=SHA, versions=VERSIONS,
        tag_commits={GP_TAG: SHA}, release_is_trunk_ancestor=True,
        requested_package="honua-gp", dry_run=False, release_tag=GP_TAG,
        workflow_ref="refs/heads/trunk",
    )
    assert plan.selected == ("gp",)
    assert plan.publish is True


def test_gp_is_a_public_apache_distribution_with_a_release_component() -> None:
    package = ROOT / "packages/honua-gp"
    metadata = tomllib.loads((package / "pyproject.toml").read_text())
    assert metadata["project"]["license"] == "Apache-2.0"
    assert metadata["project"]["license-files"] == ["LICENSE"]
    assert "Private :: Do Not Upload" not in metadata["project"]["classifiers"]
    assert (package / "LICENSE").read_bytes() == (ROOT / "packages/honua-sdk/LICENSE").read_bytes()
    assert metadata["build-system"]["requires"] == ["hatchling==1.30.1"]
    config = json.loads((ROOT / "release-please-config.json").read_text())
    assert config["packages"]["packages/honua-gp"]["component"] == "python-gp"
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    assert manifest["packages/honua-gp"] == metadata["project"]["version"]


def test_gp_publish_isolated_from_tests_and_requires_both_dependencies() -> None:
    workflow = (ROOT / ".github/workflows/publish-python-sdk.yml").read_text()
    publish = _job_block(workflow, "publish-honua-gp")
    assert "environment: pypi-honua-gp" in publish
    assert "id-token: write" in publish
    assert "contents: read" in publish
    assert "run:" not in publish
    for package in ("sdk", "admin"):
        assert f"- verify-honua-{package}-pypi" in publish
        assert f"needs.verify-honua-{package}-pypi.result == 'success'" in publish
    attest = _job_block(workflow, "attest-honua-gp")
    assert "- verify-honua-gp-pypi" in attest
    assert "needs.verify-honua-gp-pypi.result == 'success'" in attest
    assert "attestations: write" in attest

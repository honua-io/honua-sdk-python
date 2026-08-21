from __future__ import annotations

import json
import tomllib
from pathlib import Path

from scripts.resolve_publish_targets import PACKAGE_SPECS


ROOT = Path(__file__).resolve().parents[1]


def test_release_please_uses_single_v_component_tags() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))

    for package_config in config["packages"].values():
        assert package_config["include-component-in-tag"] is True
        assert package_config["tag-separator"] == "-"


def test_public_package_metadata_release_components_and_jobs_stay_mapped() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github/workflows/publish-python-sdk.yml").read_text(encoding="utf-8")
    environments = {"sdk": "pypi-honua-sdk", "admin": "pypi-honua-admin"}

    for spec in PACKAGE_SPECS:
        metadata = tomllib.loads((ROOT / spec.pyproject).read_text(encoding="utf-8"))
        release_config = config["packages"][str(spec.pyproject.parent).replace("\\", "/")]
        assert metadata["project"]["name"] == spec.distribution
        assert spec.tag_prefix == f"{release_config['component']}-v"
        assert f"  publish-{spec.distribution}:" in workflow
        assert f"    environment: {environments[spec.key]}" in workflow
        assert f"        working-directory: {spec.pyproject.parent.as_posix()}" in workflow


def test_publish_workflow_is_exact_sequential_and_least_privilege() -> None:
    workflow = (ROOT / ".github/workflows/publish-python-sdk.yml").read_text(encoding="utf-8")
    sdk_job = workflow.split("  publish-honua-sdk:", 1)[1].split(
        "  attach-honua-sdk-release:", 1
    )[0]
    sdk_attachment = workflow.split("  attach-honua-sdk-release:", 1)[1].split(
        "  publish-honua-admin:", 1
    )[0]
    admin_job = workflow.split("  publish-honua-admin:", 1)[1].split(
        "  attach-honua-admin-release:", 1
    )[0]
    admin_attachment = workflow.split("  attach-honua-admin-release:", 1)[1]

    assert "workflow_run:" in workflow
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in workflow
    assert "github.event.workflow_run.head_sha" in workflow
    assert "ref: ${{ needs.resolve-publish-targets.outputs.release_sha }}" in workflow
    assert "--workflow-ref \"$WORKFLOW_REF\"" in workflow
    assert "--release-tag \"$RELEASE_TAG\"" in workflow

    assert "      - publish-honua-sdk" in admin_job
    assert "      - attach-honua-sdk-release" in admin_job
    assert "needs.publish-honua-sdk.result == 'success'" in admin_job
    assert "needs.attach-honua-sdk-release.result == 'success'" in admin_job

    for publish_job in (sdk_job, admin_job):
        assert "contents: read" in publish_job
        assert "id-token: write" in publish_job
        assert "contents: write" not in publish_job
        assert "needs.resolve-publish-targets.outputs.publish == 'true'" in publish_job

    for attachment_job in (sdk_attachment, admin_attachment):
        assert "contents: write" in attachment_job
        assert "id-token: write" not in attachment_job
        assert "gh release upload" in attachment_job
        assert "pypi.org/project/%s/%s/" in attachment_job

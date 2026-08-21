from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from scripts.resolve_publish_targets import PACKAGE_SPECS


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github/workflows/publish-python-sdk.yml"
RELEASE_PLEASE_WORKFLOW = ROOT / ".github/workflows/release-please.yml"
PUBLISH_REQUIREMENTS_INPUT = ROOT / ".github/requirements/publish-python.in"
PUBLISH_REQUIREMENTS = ROOT / ".github/requirements/publish-python.lock"


def _job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", workflow
    )
    assert match is not None, f"Missing workflow job {job}"
    return match.group(0)


def _assert_actions_pinned(workflow: str) -> None:
    for line in workflow.splitlines():
        if "uses:" in line:
            assert re.search(r"@[0-9a-f]{40}(?:\s+#\s+\S+)?$", line)


def test_release_please_uses_single_v_component_tags() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))

    for package_config in config["packages"].values():
        assert package_config["include-component-in-tag"] is True
        assert package_config["tag-separator"] == "-"


def test_public_package_metadata_release_components_and_jobs_stay_mapped() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    environments = {"sdk": "pypi-honua-sdk", "admin": "pypi-honua-admin"}

    for spec in PACKAGE_SPECS:
        metadata = tomllib.loads((ROOT / spec.pyproject).read_text(encoding="utf-8"))
        release_config = config["packages"][spec.pyproject.parent.as_posix()]
        validate_job = _job_block(workflow, f"validate-{spec.distribution}")
        build_job = _job_block(workflow, f"build-{spec.distribution}")
        publish_job = _job_block(workflow, f"publish-{spec.distribution}")

        assert metadata["project"]["name"] == spec.distribution
        assert spec.tag_prefix == f"{release_config['component']}-v"
        assert f"working-directory: release-source/{spec.pyproject.parent.as_posix()}" in validate_job
        assert f"build-source-1/{spec.pyproject.parent.as_posix()}" in build_job
        assert f"build-source-2/{spec.pyproject.parent.as_posix()}" in build_job
        assert f"validate-{spec.distribution}" in build_job
        assert f"environment: {environments[spec.key]}" in publish_job


def test_only_workflow_run_and_strict_manual_dispatch_can_publish() -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    triggers = workflow.split("\nenv:\n", 1)[0]

    assert "workflow_run:" in triggers
    assert "workflow_dispatch:" in triggers
    assert "\n  push:" not in triggers
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in workflow
    assert "github.event.workflow_run.head_branch == 'trunk'" in workflow
    assert "--workflow-ref \"$WORKFLOW_REF\"" in workflow
    assert "--release-tag \"$RELEASE_TAG\"" in workflow
    assert "refs/remotes/origin/trunk" not in workflow  # ancestry is enforced in the resolver
    assert "ref: ${{ needs.resolve-publish-targets.outputs.release_sha }}" not in workflow
    assert workflow.count('git worktree add --detach release-source "$RELEASE_SHA"') == 3
    assert workflow.count('git worktree add --detach build-source-1 "$RELEASE_SHA"') == 2
    assert workflow.count('git worktree add --detach build-source-2 "$RELEASE_SHA"') == 2


def test_concurrency_is_scoped_to_release_identity_or_manual_coordinate() -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert "group: publish-python-packages\n" not in workflow
    assert "github.event.workflow_run.id" in workflow
    assert "format('workflow-run-{0}', github.event.workflow_run.id)" in workflow
    assert (
        "format('manual-release-{0}-{1}', inputs.package, inputs.release_tag || github.run_id)"
        in workflow
    )
    assert "format('manual-dry-run-{0}', github.run_id)" in workflow
    assert "cancel-in-progress: false" in workflow


def test_build_jobs_are_unprivileged_and_oidc_jobs_only_download_and_publish() -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    for package in ("honua-sdk", "honua-admin"):
        validate_job = _job_block(workflow, f"validate-{package}")
        build_job = _job_block(workflow, f"build-{package}")
        publish_job = _job_block(workflow, f"publish-{package}")

        assert "environment:" not in validate_job
        assert "id-token: write" not in validate_job
        assert "Run tests" in validate_job or "Run SDK tests" in validate_job
        assert "--no-deps" in validate_job

        assert "environment:" not in build_job
        assert "id-token: write" not in build_job
        assert "Run tests" not in build_job
        assert "Run SDK tests" not in build_job
        assert "pip install --no-deps" not in build_job
        assert "Require reproducible artifacts and create immutable manifest" in build_job
        assert "Upload verified" in build_job

        assert "id-token: write" in publish_job
        assert "contents: read" in publish_job
        assert publish_job.count("uses:") == 2
        assert "actions/download-artifact@" in publish_job
        assert "pypa/gh-action-pypi-publish@" in publish_job
        assert "run:" not in publish_job
        assert "actions/checkout@" not in publish_job
        assert "actions/setup-python@" not in publish_job
        assert "skip-existing" not in publish_job


def test_build_inputs_are_hash_locked_and_artifacts_are_reproducible() -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    requirements_input = PUBLISH_REQUIREMENTS_INPUT.read_text(encoding="utf-8")
    lock = PUBLISH_REQUIREMENTS.read_text(encoding="utf-8")

    assert workflow.count("--require-hashes") == 5
    assert workflow.count("--only-binary=:all:") == 5
    assert workflow.count("--no-deps") == 6
    assert workflow.count("--no-build-isolation") == 6
    assert "pip install --upgrade" not in workflow
    assert "hatch build" not in workflow
    assert workflow.count("python -m build ") == 4
    assert workflow.count("SOURCE_DATE_EPOCH") == 2
    assert workflow.count("cmp -s") == 2
    assert workflow.count("Build package from independent pristine sources") == 2
    assert workflow.count("git -C build-source-1 status") == 2
    assert workflow.count("git -C build-source-2 status") == 2
    assert lock.count("--hash=sha256:") >= 20

    direct_requirements = [
        line for line in requirements_input.splitlines() if line and not line.startswith("#")
    ]
    assert direct_requirements
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9._-]*==[^=<>~!\s]+", line) for line in direct_requirements)

    locked_requirements = list(re.finditer(r"(?m)^([a-z0-9][a-z0-9._-]*)==[^\s\\]+", lock))
    assert locked_requirements
    for index, requirement in enumerate(locked_requirements):
        block_end = locked_requirements[index + 1].start() if index + 1 < len(locked_requirements) else len(lock)
        assert "--hash=sha256:" in lock[requirement.end() : block_end]

    for package in ("honua-sdk", "honua-admin"):
        metadata = tomllib.loads((ROOT / "packages" / package / "pyproject.toml").read_text(encoding="utf-8"))
        assert metadata["build-system"]["requires"] == ["hatchling==1.30.1"]


def test_production_fails_closed_on_external_publication_controls() -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    release_job = _job_block(workflow, "verify-github-releases")

    assert "needs.resolve-publish-targets.outputs.publish == 'true'" in release_job
    assert "scripts/verify_publication_controls.py" in release_job
    controls = (ROOT / "scripts/verify_publication_controls.py").read_text(encoding="utf-8")
    assert 'f"{api_root}/branches/trunk"' in controls
    assert "branches/trunk/protection" not in controls
    assert 'payload.get("protected") is not True' in controls
    assert 'payload.get("can_admins_bypass") is not False' in controls
    assert "--environment pypi-honua-sdk" in release_job
    assert "--environment pypi-honua-admin" in release_job
    assert "--tag-pattern 'refs/tags/python-sdk-v*'" in release_job
    assert "--tag-pattern 'refs/tags/python-admin-v*'" in release_job


def test_registry_and_release_assets_require_exact_hash_parity() -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    sdk_publish = _job_block(workflow, "publish-honua-sdk")
    admin_publish = _job_block(workflow, "publish-honua-admin")

    assert "skip-existing" not in workflow
    assert "--clobber" not in workflow
    assert workflow.count("--phase preflight") == 2
    assert workflow.count("--phase post-publish") == 2
    assert workflow.count(".digest // \"\"") == 4
    assert "verify-honua-sdk-pypi" in admin_publish
    assert "attach-honua-sdk-release" in admin_publish
    assert "needs.attach-honua-sdk-release.result == 'success'" in admin_publish
    assert "needs.preflight-honua-sdk-pypi.outputs.publish_required == 'true'" in sdk_publish
    assert "preflight-honua-admin-pypi" in sdk_publish

    for package in ("honua-sdk", "honua-admin"):
        attachment = _job_block(workflow, f"attach-{package}-release")
        assert "always()" in attachment
        assert "needs.resolve-publish-targets.result == 'success'" in attachment
        assert f"needs.verify-{package}-pypi.result == 'success'" in attachment
        assert "contents: write" in attachment
        assert "id-token: write" not in attachment
        assert "gh release upload" in attachment
        assert "sha256sum" in attachment
        assert "pypi.org/project/%s/%s/" in attachment


def test_release_target_uses_rest_field_and_all_actions_are_sha_pinned() -> None:
    publish_workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    release_workflow = RELEASE_PLEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "gh api \"repos/$GITHUB_REPOSITORY/releases/tags/$tag\"" in publish_workflow
    assert ".target_commitish" in publish_workflow
    assert "targetCommitish" not in publish_workflow
    _assert_actions_pinned(publish_workflow)
    _assert_actions_pinned(release_workflow)
    assert "googleapis/release-please-action@45996ed1f6d02564a971a2fa1b5860e934307cf7" in release_workflow

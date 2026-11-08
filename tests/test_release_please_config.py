from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from scripts.resolve_publish_targets import PACKAGE_SPECS


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github/workflows/publish-python-sdk.yml"
RELEASE_PLEASE_WORKFLOW = ROOT / ".github/workflows/release-please.yml"
PUBLISH_REQUIREMENTS_INPUT = ROOT / ".github/requirements/publish-python.in"
PUBLISH_REQUIREMENTS = ROOT / ".github/requirements/publish-python.lock"
BUILD_ACTION = ROOT / ".github/actions/build-python-distribution/action.yml"
ATTACH_ACTION = ROOT / ".github/actions/attach-python-release/action.yml"
ATTEST_ACTION = ROOT / ".github/actions/attest-python-distribution/action.yml"
VALIDATE_ACTION = ROOT / ".github/actions/validate-python-release-source/action.yml"
PUBLIC_PACKAGES = ("honua-sdk", "honua-admin", "honua-gp")


def _job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", workflow
    )
    assert match is not None, f"Missing workflow job {job}"
    return match.group(0)


def _assert_actions_pinned(workflow: str) -> None:
    for line in workflow.splitlines():
        if "uses:" in line and "uses: ./" not in line:
            assert re.search(r"@[0-9a-f]{40}(?:\s+#\s+\S+)?$", line)


def test_release_please_uses_single_v_component_tags() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))

    for package_config in config["packages"].values():
        assert package_config["include-component-in-tag"] is True
        assert package_config["tag-separator"] == "-"


def test_public_package_metadata_release_components_and_jobs_stay_mapped() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    environments = {"sdk": "pypi-honua-sdk", "admin": "pypi-honua-admin", "gp": "pypi-honua-gp"}

    for spec in PACKAGE_SPECS:
        metadata = tomllib.loads((ROOT / spec.pyproject).read_text(encoding="utf-8"))
        release_config = config["packages"][spec.pyproject.parent.as_posix()]
        validate_job = _job_block(workflow, f"validate-{spec.distribution}")
        build_job = _job_block(workflow, f"build-{spec.distribution}")
        publish_job = _job_block(workflow, f"publish-{spec.distribution}")

        assert metadata["project"]["name"] == spec.distribution
        assert metadata["project"]["license"] == "Apache-2.0"
        assert metadata["project"]["license-files"] == ["LICENSE"]
        assert "Private :: Do Not Upload" not in metadata["project"]["classifiers"]
        assert (ROOT / spec.pyproject.parent / "LICENSE").read_bytes() == (ROOT / "packages/honua-sdk/LICENSE").read_bytes()
        assert spec.tag_prefix == f"{release_config['component']}-v"
        assert f"working-directory: release-source/{spec.pyproject.parent.as_posix()}" in validate_job
        assert "uses: ./.github/actions/build-python-distribution" in build_job
        assert f"package: {spec.distribution}" in build_job
        assert f"version: ${{{{ needs.resolve-publish-targets.outputs.{spec.key}_version }}}}" in build_job
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
    assert workflow.count('git worktree add --detach release-source "$RELEASE_SHA"') == 1
    assert 'git worktree add --detach release-source "$RELEASE_SHA"' in VALIDATE_ACTION.read_text()
    build = BUILD_ACTION.read_text(encoding="utf-8")
    assert 'git worktree add --detach build-source-1 "$RELEASE_SHA"' in build
    assert 'git worktree add --detach build-source-2 "$RELEASE_SHA"' in build


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

    for package in PUBLIC_PACKAGES:
        validate_job = _job_block(workflow, f"validate-{package}")
        build_job = _job_block(workflow, f"build-{package}")
        publish_job = _job_block(workflow, f"publish-{package}")

        assert "environment:" not in validate_job
        assert "id-token: write" not in validate_job
        assert "Run tests" in validate_job or "Run SDK tests" in validate_job
        assert "uses: ./.github/actions/validate-python-release-source" in validate_job
        assert "--no-deps" in VALIDATE_ACTION.read_text()

        assert "environment:" not in build_job
        assert "id-token: write" not in build_job
        assert "Run tests" not in build_job
        assert "Run SDK tests" not in build_job
        assert "pip install --no-deps" not in build_job
        assert "uses: ./.github/actions/build-python-distribution" in build_job
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

    assert workflow.count("--require-hashes") == 4
    assert VALIDATE_ACTION.read_text().count("--require-hashes") == 1
    assert workflow.count("--only-binary=:all:") == 4
    assert workflow.count("--no-deps") == 3
    assert workflow.count("--no-build-isolation") == 3
    assert "pip install --upgrade" not in workflow
    assert "hatch build" not in workflow
    build = BUILD_ACTION.read_text(encoding="utf-8")
    assert build.count("python -m build ") == 2
    assert "SOURCE_DATE_EPOCH" in build
    assert "cmp -s" in build
    assert "build-source-1/packages/$PACKAGE" in build
    assert "build-source-2/packages/$PACKAGE" in build
    assert "git -C build-source-1 status" in build
    assert "git -C build-source-2 status" in build
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

    for package in PUBLIC_PACKAGES:
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
    assert "--environment pypi-honua-gp" in release_job
    assert "--tag-pattern 'refs/tags/python-gp-v*'" in release_job
    assert "--tag-pattern 'refs/tags/python-sdk-v*'" in release_job
    assert "--tag-pattern 'refs/tags/python-admin-v*'" in release_job


def test_registry_and_release_assets_require_exact_hash_parity() -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    sdk_publish = _job_block(workflow, "publish-honua-sdk")
    admin_publish = _job_block(workflow, "publish-honua-admin")

    assert "skip-existing" not in workflow
    assert "--clobber" not in workflow
    assert "--clobber" not in ATTACH_ACTION.read_text(encoding="utf-8")
    assert workflow.count("--phase preflight") == 3
    assert workflow.count("--phase post-publish") == 3
    assert ATTACH_ACTION.read_text(encoding="utf-8").count(".digest // \"\"") == 2
    assert "verify-honua-sdk-pypi" in admin_publish
    assert "attach-honua-sdk-release" in admin_publish
    assert "needs.attach-honua-sdk-release.result == 'success'" in admin_publish
    assert "needs.preflight-honua-sdk-pypi.outputs.publish_required == 'true'" in sdk_publish
    assert "preflight-honua-admin-pypi" in sdk_publish
    for publisher in (sdk_publish, admin_publish):
        assert "- preflight-honua-gp-pypi" in publisher
        assert "needs.resolve-publish-targets.outputs.gp != 'true'" in publisher
        assert "needs.preflight-honua-gp-pypi.result == 'success'" in publisher

    for package in PUBLIC_PACKAGES:
        attachment = _job_block(workflow, f"attach-{package}-release")
        assert "always()" in attachment
        assert "needs.resolve-publish-targets.result == 'success'" in attachment
        assert f"needs.verify-{package}-pypi.result == 'success'" in attachment
        assert "contents: write" in attachment
        assert "id-token: write" not in attachment
        assert "uses: ./.github/actions/attach-python-release" in attachment
        assert f"package: {package}" in attachment
        assert "ref: ${{ github.workflow_sha }}" in attachment
        assert "persist-credentials: false" in attachment
        assert attachment.index("actions/checkout@") < attachment.index("uses: ./.github/actions/")
    shared_attachment = ATTACH_ACTION.read_text(encoding="utf-8")
    assert "gh release upload" in shared_attachment
    assert "sha256sum" in shared_attachment
    assert "pypi.org/project/%s/%s/" in shared_attachment


def test_release_target_uses_rest_field_and_all_actions_are_sha_pinned() -> None:
    publish_workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    release_workflow = RELEASE_PLEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "gh api \"repos/$GITHUB_REPOSITORY/releases/tags/$tag\"" in publish_workflow
    assert ".target_commitish" in publish_workflow
    assert "targetCommitish" not in publish_workflow
    _assert_actions_pinned(publish_workflow)
    _assert_actions_pinned(release_workflow)
    for action in (BUILD_ACTION, ATTACH_ACTION, ATTEST_ACTION, VALIDATE_ACTION):
        _assert_actions_pinned(action.read_text(encoding="utf-8"))
    assert "googleapis/release-please-action@45996ed1f6d02564a971a2fa1b5860e934307cf7" in release_workflow


def test_dependent_packages_require_the_sdk_they_are_released_with() -> None:
    # honua-admin and honua-gp import helpers that only exist in the SDK they are
    # released with (e.g. honua_sdk.http.ensure_secure_credential_transport), so the
    # release-please SDK release rewrites their honua-sdk floor to the new version.
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    sdk_version = tomllib.loads(
        (ROOT / "packages/honua-sdk/pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    extra_files = config["packages"]["packages/honua-sdk"]["extra-files"]

    for package in ("honua-admin", "honua-gp"):
        path = f"packages/{package}/pyproject.toml"
        assert {"type": "generic", "path": f"/{path}"} in extra_files
        text = (ROOT / path).read_text(encoding="utf-8")
        floors = re.findall(r'"honua-sdk>=([0-9.]+)[^"]*",\s*# x-release-please-version\n', text)
        assert floors == [sdk_version], f"{path} honua-sdk floor must track the SDK release"


@pytest.mark.parametrize(
    ("sdk_version", "compatible"),
    [("0.3.0", True), ("0.3.1", True), ("0.2.2", False), ("0.4.0", False)],
)
def test_admin_dependency_accepts_the_next_sdk_release(
    sdk_version: str, compatible: bool,
) -> None:
    metadata = tomllib.loads(
        (ROOT / "packages/honua-admin/pyproject.toml").read_text(encoding="utf-8")
    )
    dependency = next(
        Requirement(value) for value in metadata["project"]["dependencies"]
        if Requirement(value).name == "honua-sdk"
    )
    next_release_dependency = Requirement(re.sub(r">=[0-9.]+", ">=0.3.0", str(dependency)))

    assert (sdk_version in next_release_dependency.specifier) is compatible


def test_attestation_jobs_bind_verified_bytes_to_the_release_commit() -> None:
    """honua-release's collector verifies --source-digest <release commit> and this signer workflow."""
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    for package in PUBLIC_PACKAGES:
        attest = _job_block(workflow, f"attest-{package}")
        assert f"- verify-{package}-pypi" in attest
        assert f"needs.verify-{package}-pypi.result == 'success'" in attest
        assert "needs.resolve-publish-targets.outputs.publish == 'true'" in attest
        assert "id-token: write" in attest
        assert "attestations: write" in attest
        assert "contents: read" in attest
        assert "environment:" not in attest
        assert "uses: ./.github/actions/attest-python-distribution" in attest
        assert f"package: {package}" in attest
        assert "ref: ${{ github.workflow_sha }}" in attest
        assert "persist-credentials: false" in attest
        assert attest.index("actions/checkout@") < attest.index("uses: ./.github/actions/")
        assert "release-sha: ${{ needs.resolve-publish-targets.outputs.release_sha }}" in attest
        assert f"name: {package}-dist-${{{{ github.run_id }}}}\n" in attest
        assert "pypa/gh-action-pypi-publish@" not in attest
    shared_attestation = ATTEST_ACTION.read_text(encoding="utf-8")
    assert 'if [ "$GITHUB_SHA" != "$RELEASE_SHA" ]' in shared_attestation
    assert shared_attestation.index("Require the workflow source") < shared_attestation.index("actions/attest-build-provenance@")
    assert "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8" in shared_attestation
    assert "actions/attest-sbom@c604332985a26aa8cf1bdc465b92731239ec6b9e" in shared_attestation
    assert "anchore/sbom-action@66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c" in shared_attestation
    assert "format: cyclonedx-json" in shared_attestation
    assert "subject-path: artifact/dist/*" in shared_attestation
    assert "id: wheel" in shared_attestation
    assert 'echo "path=${wheels[0]}" >> "$GITHUB_OUTPUT"' in shared_attestation
    assert "subject-path: ${{ steps.wheel.outputs.path }}" in shared_attestation



DIST_ARTIFACT = "{package}-dist-${{{{ github.run_id }}}}"
DIST_CONSUMER_JOBS = (
    "preflight-{package}-pypi",
    "publish-{package}",
    "verify-{package}-pypi",
    "attach-{package}-release",
    "attest-{package}",
)


def _artifact_names(job_block: str, action: str) -> list[str]:
    return re.findall(rf"uses: actions/{action}@\S+[^\n]*\n\s+with:\n(?:\s+\S.*\n)*?\s+name: (.+)", job_block)


def _job_names(workflow: str) -> list[str]:
    return re.findall(r"(?m)^  ([a-z][a-z0-9-]*):\n", workflow)


@pytest.mark.parametrize("package", PUBLIC_PACKAGES)
def test_only_the_package_build_uploads_its_distribution(package: str) -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    name = DIST_ARTIFACT.format(package=package)

    producers = [
        job for job in _job_names(workflow) if name in _artifact_names(_job_block(workflow, job), "upload-artifact")
    ]

    assert producers == [f"build-{package}"]
    assert "overwrite: true" in _job_block(workflow, f"build-{package}")


@pytest.mark.parametrize("package", PUBLIC_PACKAGES)
@pytest.mark.parametrize("consumer", DIST_CONSUMER_JOBS)
def test_each_consumer_downloads_its_own_package_distribution(package: str, consumer: str) -> None:
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    downloads = _artifact_names(_job_block(workflow, consumer.format(package=package)), "download-artifact")

    assert downloads == [DIST_ARTIFACT.format(package=package)]


def test_distribution_artifacts_are_rerun_safe() -> None:
    assert "dist-${{ github.run_id }}-${{ github.run_attempt }}" not in PUBLISH_WORKFLOW.read_text(encoding="utf-8")


def test_gp_first_release_version_is_explicit() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text())
    assert config["packages"]["packages/honua-gp"]["release-as"] == "0.1.0"


def test_gp_registry_install_is_anonymous_and_pinned() -> None:
    workflow = PUBLISH_WORKFLOW.read_text()
    install = _job_block(workflow, "install-honua-gp")
    assert "needs.verify-honua-gp-pypi.result == 'success'" in install
    assert "needs.resolve-publish-targets.outputs.publish == 'true'" in install
    assert "VERSION: ${{ needs.resolve-publish-targets.outputs.gp_version }}" in install
    assert '--isolated install' in install
    assert '--index-url https://pypi.org/simple "honua-gp==$VERSION"' in install
    assert '-m pip check' in install
    assert '/bin/honua-gp" --help' in install
    assert "TOKEN" not in install


def test_source_mismatch_fails_before_registry_or_release_access(tmp_path: Path) -> None:
    import os
    import shutil
    import subprocess
    import textwrap

    block = _job_block(PUBLISH_WORKFLOW.read_text(), "verify-github-releases")
    step = block.split("      - name: Verify selected GitHub Releases through REST\n", 1)[1]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1].split("      - name:", 1)[0])
    marker = tmp_path / "accessed"
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\ntouch accessed\nexit 1\n")
    gh.chmod(0o755)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
           "PUBLISH": "true", "GITHUB_SHA": "a" * 40, "RELEASE_SHA": "b" * 40,
           "SDK_SELECTED": "false", "ADMIN_SELECTED": "false", "GP_SELECTED": "true",
           "GP_TAG": "python-gp-v0.1.0", "GITHUB_REPOSITORY": "honua-io/honua-sdk-python"}
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - executes a checked-in workflow against a fake gh
        [bash, "-e", "-c", script], check=False, env=env, cwd=tmp_path,
        capture_output=True, text=True)
    assert result.returncode != 0
    assert "workflow source" in result.stderr
    assert not marker.exists()


def test_gp_waits_for_verified_and_attached_dependencies() -> None:
    publish = _job_block(PUBLISH_WORKFLOW.read_text(), "publish-honua-gp")
    for package in ("honua-sdk", "honua-admin"):
        for gate in (f"verify-{package}-pypi", f"attach-{package}-release"):
            assert f"- {gate}" in publish
            assert f"needs.{gate}.result == 'success'" in publish

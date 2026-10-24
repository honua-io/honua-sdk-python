from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "conformance.yml"


def test_release_certification_uses_the_governed_candidate_cut() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "candidate_cut_at:" in workflow
    assert "CANDIDATE_CUT_AT_INPUT: ${{ github.event.inputs.candidate_cut_at }}" in workflow
    assert "from scripts._conformance import validate_candidate_cut_at" in workflow
    assert "validate_candidate_cut_at(sys.argv[1])" in workflow
    assert '"${HONUA_SDK_CERT_PYTHON}" - "${CANDIDATE_CUT_AT_INPUT}"' in workflow
    assert '"${HONUA_SDK_CERT_PYTHON}" - <<\'PY\'' in workflow
    assert 'candidate_cut_at="${CANDIDATE_CUT_AT_INPUT}"' in workflow
    assert (
        'candidate_cut_at="$(git -C "${server_root}" show -s --format=%cI '
        '"${image_revision}")"'
    ) in workflow


def test_conformance_uses_candidate_on_pr_and_public_wheel_elsewhere() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "if: ${{ github.event_name == 'pull_request' }}" in workflow
    assert "python -m build --wheel --no-isolation --outdir dist packages/honua-sdk" in workflow
    assert "HONUA_SDK_WHEEL_SOURCE=github-actions" in workflow
    assert "HONUA_SDK_SOURCE_SHA=${GITHUB_SHA}" in workflow
    assert "HONUA_PROTOCOL_CERTIFICATION_FRAGMENT_PATH: ${{ github.event_name != 'pull_request'" in workflow
    assert workflow.count("--require-hashes") == 5
    assert workflow.count(".github/requirements/publish-python.lock") == 3
    assert "--no-isolation" in workflow
    assert "pip install --upgrade" not in workflow

    assert "if: ${{ github.event_name != 'pull_request' }}" in workflow
    assert 'HONUA_SDK_PUBLIC_VERSION: "0.1.18"' in workflow
    assert 'HONUA_SDK_PUBLIC_WHEEL: "honua_sdk-0.1.18-py3-none-any.whl"' in workflow
    assert "python -m pip download" in workflow
    assert '"honua-sdk==${HONUA_SDK_PUBLIC_VERSION}"' in workflow
    assert "--only-binary=:all:" in workflow
    assert "sha256sum --check --strict" in workflow
    assert "pip install -e packages/honua-sdk" not in workflow
    assert "HONUA_SDK_WHEEL_SHA256=${HONUA_SDK_PUBLIC_WHEEL_SHA256}" in workflow
    assert "HONUA_SDK_WHEEL_SOURCE=pypi" in workflow
    assert "HONUA_SDK_SOURCE_SHA=${HONUA_SDK_PUBLIC_SOURCE_SHA}" in workflow
    assert '"${HONUA_SDK_CERT_PYTHON}" -m pytest tests/conformance' in workflow


def test_grpc_listener_is_published_from_the_same_candidate_container():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/conformance.yml").read_text()
    assert '"127.0.0.1::5001"' in workflow
    assert 'port honua 5001' in workflow
    assert 'HONUA_GRPC_TARGET=localhost:${grpc_port##*:}' in workflow
    assert 'image_revision}" != "${seed_revision}' in workflow
    assert 'HONUA_SDK_PUBLIC_SOURCE_SHA: "361978e86e816a35d93ee527b029a0c8f6e97efa"' in workflow
    assert '11d5c0074a8c3065b2ca2777a33efab6672dd1f03e0d664abc5f9f964727b033' in workflow


def test_explicitly_requested_certification_does_not_skip_missing_prerequisites():
    conftest = (Path(__file__).resolve().parents[1] / "tests/conformance/conftest.py").read_text()
    assert "pytest.skip" not in conftest
    assert "pytest.fail(str(exc), pytrace=False)" in conftest


def test_seed_execution_covers_legacy_and_migration_owned_candidate_sources():
    import json
    import re
    import subprocess
    import sys

    workflow = WORKFLOW.read_text()
    parser = re.search(r"seed_dependency=.*\| python -c '([^']+)'", workflow).group(1)
    for dependencies, expected in (({"seed": {"condition": "service_completed_successfully"}}, "true"),
                                   ({"postgres": {"condition": "service_healthy"}}, "false")):
        result = subprocess.run(  # noqa: S603 -- executes the maintained workflow parser, not external input
            [sys.executable, "-c", parser], input=json.dumps({"services": {"honua": {"depends_on": dependencies}}}),
                                text=True, capture_output=True, check=True)
        assert result.stdout.strip() == expected
    malformed = subprocess.run(  # noqa: S603 -- executes the maintained workflow parser with a malformed fixture
        [sys.executable, "-c", parser], input='{"services":{"honua":{"depends_on":null}}}',
                               text=True, capture_output=True, check=False)
    assert malformed.returncode != 0
    assert 'if [[ "${seed_dependency}" == "false" ]]' in workflow
    assert 'run --rm --no-deps seed' in workflow
    assert workflow.index('up -d --no-build honua') < workflow.index('run --rm --no-deps seed')


def test_migration_owned_seed_waits_for_readiness_and_never_runs_after_timeout(tmp_path):
    import os
    import shutil
    import subprocess
    import textwrap

    workflow = WORKFLOW.read_text()
    start = workflow.index('          docker compose -f "${compose_file}" -f "${override_file}" up -d --no-build honua')
    end = workflow.index('          resolved_image=', start)
    script = "set -eu\n" + textwrap.dedent(workflow[start:end])
    events = tmp_path / "events"
    count = tmp_path / "count"
    for name, body in {
        "docker": 'echo "docker $*" >> "$EVENTS"\n',
        "sleep": "exit 0\n",
        "curl": ('echo curl >> "$EVENTS"\n'
                 'count=0; [ ! -f "$COUNT" ] || count=$(cat "$COUNT")\n'
                 'count=$((count + 1)); echo "$count" > "$COUNT"\n'
                 '[ "$NEVER_READY" = false ] && [ "$count" -ge 2 ]\n'),
    }.items():
        tool = tmp_path / name
        tool.write_text("#!/bin/sh\n" + body)
        tool.chmod(0o755)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
           "EVENTS": str(events), "COUNT": str(count), "seed_dependency": "false",
           "compose_file": "compose.yml", "override_file": "override.yml"}
    bash = shutil.which("bash")
    assert bash is not None
    for never_ready in ("false", "true"):
        events.unlink(missing_ok=True)
        count.unlink(missing_ok=True)
        result = subprocess.run(  # noqa: S603 -- maintained workflow with local command stubs; no services started
            [bash, "-c", script], env={**env, "NEVER_READY": never_ready}, capture_output=True, text=True,
            check=False)
        lines = events.read_text().splitlines()
        seeds = [index for index, line in enumerate(lines) if "run --rm --no-deps seed" in line]
        if never_ready == "true":
            assert result.returncode != 0
            assert not seeds
        else:
            assert result.returncode == 0, result.stderr
            assert len(seeds) == 1
            assert lines[seeds[0] - 3:seeds[0]] == ["curl", "curl", "curl"]
            assert lines[seeds[0] + 1:] == ["curl"]


def test_certification_receipts_use_repository_governed_requirements() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "python3 scripts/fetch_certification_requirements.py" in workflow
    assert "Checkout governed certification requirements" not in workflow
    assert "--destination" in workflow
    assert "HONUA_CERTIFICATION_REQUIREMENTS_PATH:" in workflow


def test_governed_nightly_inputs_are_data_and_never_interpolated_into_shell_source():
    workflow = WORKFLOW.read_text()
    assert "nightly_dispatch_id:" in workflow
    assert "requirements_ref:" in workflow and "requirements_revision:" in workflow
    assert "HONUA_NIGHTLY_DISPATCH_ID: ${{ github.event.inputs.nightly_dispatch_id || '' }}" in workflow
    assert "REQUIREMENTS_SOURCE_SHA: ${{ github.event.inputs.requirements_ref || '' }}" in workflow
    assert 'args+=(--source-sha "${REQUIREMENTS_SOURCE_SHA}" --requirements-revision "${REQUIREMENTS_REVISION}")' in workflow
    assert 'python3 scripts/fetch_certification_requirements.py "${args[@]}"' in workflow

from pathlib import Path

import pytest



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
    assert (
        "HONUA_PROTOCOL_CERTIFICATION_FRAGMENT_PATH: ${{ github.event.inputs.certification_tier == 'release' "
        "&& 'protocol-certification-fragment.json' || '' }}"
    ) in workflow
    assert "HONUA_PROTOCOL_CERTIFICATION_FRAGMENT_PATH: ${{ github.event_name != 'pull_request'" not in workflow
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


def test_nightly_dispatch_names_the_run_for_candidate_tag_intake():
    # honua-evidence admits a run on refs/tags/nightly-candidate/<pin> only when its
    # display title is exactly "<title> [<dispatch_id>]" (fetch-certification-producers.py).
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.splitlines()[1] == (
        "run-name: ${{ inputs.nightly_dispatch_id && format('Python SDK Conformance [{0}]', "
        "inputs.nightly_dispatch_id) || 'Python SDK Conformance' }}"
    )
    assert workflow.splitlines()[0] == "name: Python SDK Conformance"


def test_governed_nightly_inputs_are_data_and_never_interpolated_into_shell_source():
    workflow = WORKFLOW.read_text()
    assert "nightly_dispatch_id:" in workflow
    assert "requirements_ref:" in workflow and "requirements_revision:" in workflow
    assert "HONUA_NIGHTLY_DISPATCH_ID: ${{ github.event.inputs.nightly_dispatch_id || '' }}" in workflow
    assert "REQUIREMENTS_SOURCE_SHA: ${{ github.event.inputs.requirements_ref || '' }}" in workflow
    assert 'args+=(--source-sha "${REQUIREMENTS_SOURCE_SHA}" --requirements-revision "${REQUIREMENTS_REVISION}")' in workflow
    assert 'python3 scripts/fetch_certification_requirements.py "${args[@]}"' in workflow


_NIGHTLY_PACKAGE_INPUTS = ("sdk_package", "sdk_package_version", "sdk_package_digest", "sdk_source_sha")
_BIND_STEP = "Bind nightly dispatch to the exact published honua-sdk package"
_INSTALL_STEP = "Download and install exact public honua-sdk wheel"
_DISPATCHED_DIGEST = "1" * 64
_DISPATCHED = {
    "NIGHTLY_DISPATCH_ID": "nightly-certification-123-1",
    "REQUIREMENTS_SOURCE_SHA": "a" * 40,
    "REQUIREMENTS_REVISION": "requirements-test-17",
    "SDK_PACKAGE": "honua-sdk",
    "SDK_PACKAGE_VERSION": "0.1.19",
    "SDK_PACKAGE_DIGEST": "sha256:" + _DISPATCHED_DIGEST,
    "SDK_SOURCE_SHA": "c" * 40,
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_SHA": "e" * 40,
}


def _step(name: str) -> tuple[str, str]:
    """Return (step block, dedented run script) for the named workflow step."""
    import textwrap

    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index(f"      - name: {name}\n")
    end = workflow.find("\n      - name: ", start + 1)
    block = workflow[start:end if end != -1 else len(workflow)]
    script = block[block.index("        run: |\n") + len("        run: |\n"):]
    return block, textwrap.dedent(script)


def _run_step(name: str, env: dict[str, str], tmp_path: Path, path_prefix: Path | None = None):
    import os
    import shutil
    import subprocess

    bash = shutil.which("bash")
    assert bash is not None
    _, script = _step(name)
    github_env = tmp_path / "github_env"
    github_env.write_text("")
    base = {key: value for key, value in os.environ.items()
            if not key.startswith(("HONUA_", "SDK_", "NIGHTLY_", "REQUIREMENTS_", "GITHUB_"))}
    if path_prefix is not None:
        base["PATH"] = str(path_prefix) + os.pathsep + base["PATH"]
    result = subprocess.run(  # noqa: S603 -- maintained workflow step with local stubs; no network or services
        [bash, "-c", script], env={**base, "GITHUB_ENV": str(github_env), "GITHUB_STEP_SUMMARY": os.devnull,
                                   "RUNNER_TEMP": str(tmp_path), **env},
        cwd=tmp_path, capture_output=True, text=True, check=False)
    return result, github_env.read_text()


def test_nightly_dispatch_declares_the_pinned_package_inputs_as_data() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for name in _NIGHTLY_PACKAGE_INPUTS:
        assert f"      {name}:\n" in workflow
        # Never interpolated into shell source: only ever bound through step env.
        assert workflow.count(f"github.event.inputs.{name} ") == workflow.count(
            f": ${{{{ github.event.inputs.{name} || '' }}}}")
    for name in ("Retain immutable protected-trunk certification requirements", _BIND_STEP, _INSTALL_STEP):
        _, script = _step(name)
        assert "${{" not in script
    assert workflow.index(_BIND_STEP) < workflow.index("Retain immutable protected-trunk certification")
    install_block, _ = _step(_INSTALL_STEP)
    for variable, source in (("NIGHTLY_DISPATCH_ID", "nightly_dispatch_id"), ("SDK_PACKAGE_VERSION", "sdk_package_version"),
                             ("SDK_PACKAGE_DIGEST", "sdk_package_digest"), ("SDK_SOURCE_SHA", "sdk_source_sha")):
        assert f"{variable}: ${{{{ github.event.inputs.{source} || '' }}}}" in install_block


def test_undispatched_runs_need_no_nightly_package_inputs(tmp_path) -> None:
    # Step env always binds every input; blank on push and ad-hoc dispatch.
    blank = {key: "" for key in _DISPATCHED if not key.startswith("GITHUB_")}
    result, written = _run_step(_BIND_STEP, {**blank, "GITHUB_EVENT_NAME": "push", "GITHUB_SHA": "e" * 40}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert written == ""


def test_complete_nightly_dispatch_binds(tmp_path) -> None:
    result, written = _run_step(_BIND_STEP, _DISPATCHED, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert written == ""


@pytest.mark.parametrize("field,value", [
    ("REQUIREMENTS_SOURCE_SHA", ""), ("REQUIREMENTS_SOURCE_SHA", "a" * 39), ("REQUIREMENTS_SOURCE_SHA", "trunk"),
    ("REQUIREMENTS_REVISION", ""), ("REQUIREMENTS_REVISION", "   "),
    ("SDK_PACKAGE", ""), ("SDK_PACKAGE", "honua_sdk"), ("SDK_PACKAGE", "Honua.Sdk"),
    ("SDK_PACKAGE_VERSION", ""), ("SDK_PACKAGE_VERSION", "latest"), ("SDK_PACKAGE_VERSION", "0.1.19 --pre"),
    ("SDK_PACKAGE_VERSION", "0.1.19;x"), ("SDK_PACKAGE_VERSION", ">=0.1"), ("SDK_PACKAGE_VERSION", "0.1.19+local"),
    ("SDK_PACKAGE_DIGEST", ""), ("SDK_PACKAGE_DIGEST", _DISPATCHED_DIGEST),
    ("SDK_PACKAGE_DIGEST", "sha256:" + "A" * 64), ("SDK_PACKAGE_DIGEST", "sha256:" + "1" * 63),
    ("SDK_PACKAGE_DIGEST", "sha512:" + "1" * 64),
    ("SDK_SOURCE_SHA", ""), ("SDK_SOURCE_SHA", "c" * 41), ("SDK_SOURCE_SHA", "C" * 40),
    ("GITHUB_EVENT_NAME", "push"), ("GITHUB_SHA", ""), ("GITHUB_SHA", "e" * 39),
])
def test_nightly_dispatch_fails_closed_on_missing_or_malformed_inputs(tmp_path, field, value) -> None:
    result, written = _run_step(_BIND_STEP, {**_DISPATCHED, field: value}, tmp_path)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert written == ""


def _pip_stubs(tmp_path: Path, wheel_bytes: bytes) -> Path:
    """Stub python/pip so the install step runs offline; records what it was asked to download."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    (tmp_path / "wheel-bytes").write_bytes(wheel_bytes)
    venv_python = (
        '#!/bin/sh\n'
        'if [ "$1" = "-c" ]; then echo "$STUB_INSTALLED_VERSION"; exit 0; fi\n'
        'echo "venv-python $*" >> "$STUB_EVENTS"\n'
    )
    python = (
        '#!/bin/sh\n'
        'echo "python $*" >> "$STUB_EVENTS"\n'
        'if [ "$1 $2 $3" = "-m pip download" ]; then\n'
        '  for arg; do last="$arg"; done\n'
        '  version="${last#honua-sdk==}"\n'
        '  cp "$STUB_WHEEL_BYTES" "dist/honua_sdk-${version}-py3-none-any.whl"\n'
        'elif [ "$1 $2" = "-m venv" ]; then\n'
        '  mkdir -p "$3/bin"\n'
        f'  cat > "$3/bin/python" <<\'STUB\'\n{venv_python}STUB\n'
        '  chmod +x "$3/bin/python"\n'
        'fi\n'
    )
    stub = bin_dir / "python"
    stub.write_text(python)
    stub.chmod(0o755)
    return bin_dir


def _gnu_sha256sum() -> bool:
    import shutil
    import subprocess

    tool = shutil.which("sha256sum")
    if tool is None:
        return False
    probe = subprocess.run([tool, "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    return probe.returncode == 0 and "GNU coreutils" in probe.stdout


# The step runs on ubuntu-24.04 and relies on GNU `sha256sum --check --strict`.
_needs_gnu_sha256sum = pytest.mark.skipif(
    not _gnu_sha256sum(), reason="install step targets GNU coreutils sha256sum (ubuntu runner)")


def _install(tmp_path: Path, env: dict[str, str], wheel_bytes: bytes, installed_version: str):
    bin_dir = _pip_stubs(tmp_path, wheel_bytes)
    pinned = {
        "HONUA_SDK_PUBLIC_VERSION": "0.1.18",
        "HONUA_SDK_PUBLIC_WHEEL": "honua_sdk-0.1.18-py3-none-any.whl",
        "HONUA_SDK_PUBLIC_WHEEL_SHA256": "2" * 64,
        "HONUA_SDK_PUBLIC_SOURCE_SHA": "3" * 40,
    }
    stub_env = {"STUB_EVENTS": str(tmp_path / "events"), "STUB_WHEEL_BYTES": str(tmp_path / "wheel-bytes"),
                "STUB_INSTALLED_VERSION": installed_version}
    result, written = _run_step(_INSTALL_STEP, {**pinned, **stub_env, **env}, tmp_path, bin_dir)
    events = (tmp_path / "events").read_text() if (tmp_path / "events").exists() else ""
    return result, dict(line.split("=", 1) for line in written.splitlines()), events


@_needs_gnu_sha256sum
def test_nightly_install_downloads_and_verifies_the_dispatched_package(tmp_path) -> None:
    import hashlib

    wheel_bytes = b"dispatched wheel"
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    result, written, events = _install(
        tmp_path, {**_DISPATCHED, "SDK_PACKAGE_DIGEST": "sha256:" + digest}, wheel_bytes, "0.1.19")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "honua-sdk==0.1.19" in events
    assert "honua-sdk==0.1.18" not in events
    assert written["HONUA_SDK_WHEEL_FILENAME"] == "honua_sdk-0.1.19-py3-none-any.whl"
    assert written["HONUA_SDK_WHEEL_SHA256"] == digest
    assert written["HONUA_SDK_WHEEL_SOURCE"] == "pypi"
    assert written["HONUA_SDK_SOURCE_SHA"] == "c" * 40
    requirement = (tmp_path / "honua-sdk-wheel-requirement.txt").read_text()
    assert requirement.endswith(f"honua_sdk-0.1.19-py3-none-any.whl --hash=sha256:{digest}\n")


@_needs_gnu_sha256sum
def test_nightly_install_refuses_a_package_whose_digest_differs(tmp_path) -> None:
    result, written, events = _install(tmp_path, _DISPATCHED, b"tampered wheel", "0.1.19")
    assert result.returncode != 0
    assert "honua-sdk==0.1.19" in events
    assert "venv" not in events
    assert written == {}


@_needs_gnu_sha256sum
def test_nightly_install_refuses_a_different_installed_version(tmp_path) -> None:
    import hashlib

    wheel_bytes = b"dispatched wheel"
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    result, written, _ = _install(
        tmp_path, {**_DISPATCHED, "SDK_PACKAGE_DIGEST": "sha256:" + digest}, wheel_bytes, "0.1.18")
    assert result.returncode != 0
    assert written == {}


@_needs_gnu_sha256sum
def test_undispatched_install_keeps_the_repository_pinned_public_wheel(tmp_path) -> None:
    import hashlib

    wheel_bytes = b"pinned wheel"
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    ignored = {key: value for key, value in _DISPATCHED.items() if key.startswith("SDK_")}
    result, written, events = _install(
        tmp_path, {**ignored, "NIGHTLY_DISPATCH_ID": "", "HONUA_SDK_PUBLIC_WHEEL_SHA256": digest},
        wheel_bytes, "0.1.18")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "honua-sdk==0.1.18" in events
    assert written["HONUA_SDK_WHEEL_FILENAME"] == "honua_sdk-0.1.18-py3-none-any.whl"
    assert written["HONUA_SDK_WHEEL_SHA256"] == digest
    assert written["HONUA_SDK_SOURCE_SHA"] == "3" * 40

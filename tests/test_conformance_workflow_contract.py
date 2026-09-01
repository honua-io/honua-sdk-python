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


def test_conformance_downloads_public_wheel_and_runs_from_isolated_install() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'HONUA_SDK_PUBLIC_VERSION: "0.1.11"' in workflow
    assert 'HONUA_SDK_PUBLIC_WHEEL: "honua_sdk-0.1.11-py3-none-any.whl"' in workflow
    assert "python -m pip download" in workflow
    assert '"honua-sdk==${HONUA_SDK_PUBLIC_VERSION}"' in workflow
    assert "--only-binary=:all:" in workflow
    assert "sha256sum --check --strict" in workflow
    assert "python -m build" not in workflow
    assert "pip install -e packages/honua-sdk" not in workflow
    assert "HONUA_SDK_WHEEL_SHA256=${HONUA_SDK_PUBLIC_WHEEL_SHA256}" in workflow
    assert "HONUA_SDK_WHEEL_SOURCE=pypi" in workflow
    assert "HONUA_SDK_SOURCE_SHA=${HONUA_SDK_PUBLIC_SOURCE_SHA}" in workflow
    assert '"${HONUA_SDK_CERT_PYTHON}" -m pytest tests/conformance' in workflow

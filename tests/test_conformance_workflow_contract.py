from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "conformance.yml"


def test_release_certification_uses_the_governed_candidate_cut() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "candidate_cut_at:" in workflow
    assert "CANDIDATE_CUT_AT_INPUT: ${{ github.event.inputs.candidate_cut_at }}" in workflow
    assert "from scripts._conformance import validate_candidate_cut_at" in workflow
    assert "validate_candidate_cut_at(sys.argv[1])" in workflow
    assert 'candidate_cut_at="${CANDIDATE_CUT_AT_INPUT}"' in workflow
    assert (
        'candidate_cut_at="$(git -C "${server_root}" show -s --format=%cI '
        '"${image_revision}")"'
    ) in workflow


def test_conformance_builds_and_runs_from_an_isolated_wheel_install() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m build --wheel --outdir dist packages/honua-sdk" in workflow
    assert "pip install -e packages/honua-sdk" not in workflow
    assert "HONUA_SDK_WHEEL_SHA256=${wheel_sha256}" in workflow
    assert '"${HONUA_SDK_CERT_PYTHON}" -m pytest tests/conformance' in workflow

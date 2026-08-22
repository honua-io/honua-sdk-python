from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "conformance.yml"


def test_release_certification_uses_the_governed_candidate_cut() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "candidate_cut_at:" in workflow
    assert "CANDIDATE_CUT_AT_INPUT: ${{ github.event.inputs.candidate_cut_at }}" in workflow
    assert (
        'if [[ ! "${CANDIDATE_CUT_AT_INPUT}" =~ '
        "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]"
    ) in workflow
    assert 'candidate_cut_at="${CANDIDATE_CUT_AT_INPUT}"' in workflow
    assert (
        'candidate_cut_at="$(git -C "${server_root}" show -s --format=%cI '
        '"${image_revision}")"'
    ) in workflow

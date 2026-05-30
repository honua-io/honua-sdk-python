"""Blocking live-server conformance lane (issue #81, epic geospatial-grpc#18).

Each test asserts one shared geospatial-grpc fixture's contract against a pinned
live ``honua-server:nightly`` exercised through the ``httpx`` clients. Drift in a
*required* case fails CI. Cases bound to a tracked, already-filed server gap are
``xfail``ed with an explicit issue reference (never silently skipped, never a
blanket ``continue-on-error``) so the lane is green and the harness is in place
while the gap is open; *new* drift in any required case still fails.

See ``scripts/_conformance.py`` for the fixture loader and the gRPC->REST
contract mapping.
"""

from __future__ import annotations

import pytest

from scripts._conformance import KNOWN_SERVER_GAPS, build_cases

pytestmark = [
    pytest.mark.integration,
    pytest.mark.conformance,
]

_CASES = build_cases()


def test_known_server_gaps_are_registered() -> None:
    """Every case's declared known-gap issue must be in the tracked registry.

    Guards against typos or unfiled references in case definitions so an xfail
    can never hide behind an unknown issue id.
    """
    for case in _CASES:
        if case.known_gap_issue is not None:
            assert case.known_gap_issue in KNOWN_SERVER_GAPS, (
                f"case {case.name!r} references untracked gap {case.known_gap_issue!r}"
            )


@pytest.mark.parametrize("case", _CASES, ids=[c.name for c in _CASES])
def test_live_conformance_case(case, conformance_results, request) -> None:
    _, result = conformance_results[case.name]

    if case.known_gap_issue is not None and result.status != "passed":
        # Tracked, already-filed nightly gap: expected failure with an explicit
        # reference. strict=False so that when the server fix lands and the case
        # starts passing, the lane stays green (an xpass) and a maintainer flips
        # the case to required by clearing ``known_gap_issue``.
        request.node.add_marker(
            pytest.mark.xfail(
                reason=(
                    f"KNOWN-EXPECTED-FAILING: {case.known_gap_issue} — "
                    f"{KNOWN_SERVER_GAPS[case.known_gap_issue]}"
                ),
                strict=False,
            )
        )
        pytest.xfail(
            f"{case.known_gap_issue}: {KNOWN_SERVER_GAPS[case.known_gap_issue]} "
            f"({result.error})"
        )

    assert result.status == "passed", (
        f"conformance drift in {case.name} "
        f"[{result.message_type or 'n/a'}] via {result.sdk_method}: {result.error}"
    )

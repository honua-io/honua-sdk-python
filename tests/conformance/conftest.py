from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts._conformance import (
    ConformanceFixturesError,
    locate_fixture_bundle,
    load_target_from_env,
)


@pytest.fixture(scope="session")
def fixture_bundle():
    try:
        return locate_fixture_bundle()
    except ConformanceFixturesError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="session")
def conformance_target():
    if not os.environ.get("HONUA_BASE_URL"):
        pytest.skip(
            "HONUA_BASE_URL is not set; live conformance requires a pinned "
            "honua-server target (set by the conformance CI lane)."
        )
    try:
        return load_target_from_env()
    except ConformanceFixturesError as exc:  # pragma: no cover - guarded above
        pytest.skip(str(exc))


@pytest.fixture(scope="session")
def conformance_client(conformance_target):
    from honua_sdk import HonuaClient

    with HonuaClient(conformance_target.base_url, api_key=conformance_target.api_key) as client:
        yield client


@pytest.fixture(scope="session")
def conformance_results(conformance_client, conformance_target, fixture_bundle):
    """Run every case once per session; tests assert per-case outcomes.

    Centralizing the run lets a session-scoped finalizer write the JUnit-adjacent
    JSON/Markdown summary the CI lane uploads.
    """
    from scripts._conformance import build_cases, render_summary

    results = {
        case.name: (case, case.run(conformance_client, conformance_target, fixture_bundle))
        for case in build_cases()
    }

    summary_path = os.environ.get("HONUA_CONFORMANCE_SUMMARY_PATH")
    if summary_path:
        Path(summary_path).write_text(
            render_summary(
                fixture_bundle,
                conformance_target,
                [result for _, result in results.values()],
            ),
            encoding="utf-8",
        )
    return results

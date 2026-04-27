from __future__ import annotations

import pytest

from scripts._smoke_harness import assert_probe_passed, run_protocol_surface_smoke

pytestmark = [
    pytest.mark.integration,
    pytest.mark.staging,
    pytest.mark.smoke,
]


def test_staging_protocol_surfaces(smoke_client, smoke_config, smoke_report) -> None:
    results = run_protocol_surface_smoke(smoke_client, smoke_config, smoke_report)

    for result in results:
        if result.required:
            assert_probe_passed(result)

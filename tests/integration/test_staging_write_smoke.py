from __future__ import annotations

import pytest

from scripts._smoke_harness import (
    assert_probe_passed,
    probe_apply_edits_roundtrip,
    run_probe,
    skipped_probe,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.staging,
    pytest.mark.smoke,
]


def test_staging_apply_edits_roundtrip(smoke_client, smoke_config, smoke_report) -> None:
    if not smoke_config.enable_write_smoke:
        smoke_report.record(
            skipped_probe(
                "apply_edits_roundtrip",
                "Write smoke disabled. Set HONUA_ENABLE_WRITE_SMOKE=true to enable applyEdits coverage.",
                context=smoke_config.target_dict(),
            )
        )
        pytest.skip("Write smoke disabled.")

    result = smoke_report.record(
        run_probe(
            "apply_edits_roundtrip",
            lambda: probe_apply_edits_roundtrip(smoke_client, smoke_config),
            context=smoke_config.target_dict(),
        )
    )
    assert_probe_passed(result)

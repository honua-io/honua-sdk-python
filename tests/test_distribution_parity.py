from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.verify_distribution_parity import (
    ParityError,
    backoff_delays,
    create_manifest,
    manifest_hashes,
    PublicationPoll,
    poll_until_published,
    verify_hash_parity,
    verify_local_files,
)


def _built_sdk(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / "honua_sdk-0.1.11-py3-none-any.whl").write_bytes(b"wheel-bytes")
    (tmp_path / "honua_sdk-0.1.11.tar.gz").write_bytes(b"sdist-bytes")
    return create_manifest(tmp_path, "honua-sdk", "0.1.11")


def _pypi_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "urls": [
            {"filename": filename, "digests": {"sha256": digest}}
            for filename, digest in manifest_hashes(manifest).items()
        ]
    }


def test_manifest_records_exact_wheel_and_sdist_hashes(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)

    assert manifest["package"] == "honua-sdk"
    assert manifest["version"] == "0.1.11"
    assert len(manifest_hashes(manifest)) == 2


def test_manifest_rejects_extra_distribution_file(tmp_path: Path) -> None:
    _built_sdk(tmp_path)
    (tmp_path / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ParityError, match="exactly one wheel and one sdist"):
        create_manifest(tmp_path, "honua-sdk", "0.1.11")


def test_pypi_exact_filename_and_hash_parity_is_accepted(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)

    verify_hash_parity(manifest, _pypi_payload(manifest))


def test_pypi_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)
    payload = _pypi_payload(manifest)
    payload["urls"][0]["digests"]["sha256"] = "0" * 64

    with pytest.raises(ParityError, match="parity mismatch"):
        verify_hash_parity(manifest, payload)


def test_pypi_extra_filename_is_rejected(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)
    payload = _pypi_payload(manifest)
    payload["urls"].append({"filename": "unexpected.whl", "digests": {"sha256": "1" * 64}})

    with pytest.raises(ParityError, match="parity mismatch"):
        verify_hash_parity(manifest, payload)


def test_downloaded_artifact_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)
    (tmp_path / "honua_sdk-0.1.11.tar.gz").write_bytes(b"replaced")

    with pytest.raises(ParityError, match="Downloaded artifact parity mismatch"):
        verify_local_files(manifest, tmp_path)


def test_backoff_doubles_up_to_a_minute_within_the_budget() -> None:
    delays = backoff_delays(5.0, 300.0)

    assert delays[:4] == [5.0, 10.0, 20.0, 40.0]
    assert max(delays) == 60.0
    assert sum(delays) <= 300.0


def test_backoff_caps_an_initial_delay_above_a_minute() -> None:
    assert backoff_delays(120.0, 300.0) == [60.0, 60.0, 60.0, 60.0, 60.0]


def test_polling_waits_until_pypi_shows_the_upload(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)
    responses = iter([None, None, _pypi_payload(manifest)])
    slept: list[float] = []

    poll_until_published(manifest, PublicationPoll(lambda: next(responses), [5.0, 10.0, 20.0], slept.append))

    assert slept == [5.0, 10.0]


def test_polling_reports_an_unoccupied_coordinate_after_the_budget(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)
    slept: list[float] = []

    with pytest.raises(ParityError, match="still unoccupied"):
        poll_until_published(manifest, PublicationPoll(lambda: None, [5.0, 10.0], slept.append))
    assert slept == [5.0, 10.0]


def test_polling_reports_a_hash_mismatch_after_the_budget(tmp_path: Path) -> None:
    manifest = _built_sdk(tmp_path)
    mismatched = {"urls": [{"filename": name, "digests": {"sha256": "0" * 64}} for name in manifest_hashes(manifest)]}

    with pytest.raises(ParityError, match="parity mismatch"):
        poll_until_published(manifest, PublicationPoll(lambda: mismatched, [1.0], lambda _: None))

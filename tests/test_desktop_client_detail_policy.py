"""Contain desktop-client test procedures outside the public repository."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NEUTRALISED_FILES = (
    ROOT / ".github/workflows/honua-gp-eval.yml",
    ROOT / "packages/honua-gp/docs/golden-eval.md",
)
PROHIBITED_TESTING_DETAIL = (
    "arcgis pro parity",
    "licensed arcpy",
    "real arcgis pro baseline",
    "arcpy-level output equivalence",
    "license-gated",
)
EVIDENCE_IDENTIFIER = "honua-release#425"


@pytest.mark.parametrize("path", NEUTRALISED_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_neutralised_files_exclude_desktop_client_testing_detail(path: Path) -> None:
    content = path.read_text(encoding="utf-8").lower()

    found = [detail for detail in PROHIBITED_TESTING_DETAIL if detail in content]

    assert not found, f"{path.relative_to(ROOT)} contains private desktop-client testing detail: {found}"
    assert EVIDENCE_IDENTIFIER in content

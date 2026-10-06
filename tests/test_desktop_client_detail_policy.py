"""Contain desktop-client test procedures outside the public repository."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY_TEST = Path(__file__).resolve()
NEUTRALISED_FILES = (
    ROOT / ".github/workflows/honua-gp-eval.yml",
    ROOT / "packages/honua-gp/docs/golden-eval.md",
    ROOT / "packages/honua-gp/eval/run_eval.py",
    ROOT / "packages/honua-gp/eval/_emit.py",
)
PROHIBITED_TESTING_DETAIL = (
    "arcgis pro parity",
    "arcgis pro output parity",
    "licensed arcpy",
    "real arcgis pro baseline",
    "arcpy-level output equivalence",
    "arcpy-level output parity",
    "license-gated",
)
EVIDENCE_IDENTIFIER = "honua-release#425"


def _tracked_files() -> list[Path]:
    git = shutil.which("git")
    assert git, "git is required to enumerate the public tree"
    result = subprocess.run([git, "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)  # noqa: S603 -- resolved git + literal args
    listing = result.stdout.decode("utf-8")
    return [ROOT / name for name in listing.split("\0") if name]


def _found_detail(content: str) -> list[str]:
    lowered = content.lower()
    return [detail for detail in PROHIBITED_TESTING_DETAIL if detail in lowered]


@pytest.mark.parametrize("path", NEUTRALISED_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_neutralised_files_exclude_desktop_client_testing_detail(path: Path) -> None:
    content = path.read_text(encoding="utf-8")

    found = _found_detail(content)

    assert not found, f"{path.relative_to(ROOT)} contains private desktop-client testing detail: {found}"
    assert EVIDENCE_IDENTIFIER in content


def test_public_tree_excludes_desktop_client_testing_detail() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _tracked_files():
        if path.resolve() == POLICY_TEST or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = _found_detail(content)
        if found:
            offenders[path.relative_to(ROOT).as_posix()] = found

    assert not offenders, f"tracked files contain private desktop-client testing detail: {offenders}"

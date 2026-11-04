from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_lock_pip_pins.py"
_SPEC = importlib.util.spec_from_file_location("check_lock_pip_pins", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
check_lock_pip_pins = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_lock_pip_pins)


def _write_lock(directory: Path, name: str, body: str) -> Path:
    lock = directory / name
    lock.write_text(body, encoding="utf-8")
    return lock


def test_reads_the_pinned_pip_version(tmp_path: Path) -> None:
    lock = _write_lock(
        tmp_path, "ci.lock", "anyio==4.0 \\\n    --hash=sha256:aa\npip==26.2.1 \\\n    --hash=sha256:bb\n"
    )

    assert check_lock_pip_pins.pip_pins([lock]) == {"ci.lock": "26.2.1"}


def test_reports_a_lock_without_pip(tmp_path: Path) -> None:
    lock = _write_lock(tmp_path, "publish.lock", "pipx==1.0 \\\n    --hash=sha256:aa\n")

    assert check_lock_pip_pins.pin_problems(check_lock_pip_pins.pip_pins([lock])) == ["publish.lock does not pin pip"]


def test_reports_locks_that_disagree() -> None:
    problems = check_lock_pip_pins.pin_problems({"a.lock": "26.2.1", "b.lock": "25.0"})

    assert problems == ["locks pin different pip versions: 25.0, 26.2.1"]


def test_accepts_matching_pins() -> None:
    assert check_lock_pip_pins.pin_problems({"a.lock": "26.2.1", "b.lock": "26.2.1"}) == []


def test_every_tracked_lock_pins_the_same_pip() -> None:
    pins = check_lock_pip_pins.pip_pins(check_lock_pip_pins.tracked_locks())

    assert pins
    assert check_lock_pip_pins.pin_problems(pins) == []

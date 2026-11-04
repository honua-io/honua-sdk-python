"""Require every tracked dependency lock to pin pip, and all of them to the same version.

Tests that review pip's installed-file transformations depend on pip's exact behaviour,
so a lock that leaves pip to the runner lets one workflow drift from the others.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIP_PIN = re.compile(r"^pip==(\S+)", re.MULTILINE)


def tracked_locks(root: Path = ROOT) -> list[Path]:
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "*.lock"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [root / name for name in listing.split("\0") if name]


def pip_pins(locks: list[Path]) -> dict[str, str | None]:
    pins: dict[str, str | None] = {}
    for lock in locks:
        match = PIP_PIN.search(lock.read_text(encoding="utf-8"))
        pins[lock.name] = match.group(1) if match else None
    return pins


def pin_problems(pins: dict[str, str | None]) -> list[str]:
    problems = [f"{name} does not pin pip" for name, version in sorted(pins.items()) if version is None]
    versions = sorted({version for version in pins.values() if version is not None})
    if len(versions) > 1:
        problems.append(f"locks pin different pip versions: {', '.join(versions)}")
    return problems


def main() -> int:
    pins = pip_pins(tracked_locks())
    problems = pin_problems(pins)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"pip is pinned to {next(iter(set(pins.values())), 'n/a')} in all {len(pins)} locks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

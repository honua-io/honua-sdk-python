"""Reject new review findings while preserving individually recorded existing debt."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "config" / "ruff-review-baseline.json"
Finding = tuple[str, str, str, str]


def findings() -> Counter[Finding]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--config", ".ruff-review.toml",
         "--ignore-noqa", "--output-format", "json"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    counts: Counter[Finding] = Counter()
    for item in json.loads(result.stdout):
        path = Path(item["filename"])
        source = path.read_text(encoding="utf-8-sig").splitlines()[item["location"]["row"] - 1].strip()
        counts[(item["code"], path.relative_to(ROOT).as_posix(), item["message"], source)] += 1
    return counts


def read_baseline(path: Path) -> Counter[Finding]:
    counts: Counter[Finding] = Counter()
    for row in json.loads(path.read_text(encoding="utf-8")):
        key = (row["code"], row["path"], row["message"], row["source"])
        if type(row["count"]) is not int or row["count"] < 1 or key in counts:
            raise ValueError("Baseline entries need unique findings and positive integer counts")
        counts[key] = row["count"]
    return counts


def write_baseline(counts: Counter[Finding]) -> None:
    rows = [dict(zip(("code", "path", "message", "source", "count"), (*key, count), strict=True))
            for key, count in sorted(counts.items())]
    BASELINE.parent.mkdir(exist_ok=True)
    BASELINE.write_text("[\n" + ",\n".join(json.dumps(row) for row in rows) + "\n]\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Replace the baseline for explicit review")
    options = parser.parse_args()
    current = findings()
    if options.capture:
        write_baseline(current)
        return 0
    unexpected = current - read_baseline(BASELINE)
    for (code, path, message, source), count in sorted(unexpected.items()):
        print(f"{path}: {code} {message} ({count} new): {source}")
    print(f"Review baseline: {sum(unexpected.values())} new finding(s)")
    return int(bool(unexpected))


if __name__ == "__main__":
    sys.exit(main())

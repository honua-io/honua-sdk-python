"""Reject new lint violations while preserving individually recorded existing debt."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "ruff-review-baseline.json"
Finding = tuple[str, str, str, str, str]


def findings() -> Counter[Finding]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--config", ".ruff-review.toml",
         "--ignore-noqa", "--output-format", "json"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    counts: Counter[Finding] = Counter()
    parsed: dict[Path, tuple[list[str], ast.Module]] = {}
    for item in json.loads(result.stdout):
        path = Path(item["filename"])
        if path not in parsed:
            text = path.read_text(encoding="utf-8-sig")
            parsed[path] = (text.splitlines(), ast.parse(text))
        lines, tree = parsed[path]
        row = item["location"]["row"]
        scopes = sorted(
            (node for node in ast.walk(tree)
             if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
             and node.lineno <= row <= node.end_lineno),
            key=lambda node: (node.lineno, -node.end_lineno),
        )
        context = ".".join(node.name for node in scopes) or "<module>"
        source = lines[row - 1].strip()
        counts[(item["code"], path.relative_to(ROOT).as_posix(), item["message"], context, source)] += 1
    return counts


def read_baseline(path: Path) -> Counter[Finding]:
    counts: Counter[Finding] = Counter()
    for row in json.loads(path.read_text(encoding="utf-8")):
        key = (row["code"], row["path"], row["message"], row["context"], row["source"])
        if type(row["count"]) is not int or row["count"] < 1 or key in counts:
            raise ValueError("Baseline entries need unique findings and positive integer counts")
        counts[key] = row["count"]
    return counts


def write_baseline(counts: Counter[Finding]) -> None:
    rows = [dict(zip(("code", "path", "message", "context", "source", "count"), (*key, count), strict=True))
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
    for (code, path, message, context, source), count in sorted(unexpected.items()):
        print(f"{path}: {context}: {code} {message} ({count} new): {source}")
    print(f"Review baseline: {sum(unexpected.values())} new finding(s)")
    return int(bool(unexpected))


if __name__ == "__main__":
    sys.exit(main())

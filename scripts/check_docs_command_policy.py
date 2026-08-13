"""Reject unsupported raw HTTP command examples in maintained documentation."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOC_ROOTS = (ROOT / "docs", ROOT / "examples", ROOT / "packages")
TOP_LEVEL_DOCS = (ROOT / "README.md", ROOT / "INSTALL.md", *ROOT.glob("llms*.txt"))
DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
RAW_HTTP_COMMAND = re.compile(r"\bcurl(?:\.exe)?\b", re.IGNORECASE)


def maintained_docs() -> list[Path]:
    files = [path for path in TOP_LEVEL_DOCS if path.is_file()]
    for root in DOC_ROOTS:
        if not root.exists():
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in DOC_SUFFIXES
            and path.name not in {"AGENTS.md", "CHANGELOG.md"}
        )
    return sorted(set(files))


def main() -> int:
    violations: list[str] = []
    for path in maintained_docs():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW_HTTP_COMMAND.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}:{line.strip()}")
    if violations:
        print("Maintained documentation must use supported SDK, CLI, or API-reference workflows:")
        print("\n".join(violations))
        return 1
    print("Maintained documentation command policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

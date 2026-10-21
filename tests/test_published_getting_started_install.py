"""Getting-started release installs stay on the admitted published package.

Source-checkout fences remain in README and INSTALL so the development-source
producer can still capture them. The executable-docs gate must not run those
fences: a direct-origin install replaces the admitted package, and release
qualification refuses that origin even when the version string matches.
"""
from __future__ import annotations

from pathlib import Path
import re

from scripts import development_source_inputs as inputs
from scripts import python_document_inputs as documentation


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("README.md", "INSTALL.md")
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
SKIP = re.compile(
    r"<!--\s*doc-run:\s*skip\s+reason=\"[^\"]+\"\s*-->\s*$",
    re.MULTILINE,
)
DIRECT_ORIGIN = re.compile(
    r"git\s+clone\b|pip\s+install\s+-e\b|pip\s+install\s+\.?/?packages/|pip\s+install\s+\"\./packages/",
)


def _release_fences(text: str) -> list[tuple[str, str, str]]:
    """Return (info, preceding, code) for each fence."""
    found = []
    cursor = 0
    for match in FENCE.finditer(text):
        found.append((match.group(1), text[cursor:match.start()], match.group(2)))
        cursor = match.end()
    return found


def test_release_install_fences_use_the_published_package() -> None:
    for name in DOCUMENTS:
        text = (ROOT / name).read_text(encoding="utf-8")
        release_installs = []
        for info, preceding, code in _release_fences(text):
            if info.strip().split()[0] not in {"bash", "sh", "shell"}:
                continue
            if SKIP.search(preceding):
                continue
            assert DIRECT_ORIGIN.search(code) is None, name
            if "pip install" in code and "honua-sdk" in code:
                release_installs.append(code)
        assert release_installs, name
        assert any(re.search(r"^pip install honua-sdk\b", line) or 'pip install "honua-sdk' in line
                   for code in release_installs for line in code.splitlines()), name


def test_source_checkout_fences_stay_captured_and_are_not_release_steps() -> None:
    source = {"files": {name: {"gitBlob": "0" * 40} for name in DOCUMENTS}}
    planned = documentation.plan(inputs, ROOT, source)
    by_document: dict[str, int] = {}
    for item in planned:
        by_document[item["document"]] = by_document.get(item["document"], 0) + 1
        text = (ROOT / item["document"]).read_text(encoding="utf-8")
        fences = [code for info, _preceding, code in _release_fences(text) if code == item["blockBytes"]]
        assert fences, item["document"]
        preceding = next(preceding for _info, preceding, code in _release_fences(text) if code == item["blockBytes"])
        assert SKIP.search(preceding), item["document"]
    assert by_document["INSTALL.md"] >= 1
    assert by_document["README.md"] >= 2

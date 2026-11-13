"""Exercise the review gate with actual Ruff findings and finite suppression budgets."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import check_review_baseline as gate


class ReviewBaselineTests(unittest.TestCase):
    def test_all_requested_rules_are_enabled(self) -> None:
        source = """def flags(value: bool, a, b, c):
    try:
        return a()
    except Exception:
        pass

def bare():
    try:
        return work()
    except:
        return None
"""
        findings = self.scan(source)
        self.assertEqual({key[0] for key in findings}, {"S110", "E722", "BLE001", "FBT001", "PLR0913"})

    def test_shifted_lines_preserve_but_duplicates_exceed_budget(self) -> None:
        source = "def flags(value: bool): return value\n"
        existing = self.scan(source)
        self.assertEqual(existing, self.scan("\n\n" + source))
        self.assertEqual(sum((self.scan(source * 2) - existing).values()), 1)

    def test_replacement_handler_in_another_function_is_new(self) -> None:
        original = "def old():\n    try: work()\n    except Exception: pass\n"
        changed = original.replace("except Exception", "except OSError")
        changed += original.replace("def old", "def new")
        new = self.scan(changed) - self.scan(original)
        self.assertEqual({key[0] for key in new}, {"S110", "BLE001"})
        self.assertEqual(sum(new.values()), 2)

    def test_noqa_cannot_hide_new_finding(self) -> None:
        self.assertEqual(sum(self.scan("def flags(value: bool): return value  # noqa: FBT001\n").values()), 1)

    def test_invalid_or_duplicate_baseline_rows_are_rejected(self) -> None:
        row = {"code": "FBT001", "path": "sample.py", "message": "existing", "context": "flags", "source": "source", "count": 1}
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.json"
            for rows in ([row, row], [dict(row, count=0)], [dict(row, count=True)]):
                baseline.write_text(json.dumps(rows), encoding="utf-8")
                with self.assertRaises(ValueError):
                    gate.read_baseline(baseline)

    def scan(self, source: str) -> Counter[gate.Finding]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(source, encoding="utf-8")
            (root / "scripts").mkdir()
            (root / "scripts/ruff-review.toml").write_text(
                (gate.ROOT / "scripts/ruff-review.toml").read_text(encoding="utf-8"), encoding="utf-8")
            with patch.object(gate, "ROOT", root):
                return gate.findings()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_please_uses_single_v_component_tags() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))

    for package_config in config["packages"].values():
        assert package_config["include-component-in-tag"] is True
        assert package_config["tag-separator"] == "-"

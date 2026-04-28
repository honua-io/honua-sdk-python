"""Tests for publish tag validation helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "validate_publish_tag.py"
SPEC = importlib.util.spec_from_file_location("validate_publish_tag", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
validate_publish_tag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_publish_tag)


@pytest.mark.parametrize(
    "tag_name",
    [
        "python-sdk-v0.1.0",
        "python-sdk-vv0.1.0",
    ],
)
def test_validate_publish_tag_accepts_single_or_double_v_prefix(tag_name: str) -> None:
    validate_publish_tag.validate_publish_tag(
        ROOT / "packages" / "honua-sdk" / "pyproject.toml",
        tag_name,
        "python-sdk-v",
    )


def test_validate_publish_tag_rejects_version_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_publish_tag.validate_publish_tag(
            ROOT / "packages" / "honua-sdk" / "pyproject.toml",
            "python-sdk-v9.9.9",
            "python-sdk-v",
        )


def test_validate_publish_tag_rejects_wrong_component_prefix() -> None:
    with pytest.raises(ValueError, match="does not start"):
        validate_publish_tag.validate_publish_tag(
            ROOT / "packages" / "honua-sdk" / "pyproject.toml",
            "python-admin-v0.0.2",
            "python-sdk-v",
        )

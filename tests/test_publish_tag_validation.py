"""Tests for publish tag validation helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import validate_publish_tag

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "tag_template",
    [
        "python-sdk-v{version}",
        "python-sdk-vv{version}",
    ],
)
def test_validate_publish_tag_accepts_single_or_double_v_prefix(tag_template: str) -> None:
    pyproject_path = ROOT / "packages" / "honua-sdk" / "pyproject.toml"
    version = validate_publish_tag.package_version(pyproject_path)

    validate_publish_tag.validate_publish_tag(
        pyproject_path,
        tag_template.format(version=version),
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

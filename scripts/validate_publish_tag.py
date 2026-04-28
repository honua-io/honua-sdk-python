"""Validate that a package publish tag matches a package version."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib


def normalized_tag_version(tag_name: str, prefix: str) -> str:
    """Return the version suffix from a publish tag.

    Release automation has produced both ``python-sdk-v0.0.2`` and
    ``python-sdk-vv0.0.2`` style tags. The publish gate accepts either and
    compares the normalized version to the package metadata.
    """
    if not tag_name.startswith(prefix):
        raise ValueError(f"Tag {tag_name!r} does not start with expected prefix {prefix!r}.")

    version = tag_name[len(prefix) :]
    if version.startswith("v"):
        version = version[1:]
    if not version:
        raise ValueError(f"Tag {tag_name!r} does not include a version suffix.")
    return version


def package_version(pyproject_path: Path) -> str:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    try:
        version = data["project"]["version"]
    except KeyError as exc:
        raise ValueError(f"{pyproject_path} is missing project.version.") from exc
    if not isinstance(version, str) or not version:
        raise ValueError(f"{pyproject_path} project.version must be a non-empty string.")
    return version


def validate_publish_tag(pyproject_path: Path, tag_name: str, prefix: str) -> None:
    expected_version = package_version(pyproject_path)
    actual_version = normalized_tag_version(tag_name, prefix)
    if actual_version != expected_version:
        raise ValueError(
            f"Tag version ({actual_version}) does not match "
            f"pyproject.toml version ({expected_version})."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, required=True, help="Path to package pyproject.toml.")
    parser.add_argument("--tag", required=True, help="Git ref name/tag to validate.")
    parser.add_argument("--prefix", required=True, help="Expected tag prefix, for example python-sdk-v.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_publish_tag(args.pyproject, args.tag, args.prefix)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

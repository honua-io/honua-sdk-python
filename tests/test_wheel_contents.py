"""Wheel-contents assertions for the built distributions.

``twine check`` validates wheel *metadata* but never inspects the packaged
files, so a dropped ``[tool.hatch.build]`` include, a missing ``py.typed``
marker, or a whole subpackage that stops being shipped would sail past it and
produce a wheel that silently loses type hints (PEP 561) or runtime modules.

These tests build each package's wheel in-process with hatchling (the declared
build backend — no isolated venv, ~0.5s) and assert that the non-obvious
payload is actually inside the archive. They mirror, and are kept in sync with,
the ``Assert <pkg> wheel contents`` steps in ``.github/workflows/ci.yml``; the
CI build job remains the hard gate, while these give local developers the same
signal from a plain ``pytest tests/`` run.

The tests skip cleanly when hatchling is not importable (e.g. a minimal test
environment that only installs the runtime packages), so they never turn a
build-tooling gap into a spurious test failure.
"""

from __future__ import annotations

import tempfile
import zipfile
from contextlib import chdir
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = REPO_ROOT / "packages"

# Per-package payload that must survive packaging. Entries ending in ``/`` are
# treated as directory prefixes (any member underneath satisfies them); the
# rest are exact archive member paths.
EXPECTED_CONTENTS: dict[str, tuple[str, ...]] = {
    "honua-sdk": (
        # PEP 561 marker — without it installed type hints are invisible.
        "honua_sdk/py.typed",
        # Shared retry core that both client facades delegate to.
        "honua_sdk/_retry_core.py",
        # Optional but first-party subpackages that must ship whole.
        "honua_sdk/grpc/",
        "honua_sdk/migration/",
        # The generated gRPC type stub is the type signal for the streaming
        # client; a wheel that drops it ships an untyped grpc surface.
        "honua_sdk/grpc/_generated/honua/v1/feature_service_pb2.pyi",
    ),
    "honua-admin": (
        "honua_admin/py.typed",
        "honua_admin/_client.py",
        "honua_admin/_async_client.py",
        # Shared request/parse helpers for the admin client facades.
        "honua_admin/_endpoints.py",
        # AST-walking arcpy inventory scanner.
        "honua_admin/_arcpy_scanner.py",
    ),
}


def _build_wheel(package_dir: Path, dest: Path) -> Path:
    """Build *package_dir* into *dest* using the hatchling build backend."""
    hatchling_build = pytest.importorskip(
        "hatchling.build",
        reason="hatchling (the build backend) is not installed in this environment",
    )
    with chdir(package_dir):
        wheel_name = hatchling_build.build_wheel(str(dest))
    return dest / wheel_name


@pytest.mark.parametrize("package", sorted(EXPECTED_CONTENTS))
def test_wheel_ships_expected_contents(package: str) -> None:
    package_dir = PACKAGES_DIR / package
    assert package_dir.is_dir(), f"missing package source dir: {package_dir}"

    with tempfile.TemporaryDirectory() as tmp:
        wheel_path = _build_wheel(package_dir, Path(tmp))
        with zipfile.ZipFile(wheel_path) as archive:
            members = archive.namelist()

    missing = []
    for expected in EXPECTED_CONTENTS[package]:
        if expected.endswith("/"):
            present = any(member.startswith(expected) for member in members)
        else:
            present = expected in members
        if not present:
            missing.append(expected)

    assert not missing, (
        f"{package} wheel is missing expected contents: {missing}\n"
        f"wheel members:\n" + "\n".join(sorted(members))
    )


@pytest.mark.parametrize("package", sorted(EXPECTED_CONTENTS))
def test_wheel_ships_license_text(package: str) -> None:
    """Each wheel must carry the actual Apache-2.0 license text, not just the
    ``License`` metadata field.

    Hatchling only auto-includes license files found in the package's build
    root, so without a ``LICENSE`` in the package directory (and a matching
    ``license-files`` declaration) the wheel advertises a license it does not
    ship — a distribution-compliance gap that ``twine check`` does not catch.
    """
    package_dir = PACKAGES_DIR / package
    assert package_dir.is_dir(), f"missing package source dir: {package_dir}"

    with tempfile.TemporaryDirectory() as tmp:
        wheel_path = _build_wheel(package_dir, Path(tmp))
        with zipfile.ZipFile(wheel_path) as archive:
            members = archive.namelist()

    # PEP 639 places license files under ``*.dist-info/licenses/``; older
    # hatchling layouts put them directly under ``*.dist-info/``. Accept either.
    license_members = [
        m
        for m in members
        if ".dist-info/" in m
        and "LICENSE" in m.rsplit("/", 1)[-1].upper()
    ]
    assert license_members, (
        f"{package} wheel ships no LICENSE file under *.dist-info/\n"
        f"wheel members:\n" + "\n".join(sorted(members))
    )

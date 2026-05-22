#!/usr/bin/env python3
"""Regenerate ``docs/compatibility-matrix.md`` from the in-code COMPAT manifest.

Run from the package root::

    python -m honua_arcpy._cli matrix --output docs/compatibility-matrix.md

Or, equivalently::

    python scripts/render_compat_matrix.py

CI uses ``--check`` to fail builds when the manifest drifts from the
committed matrix.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(package_root))
    sys.path.insert(0, str(package_root.parent / "honua-sdk"))
    sys.path.insert(0, str(package_root.parent / "honua-admin"))

    from honua_arcpy._cli import main

    target = package_root / "docs" / "compatibility-matrix.md"
    sys.exit(main(["matrix", "--output", str(target)]))

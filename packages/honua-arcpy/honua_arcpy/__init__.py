"""Deprecated backward-compatibility shim for the renamed ``honua_gp`` package.

The geoprocessing compatibility layer was renamed from ``honua-arcpy`` /
``honua_arcpy`` to ``honua-gp`` / ``honua_gp`` to avoid using an Esri
trademark in a distribution and import-namespace name. This module preserves
the legacy ``import honua_arcpy`` entry point by re-exporting the public API
of :mod:`honua_gp` and emitting a :class:`DeprecationWarning`.

Migrate to::

    import honua_gp as arcpy

This shim forwards to the same implementation, so behavior is unchanged.
"""

from __future__ import annotations

import sys as _sys
import warnings as _warnings

import honua_gp as _honua_gp
from honua_gp import *  # noqa: F401,F403  -- re-export the public surface
from honua_gp import analysis as analysis
from honua_gp import da as da
from honua_gp import env as env
from honua_gp import management as management

# Make ``from honua_arcpy.<sub> import ...`` and ``import honua_arcpy.<sub>``
# resolve to the renamed sub-packages without duplicating their source.
_sys.modules.setdefault("honua_arcpy.analysis", analysis)
_sys.modules.setdefault("honua_arcpy.da", da)
_sys.modules.setdefault("honua_arcpy.management", management)

__all__ = list(getattr(_honua_gp, "__all__", []))
__version__ = getattr(_honua_gp, "__version__", "0.0.0")

_warnings.warn(
    "The 'honua_arcpy' package is deprecated and will be removed in a future "
    "release; import 'honua_gp' instead (e.g. `import honua_gp as arcpy`).",
    DeprecationWarning,
    stacklevel=2,
)

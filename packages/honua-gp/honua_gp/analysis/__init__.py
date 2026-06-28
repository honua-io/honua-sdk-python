"""``arcpy.analysis`` shim -- 15 functions.

Two analysis tools are now process-backed via the layer-aware projection
adapter (:mod:`honua_gp._process_tools`):

* ``Buffer`` -> honua-server ``analytics.buffer-aggregate`` (layerId +
  distance/unit + dissolve).
* ``SpatialJoin`` -> honua-server ``analytics.spatial-join`` (layerId +
  joinLayerId + predicate).

The four overlay tools that arcpy expresses over feature classes -- ``Clip``,
``Intersect``, ``Union``, ``Erase`` -- have **no** layer-aware catalog
counterpart. honua-server only exposes the single-geometry ``geometry.*``
family (``geometry.clip`` / ``geometry.intersect`` / ``geometry.union`` /
``geometry.difference``), which buffers/clips/etc. one base64-WKB geometry at a
time rather than every feature in a layer. Wiring those would require a
client-side per-feature WKB serialization + reassembly loop that does not exist
yet, so they stay honest ``HonuaGpUnsupportedError`` stubs with a tracking
ticket. The remaining analytics stubs (Near, NearestNeighbor, ...) likewise
have no catalog op.
"""

from __future__ import annotations

from typing import Any

from .._dispatch import raise_unsupported
from .._process_tools import Result, run_layer_process


def Buffer(*args: Any, **kwargs: Any) -> Result:
    return run_layer_process("analysis.Buffer", *args, **kwargs)


def Clip(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Clip", args=args, kwargs=kwargs)


def Intersect(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Intersect", args=args, kwargs=kwargs)


def Union(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Union", args=args, kwargs=kwargs)


def Erase(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Erase", args=args, kwargs=kwargs)


def SpatialJoin(*args: Any, **kwargs: Any) -> Result:
    return run_layer_process("analysis.SpatialJoin", *args, **kwargs)


def NearestNeighbor(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.NearestNeighbor", args=args, kwargs=kwargs)


def Near(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Near", args=args, kwargs=kwargs)


def TabulateIntersection(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.TabulateIntersection", args=args, kwargs=kwargs)


def MultipleRingBuffer(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.MultipleRingBuffer", args=args, kwargs=kwargs)


def PointDistance(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.PointDistance", args=args, kwargs=kwargs)


def SummarizeWithin(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.SummarizeWithin", args=args, kwargs=kwargs)


def SymmetricalDifference(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.SymmetricalDifference", args=args, kwargs=kwargs)


def Update(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Update", args=args, kwargs=kwargs)


def Identity(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Identity", args=args, kwargs=kwargs)


__all__ = [
    "Buffer",
    "Clip",
    "Erase",
    "Identity",
    "Intersect",
    "MultipleRingBuffer",
    "Near",
    "NearestNeighbor",
    "PointDistance",
    "Result",
    "SpatialJoin",
    "SummarizeWithin",
    "SymmetricalDifference",
    "TabulateIntersection",
    "Union",
    "Update",
]

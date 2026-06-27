"""``arcpy.analysis`` shim -- 15 functions, all currently stubbed.

The 6 process-backed entries (Buffer, Clip, Intersect, Union, Erase,
SpatialJoin) were previously dispatched via
``honua_sdk.protocols.OgcProcessesClient`` against honua-server's
``geometry.*`` / ``analytics.*`` processes. Audit against
``BuiltInProcessCatalog`` showed the shim emitted an arcpy-style
``input_features`` / ``result`` payload while honua-server expects raw
WKB-with-srid (for ``geometry.*``) or ``layerId``-shaped references
(for ``analytics.*``). Those calls would have been rejected by live
process validation, so every analysis shim now raises
:class:`~honua_gp._errors.HonuaGpUnsupportedError` with the
relevant honua-server tracking ticket until the projection adapter
lands.
"""

from __future__ import annotations

from typing import Any

from .._dispatch import raise_unsupported


def Buffer(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Buffer", args=args, kwargs=kwargs)


def Clip(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Clip", args=args, kwargs=kwargs)


def Intersect(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Intersect", args=args, kwargs=kwargs)


def Union(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Union", args=args, kwargs=kwargs)


def Erase(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.Erase", args=args, kwargs=kwargs)


def SpatialJoin(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("analysis.SpatialJoin", args=args, kwargs=kwargs)


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
    "Intersect",
    "Union",
    "Erase",
    "SpatialJoin",
    "NearestNeighbor",
    "Near",
    "TabulateIntersection",
    "MultipleRingBuffer",
    "PointDistance",
    "SummarizeWithin",
    "SymmetricalDifference",
    "Update",
    "Identity",
]

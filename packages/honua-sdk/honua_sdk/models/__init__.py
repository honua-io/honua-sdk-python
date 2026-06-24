"""Typed models for core Honua SDK responses.

This package fans the former single-file ``models.py`` module out into focused
submodules grouped by resource:

* :mod:`._protocols` — :data:`Protocol` / :data:`Capability` literals, the
  ``PROTOCOLS`` / ``CAPABILITIES`` / alias / default tables, and the
  ``normalize_protocol`` / ``normalize_capability`` coercion helpers.
* :mod:`._discovery` — :class:`ServiceSummary`, :class:`DataPlaneCapabilities`.
* :mod:`._sources` — :class:`SourceLocator`, :class:`SourceDescriptor`.
* :mod:`._query` — :class:`Pagination`, :class:`Query`, :class:`DegradedReason`,
  :class:`Result`.
* :mod:`._features` — :class:`Feature`, :class:`FeatureSet`,
  :class:`FeatureQuery`, :class:`QueryFeature`, :class:`FeatureQueryResult`.
* :mod:`._edits` — :class:`EditOperationResult`, :class:`ApplyEditsResult`.

Every public name that previously lived at ``honua_sdk.models`` is re-exported
here unchanged, so ``from honua_sdk.models import Query`` (and the top-level
``from honua_sdk import Query``) keep working. Each re-exported symbol's
``__module__`` is pinned back to ``honua_sdk.models`` so the public-API
snapshot, ``repr()``, and ``pickle`` identity stay byte-for-byte stable across
the split.
"""

from __future__ import annotations

from typing import TypeVar

from ._discovery import DataPlaneCapabilities, ServiceSummary
from ._edits import ApplyEditsResult, EditOperationResult
from ._features import (
    Feature,
    FeatureQuery,
    FeatureQueryResult,
    FeatureSet,
    QueryFeature,
)
from ._protocols import (
    CAPABILITIES,
    DEFAULT_CAPABILITIES,
    PROTOCOL_ALIASES,
    PROTOCOLS,
    Capability,
    Protocol,
    QueryProtocol,
    capability_set,
    default_capabilities,
    normalize_capability,
    normalize_protocol,
)
from ._query import DegradedReason, Pagination, Query, Result
from ._sources import SourceDescriptor, SourceLocator

#: Backwards-compatible alias for the result element type variable that used to
#: be a module-level name in the former ``models.py``.
T = TypeVar("T")

# Pin ``__module__`` back to this package for every public symbol so the
# compatibility-gate public-API snapshot (which records ``cls.__module__``),
# ``repr()`` output, and pickling stay identical to the pre-split single-file
# module. The submodules are private implementation detail.
for _symbol in (
    ServiceSummary,
    DataPlaneCapabilities,
    SourceLocator,
    SourceDescriptor,
    Pagination,
    Query,
    DegradedReason,
    Result,
    Feature,
    FeatureSet,
    FeatureQuery,
    QueryFeature,
    FeatureQueryResult,
    EditOperationResult,
    ApplyEditsResult,
    normalize_protocol,
    normalize_capability,
    capability_set,
    default_capabilities,
):
    _symbol.__module__ = __name__
del _symbol

__all__ = [
    "CAPABILITIES",
    "DEFAULT_CAPABILITIES",
    "PROTOCOLS",
    "PROTOCOL_ALIASES",
    "ApplyEditsResult",
    "Capability",
    "DataPlaneCapabilities",
    "DegradedReason",
    "EditOperationResult",
    "Feature",
    "FeatureQuery",
    "FeatureQueryResult",
    "FeatureSet",
    "Pagination",
    "Protocol",
    "Query",
    "QueryFeature",
    "QueryProtocol",
    "Result",
    "ServiceSummary",
    "SourceDescriptor",
    "SourceLocator",
    "T",
    "capability_set",
    "default_capabilities",
    "normalize_capability",
    "normalize_protocol",
]

"""Deprecated back-compat alias for :mod:`honua_sdk.http`.

.. deprecated::
    Import from :mod:`honua_sdk.http` instead. This module is a thin
    re-export shim retained only for downstream code that historically
    imported the leading-underscore name. It is scheduled for removal
    in a future release.
"""

from __future__ import annotations

import warnings

from honua_sdk.http import *  # noqa: F403

warnings.warn(
    "honua_sdk._shared is deprecated; import from honua_sdk.http instead.",
    DeprecationWarning,
    stacklevel=2,
)

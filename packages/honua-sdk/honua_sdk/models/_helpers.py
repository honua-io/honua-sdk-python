"""Shared payload-coercion helpers for the model dataclasses.

These private helpers are imported across the ``honua_sdk.models`` submodules
and were factored out of the former single-file ``models.py`` module. They are
not part of the public API; the canonical public names are re-exported from
:mod:`honua_sdk.models`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _sequence_value(value: Any) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    return None


def _mapping_value(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None

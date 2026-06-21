"""Tests for pagination-signal total-count coercion (issue #107).

Servers occasionally emit ``numberMatched`` / ``@odata.count`` as a JSON
float (e.g. ``1000.0``) rather than an integer. The coercion must accept
whole-valued floats and reject ``bool`` (an ``int`` subclass) so totals
aren't silently dropped to ``None``.
"""

from __future__ import annotations

import pytest

from honua_sdk._query import (
    _coerce_total_count,
    odata_pagination_signals,
    ogc_pagination_signals,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1000, 1000),
        (1000.0, 1000),
        ("1000", 1000),
        (0, 0),
        (0.0, 0),
        (1000.5, None),  # non-integer float is not a meaningful count
        ("12.5", None),
        ("abc", None),
        (None, None),
        (True, None),  # bool rejected despite being an int subclass
        (False, None),
    ],
)
def test_coerce_total_count(raw: object, expected: int | None) -> None:
    assert _coerce_total_count(raw) == expected


def test_ogc_pagination_signals_accepts_float_total() -> None:
    total, exceeded = ogc_pagination_signals({"numberMatched": 1000.0})
    assert total == 1000
    assert exceeded is False


def test_odata_pagination_signals_accepts_float_total() -> None:
    total, exceeded = odata_pagination_signals({"@odata.count": 42.0})
    assert total == 42
    assert exceeded is False


def test_ogc_pagination_signals_rejects_bool_total() -> None:
    total, _exceeded = ogc_pagination_signals({"numberMatched": True})
    assert total is None

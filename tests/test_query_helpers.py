from __future__ import annotations

from honua_sdk._query import ogc_pagination_signals, odata_pagination_signals


def test_pagination_signals_accept_integral_float_totals() -> None:
    assert ogc_pagination_signals({"numberMatched": 1000.0}) == (1000, False)
    assert ogc_pagination_signals({"numberMatched": "1000.0"}) == (1000, False)
    assert odata_pagination_signals({"@odata.count": 42.0}) == (42, False)


def test_pagination_signals_reject_bool_and_fractional_totals() -> None:
    assert ogc_pagination_signals({"numberMatched": True}) == (None, False)
    assert ogc_pagination_signals({"numberMatched": 10.5}) == (None, False)
    assert odata_pagination_signals({"@odata.count": "10.5"}) == (None, False)

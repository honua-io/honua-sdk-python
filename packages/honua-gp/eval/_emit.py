"""Response-value emitter for eval scripts.

The golden harness verifies two independent things:

* The **request** honua_gp projects onto the server (process id + typed
  inputs). That fingerprint is captured from the audit JSONL stream and is
  deterministic across the stub transport and a live server, so it is diffed
  in both modes (see ``run_eval.py``).
* The **response** honua_gp parses back from the server. The stub transport
  only returns a canned ``href``, so a response value diff is meaningful
  *only* against a live, seeded honua-server. Scripts that read a computed
  result (buffered geometry, a row count, cursor rows) call
  :func:`emit_response` here to record what ``honua_gp`` actually parsed;
  ``run_eval.py`` diffs that sidecar against the golden ``response`` block
  when running in live mode.

The emitter is a no-op unless ``HONUA_GP_EVAL_RESULT_DIR`` is set (the harness
sets it), so the scripts stay runnable by hand and in stub CI without writing
stray files.

This is NOT an ArcGIS Pro parity check: the response fingerprint is pinned to
the honua-server client-compat seed, not to a licensed arcpy baseline. It
verifies that ``honua_gp`` round-trips correctly against the real Honua
server; arcpy-level output parity remains license-gated and out of scope here.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping


_RESULT_DIR_ENV = "HONUA_GP_EVAL_RESULT_DIR"


def _result_dir() -> Path | None:
    raw = os.environ.get(_RESULT_DIR_ENV)
    if not raw:
        return None
    return Path(raw)


def emit_response(name: str, response: Mapping[str, Any]) -> None:
    """Write ``{HONUA_GP_EVAL_RESULT_DIR}/{name}.json`` when capture is enabled.

    ``response`` is a normalized, seed-stable fingerprint (geometry type,
    feature/row counts, output keys) -- never the raw floating-point geometry,
    which would be brittle across server versions.
    """

    target_dir = _result_dir()
    if target_dir is None:
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{name}.json").write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _decode_feature_layer_href(href: str) -> Mapping[str, Any] | None:
    """Decode a ``data:application/geo+json;base64,...`` FeatureLayer href."""

    marker = "base64,"
    if not isinstance(href, str) or marker not in href:
        return None
    payload = href.split(marker, 1)[1]
    try:
        decoded = base64.b64decode(payload)
        parsed = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def feature_layer_fingerprint(result: Any) -> dict[str, Any]:
    """Normalize a process ``Result`` into a seed-stable response fingerprint.

    Extracts the sorted output keys, and -- when the primary output is a
    GeoJSON FeatureLayer -- the geometry type and feature count that the
    server actually computed and ``honua_gp`` parsed back. Absent / unreadable
    geometry degrades gracefully to ``None`` so the harness still diffs the
    structural keys.
    """

    outputs = getattr(result, "outputs", None)
    if not isinstance(outputs, Mapping):
        return {"output_keys": [], "geometry_type": None, "feature_count": None}

    fingerprint: dict[str, Any] = {
        "output_keys": sorted(str(key) for key in outputs),
        "geometry_type": None,
        "feature_count": None,
    }

    # The layer-aware analysis/management processes return a single
    # ``outputFeatureLayer`` (or similarly named) FeatureLayer artifact.
    for value in outputs.values():
        if not isinstance(value, Mapping):
            continue
        href = value.get("href")
        geojson = _decode_feature_layer_href(href) if isinstance(href, str) else None
        if geojson is None:
            continue
        features = geojson.get("features")
        if isinstance(features, list):
            fingerprint["feature_count"] = len(features)
            if features and isinstance(features[0], Mapping):
                geometry = features[0].get("geometry")
                if isinstance(geometry, Mapping):
                    fingerprint["geometry_type"] = geometry.get("type")
        break

    return fingerprint


__all__ = ["emit_response", "feature_layer_fingerprint"]

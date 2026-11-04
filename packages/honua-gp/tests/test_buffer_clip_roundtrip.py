"""End-to-end exercise of the example script against the stub transport.

This proves the AC line item: "At least one end-to-end script demo in
``examples/`` showing arcpy -> honua_gp parity."

Audit pass 8 caught the original Buffer / Clip demo emitting a payload
that did not match honua-server's contract; the example now focuses on
the source-backed surface (MakeFeatureLayer / GetCount / UpdateCursor)
that *is* supported end-to-end today. The test below pins that
behavior via the stub Honua client used by the eval suite.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import honua_gp


def _load_example() -> object:
    """Import the example module without putting it on sys.path."""

    example_path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "buffer_clip_roundtrip.py"
    )
    spec = importlib.util.spec_from_file_location("buffer_clip_roundtrip", example_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_uses_only_supported_shim_surface(
    monkeypatch, stub_clients, _isolated_audit_dir: Path,
) -> None:
    """The example script must run end-to-end against the stub transport.

    No process-backed shim is invoked -- the demo deliberately uses only
    MakeFeatureLayer / GetCount / UpdateCursor, all of which are mapped
    against the source facade today.
    """

    monkeypatch.setenv("HONUA_BASE_URL", "http://example.test")
    module = _load_example()
    assert module.main() == 0

    # The session should now hold a layer alias from MakeFeatureLayer.
    alias = honua_gp.get_session().get_layer("roads_lyr")
    assert alias is not None
    assert alias.where == "STATUS = 'OPEN'"

"""Tests for server-attested toolbox translation reports (honua-sdk-python#188).

The contract under test is narrow but load-bearing: a migration report must say
whether its verdict came from the server's canonical process catalog or only
from the SDK's local view of it, and a local fallback must never be dressed up
as attested. These tests pin all four paths the issue calls out -- attested
success, server-vs-local disagreement, an unreachable server, and a failed
(unauthorized) call -- plus the offline default.
"""

from __future__ import annotations

import pytest

from honua_sdk.migration import (
    AGREEMENT_AGREED,
    AGREEMENT_DISAGREED,
    AGREEMENT_NOT_ATTESTED,
    CLASSIFICATION_PARTIALLY_TRANSLATED,
    CLASSIFICATION_TRANSLATED,
    CLASSIFICATION_UNSUPPORTED,
    LOCAL_ONLY,
    MAX_MANIFEST_TOOLS,
    SERVER_ATTESTED,
    SOURCE_FORMAT_ATBX,
    SOURCE_FORMAT_PYT,
    SOURCE_FORMAT_TBX,
    ModelBuilderToolbox,
    TranslationManifest,
    TranslationToolProposal,
    attest_translation,
    build_atbx_translation_manifest,
    build_pyt_translation_manifest,
    parse_pyt_source,
    resolve_argument_bindings,
    scan_arcpy_source,
    source_format_for_path,
)

# Buffer -> translatable (geometry.buffer); Erase -> manual-review (the server
# cannot job-execute it); Kriging -> unsupported (no registered mapping).
PYT_SOURCE = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "Roads Toolbox"
        self.alias = "roads"
        self.tools = [BufferRoads, EraseRivers, InterpolateStations, EmptyTool]


class BufferRoads(object):
    def __init__(self):
        self.label = "Buffer Roads"

    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters")


class EraseRivers(object):
    def __init__(self):
        self.label = "Erase Rivers"

    def execute(self, parameters, messages):
        arcpy.analysis.Erase("a", "b", "c")


class InterpolateStations(object):
    def __init__(self):
        self.label = "Interpolate"

    def execute(self, parameters, messages):
        arcpy.sa.Kriging("stations", "PredZ")


class EmptyTool(object):
    def __init__(self):
        self.label = "Empty"

    def execute(self, parameters, messages):
        return None
'''


def _manifest() -> TranslationManifest:
    toolbox = parse_pyt_source(PYT_SOURCE, filename="/home/operator/private/roads.pyt")
    return build_pyt_translation_manifest(toolbox)


def _server_report(manifest: TranslationManifest, **classifications: str) -> dict[str, object]:
    """A server report classifying every submitted tool.

    Anything not named in ``classifications`` echoes the local verdict back, so a
    test only has to spell out the tools it wants the server to disagree about.
    """

    return {
        "artifactKind": "honua.migration.toolbox-translation-report",
        "artifactVersion": "1.0",
        "toolboxName": manifest.toolbox_name,
        "sourceFormat": manifest.source_format,
        "summary": {},
        "tools": [
            {
                "toolName": tool.tool_name,
                "classification": classifications.get(tool.tool_name, tool.local_classification),
                "processId": tool.target_process_id,
                "parameterBindings": [],
                "issues": [],
            }
            for tool in manifest.tools
        ],
    }


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def test_build_pyt_manifest_declares_the_server_artifact_identity() -> None:
    payload = _manifest().to_dict()

    assert payload["artifactKind"] == "honua.migration.toolbox-translation"
    assert payload["artifactVersion"] == "1.0"
    assert payload["sourceFormat"] == SOURCE_FORMAT_PYT
    assert payload["toolboxName"] == "Roads Toolbox"


def test_build_pyt_manifest_redacts_the_local_directory_from_the_source_label() -> None:
    payload = _manifest().to_dict()

    # The server echoes sourceLabel into operator-visible output, so only the
    # basename travels -- never the operator's directory layout.
    assert payload["sourceLabel"] == "roads.pyt"
    assert "/home/operator" not in str(payload)


def test_build_pyt_manifest_classifies_each_tool_locally() -> None:
    local = {tool.tool_name: tool.local_classification for tool in _manifest().tools}

    assert local["BufferRoads"] == CLASSIFICATION_TRANSLATED
    # Registered but not job-executable is not runnable, so it is unsupported.
    assert local["EraseRivers"] == CLASSIFICATION_UNSUPPORTED
    assert local["InterpolateStations"] == CLASSIFICATION_UNSUPPORTED
    # A tool with no recognized GP call still appears, rather than vanishing
    # from the tool count.
    assert local["EmptyTool"] == CLASSIFICATION_UNSUPPORTED


def test_build_pyt_manifest_proposes_a_native_target_and_parameter_mappings() -> None:
    buffer_tool = next(tool for tool in _manifest().tools if tool.tool_name == "BufferRoads")

    assert buffer_tool.target_process_id == "geometry.buffer"
    mappings = {mapping.source_name: mapping.target_parameter for mapping in buffer_tool.parameter_mappings}
    assert mappings["in_features"] == "input_features"
    assert mappings["buffer_distance_or_field"] == "distance"
    # Output destinations are not canonical process inputs, so they are not
    # proposed as parameter mappings.
    assert "out_feature_class" not in mappings


def test_build_pyt_manifest_reports_an_unmapped_keyword_as_an_unsupported_construct() -> None:
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.tools = [T]


class T(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("roads", "out", "25 Meters", not_a_real_arg=1)
'''
    manifest = build_pyt_translation_manifest(parse_pyt_source(source, filename="t.pyt"))
    tool = manifest.tools[0]

    assert any("not_a_real_arg" in construct for construct in tool.unsupported_constructs)
    # A translatable call carrying an unmapped construct is partial, not clean.
    assert tool.local_classification == CLASSIFICATION_PARTIALLY_TRANSLATED


def test_build_pyt_manifest_splits_a_multi_step_tool_into_unique_names() -> None:
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.tools = [T]


class T(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("roads", "out", "25 Meters")
        arcpy.analysis.Clip("out", "aoi", "clipped")
'''
    manifest = build_pyt_translation_manifest(parse_pyt_source(source, filename="t.pyt"))

    # The endpoint certifies one native process per manifest tool, and rejects a
    # duplicate toolName outright, so steps get distinct names.
    names = [tool.tool_name for tool in manifest.tools]
    assert names == ["T#1", "T#2"]
    assert len(set(names)) == len(names)


def test_resolve_argument_bindings_returns_nothing_for_an_unmapped_call() -> None:
    call = scan_arcpy_source("import arcpy\narcpy.sa.Kriging('a', 'b')\n").calls[0]

    assert resolve_argument_bindings(call) == ()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("toolbox.pyt", SOURCE_FORMAT_PYT),
        ("Toolbox.ATBX", SOURCE_FORMAT_ATBX),
        ("legacy.tbx", SOURCE_FORMAT_TBX),
        ("workflow.py", None),
        ("service.json", None),
    ],
)
def test_source_format_for_path(path: str, expected: str | None) -> None:
    assert source_format_for_path(path) == expected


def test_manifest_batches_respect_the_server_tool_cap() -> None:
    tools = tuple(
        TranslationToolProposal(tool_name=f"T{index}", local_classification=CLASSIFICATION_UNSUPPORTED)
        for index in range(MAX_MANIFEST_TOOLS + 5)
    )
    manifest = TranslationManifest(toolbox_name="Big", source_format=SOURCE_FORMAT_PYT, tools=tools)

    batches = manifest.batches()

    assert [len(batch.tools) for batch in batches] == [MAX_MANIFEST_TOOLS, 5]
    assert [tool.tool_name for batch in batches for tool in batch.tools] == [t.tool_name for t in tools]


def test_manifest_batches_rejects_a_non_positive_size() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        _manifest().batches(0)


# ---------------------------------------------------------------------------
# Attested success
# ---------------------------------------------------------------------------


def test_attest_translation_marks_a_server_verdict_as_attested() -> None:
    manifest = _manifest()
    submitted: list[TranslationManifest] = []

    def validator(batch: TranslationManifest) -> dict[str, object]:
        submitted.append(batch)
        return _server_report(batch)

    report = attest_translation(manifest, validator=validator, server="https://honua.test")

    assert report.attested is True
    assert report.verdict_source == SERVER_ATTESTED
    assert report.fallback_reason is None
    assert report.server == "https://honua.test"
    assert [tool.tool_name for tool in submitted[0].tools] == [t.tool_name for t in manifest.tools]
    assert all(verdict.agreement == AGREEMENT_AGREED for verdict in report.tools)

    document = report.to_dict()
    assert document["verdictSource"] == SERVER_ATTESTED
    assert document["attested"] is True
    assert document["summary"]["toolCount"] == len(manifest.tools)
    assert document["summary"]["disagreementCount"] == 0


def test_attest_translation_carries_the_server_bindings_and_issues() -> None:
    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        payload = _server_report(batch)
        tools = payload["tools"]
        assert isinstance(tools, list)
        tools[0]["parameterBindings"] = [
            {"sourceName": "in_features", "targetParameter": "wkb", "valueType": "Wkb", "required": True}
        ]
        tools[0]["issues"] = [{"code": "missing-required-parameter", "message": "srid is not mapped."}]
        tools[0]["processId"] = "geometry.buffer"
        return payload

    verdict = attest_translation(manifest, validator=validator).tools[0]

    assert verdict.process_id == "geometry.buffer"
    assert verdict.parameter_bindings[0]["valueType"] == "Wkb"
    assert verdict.issues[0]["code"] == "missing-required-parameter"


def test_attest_translation_submits_every_batch_of_a_large_toolbox() -> None:
    tools = tuple(
        TranslationToolProposal(tool_name=f"T{index}", local_classification=CLASSIFICATION_UNSUPPORTED)
        for index in range(MAX_MANIFEST_TOOLS + 3)
    )
    manifest = TranslationManifest(toolbox_name="Big", source_format=SOURCE_FORMAT_PYT, tools=tools)
    calls = 0

    def validator(batch: TranslationManifest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _server_report(batch)

    report = attest_translation(manifest, validator=validator)

    assert calls == 2
    assert report.attested is True
    assert len(report.tools) == len(tools)


# ---------------------------------------------------------------------------
# Disagreement: the server wins, and the disagreement is surfaced
# ---------------------------------------------------------------------------


def test_server_verdict_overrides_the_local_one_and_the_disagreement_is_surfaced() -> None:
    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        # The SDK called this one translated; the canonical catalog does not.
        return _server_report(batch, BufferRoads=CLASSIFICATION_UNSUPPORTED)

    report = attest_translation(manifest, validator=validator)
    buffer_verdict = next(verdict for verdict in report.tools if verdict.tool_name == "BufferRoads")

    assert buffer_verdict.classification == CLASSIFICATION_UNSUPPORTED
    assert buffer_verdict.server_classification == CLASSIFICATION_UNSUPPORTED
    # The local verdict is retained beside the server's, not overwritten, so the
    # drift is auditable rather than invisible.
    assert buffer_verdict.local_classification == CLASSIFICATION_TRANSLATED
    assert buffer_verdict.agreement == AGREEMENT_DISAGREED
    assert buffer_verdict.disagreed is True

    assert [verdict.tool_name for verdict in report.disagreements] == ["BufferRoads"]
    document = report.to_dict()
    assert document["summary"]["disagreementCount"] == 1
    assert document["disagreements"] == [
        {"toolName": "BufferRoads", "local": CLASSIFICATION_TRANSLATED, "server": CLASSIFICATION_UNSUPPORTED}
    ]


def test_a_server_verdict_more_generous_than_the_local_one_also_wins() -> None:
    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        return _server_report(batch, EraseRivers=CLASSIFICATION_TRANSLATED)

    verdict = next(v for v in attest_translation(manifest, validator=validator).tools if v.tool_name == "EraseRivers")

    assert verdict.classification == CLASSIFICATION_TRANSLATED
    assert verdict.local_classification == CLASSIFICATION_UNSUPPORTED
    assert verdict.disagreed is True


# ---------------------------------------------------------------------------
# Offline / degraded paths: never presented as attested
# ---------------------------------------------------------------------------


def test_no_validator_produces_a_local_only_report_with_a_stated_reason() -> None:
    report = attest_translation(_manifest())

    assert report.attested is False
    assert report.verdict_source == LOCAL_ONLY
    assert report.fallback_reason is not None
    assert "has not been attested" in report.fallback_reason
    # The offline report is still complete and usable, just not attested.
    assert len(report.tools) == len(_manifest().tools)
    assert all(verdict.agreement == AGREEMENT_NOT_ATTESTED for verdict in report.tools)
    assert all(verdict.server_classification is None for verdict in report.tools)

    document = report.to_dict()
    assert document["attested"] is False
    assert document["verdictSource"] == LOCAL_ONLY


def test_an_unreachable_server_degrades_to_local_only_rather_than_failing() -> None:
    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        raise ConnectionError("All connection attempts failed")

    report = attest_translation(manifest, validator=validator, server="https://offline.test")

    assert report.attested is False
    assert report.verdict_source == LOCAL_ONLY
    assert report.fallback_reason == "ConnectionError: All connection attempts failed"
    # The local verdicts survive, so the run still produces a migration report.
    assert {verdict.tool_name for verdict in report.tools} == {tool.tool_name for tool in manifest.tools}
    assert next(v for v in report.tools if v.tool_name == "BufferRoads").classification == CLASSIFICATION_TRANSLATED


def test_an_unauthorized_call_is_never_reported_as_attested() -> None:
    class HonuaAuthError(Exception):
        pass

    def validator(batch: TranslationManifest) -> dict[str, object]:
        raise HonuaAuthError("401 Unauthorized")

    report = attest_translation(_manifest(), validator=validator, server="https://honua.test")

    assert report.attested is False
    assert report.verdict_source == LOCAL_ONLY
    assert report.fallback_reason == "HonuaAuthError: 401 Unauthorized"
    assert report.to_dict()["attested"] is False
    assert all(verdict.server_classification is None for verdict in report.tools)


def test_a_failure_with_no_message_still_names_the_failure_type() -> None:
    def validator(batch: TranslationManifest) -> dict[str, object]:
        raise TimeoutError

    report = attest_translation(_manifest(), validator=validator)

    assert report.fallback_reason == "TimeoutError"


_VALID_IDENTITY = {
    "artifactKind": "honua.migration.toolbox-translation-report",
    "artifactVersion": "1.0",
}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param([], "list where a translation report object", id="not-an-object"),
        pytest.param(
            {"artifactKind": "honua.migration.source-inventory", "artifactVersion": "1.0", "tools": []},
            "artifactKind",
            id="wrong-artifact",
        ),
        pytest.param({**_VALID_IDENTITY, "summary": {}}, "no 'tools' array", id="no-tools"),
        pytest.param({**_VALID_IDENTITY, "tools": ["nope"]}, "non-object tool entry", id="non-object-entry"),
        pytest.param(
            {**_VALID_IDENTITY, "tools": [{"toolName": "BufferRoads"}]},
            "toolName/classification",
            id="no-classification",
        ),
    ],
)
def test_a_malformed_server_report_degrades_to_local_only(payload: object, expected: str) -> None:
    report = attest_translation(_manifest(), validator=lambda batch: payload)  # type: ignore[arg-type,return-value]

    assert report.attested is False
    assert report.fallback_reason is not None
    assert expected in report.fallback_reason


def test_a_report_missing_a_submitted_tool_is_not_attested() -> None:
    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        payload = _server_report(batch)
        tools = payload["tools"]
        assert isinstance(tools, list)
        # A partially-classified response cannot back a whole-toolbox claim.
        return {**payload, "tools": tools[:1]}

    report = attest_translation(manifest, validator=validator)

    assert report.attested is False
    assert report.fallback_reason is not None
    assert "did not classify every submitted tool" in report.fallback_reason


def test_a_report_classifying_an_unsubmitted_tool_is_not_attested() -> None:
    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        payload = _server_report(batch)
        tools = payload["tools"]
        assert isinstance(tools, list)
        tools.append({"toolName": "NeverSubmitted", "classification": CLASSIFICATION_TRANSLATED})
        return payload

    report = attest_translation(manifest, validator=validator)

    assert report.attested is False
    assert report.fallback_reason is not None
    assert "which was not submitted" in report.fallback_reason


def test_a_batch_failing_after_a_successful_one_degrades_the_whole_report() -> None:
    tools = tuple(
        TranslationToolProposal(tool_name=f"T{index}", local_classification=CLASSIFICATION_UNSUPPORTED)
        for index in range(MAX_MANIFEST_TOOLS + 1)
    )
    manifest = TranslationManifest(toolbox_name="Big", source_format=SOURCE_FORMAT_PYT, tools=tools)
    calls = 0

    def validator(batch: TranslationManifest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _server_report(batch)
        raise ConnectionError("dropped mid-toolbox")

    report = attest_translation(manifest, validator=validator)

    # There is no partial attestation: one failed batch un-attests the toolbox.
    assert report.attested is False
    assert report.verdict_source == LOCAL_ONLY
    assert all(verdict.agreement == AGREEMENT_NOT_ATTESTED for verdict in report.tools)


# ---------------------------------------------------------------------------
# Review regressions (honua-sdk-python#188): three ways a report could have
# claimed `attested: true` while not actually being fully attested.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            {"artifactVersion": "1.0", "toolboxName": "T", "sourceFormat": "pyt", "tools": []},
            "artifactKind None",
            id="missing-artifact-kind",
        ),
        pytest.param(
            {
                "artifactKind": "honua.migration.toolbox-translation-report",
                "toolboxName": "T",
                "sourceFormat": "pyt",
                "tools": [],
            },
            "artifactVersion None",
            id="missing-artifact-version",
        ),
        pytest.param(
            {**_VALID_IDENTITY, "artifactVersion": "2.0", "tools": []},
            "artifactVersion '2.0'",
            id="unreadable-artifact-version",
        ),
    ],
)
def test_a_report_without_a_usable_artifact_identity_is_not_attested(payload: dict, expected: str) -> None:
    """A 200 that does not identify itself as a v1 report cannot back attestation.

    The genuine endpoint always stamps both identity fields. Treating them as
    optional -- or letting the response model default them in -- would make an
    error envelope, a proxy page, or a different API's payload indistinguishable
    from a real report.
    """

    report = attest_translation(_manifest(), validator=lambda batch: payload)

    assert report.attested is False
    assert report.verdict_source == LOCAL_ONLY
    assert report.fallback_reason is not None
    assert expected in report.fallback_reason
    assert all(verdict.server_classification is None for verdict in report.tools)


def test_an_admin_report_missing_its_identity_is_not_attested_end_to_end() -> None:
    """The admin response model must not paper over a missing identity.

    This is the real CLI path: the admin client parses the response into
    ``ToolboxTranslationReport`` and hands ``to_dict()`` to the attestation
    layer. If the model defaulted the identity fields, that layer would receive
    a perfectly-formed v1 report and mark a malformed response attested.
    """

    from honua_admin import ToolboxTranslationReport

    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        # A 200 body with no artifactKind/artifactVersion at all.
        body = {
            "toolboxName": batch.toolbox_name,
            "sourceFormat": batch.source_format,
            "summary": {},
            "tools": [
                {"toolName": tool.tool_name, "classification": CLASSIFICATION_TRANSLATED}
                for tool in batch.tools
            ],
        }
        return ToolboxTranslationReport.from_dict(body).to_dict()

    report = attest_translation(manifest, validator=validator, server="https://honua.test")

    assert report.attested is False
    assert report.verdict_source == LOCAL_ONLY
    assert "artifactKind" in str(report.fallback_reason)


@pytest.mark.parametrize("classification", ["manual-review", "translated-v2", "TRANSLATED", ""])
def test_a_classification_outside_the_vocabulary_is_not_attested(classification: str) -> None:
    """An unknown classification would produce an attestation that does not add up.

    The summary counts tools by exactly the three declared values, so a fourth
    value would appear as a tool's effective classification while no counter
    included it. Refuse the report instead of emitting an inconsistent one.
    """

    manifest = _manifest()

    def validator(batch: TranslationManifest) -> dict[str, object]:
        payload = _server_report(batch)
        tools = payload["tools"]
        assert isinstance(tools, list)
        tools[0]["classification"] = classification
        return payload

    report = attest_translation(manifest, validator=validator, server="https://honua.test")

    assert report.attested is False
    assert report.verdict_source == LOCAL_ONLY
    assert report.fallback_reason is not None
    assert "outside this report format's vocabulary" in report.fallback_reason
    # Nothing from the refused response leaks into the local-only report.
    assert all(verdict.server_classification is None for verdict in report.tools)
    assert all(verdict.agreement == AGREEMENT_NOT_ATTESTED for verdict in report.tools)


def test_an_attested_report_summary_accounts_for_every_tool() -> None:
    """The invariant the vocabulary check exists to protect."""

    manifest = _manifest()
    report = attest_translation(manifest, validator=lambda batch: _server_report(batch))
    summary = report.to_dict()["summary"]

    assert report.attested is True
    counted = (
        summary["translatedCount"] + summary["partiallyTranslatedCount"] + summary["unsupportedCount"]
    )
    assert counted == summary["toolCount"] == len(manifest.tools)


def test_atbx_manifest_includes_script_tools_alongside_models() -> None:
    """Script tools must be submitted, not silently omitted.

    ``parse_atbx_toolbox`` records a script tool by name only (its logic lives
    in an external .py the reader does not follow). Building the manifest from
    ``models`` alone let the server return a clean report for a strict subset of
    the toolbox, which the CLI then presented as a whole-toolbox attestation
    (honua-sdk-python#188 review).
    """

    toolbox = ModelBuilderToolbox(
        filename="/home/operator/private/wf.atbx",
        models=(),
        script_tool_names=("LegacyScriptTool", "AnotherScript"),
    )

    manifest = build_atbx_translation_manifest(toolbox)

    assert [tool.tool_name for tool in manifest.tools] == ["LegacyScriptTool", "AnotherScript"]
    for tool in manifest.tools:
        # No native target may be proposed: the translator never read the body.
        assert tool.target_process_id is None
        assert tool.local_classification == CLASSIFICATION_UNSUPPORTED
        assert any("script tool" in construct for construct in tool.unsupported_constructs)
        assert any("arcpy .py scanner" in construct for construct in tool.unsupported_constructs)


def test_atbx_attestation_covers_every_discovered_tool(tmp_path) -> None:
    """End-to-end: an .atbx holding both a model and a script tool."""

    import io
    import json as _json
    import zipfile

    from honua_sdk.migration import parse_atbx_toolbox

    model = {
        "name": "BufferModel",
        "processes": [
            {
                "toolName": "Buffer",
                "toolbox": "analysis",
                "parameters": {
                    "in_features": "a",
                    "out_feature_class": "b",
                    "buffer_distance_or_field": "5 Meters",
                },
            }
        ],
    }
    script_tool = {"name": "LegacyScriptTool", "type": "script", "script": "legacy.py"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BufferModel.tool/tool.content", _json.dumps(model))
        archive.writestr("LegacyScriptTool.tool/tool.content", _json.dumps(script_tool))
    path = tmp_path / "wf.atbx"
    path.write_bytes(buffer.getvalue())

    toolbox = parse_atbx_toolbox(path)
    assert toolbox.models, "fixture should parse one model"
    assert toolbox.script_tool_names == ("LegacyScriptTool",), "fixture should record one script tool"

    manifest = build_atbx_translation_manifest(toolbox)
    submitted = [tool.tool_name for tool in manifest.tools]
    assert "BufferModel" in submitted
    assert "LegacyScriptTool" in submitted

    report = attest_translation(manifest, validator=lambda batch: _server_report(batch))

    assert report.attested is True
    # The attestation covers the whole toolbox, not just its models.
    assert {verdict.tool_name for verdict in report.tools} == {"BufferModel", "LegacyScriptTool"}
    assert report.to_dict()["summary"]["toolCount"] == 2


def test_pyt_manifest_includes_declared_tools_whose_class_is_not_in_the_file() -> None:
    """A declared-but-unmaterialised tool must be submitted, not silently omitted.

    ``self.tools = [Present, ImportedTool]`` keeps both names in
    ``declared_tool_names``, but only classes defined in the same file become
    ``toolbox.tools`` -- there is no ``execute`` body to read for an imported
    one. Building the manifest from ``toolbox.tools`` alone let the server
    return a clean report covering only ``Present`` while the CLI presented it
    as whole-toolbox attestation (honua-sdk-python#188 review).
    """

    source = '''
import arcpy
from other_module import ImportedTool


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.tools = [Present, ImportedTool]


class Present(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    toolbox = parse_pyt_source(source, filename="t.pyt")
    # Precondition: the reader really does drop the imported name.
    assert toolbox.declared_tool_names == ("Present", "ImportedTool")
    assert [tool.class_name for tool in toolbox.tools] == ["Present"]

    manifest = build_pyt_translation_manifest(toolbox)

    assert [tool.tool_name for tool in manifest.tools] == ["Present", "ImportedTool"]
    imported = manifest.tools[1]
    # Nothing was read, so nothing may be proposed.
    assert imported.target_process_id is None
    assert imported.local_classification == CLASSIFICATION_UNSUPPORTED
    assert any("not defined in this .pyt" in c for c in imported.unsupported_constructs)
    assert any("arcpy .py scanner" in c for c in imported.unsupported_constructs)


def test_pyt_attestation_covers_declared_tools_the_reader_could_not_materialise() -> None:
    """End-to-end: attestation must not certify a strict subset of the toolbox."""

    source = '''
import arcpy
from vendor.tools import VendorTool


class Toolbox(object):
    def __init__(self):
        self.label = "Mixed"
        self.tools = [Local, VendorTool]


class Local(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    manifest = build_pyt_translation_manifest(parse_pyt_source(source, filename="mixed.pyt"))
    submitted = [tool.tool_name for tool in manifest.tools]
    assert submitted == ["Local", "VendorTool"]

    report = attest_translation(manifest, validator=lambda batch: _server_report(batch))

    assert report.attested is True
    assert {verdict.tool_name for verdict in report.tools} == {"Local", "VendorTool"}
    summary = report.to_dict()["summary"]
    assert summary["toolCount"] == 2
    assert (
        summary["translatedCount"] + summary["partiallyTranslatedCount"] + summary["unsupportedCount"]
        == 2
    )


def test_a_pyt_toolbox_whose_tools_are_all_imported_still_submits_them() -> None:
    """The degenerate case: nothing materialises, so nothing would be submitted.

    Before the fix this produced an empty manifest, which the endpoint rejects
    ("tools is required") -- turning a real coverage gap into an unexplained
    attestation failure instead of an honest unsupported report.
    """

    source = '''
from vendor.tools import AlphaTool, BetaTool


class Toolbox(object):
    def __init__(self):
        self.label = "All imported"
        self.tools = [AlphaTool, BetaTool]
'''
    manifest = build_pyt_translation_manifest(parse_pyt_source(source, filename="vendor.pyt"))

    assert [tool.tool_name for tool in manifest.tools] == ["AlphaTool", "BetaTool"]
    assert all(tool.target_process_id is None for tool in manifest.tools)
    assert all(tool.local_classification == CLASSIFICATION_UNSUPPORTED for tool in manifest.tools)


def _atbx_with(tmp_path, entries: dict) -> object:
    import io
    import json as _json
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, _json.dumps(payload))
    path = tmp_path / "wf.atbx"
    path.write_bytes(buffer.getvalue())
    return path


def test_atbx_manifest_includes_models_that_yielded_no_steps(tmp_path) -> None:
    """A declared model with no recognizable step must still be submitted.

    ``parse_atbx_toolbox`` deliberately keeps a stepless model out of ``models``
    -- there is nothing to translate -- but the name is still a tool the toolbox
    declares. Dropping it entirely let the manifest under-count the toolbox and
    certify coverage it did not have (honua-sdk-python#188 review follow-up).
    """

    from honua_sdk.migration import parse_atbx_toolbox

    path = _atbx_with(
        tmp_path,
        {
            "BufferModel.tool/tool.content": {
                "name": "BufferModel",
                "processes": [
                    {
                        "toolName": "Buffer",
                        "toolbox": "analysis",
                        "parameters": {
                            "in_features": "a",
                            "out_feature_class": "b",
                            "buffer_distance_or_field": "5 Meters",
                        },
                    }
                ],
            },
            "EmptyModel.tool/tool.content": {"type": "ModelTool", "processes": []},
        },
    )

    toolbox = parse_atbx_toolbox(path)
    # The reader's existing contract is unchanged: a stepless model is not a model.
    assert [model.name for model in toolbox.models] == ["BufferModel"]
    # ...but it is now discoverable rather than lost.
    assert toolbox.unresolved_tool_names == ("EmptyModel",)
    assert toolbox.to_dict()["unresolvedToolNames"] == ["EmptyModel"]

    manifest = build_atbx_translation_manifest(toolbox)

    assert [tool.tool_name for tool in manifest.tools] == ["BufferModel", "EmptyModel"]
    empty = manifest.tools[1]
    assert empty.target_process_id is None
    assert empty.local_classification == CLASSIFICATION_UNSUPPORTED
    assert any("no recognizable" in construct for construct in empty.unsupported_constructs)

    report = attest_translation(manifest, validator=lambda batch: _server_report(batch))

    assert report.attested is True
    assert {verdict.tool_name for verdict in report.tools} == {"BufferModel", "EmptyModel"}
    assert report.to_dict()["summary"]["toolCount"] == 2


def test_atbx_manifest_covers_models_script_tools_and_unresolved_together(tmp_path) -> None:
    """All three .atbx tool kinds land in one manifest."""

    from honua_sdk.migration import parse_atbx_toolbox

    path = _atbx_with(
        tmp_path,
        {
            "BufferModel.tool/tool.content": {
                "name": "BufferModel",
                "processes": [
                    {
                        "toolName": "Buffer",
                        "toolbox": "analysis",
                        "parameters": {
                            "in_features": "a",
                            "out_feature_class": "b",
                            "buffer_distance_or_field": "5 Meters",
                        },
                    }
                ],
            },
            "LegacyScriptTool.tool/tool.content": {
                "name": "LegacyScriptTool",
                "type": "script",
                "script": "legacy.py",
            },
            "EmptyModel.tool/tool.content": {"type": "ModelTool", "processes": []},
        },
    )

    toolbox = parse_atbx_toolbox(path)
    manifest = build_atbx_translation_manifest(toolbox)
    submitted = {tool.tool_name for tool in manifest.tools}

    assert submitted == {"BufferModel", "LegacyScriptTool", "EmptyModel"}

    report = attest_translation(manifest, validator=lambda batch: _server_report(batch))
    summary = report.to_dict()["summary"]

    assert report.attested is True
    assert summary["toolCount"] == 3
    assert (
        summary["translatedCount"] + summary["partiallyTranslatedCount"] + summary["unsupportedCount"]
        == 3
    )

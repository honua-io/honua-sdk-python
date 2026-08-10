"""Server-attested toolbox translation reports.

The migration codemod can classify an ArcGIS toolbox tool on its own, from the
SDK's built-in view of which Honua processes exist and what they accept. That
local view can drift from the server that would actually run the job: the SDK
can call a tool translated when the server's submit validator would reject it,
or flag one unsupported when the server would accept it. A migration report is
used to decide whether a migration is viable, so a locally-derived verdict that
has silently drifted is worse than no verdict.

This module closes that gap. It builds the manifest the server's
``POST /api/v1/admin/import/toolbox/translation/validate`` endpoint expects,
submits it through a caller-supplied validator, and merges the server's per-tool
classification over the local one. Two rules govern the result:

* **The server wins.** Where the two verdicts disagree, the server's stands and
  the disagreement is reported rather than quietly overwritten -- a disagreement
  is the signal that the SDK's catalog view has drifted.
* **A local verdict is never dressed up as attested.** Offline operation still
  works, but the report is stamped ``local-only`` with an explicit reason. Any
  failure -- unreachable server, refused credentials, a malformed or incomplete
  response -- degrades the *whole* report to ``local-only``. There is no partial
  attestation.

The validator is injected rather than constructed here so this module stays
pure, offline, and free of a dependency on the admin client. The
``honua-migrate`` CLI supplies one backed by
:meth:`honua_admin.HonuaAdminClient.validate_toolbox_translation`, which is the
existing admin credential path -- the endpoint lives in the admin import group.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .arcpy import ArcPyCall, JsonObject, resolve_argument_bindings
from .modelbuilder import ModelBuilderToolbox
from .pyt import PytToolbox

#: Verdict source for a report whose classifications came from the server's
#: canonical process catalog.
SERVER_ATTESTED = "server-attested"

#: Verdict source for a report that carries only the SDK's local classification.
#: A ``local-only`` report is a useful offline artifact; it is not attestation.
LOCAL_ONLY = "local-only"

#: Per-tool classifications, matching the server's vocabulary exactly.
CLASSIFICATION_TRANSLATED = "translated"
CLASSIFICATION_PARTIALLY_TRANSLATED = "partially-translated"
CLASSIFICATION_UNSUPPORTED = "unsupported"

#: The complete classification vocabulary this report format understands.
#:
#: The summary counts tools by exactly these three values, so a fourth value --
#: from a newer server, a rewriting proxy, or a malformed response -- would
#: appear as a tool's effective classification while no counter included it.
#: That is an internally inconsistent artifact, so an unrecognized
#: classification degrades the report to ``local-only`` instead of being
#: attested. Widening the vocabulary is a deliberate change here, not something
#: a response gets to do at runtime.
CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        CLASSIFICATION_TRANSLATED,
        CLASSIFICATION_PARTIALLY_TRANSLATED,
        CLASSIFICATION_UNSUPPORTED,
    }
)

#: Agreement between the local and server verdict for one tool.
AGREEMENT_AGREED = "agreed"
AGREEMENT_DISAGREED = "disagreed"
AGREEMENT_NOT_ATTESTED = "not-attested"

#: Artifact identity the server requires on an inbound manifest. A payload that
#: identifies as anything else is rejected rather than reinterpreted as v1.
MANIFEST_ARTIFACT_KIND = "honua.migration.toolbox-translation"
MANIFEST_ARTIFACT_VERSION = "1.0"

#: Artifact identity the server stamps on the report it returns.
#:
#: This is *required* on an attested response, not optional. The genuine
#: endpoint always emits both fields, so their absence means the payload came
#: from something else -- a proxy, an error envelope, a different API -- and
#: cannot back an attestation claim. Client-side parsing must never fill them
#: in: a locally-manufactured identity would make a malformed response
#: indistinguishable from a real v1 report.
REPORT_ARTIFACT_KIND = "honua.migration.toolbox-translation-report"

#: Report schema versions this client knows how to read.
SUPPORTED_REPORT_VERSIONS: frozenset[str] = frozenset({"1.0"})

#: Schema id for the merged attestation artifact this module emits.
ATTESTATION_SCHEMA = "honua.migration.toolbox-translation-attestation/v1"

#: Source toolbox formats the server accepts.
SOURCE_FORMAT_PYT = "pyt"
SOURCE_FORMAT_ATBX = "atbx"
SOURCE_FORMAT_TBX = "tbx"

#: Tools the server accepts in one manifest. Larger toolboxes are submitted as
#: several manifests and the reports merged, rather than truncated.
MAX_MANIFEST_TOOLS = 200

#: Signature of a validator: a manifest in, the server's report payload out.
#: Raising is the documented way to signal that attestation is unavailable --
#: an unreachable server, refused credentials, or a rejected manifest all
#: surface that way and all degrade the report to ``local-only``.
TranslationValidator = Callable[["TranslationManifest"], JsonObject]

_SUFFIX_SOURCE_FORMATS = {
    ".pyt": SOURCE_FORMAT_PYT,
    ".atbx": SOURCE_FORMAT_ATBX,
    ".tbx": SOURCE_FORMAT_TBX,
}


class TranslationAttestationError(RuntimeError):
    """Raised when a server response cannot be trusted as an attestation.

    Carried as a ``fallbackReason`` rather than propagated: a report that cannot
    be attested degrades to ``local-only`` instead of failing the migration run.
    """


@dataclass(frozen=True)
class TranslationParameterMapping:
    """One proposed source-parameter to canonical-parameter mapping."""

    source_name: str
    target_parameter: str
    source_data_type: str | None = None

    def to_dict(self) -> JsonObject:
        result: JsonObject = {
            "sourceName": self.source_name,
            "targetParameter": self.target_parameter,
        }
        if self.source_data_type is not None:
            result["sourceDataType"] = self.source_data_type
        return result


@dataclass(frozen=True)
class TranslationToolProposal:
    """One toolbox tool the scanner proposes to map onto a native process.

    ``local_classification`` is what the SDK concluded on its own. It is kept
    beside the server's answer rather than replaced by it, so a reader can see
    both and a drifting SDK catalog view is visible instead of invisible.
    """

    tool_name: str
    local_classification: str
    display_name: str | None = None
    target_process_id: str | None = None
    parameter_mappings: tuple[TranslationParameterMapping, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()

    def to_descriptor(self) -> JsonObject:
        """Render the wire descriptor the validation endpoint expects."""

        return {
            "toolName": self.tool_name,
            "displayName": self.display_name,
            "targetProcessId": self.target_process_id,
            "parameterMappings": [mapping.to_dict() for mapping in self.parameter_mappings],
            "unsupportedConstructs": list(self.unsupported_constructs),
        }


@dataclass(frozen=True)
class TranslationManifest:
    """A translated toolbox, ready to submit for server validation."""

    toolbox_name: str
    source_format: str
    tools: tuple[TranslationToolProposal, ...]
    source_label: str | None = None

    def to_dict(self) -> JsonObject:
        """Render the manifest payload for the validation endpoint."""

        result: JsonObject = {
            "artifactKind": MANIFEST_ARTIFACT_KIND,
            "artifactVersion": MANIFEST_ARTIFACT_VERSION,
            "toolboxName": self.toolbox_name,
            "sourceFormat": self.source_format,
        }
        if self.source_label is not None:
            result["sourceLabel"] = self.source_label
        result["tools"] = [tool.to_descriptor() for tool in self.tools]
        return result

    def batches(self, size: int = MAX_MANIFEST_TOOLS) -> tuple["TranslationManifest", ...]:
        """Split into manifests the server will accept, preserving tool order.

        The endpoint caps a manifest at :data:`MAX_MANIFEST_TOOLS` tools. A
        larger toolbox is submitted as several manifests whose reports are then
        merged, so a big toolbox degrades to more requests rather than to a
        rejected manifest and a silent loss of attestation.
        """

        if size < 1:
            raise ValueError("size must be at least 1.")
        if len(self.tools) <= size:
            return (self,)
        return tuple(
            TranslationManifest(
                toolbox_name=self.toolbox_name,
                source_format=self.source_format,
                tools=tuple(self.tools[start : start + size]),
                source_label=self.source_label,
            )
            for start in range(0, len(self.tools), size)
        )


@dataclass(frozen=True)
class AttestedToolVerdict:
    """The merged verdict for one tool.

    ``classification`` is the *effective* verdict: the server's when the report
    is attested, the SDK's local one otherwise. ``local_classification`` and
    ``server_classification`` are both retained so the merge is auditable.
    """

    tool_name: str
    classification: str
    local_classification: str
    agreement: str
    server_classification: str | None = None
    process_id: str | None = None
    parameter_bindings: tuple[JsonObject, ...] = ()
    issues: tuple[JsonObject, ...] = ()

    @property
    def disagreed(self) -> bool:
        """Whether the server contradicted the SDK's local classification."""

        return self.agreement == AGREEMENT_DISAGREED

    def to_dict(self) -> JsonObject:
        return {
            "toolName": self.tool_name,
            "classification": self.classification,
            "localClassification": self.local_classification,
            "serverClassification": self.server_classification,
            "agreement": self.agreement,
            "processId": self.process_id,
            "parameterBindings": [dict(binding) for binding in self.parameter_bindings],
            "issues": [dict(issue) for issue in self.issues],
        }


@dataclass(frozen=True)
class AttestedTranslationReport:
    """A translation report plus an explicit statement of who attested it."""

    manifest: TranslationManifest
    verdict_source: str
    tools: tuple[AttestedToolVerdict, ...]
    fallback_reason: str | None = None
    server: str | None = None

    @property
    def attested(self) -> bool:
        """Whether the classifications came from the server's process catalog."""

        return self.verdict_source == SERVER_ATTESTED

    @property
    def disagreements(self) -> tuple[AttestedToolVerdict, ...]:
        """Tools where the server contradicted the SDK's local verdict."""

        return tuple(verdict for verdict in self.tools if verdict.disagreed)

    def count(self, classification: str) -> int:
        """Number of tools carrying *classification* as their effective verdict."""

        return sum(1 for verdict in self.tools if verdict.classification == classification)

    def to_dict(self) -> JsonObject:
        """Render the attestation artifact."""

        result: JsonObject = {
            "schema": ATTESTATION_SCHEMA,
            "verdictSource": self.verdict_source,
            "attested": self.attested,
            "server": self.server,
            "fallbackReason": self.fallback_reason,
            "toolboxName": self.manifest.toolbox_name,
            "sourceFormat": self.manifest.source_format,
            "sourceLabel": self.manifest.source_label,
            "summary": {
                "toolCount": len(self.tools),
                "translatedCount": self.count(CLASSIFICATION_TRANSLATED),
                "partiallyTranslatedCount": self.count(CLASSIFICATION_PARTIALLY_TRANSLATED),
                "unsupportedCount": self.count(CLASSIFICATION_UNSUPPORTED),
                "disagreementCount": len(self.disagreements),
            },
            "tools": [verdict.to_dict() for verdict in self.tools],
            "disagreements": [
                {
                    "toolName": verdict.tool_name,
                    "local": verdict.local_classification,
                    "server": verdict.server_classification,
                }
                for verdict in self.disagreements
            ],
        }
        return result


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------


def attest_translation(
    manifest: TranslationManifest,
    *,
    validator: TranslationValidator | None = None,
    server: str | None = None,
) -> AttestedTranslationReport:
    """Merge a server validation over a manifest's local classifications.

    Args:
        manifest: The translated toolbox to have validated.
        validator: Callable that submits a manifest and returns the server's
            report payload. ``None`` -- the default -- produces a
            ``local-only`` report without any network access. A validator that
            raises also produces a ``local-only`` report, carrying the failure
            as :attr:`AttestedTranslationReport.fallback_reason`.
        server: Operator-visible label for the validating server, recorded on
            the report. Pass a base URL, never a credential.

    Returns:
        The merged :class:`AttestedTranslationReport`. It is
        ``server-attested`` only when every submitted tool came back classified;
        any failure at all degrades the whole report to ``local-only``.
    """

    if validator is None:
        return _local_only(
            manifest,
            "No server validator was configured, so the verdict is the SDK's local "
            "view of the process catalog and has not been attested by a server.",
            server=server,
        )

    try:
        classifications = _collect_server_classifications(manifest, validator)
    # Deliberately broad: any failure at all -- transport, HTTP status, a
    # malformed report -- means the verdict is not attested, and none of them
    # is allowed to abort an otherwise-usable offline migration run.
    except Exception as exc:
        return _local_only(manifest, _describe_failure(exc), server=server)

    return AttestedTranslationReport(
        manifest=manifest,
        verdict_source=SERVER_ATTESTED,
        tools=tuple(
            _merge_verdict(tool, classifications[tool.tool_name]) for tool in manifest.tools
        ),
        server=server,
    )


def _collect_server_classifications(
    manifest: TranslationManifest,
    validator: TranslationValidator,
) -> dict[str, JsonObject]:
    """Submit every batch and return the per-tool server verdicts.

    Raises:
        TranslationAttestationError: The response is not a usable report, or it
            does not classify every submitted tool. Both cases mean the report
            cannot be presented as attested.
    """

    classifications: dict[str, JsonObject] = {}
    for batch in manifest.batches():
        classifications.update(_parse_report(validator(batch), batch))

    missing = [tool.tool_name for tool in manifest.tools if tool.tool_name not in classifications]
    if missing:
        raise TranslationAttestationError(
            "The server report did not classify every submitted tool "
            f"(missing: {', '.join(missing)})."
        )
    return classifications


def _parse_report(payload: Any, batch: TranslationManifest) -> dict[str, JsonObject]:
    """Extract per-tool verdicts from one server report payload."""

    if not isinstance(payload, dict):
        raise TranslationAttestationError(
            f"The server returned a {type(payload).__name__} where a translation report object was expected."
        )

    # Artifact identity is REQUIRED, not merely consistent-if-present. The
    # genuine endpoint always stamps both fields, so a payload without them is
    # not a translation report and must not back an attestation claim.
    artifact_kind = payload.get("artifactKind")
    if artifact_kind != REPORT_ARTIFACT_KIND:
        raise TranslationAttestationError(
            f"The server returned artifactKind {artifact_kind!r}, not {REPORT_ARTIFACT_KIND!r}; "
            "the response cannot be trusted as a translation report."
        )

    artifact_version = payload.get("artifactVersion")
    if artifact_version not in SUPPORTED_REPORT_VERSIONS:
        raise TranslationAttestationError(
            f"The server returned artifactVersion {artifact_version!r}; this client reads "
            f"{', '.join(sorted(SUPPORTED_REPORT_VERSIONS))}."
        )

    tools = payload.get("tools")
    if not isinstance(tools, list):
        raise TranslationAttestationError("The server report carries no 'tools' array.")

    submitted = {tool.tool_name for tool in batch.tools}
    verdicts: dict[str, JsonObject] = {}
    for entry in tools:
        if not isinstance(entry, dict):
            raise TranslationAttestationError("The server report contains a non-object tool entry.")
        tool_name = entry.get("toolName")
        classification = entry.get("classification")
        if not isinstance(tool_name, str) or not isinstance(classification, str):
            raise TranslationAttestationError(
                "The server report contains a tool entry without a toolName/classification pair."
            )
        if classification not in CLASSIFICATIONS:
            # Accepting it would put a value in `classification` that no summary
            # counter tallies, producing an attested report that does not add up.
            raise TranslationAttestationError(
                f"The server classified {tool_name!r} as {classification!r}, which is outside this "
                f"report format's vocabulary ({', '.join(sorted(CLASSIFICATIONS))})."
            )
        if tool_name not in submitted:
            raise TranslationAttestationError(
                f"The server report classifies {tool_name!r}, which was not submitted."
            )
        verdicts[tool_name] = entry
    return verdicts


def _merge_verdict(tool: TranslationToolProposal, entry: JsonObject) -> AttestedToolVerdict:
    """Apply one server verdict over a tool's local classification."""

    server_classification = str(entry["classification"])
    agreement = (
        AGREEMENT_AGREED
        if server_classification == tool.local_classification
        else AGREEMENT_DISAGREED
    )
    process_id = entry.get("processId")
    return AttestedToolVerdict(
        tool_name=tool.tool_name,
        # The server owns the canonical catalog, so its verdict is the effective
        # one even when it contradicts the SDK. The local value stays on the
        # record beside it rather than being overwritten.
        classification=server_classification,
        local_classification=tool.local_classification,
        server_classification=server_classification,
        agreement=agreement,
        process_id=process_id if isinstance(process_id, str) else None,
        parameter_bindings=_object_list(entry.get("parameterBindings")),
        issues=_object_list(entry.get("issues")),
    )


def _local_only(
    manifest: TranslationManifest,
    reason: str,
    *,
    server: str | None,
) -> AttestedTranslationReport:
    """Build the unattested report, with the reason stated rather than implied."""

    return AttestedTranslationReport(
        manifest=manifest,
        verdict_source=LOCAL_ONLY,
        tools=tuple(
            AttestedToolVerdict(
                tool_name=tool.tool_name,
                classification=tool.local_classification,
                local_classification=tool.local_classification,
                agreement=AGREEMENT_NOT_ATTESTED,
                process_id=tool.target_process_id,
            )
            for tool in manifest.tools
        ),
        fallback_reason=reason,
        server=server,
    )


def _describe_failure(exc: BaseException) -> str:
    detail = str(exc).strip()
    label = type(exc).__name__
    return f"{label}: {detail}" if detail else label


def _object_list(value: Any) -> tuple[JsonObject, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def source_format_for_path(path: str | Path) -> str | None:
    """Return the manifest ``sourceFormat`` for a toolbox path, or ``None``.

    ``None`` means the file is not one of the toolbox containers the validation
    endpoint accepts -- a bare ``.py`` arcpy script, for example, which is a
    script rather than a toolbox.
    """

    return _SUFFIX_SOURCE_FORMATS.get(Path(path).suffix.lower())


def build_pyt_translation_manifest(
    toolbox: PytToolbox,
    *,
    source_format: str = SOURCE_FORMAT_PYT,
) -> TranslationManifest:
    """Build the validation manifest for a parsed ``.pyt`` Python toolbox."""

    return TranslationManifest(
        toolbox_name=_toolbox_name(toolbox.label or toolbox.alias, toolbox.filename),
        source_format=source_format,
        source_label=_source_label(toolbox.filename),
        tools=tuple(
            _flatten(
                # Every discovered call, not just the translatable ones: a tool the
                # SDK cannot map still belongs in the report as explicitly
                # unsupported rather than missing from the tool count.
                _proposals_for_tool(tool.class_name, tool.label, tool.report.calls)
                for tool in toolbox.tools
            )
        ),
    )


def build_atbx_translation_manifest(
    toolbox: ModelBuilderToolbox,
    *,
    source_format: str = SOURCE_FORMAT_ATBX,
) -> TranslationManifest:
    """Build the validation manifest for a parsed ``.atbx`` ModelBuilder toolbox.

    A ``.atbx`` holds two kinds of tool. ModelBuilder **models** carry their
    geoprocessing steps inline and are translated. **Script tools** only
    reference an external Python body the reader deliberately does not follow,
    so `parse_atbx_toolbox` surfaces them by name in
    :attr:`~honua_sdk.migration.ModelBuilderToolbox.script_tool_names`.

    Both go into the manifest. Submitting only the models would let the server
    return a clean report for a toolbox whose script tools were never
    classified, and the attestation would then cover a strict subset of the
    toolbox while claiming to cover all of it. Script tools are therefore
    submitted with no proposed target, which is the honest statement -- the
    translator has not established that they map to anything -- and the server
    reports them ``unsupported``.
    """

    return TranslationManifest(
        toolbox_name=_toolbox_name(None, toolbox.filename),
        source_format=source_format,
        source_label=_source_label(toolbox.filename),
        tools=tuple(
            _flatten(
                [
                    *(
                        _proposals_for_tool(model.name, model.label, [step.call for step in model.steps])
                        for model in toolbox.models
                    ),
                    *(_script_tool_proposals(toolbox.script_tool_names),),
                ]
            )
        ),
    )


def _script_tool_proposals(script_tool_names: Sequence[str]) -> tuple[TranslationToolProposal, ...]:
    """Propose each ``.atbx`` script tool as explicitly unclassified-by-the-SDK.

    The referenced ``.py`` body is not read here (point the arcpy script scanner
    at it separately), so no native target can be proposed and no coverage may
    be claimed. The tool still has to appear in the manifest so the report's
    tool count matches the toolbox.
    """

    return tuple(
        TranslationToolProposal(
            tool_name=name.strip(),
            local_classification=CLASSIFICATION_UNSUPPORTED,
            unsupported_constructs=(
                f"'{name.strip()}' is a script tool: its geoprocessing logic lives in an external "
                "Python script the .atbx reader does not follow, so no native process mapping has "
                "been established. Scan that script with the arcpy .py scanner to classify it.",
            ),
        )
        for name in script_tool_names
        if name and name.strip()
    )


def _flatten(groups: Iterable[Sequence[TranslationToolProposal]]) -> Iterator[TranslationToolProposal]:
    """Concatenate per-tool proposals, keeping every manifest tool name unique.

    The endpoint rejects a manifest containing a duplicate ``toolName``, and the
    report is keyed by that name, so a repeated name would cost attestation for
    the whole toolbox. Disambiguate instead of failing.
    """

    seen: dict[str, int] = {}
    for group in groups:
        for proposal in group:
            count = seen.get(proposal.tool_name, 0)
            seen[proposal.tool_name] = count + 1
            if count == 0:
                yield proposal
            else:
                yield _renamed(proposal, f"{proposal.tool_name}~{count + 1}", seen)


def _renamed(
    proposal: TranslationToolProposal,
    candidate: str,
    seen: dict[str, int],
) -> TranslationToolProposal:
    name = candidate
    suffix = 1
    while name in seen:
        suffix += 1
        name = f"{candidate}.{suffix}"
    seen[name] = 1
    return TranslationToolProposal(
        tool_name=name,
        local_classification=proposal.local_classification,
        display_name=proposal.display_name,
        target_process_id=proposal.target_process_id,
        parameter_mappings=proposal.parameter_mappings,
        unsupported_constructs=proposal.unsupported_constructs,
    )


def _proposals_for_tool(
    tool_name: str,
    display_name: str | None,
    calls: Sequence[ArcPyCall],
) -> tuple[TranslationToolProposal, ...]:
    """Turn one toolbox tool into the proposals the server validates.

    The server certifies *one* native process per manifest tool, so a tool whose
    body runs several geoprocessing calls is submitted as one proposal per call,
    suffixed to keep manifest tool names unique. A tool with no recognized call
    is still submitted -- with no target -- so it appears in the report as
    explicitly unsupported rather than being dropped from the count.
    """

    if not calls:
        return (
            TranslationToolProposal(
                tool_name=tool_name.strip(),
                local_classification=CLASSIFICATION_UNSUPPORTED,
                display_name=display_name,
                unsupported_constructs=(
                    "The tool body contains no geoprocessing call the translator recognizes.",
                ),
            ),
        )

    multiple = len(calls) > 1
    return tuple(
        _proposal_for_call(
            f"{tool_name.strip()}#{index + 1}" if multiple else tool_name.strip(),
            display_name,
            call,
        )
        for index, call in enumerate(calls)
    )


def _proposal_for_call(
    tool_name: str,
    display_name: str | None,
    call: ArcPyCall,
) -> TranslationToolProposal:
    """Translate one geoprocessing call into a server-validatable proposal."""

    constructs: list[str] = []
    mappings: list[TranslationParameterMapping] = []

    for binding in resolve_argument_bindings(call):
        if binding.kind == "output":
            # Outputs name a destination dataset, not a canonical process input;
            # submitting them would only produce unknown-parameter noise.
            continue
        mappings.append(
            TranslationParameterMapping(
                source_name=binding.source_name,
                target_parameter=binding.target_parameter,
            )
        )
        if not binding.declared:
            constructs.append(
                f"Argument {binding.source_name!r} is not part of the registered "
                f"{call.qualified_name} signature and is passed through unmapped."
            )

    reason = call.manual_review_reason
    if reason is not None:
        constructs.append(reason)
    elif call.process_id is None:
        constructs.append(
            f"No Honua process mapping is registered for {call.qualified_name}."
        )

    return TranslationToolProposal(
        tool_name=tool_name,
        local_classification=_local_classification(call, constructs),
        display_name=display_name,
        target_process_id=call.job_process_id,
        parameter_mappings=tuple(mappings),
        unsupported_constructs=tuple(constructs),
    )


def _local_classification(call: ArcPyCall, constructs: Sequence[str]) -> str:
    """The SDK's own verdict for one call, in the server's vocabulary."""

    if not call.translatable:
        # Both "no mapping at all" and "mapped but the server cannot job-execute
        # it" mean the tool is not runnable, which is the server's `unsupported`.
        return CLASSIFICATION_UNSUPPORTED
    if constructs:
        return CLASSIFICATION_PARTIALLY_TRANSLATED
    return CLASSIFICATION_TRANSLATED


def _toolbox_name(declared: str | None, filename: str | None) -> str:
    if declared and declared.strip():
        return declared.strip()
    if filename:
        stem = Path(filename).stem
        if stem:
            return stem
    return "toolbox"


def _source_label(filename: str | None) -> str | None:
    """Basename only: the directory path is the operator's, not the server's."""

    return Path(filename).name if filename else None

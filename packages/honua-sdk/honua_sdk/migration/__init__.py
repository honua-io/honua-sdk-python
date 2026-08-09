"""Migration helpers for moving GIS workflows onto Honua surfaces.

These helpers translate ArcPy scripts, Python toolboxes (``.pyt``), and
ModelBuilder models into calls against **built-in** Honua server geoprocessing
processes. A tool is only classified ``"translatable"`` when its target is in
:data:`~honua_sdk.migration.arcpy.EXECUTABLE_PROCESS_IDS` (a server-runnable
built-in process); anything else is emitted as ``"manual-review"``.

A toolbox verdict can additionally be **server-attested**: build a manifest with
:func:`~honua_sdk.migration.build_pyt_translation_manifest` /
:func:`~honua_sdk.migration.build_atbx_translation_manifest` and pass it through
:func:`~honua_sdk.migration.attest_translation`, which has the server's canonical
process catalog classify every tool. Where the server and the SDK disagree the
server wins and the disagreement is reported; where no server is reachable the
report degrades to an explicitly marked ``local-only`` verdict. A local verdict
is never presented as attested. See :mod:`honua_sdk.migration.attestation`.

The codemod deliberately has **no** notion of "custom code" execution or backend
selection: it never emits a custom-code (operator-supplied-code) geoprocessing
job, and it cannot request local/on-host execution. Per honua-server ADR-0063,
custom GP tools run only in an isolated cloud-managed AWS Batch container,
server-side; the SDK exposes no local-execution path. Keep it that way (see
``tests/test_custom_code_batch_only_policy.py``).
"""

from __future__ import annotations

from .arcpy import (
    EXECUTABLE_PROCESS_IDS,
    JOB_STATUS_ACCEPTED,
    JOB_STATUS_DISMISSED,
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCESSFUL,
    ArcPyArgumentBinding,
    ArcPyCall,
    ArcPyJobError,
    ArcPyJobTimeoutError,
    ArcPyMigrationPlan,
    ArcPyProcessExecution,
    ArcPyProcessRunner,
    ArcPyProcessTranslation,
    ArcPyScanReport,
    UnsupportedArcPyCallError,
    build_parity_evidence,
    build_parity_evidence_for_source,
    resolve_argument_bindings,
    scan_arcpy_file,
    scan_arcpy_source,
    translate_arcpy_report,
    translate_arcpy_source,
)
from .attestation import (
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
    AttestedToolVerdict,
    AttestedTranslationReport,
    TranslationAttestationError,
    TranslationManifest,
    TranslationParameterMapping,
    TranslationToolProposal,
    TranslationValidator,
    attest_translation,
    build_atbx_translation_manifest,
    build_pyt_translation_manifest,
    source_format_for_path,
)
from .modelbuilder import (
    GpService,
    GpTask,
    GpTaskParameter,
    ModelBuilderModel,
    ModelBuilderToolbox,
    ModelStep,
    UnsupportedModelFormatError,
    build_atbx_parity_evidence,
    build_gp_service_parity_evidence,
    build_model_parity_evidence,
    parse_atbx_toolbox,
    parse_gp_service_definition,
    parse_gp_task_definition,
    parse_model_definition,
)
from .pyt import (
    BINARY_TOOLBOX_EXPORT_GUIDANCE,
    PytParameter,
    PytTool,
    PytToolbox,
    UnsupportedToolboxError,
    build_pyt_parity_evidence,
    parse_binary_toolbox,
    parse_pyt_file,
    parse_pyt_source,
)

__all__ = [
    "AGREEMENT_AGREED",
    "AGREEMENT_DISAGREED",
    "AGREEMENT_NOT_ATTESTED",
    "BINARY_TOOLBOX_EXPORT_GUIDANCE",
    "CLASSIFICATION_PARTIALLY_TRANSLATED",
    "CLASSIFICATION_TRANSLATED",
    "CLASSIFICATION_UNSUPPORTED",
    "EXECUTABLE_PROCESS_IDS",
    "JOB_STATUS_ACCEPTED",
    "JOB_STATUS_DISMISSED",
    "JOB_STATUS_FAILED",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCESSFUL",
    "LOCAL_ONLY",
    "MAX_MANIFEST_TOOLS",
    "SERVER_ATTESTED",
    "SOURCE_FORMAT_ATBX",
    "SOURCE_FORMAT_PYT",
    "SOURCE_FORMAT_TBX",
    "ArcPyArgumentBinding",
    "ArcPyCall",
    "ArcPyJobError",
    "ArcPyJobTimeoutError",
    "ArcPyMigrationPlan",
    "ArcPyProcessExecution",
    "ArcPyProcessRunner",
    "ArcPyProcessTranslation",
    "ArcPyScanReport",
    "AttestedToolVerdict",
    "AttestedTranslationReport",
    "GpService",
    "GpTask",
    "GpTaskParameter",
    "ModelBuilderModel",
    "ModelBuilderToolbox",
    "ModelStep",
    "PytParameter",
    "PytTool",
    "PytToolbox",
    "TranslationAttestationError",
    "TranslationManifest",
    "TranslationParameterMapping",
    "TranslationToolProposal",
    "TranslationValidator",
    "UnsupportedArcPyCallError",
    "UnsupportedModelFormatError",
    "UnsupportedToolboxError",
    "attest_translation",
    "build_atbx_parity_evidence",
    "build_atbx_translation_manifest",
    "build_gp_service_parity_evidence",
    "build_model_parity_evidence",
    "build_parity_evidence",
    "build_parity_evidence_for_source",
    "build_pyt_parity_evidence",
    "build_pyt_translation_manifest",
    "parse_atbx_toolbox",
    "parse_binary_toolbox",
    "parse_gp_service_definition",
    "parse_gp_task_definition",
    "parse_model_definition",
    "parse_pyt_file",
    "parse_pyt_source",
    "resolve_argument_bindings",
    "scan_arcpy_file",
    "scan_arcpy_source",
    "source_format_for_path",
    "translate_arcpy_report",
    "translate_arcpy_source",
]

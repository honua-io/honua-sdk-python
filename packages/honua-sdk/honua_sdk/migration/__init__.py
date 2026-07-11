"""Migration helpers for moving GIS workflows onto Honua surfaces.

These helpers translate ArcPy scripts, Python toolboxes (``.pyt``), and
ModelBuilder models into calls against **built-in** Honua server geoprocessing
processes. A tool is only classified ``"translatable"`` when its target is in
:data:`~honua_sdk.migration.arcpy.EXECUTABLE_PROCESS_IDS` (a server-runnable
built-in process); anything else is emitted as ``"manual-review"``.

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
    scan_arcpy_file,
    scan_arcpy_source,
    translate_arcpy_report,
    translate_arcpy_source,
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
    "EXECUTABLE_PROCESS_IDS",
    "JOB_STATUS_ACCEPTED",
    "JOB_STATUS_DISMISSED",
    "JOB_STATUS_FAILED",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCESSFUL",
    "ArcPyCall",
    "ArcPyJobError",
    "ArcPyJobTimeoutError",
    "ArcPyMigrationPlan",
    "ArcPyProcessExecution",
    "ArcPyProcessRunner",
    "ArcPyProcessTranslation",
    "ArcPyScanReport",
    "GpService",
    "GpTask",
    "GpTaskParameter",
    "ModelBuilderModel",
    "ModelBuilderToolbox",
    "ModelStep",
    "PytParameter",
    "PytTool",
    "PytToolbox",
    "UnsupportedArcPyCallError",
    "UnsupportedModelFormatError",
    "UnsupportedToolboxError",
    "build_atbx_parity_evidence",
    "build_gp_service_parity_evidence",
    "build_model_parity_evidence",
    "build_parity_evidence",
    "build_parity_evidence_for_source",
    "build_pyt_parity_evidence",
    "parse_atbx_toolbox",
    "parse_binary_toolbox",
    "parse_gp_service_definition",
    "parse_gp_task_definition",
    "parse_model_definition",
    "parse_pyt_file",
    "parse_pyt_source",
    "scan_arcpy_file",
    "scan_arcpy_source",
    "translate_arcpy_report",
    "translate_arcpy_source",
]

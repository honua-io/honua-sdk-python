"""Data quality report demo for the geospatial ETL source contract."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import html
from pathlib import Path
import struct
import sys
from typing import Any
import zlib

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.geospatial_etl import workflow

EXAMPLE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_PATH = EXAMPLE_DIR / "geospatial_etl" / "data" / "demo_sites.csv"
DEFAULT_OUTPUT_DIR = EXAMPLE_DIR / "geospatial_etl" / "output"


@dataclass(slots=True)
class DataQualityReport:
    summary: dict[str, Any]
    json_path: Path
    html_path: Path
    png_path: Path


def build_data_quality_report(
    *,
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    target_crs: str = workflow.DEFAULT_TARGET_CRS,
) -> DataQualityReport:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    json_path = output_path / "data-quality-report.json"
    html_path = output_path / "data-quality-report.html"
    png_path = output_path / "data-quality-report.png"

    source_frame = workflow.load_source_dataframe(input_path)
    source_gdf = workflow.dataframe_to_source_geodataframe(source_frame)
    normalized = workflow.normalize_source_geodataframe(source_gdf, target_crs=target_crs)
    validation = workflow.validate_source_geodataframe(normalized)

    reason_counts = Counter(reason for issue in validation.rejected_rows for reason in issue.reasons)
    missing_columns = [
        column for column in workflow.REQUIRED_SOURCE_COLUMNS
        if column not in source_frame.columns
    ]
    unexpected_columns = [
        column for column in source_frame.columns
        if column not in {*workflow.REQUIRED_SOURCE_COLUMNS, "_source_row"}
    ]

    summary: dict[str, Any] = {
        "schema_version": 1,
        "input_path": str(Path(input_path).expanduser().resolve()),
        "target_crs": target_crs,
        "source_row_count": validation.source_row_count,
        "valid_row_count": validation.valid_count,
        "rejected_row_count": validation.rejected_count,
        "reason_counts": dict(sorted(reason_counts.items())),
        "schema": {
            "required_columns": list(workflow.REQUIRED_SOURCE_COLUMNS),
            "missing_columns": missing_columns,
            "unexpected_columns": unexpected_columns,
        },
        "rejected_rows": [issue.to_dict() for issue in validation.rejected_rows],
        "artifacts": {
            "json": str(json_path),
            "html": str(html_path),
            "png": str(png_path),
        },
    }

    workflow.write_summary_artifact(summary, json_path)
    _write_html_report(summary, html_path)
    _write_png_report(summary, png_path)
    return DataQualityReport(summary=summary, json_path=json_path, html_path=html_path, png_path=png_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write deterministic data quality artifacts for the ETL source CSV.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-crs", default=workflow.DEFAULT_TARGET_CRS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = build_data_quality_report(
        input_path=args.input,
        output_dir=args.output_dir,
        target_crs=args.target_crs,
    )
    print(
        f"Validated {report.summary['source_row_count']} rows: "
        f"{report.summary['valid_row_count']} valid, "
        f"{report.summary['rejected_row_count']} rejected"
    )
    print(f"JSON artifact: {report.json_path}")
    print(f"HTML artifact: {report.html_path}")
    print(f"PNG artifact: {report.png_path}")
    return 0 if report.summary["rejected_row_count"] == 0 else 1


def _write_html_report(summary: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    reasons = "\n".join(
        f"<li>{html.escape(reason)}: {count}</li>"
        for reason, count in summary["reason_counts"].items()
    ) or "<li>None</li>"
    rejected_rows = "\n".join(
        "<tr>"
        f"<td>{issue['source_row']}</td>"
        f"<td>{html.escape(str(issue.get('uid') or ''))}</td>"
        f"<td>{html.escape(', '.join(issue['reasons']))}</td>"
        "</tr>"
        for issue in summary["rejected_rows"]
    ) or "<tr><td colspan=\"3\">No rejected rows</td></tr>"
    path.write_text(
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head><meta charset=\"utf-8\"><title>Honua Data Quality Report</title></head>\n"
        "<body>\n"
        "<h1>Honua Data Quality Report</h1>\n"
        f"<p>Input: {html.escape(summary['input_path'])}</p>\n"
        f"<p>Rows: {summary['source_row_count']} source, "
        f"{summary['valid_row_count']} valid, {summary['rejected_row_count']} rejected</p>\n"
        "<h2>Reason Counts</h2>\n"
        f"<ul>{reasons}</ul>\n"
        "<h2>Rejected Rows</h2>\n"
        "<table><thead><tr><th>Source row</th><th>UID</th><th>Reasons</th></tr></thead><tbody>\n"
        f"{rejected_rows}\n"
        "</tbody></table>\n"
        "</body></html>\n",
        encoding="utf-8",
    )
    return path


def _write_png_report(summary: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    reason_counts = summary["reason_counts"]
    values = [reason_counts[label] for label in reason_counts] or [0]
    path.write_bytes(_build_bar_chart_png(values))
    return path


def _build_bar_chart_png(values: list[int]) -> bytes:
    width = 640
    height = 360
    margin = 48
    image = bytearray([255, 255, 255] * width * height)

    def set_pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            image[offset:offset + 3] = bytes(color)

    axis_color = (31, 41, 55)
    grid_color = (229, 231, 235)
    bar_color = (37, 99, 235)

    for grid_index in range(5):
        y = margin + grid_index * (height - 2 * margin) // 4
        for x in range(margin, width - margin):
            set_pixel(x, y, grid_color)

    for x in range(margin, width - margin):
        set_pixel(x, height - margin, axis_color)
    for y in range(margin, height - margin + 1):
        set_pixel(margin, y, axis_color)

    max_value = max(values + [1])
    bar_count = max(len(values), 1)
    available_width = width - 2 * margin
    slot_width = max(1, available_width // bar_count)
    bar_width = max(8, int(slot_width * 0.55))
    chart_height = height - 2 * margin

    for index, value in enumerate(values):
        bar_height = int(chart_height * value / max_value) if max_value else 0
        x0 = margin + index * slot_width + (slot_width - bar_width) // 2
        x1 = x0 + bar_width
        y0 = height - margin - bar_height
        y1 = height - margin
        for y in range(y0, y1):
            for x in range(x0, x1):
                set_pixel(x, y, bar_color)

    scanlines = bytearray()
    row_width = width * 3
    for y in range(height):
        scanlines.append(0)
        start = y * row_width
        scanlines.extend(image[start:start + row_width])

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(scanlines), level=9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    raise SystemExit(main())

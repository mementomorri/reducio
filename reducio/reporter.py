"""Markdown report generation."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from reducio.models import AnalyzeResult, AppConfig, RefactorPlan, RefactorResult
from reducio.plan_review import plan_preview, terminal_text
from reducio.presentation import markdown_cell as _md_cell
from reducio.presentation import table
from reducio.storage import (
    StorageError,
    checked_file,
    read_text,
    report_stem,
    validate_session_id,
    write_text,
)


class Reporter:
    def __init__(
        self,
        cfg: AppConfig | None = None,
        output_dir: str | Path | None = None,
        *,
        target: str | Path = ".",
    ):
        self.cfg = cfg or AppConfig()
        self.output_dir = (
            Path(output_dir) if output_dir is not None else Path(target).resolve() / ".reducio"
        )

    def _path(self, name: str) -> Path:
        path = checked_file(self.output_dir, name)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return path

    def generate_baseline(self, result: AnalyzeResult) -> Path:
        from reducio.analysis import analysis_configuration
        from reducio.visual_report import write_reports

        if not result.configuration:
            result = result.model_copy(update={"configuration": analysis_configuration(self.cfg)})
        return write_reports(result, self.output_dir)[0]

    def generate_check(self, result: dict) -> Path:
        name = report_stem("check") + ".md"
        path = self._path(name)
        lines = [
            "# reducio Quality Check Report\n",
            f"**Generated:** {datetime.now().isoformat()}\n\n",
            "## Summary\n\n",
            table(
                ["Metric", "Value"],
                [
                    [label, result.get(key, 0)]
                    for label, key in (
                        ("Total Issues", "total_issues"),
                        ("Critical", "critical"),
                        ("Warning", "warning"),
                        ("Info", "info"),
                        ("Suppressed", "suppressed_count"),
                    )
                ],
            )
            + "\n",
        ]
        issues = result.get("issues") or []
        if "gate_threshold" in result:
            lines.append(
                f"Quality gate: {_md_cell(result['gate_threshold'])}; failed: {result['gate_failed']}\n\n"
            )
        if issues:
            keys = ("severity", "issue_type", "file", "line", "symbol", "message", "suggestion")
            lines.append(
                "## Issues\n\n"
                + table(
                    ["Severity", "Type", "File", "Line", "Symbol", "Message", "Suggestion"],
                    [[issue.get(key, "") for key in keys] for issue in issues],
                )
            )
        suppressed = result.get("suppressed_issues") or []
        if suppressed:
            lines.append(
                "\n## Suppressed findings (not counted by the gate)\n\n"
                + table(
                    ["Type", "File", "Line", "Symbol", "Reason"],
                    [
                        [
                            issue.get(key, "")
                            for key in (
                                "issue_type",
                                "file",
                                "line",
                                "symbol",
                                "suppression_reason",
                            )
                        ]
                        for issue in suppressed
                    ],
                )
            )
        write_text(path, "".join(lines))
        return path

    def generate_dry_run(self, plan: RefactorPlan, command: str, path: str) -> Path:
        out = self._path(f"reducio-dryrun-{validate_session_id(plan.session_id)}.md")
        preview = terminal_text(f"Command: {command}\nPath: {path}\n" + plan_preview(plan))
        fence = "`" * max(
            3, max((len(m.group()) + 1 for m in re.finditer(r"`+", preview)), default=3)
        )
        write_text(out, f"# reducio dry-run review\n\n{fence}diff\n{preview}\n{fence}\n")
        return out

    def generate(self, result: RefactorResult) -> Path:
        out = self._path(f"reducio-report-{validate_session_id(result.session_id)}.md")
        loc_before = result.metrics_before.lines_of_code if result.metrics_before else "unavailable"
        loc_after = result.metrics_after.lines_of_code if result.metrics_after else "unavailable"
        content = (
            f"# reducio Report\n\n"
            f"Session: {result.session_id}\n\n"
            f"LOC before: {loc_before}\nLOC after: {loc_after}\n"
            f"\nSuccess: {result.success}\nTests: {result.test_status}\n"
            f"Recovery: {result.recovery_status}\n\n"
            f"Error: {_md_cell(result.error or 'none')}\n\n"
            f"Backup: {_md_cell(result.backup_location or 'none')}\n\n"
        )
        content += "\n".join(_md_cell(e) for e in result.recovery_errors) + "\n\n"
        content += "Metrics v2; whole affected Python files, not snippets.\n\n"
        content += "| State | LOC | Cyclomatic | Cognitive |\n|---|---:|---:|---:|\n"
        from reducio.analysis import match_functions, totals

        for label, measurement in (
            ("Before", result.measurements_before),
            ("Attempted", result.measurements_attempted),
            ("Retained", result.measurements_after),
        ):
            measured = totals(measurement)
            values = (
                f"{measured.lines_of_code} | {measured.cyclomatic_complexity} | {measured.cognitive_complexity}"
                if measured
                else "unavailable | unavailable | unavailable"
            )
            content += f"| {label} | {values} |\n"
        for label, measurement in (
            ("Retained", result.measurements_after),
            ("Attempted", result.measurements_attempted),
        ):
            before = result.measurements_before
            if not before or not before.complete or not measurement or not measurement.complete:
                continue
            content += f"\n## {label} function changes\n\n"
            comparisons, notes = match_functions(
                before, measurement, self.cfg.complexity_thresholds.cyclomatic_complexity
            )
            if notes:
                content += "\n\n".join(_md_cell(note) for note in notes) + "\n\n"
            rows = []
            for comparison in comparisons:
                function = comparison.after or comparison.before
                key = (function.file, function.qualified_name, function.kind)
                rows.append(
                    [
                        ":".join(key),
                        comparison.status,
                        (
                            comparison.cyclomatic_delta
                            if comparison.cyclomatic_delta is not None
                            else "—"
                        ),
                        (
                            comparison.cognitive_delta
                            if comparison.cognitive_delta is not None
                            else "—"
                        ),
                    ]
                )
            content += table(["Function", "Status", "Δ cyclomatic", "Δ cognitive"], rows)
        write_text(
            self._path(f"reducio-report-{validate_session_id(result.session_id)}.json"),
            result.model_dump_json(indent=2),
        )
        write_text(out, content)
        return out

    def load_latest(self, session_id: str = "") -> str:
        if session_id:
            validate_session_id(session_id)
            for kind in ("report", "dryrun"):
                p = checked_file(self.output_dir, f"reducio-{kind}-{session_id}.md")
                if p.exists():
                    return read_text(p)
            raise FileNotFoundError(session_id)
        reports = []
        for candidate in self.output_dir.glob("reducio-*.md"):
            try:
                p = checked_file(self.output_dir, candidate.name)
                reports.append((p.stat().st_mtime, p))
            except StorageError, OSError:
                logging.getLogger(__name__).warning("Skipping unsafe report file")
        reports.sort(reverse=True)
        if not reports:
            raise FileNotFoundError("no reports found")
        return read_text(reports[0][1])

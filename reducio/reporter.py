"""Markdown report generation."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from reducio.models import AnalyzeResult, AppConfig, RefactorPlan, RefactorResult
from reducio.plan_review import plan_preview, terminal_text
from reducio.storage import StorageError, checked_file, read_text, validate_session_id, write_text


def _md_cell(value: object) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


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
        name = f"reducio-check-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        path = self._path(name)
        lines = [
            "# reducio Quality Check Report\n",
            f"**Generated:** {datetime.now().isoformat()}\n\n",
            "## Summary\n\n",
            "| Metric | Value |\n|--------|-------|\n",
            f"| Total Issues | {result.get('total_issues', 0)} |\n",
            f"| Critical | {result.get('critical', 0)} |\n",
            f"| Warning | {result.get('warning', 0)} |\n",
            f"| Info | {result.get('info', 0)} |\n\n",
        ]
        issues = result.get("issues") or []
        if "gate_threshold" in result:
            lines.append(
                f"Quality gate: {result['gate_threshold']}; failed: {result['gate_failed']}\n\n"
            )
        if issues:
            lines.append(
                "## Issues\n\n"
                "| Severity | Type | File | Line | Symbol | Message | Suggestion |\n"
                "|----------|------|------|------|--------|---------|------------|\n"
            )
            for i in issues:
                lines.append(
                    "| "
                    + " | ".join(
                        _md_cell(i.get(k, ""))
                        for k in (
                            "severity",
                            "issue_type",
                            "file",
                            "line",
                            "symbol",
                            "message",
                            "suggestion",
                        )
                    )
                    + " |\n"
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
        from collections import defaultdict

        from reducio.compare import _comparison
        from reducio.services import _totals

        for label, measurement in (
            ("Before", result.measurements_before),
            ("Attempted", result.measurements_attempted),
            ("Retained", result.measurements_after),
        ):
            totals = _totals(measurement)
            values = (
                f"{totals.lines_of_code} | {totals.cyclomatic_complexity} | {totals.cognitive_complexity}"
                if totals
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
            content += "| Function | Status | Δ cyclomatic | Δ cognitive |\n|---|---|---:|---:|\n"
            indexes = []
            for snapshot in (before, measurement):
                index = defaultdict(list)
                for function in snapshot.functions:
                    index[(function.file, function.qualified_name, function.kind)].append(function)
                indexes.append(index)
            for key in sorted(indexes[0].keys() | indexes[1].keys()):
                left, right = indexes[0][key], indexes[1][key]
                if len(left) > 1 or len(right) > 1:
                    content += f"| {_md_cell(':'.join(key))} | ambiguous | — | — |\n"
                    continue
                comparison = _comparison(
                    left[0] if left else None,
                    right[0] if right else None,
                    self.cfg.complexity_thresholds.cyclomatic_complexity,
                )
                content += (
                    f"| {_md_cell(':'.join(key))} | {comparison.status} | "
                    f"{comparison.cyclomatic_delta if comparison.cyclomatic_delta is not None else '—'} | "
                    f"{comparison.cognitive_delta if comparison.cognitive_delta is not None else '—'} |\n"
                )
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

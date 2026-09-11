"""Markdown report generation."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from reducto.models import AnalyzeResult, AppConfig, RefactorPlan, RefactorResult
from reducto.plan_review import plan_preview, terminal_text
from reducto.storage import StorageError, checked_file, read_text, validate_session_id, write_text


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
            Path(output_dir) if output_dir is not None else Path(target).resolve() / ".reducto"
        )

    def _path(self, name: str) -> Path:
        path = checked_file(self.output_dir, name)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return path

    def generate_baseline(self, result: AnalyzeResult) -> Path:
        from reducto.analysis import analysis_configuration
        from reducto.visual_report import write_reports

        if not result.configuration:
            result = result.model_copy(update={"configuration": analysis_configuration(self.cfg)})
        return write_reports(result, self.output_dir)[0]

    def generate_check(self, result: dict) -> Path:
        name = f"reducto-check-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        path = self._path(name)
        lines = [
            "# reducto Quality Check Report\n",
            f"**Generated:** {datetime.now().isoformat()}\n\n",
            "## Summary\n\n",
            "| Metric | Value |\n|--------|-------|\n",
            f"| Total Issues | {result.get('total_issues', 0)} |\n",
            f"| Critical | {result.get('critical', 0)} |\n",
            f"| Warning | {result.get('warning', 0)} |\n",
            f"| Info | {result.get('info', 0)} |\n\n",
        ]
        issues = result.get("issues") or []
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
        out = self._path(f"reducto-dryrun-{validate_session_id(plan.session_id)}.md")
        preview = terminal_text(f"Command: {command}\nPath: {path}\n" + plan_preview(plan))
        fence = "`" * max(
            3, max((len(m.group()) + 1 for m in re.finditer(r"`+", preview)), default=3)
        )
        write_text(out, f"# reducto dry-run review\n\n{fence}diff\n{preview}\n{fence}\n")
        return out

    def generate(self, result: RefactorResult) -> Path:
        out = self._path(f"reducto-report-{validate_session_id(result.session_id)}.md")
        loc_before = result.metrics_before.lines_of_code
        loc_after = result.metrics_after.lines_of_code
        content = (
            f"# reducto Report\n\n"
            f"Session: {result.session_id}\n\n"
            f"LOC before: {loc_before}\nLOC after: {loc_after}\n"
            f"Reduced: {loc_before - loc_after}\n\n"
            f"Success: {result.success}\nTests passed: {result.tests_passed}\n"
        )
        write_text(out, content)
        return out

    def load_latest(self, session_id: str = "") -> str:
        if session_id:
            validate_session_id(session_id)
            for kind in ("report", "dryrun"):
                p = checked_file(self.output_dir, f"reducto-{kind}-{session_id}.md")
                if p.exists():
                    return read_text(p)
            raise FileNotFoundError(session_id)
        reports = []
        for candidate in self.output_dir.glob("reducto-*.md"):
            try:
                p = checked_file(self.output_dir, candidate.name)
                reports.append((p.stat().st_mtime, p))
            except StorageError, OSError:
                logging.getLogger(__name__).warning("Skipping unsafe report file")
        reports.sort(reverse=True)
        if not reports:
            raise FileNotFoundError("no reports found")
        return read_text(reports[0][1])

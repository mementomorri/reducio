"""Markdown report generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reducto.models import AnalyzeResult, AppConfig, RefactorPlan, RefactorResult


def _md_cell(value: object) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


class Reporter:
    def __init__(self, cfg: AppConfig | None = None, output_dir: str = ".reducto"):
        self.cfg = cfg or AppConfig()
        self.output_dir = Path(output_dir)

    def generate_baseline(self, result: AnalyzeResult) -> Path:
        from reducto.analysis import analysis_configuration
        from reducto.visual_report import write_reports

        if not result.configuration:
            result = result.model_copy(update={"configuration": analysis_configuration(self.cfg)})
        return write_reports(result, self.output_dir)[0]

    def generate_check(self, result: dict) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        name = f"reducto-check-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        path = self.output_dir / name
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
        path.write_text("".join(lines))
        return path

    def generate_dry_run(self, plan: RefactorPlan, command: str, path: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / f"reducto-dryrun-{plan.session_id[:8]}.md"
        body = [
            f"# Dry Run: {command}\n\n",
            f"**Path:** {path}\n\n",
            f"**Description:** {plan.description}\n\n",
            f"**Changes:** {len(plan.changes)}\n\n",
        ]
        for i, c in enumerate(plan.changes, 1):
            body.append(f"{i}. `{c.path}` — {c.description}\n")
        out.write_text("".join(body))
        return out

    def generate(self, result: RefactorResult) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / f"reducto-report-{result.session_id}.md"
        loc_before = result.metrics_before.lines_of_code
        loc_after = result.metrics_after.lines_of_code
        content = (
            f"# reducto Report\n\n"
            f"Session: {result.session_id}\n\n"
            f"LOC before: {loc_before}\nLOC after: {loc_after}\n"
            f"Reduced: {loc_before - loc_after}\n\n"
            f"Success: {result.success}\nTests passed: {result.tests_passed}\n"
        )
        out.write_text(content)
        return out

    def load_latest(self, session_id: str = "") -> str:
        if session_id:
            p = self.output_dir / f"reducto-report-{session_id}.md"
            if p.exists():
                return p.read_text()
            raise FileNotFoundError(session_id)
        reports = sorted(
            self.output_dir.glob("reducto-*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not reports:
            raise FileNotFoundError("no reports found")
        return reports[0].read_text()

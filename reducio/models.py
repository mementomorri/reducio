"""Data models for reducio."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_serializer, model_validator


class Language(StrEnum):
    PYTHON = "python"
    UNKNOWN = "unknown"


class FileInfo(BaseModel):
    path: str
    content: str
    hash: str | None = None


class Symbol(BaseModel):
    name: str
    type: str
    file: str = ""
    start_line: int
    end_line: int
    signature: str | None = None
    references: list[str] = Field(default_factory=list)


class ComplexityMetrics(BaseModel):
    cyclomatic_complexity: int = 0
    cognitive_complexity: int = 0
    lines_of_code: int = 0
    maintainability_index: float = 0.0


class CodeBlock(BaseModel):
    id: str
    file: str
    start_line: int
    end_line: int
    content: str
    language: Language
    symbol_type: str
    symbol_name: str
    metrics: ComplexityMetrics
    embedding: list[float] | None = None


class DuplicateGroup(BaseModel):
    id: str
    blocks: list[CodeBlock]
    similarity: float
    suggested_fix: str | None = None


class FileChange(BaseModel):
    path: str
    original: str
    modified: str
    description: str


class PlanDiagnostic(BaseModel):
    code: str
    message: str
    file: str = ""
    severity: Literal["info", "warning", "error"] = "warning"


class PlanningProvenance(BaseModel):
    file: str
    engine: Literal["heuristic", "template", "model", "embeddings", "unknown"]
    outcome: str
    model: str = ""


class RefactorPlan(BaseModel):
    session_id: str
    changes: list[FileChange]
    description: str
    pattern: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    complete: bool = True
    diagnostics: list[PlanDiagnostic] = Field(default_factory=list)
    provenance: list[PlanningProvenance] = Field(default_factory=list)


class RefactorResult(BaseModel):
    session_id: str
    success: bool
    changes: list[FileChange]
    tests_passed: bool
    error: str | None = None
    metrics_before: ComplexityMetrics | None = None
    metrics_after: ComplexityMetrics | None = None
    test_status: Literal["not_run", "passed", "failed", "error"] = "not_run"
    test_output: str = ""
    test_command: str = ""
    test_count: int | None = None
    recovery_status: Literal["not_needed", "restored", "failed"] = "not_needed"
    recovery_errors: list[str] = Field(default_factory=list)
    backup_location: str | None = None
    measurements_before: AnalyzeResult | None = None
    measurements_after: AnalyzeResult | None = None
    measurements_attempted: AnalyzeResult | None = None

    @field_serializer("metrics_before", "metrics_after")
    def serialize_measured_totals(self, metric):
        return metric.model_dump(exclude={"maintainability_index"}) if metric is not None else None

    @model_validator(mode="after")
    def truthful_tests(self):
        self.tests_passed = self.test_status == "passed"
        return self


class PatternApplied(BaseModel):
    pattern: str
    files: list[str]
    description: str


class MetricsDelta(BaseModel):
    cyclomatic_complexity_delta: int = 0
    cognitive_complexity_delta: int = 0
    maintainability_index_delta: float = 0.0


class Report(BaseModel):
    session_id: str
    generated_at: datetime = Field(default_factory=datetime.now)
    loc_before: int
    loc_after: int
    loc_reduced: int
    duplicates_found: int = 0
    patterns_applied: list[PatternApplied] = Field(default_factory=list)
    files_modified: list[str]
    metrics_delta: MetricsDelta


class ComplexityHotspot(BaseModel):
    file: str
    line: int
    symbol: str
    cyclomatic_complexity: int
    cognitive_complexity: int


class FunctionMetrics(ComplexityMetrics):
    # Inherited for compatibility, but not measured or published as a fake zero.
    maintainability_index: float = Field(default=0.0, exclude=True)
    file: str
    name: str
    qualified_name: str
    kind: str = "function"
    line: int
    end_line: int


class AnalysisDiagnostic(BaseModel):
    file: str
    message: str
    line: int | None = None
    revision: str | None = None


class AnalyzeResult(BaseModel):
    total_files: int
    total_symbols: int
    hotspots: list[ComplexityHotspot]
    duplicates: list[DuplicateGroup] = Field(default_factory=list)
    symbols: list[Symbol] = Field(default_factory=list)
    metrics_version: int = 2
    scope: str = "."
    configuration: dict = Field(default_factory=dict)
    functions: list[FunctionMetrics] = Field(default_factory=list)
    file_lines: dict[str, int] = Field(default_factory=dict)
    diagnostics: list[AnalysisDiagnostic] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def complete(self) -> bool:
        return not self.diagnostics

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_hotspots(self) -> int:
        return len(self.hotspots)


class FunctionComparison(BaseModel):
    before: FunctionMetrics | None = None
    after: FunctionMetrics | None = None
    status: str
    cyclomatic_delta: int | None = None
    cognitive_delta: int | None = None
    lines_delta: int | None = None
    new_hotspot: bool = False
    resolved_hotspot: bool = False


class CompareResult(BaseModel):
    metrics_version: int = 2
    scope: str = "."
    base_revision: str
    head_revision: str
    configuration: dict = Field(default_factory=dict)
    files: list[dict[str, str | None]] = Field(default_factory=list)
    before: AnalyzeResult
    after: AnalyzeResult
    changes: list[FunctionComparison] = Field(default_factory=list)
    diagnostics: list[AnalysisDiagnostic] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def complete(self) -> bool:
        return self.before.complete and self.after.complete and not self.diagnostics

    @computed_field  # type: ignore[prop-decorator]
    @property
    def counts(self) -> dict[str, int]:
        counts = {
            status: sum(c.status == status for c in self.changes)
            for status in ("improved", "regressed", "mixed", "unchanged", "added", "removed")
        }
        counts["new_hotspots"] = sum(c.new_hotspot for c in self.changes)
        counts["resolved_hotspots"] = sum(c.resolved_hotspot for c in self.changes)
        return counts


class ModelTier(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


class ComplexityThresholds(BaseModel):
    cyclomatic_complexity: int = 10
    cognitive_complexity: int = 15
    lines_of_code: int = 50


class AppConfig(BaseModel):
    complexity_thresholds: ComplexityThresholds = Field(default_factory=ComplexityThresholds)
    pre_approve: bool = False
    test_command: list[str] | None = Field(default=None, min_length=1)
    test_python: str | None = None
    test_runner: Literal["pytest", "unittest"] = "pytest"
    test_timeout_seconds: int = Field(default=300, gt=0)
    dry_run: bool = False
    report: bool = False
    verbose: bool = False
    model: str = ""
    prefer_local: bool = True
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [".git", "node_modules", "venv", "__pycache__"]
    )
    include_patterns: list[str] = Field(default_factory=lambda: ["*.py"])

    @model_validator(mode="before")
    @classmethod
    def reject_commit_setting(cls, data):
        if isinstance(data, dict) and "commit_changes" in data:
            raise ValueError("commit_changes was removed; commit changes manually")
        if isinstance(data, dict) and data.get("test_command") is not None:
            if (
                not isinstance(data["test_command"], list)
                or not data["test_command"]
                or any(not isinstance(x, str) or not x.strip() for x in data["test_command"])
            ):
                raise ValueError("test_command must contain nonempty argv strings")
        return data


class AnalyzeRequest(BaseModel):
    path: str
    files: list[FileInfo] = Field(default_factory=list)


class DeduplicateRequest(BaseModel):
    path: str
    files: list[FileInfo] = Field(default_factory=list)
    similarity_threshold: float = 0.85


class IdiomatizeRequest(BaseModel):
    path: str
    files: list[FileInfo] = Field(default_factory=list)
    allow_fallback: bool = False


class PatternRequest(BaseModel):
    pattern: str
    path: str
    files: list[FileInfo] = Field(default_factory=list)
    allow_fallback: bool = False

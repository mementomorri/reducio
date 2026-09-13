"""Data models for reducio."""

from __future__ import annotations

import ast
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class Language(StrEnum):
    PYTHON = "python"
    UNKNOWN = "unknown"


class FileInfo(BaseModel):
    path: str
    content: str
    hash: str | None = None
    encoding: str = "utf-8"
    error: str | None = None

    @cached_property
    def tree(self) -> ast.Module:
        if self.error:
            raise ValueError(self.error)
        tree = ast.parse(self.content, filename=self.path)
        compile(tree, self.path, "exec")
        return tree


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
    operation: Literal["create", "replace"] | None = None
    encoding: str = "utf-8"

    @property
    def creates_file(self) -> bool:
        # Missing operation is the v1 contract: empty original means create.
        return self.operation == "create" or (self.operation is None and not self.original)


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
    schema_version: Literal[1, 2] = 1
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

    @model_validator(mode="after")
    def truthful_tests(self):
        self.tests_passed = self.test_status == "passed"
        return self


class ComplexityHotspot(BaseModel):
    file: str
    line: int
    symbol: str
    cyclomatic_complexity: int
    cognitive_complexity: int


class FunctionMetrics(ComplexityMetrics):
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


class ComplexityThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cyclomatic_complexity: int = Field(default=10, gt=0)
    cognitive_complexity: int = Field(default=15, gt=0)
    lines_of_code: int = Field(default=50, gt=0)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    complexity_thresholds: ComplexityThresholds = Field(default_factory=ComplexityThresholds)
    test_command: list[str] | None = Field(default=None, min_length=1)
    test_python: str | None = None
    test_runner: Literal["pytest", "unittest"] = "pytest"
    test_timeout_seconds: int = Field(default=300, gt=0)
    verbose: bool = False
    model: str = ""
    llm_api: Literal["openai", "anthropic"] | None = None
    llm_base_url: str = ""
    llm_timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    llm_max_tokens: int = Field(default=2048, gt=0)
    check_fail_on: Literal["none", "info", "warning", "critical"] = "none"
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [".git", "node_modules", "venv", "__pycache__"]
    )
    include_patterns: list[str] = Field(default_factory=lambda: ["*.py"])

    @model_validator(mode="before")
    @classmethod
    def reject_commit_setting(cls, data):
        if isinstance(data, dict) and {"dry_run", "report", "pre_approve"}.intersection(data):
            raise ValueError(
                "Use CLI --dry-run, --report or --yes instead of these retired settings"
            )
        if isinstance(data, dict) and {
            "prefer_local",
            "prefer_remote",
            "model_tiers",
            "tier",
        }.intersection(data):
            raise ValueError(
                "Model tiers/preferences were removed; set llm_api and model explicitly"
            )
        if isinstance(data, dict) and {"api_key", "llm_api_key"}.intersection(data):
            raise ValueError("Use REDUCIO_API_KEY in the environment, not configuration")
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
    similarity_threshold: float = Field(default=0.85, ge=0, le=1, allow_inf_nan=False)


class IdiomatizeRequest(BaseModel):
    path: str
    files: list[FileInfo] = Field(default_factory=list)
    allow_fallback: bool = False


class PatternRequest(BaseModel):
    pattern: str
    path: str
    files: list[FileInfo] = Field(default_factory=list)
    allow_fallback: bool = False

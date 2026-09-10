"""Data models for reducto."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


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


class RefactorPlan(BaseModel):
    session_id: str
    changes: list[FileChange]
    description: str
    pattern: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class RefactorResult(BaseModel):
    session_id: str
    success: bool
    changes: list[FileChange]
    tests_passed: bool
    error: str | None = None
    metrics_before: ComplexityMetrics = Field(default_factory=ComplexityMetrics)
    metrics_after: ComplexityMetrics = Field(default_factory=ComplexityMetrics)


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
    commit_changes: bool = False
    dry_run: bool = False
    report: bool = False
    verbose: bool = False
    model: str = ""
    prefer_local: bool = True
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [".git", "node_modules", "venv", "__pycache__"]
    )
    include_patterns: list[str] = Field(default_factory=lambda: ["*.py"])


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


class PatternRequest(BaseModel):
    pattern: str
    path: str
    files: list[FileInfo] = Field(default_factory=list)

"""
Quality checker agent for detecting code quality issues.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from reducto.metrics import line_decisions, measure_functions
from reducto.models import (
    ComplexityThresholds,
    FileInfo,
    Language,
)
from reducto.repo import detect_language
from reducto.utils.code_utils import (
    extract_class_name,
    extract_python_function_name,
    to_pascal_case,
    to_snake_case,
)
from reducto.workspace import Workspace

logger = logging.getLogger(__name__)

# Unpronounceable letter/digit-salad names, e.g. "a1b2", "x3yz".
_GIBBERISH_NAME_RE = re.compile(r"^(?:[a-z]+\d+[a-z]+\d+|x\d+[a-z]+\d*)")


@dataclass
class QualityIssue:
    file: str
    line: int
    issue_type: str
    severity: str
    message: str
    symbol: str = ""
    suggestion: str = ""


@dataclass
class QualityReport:
    total_issues: int = 0
    critical: int = 0
    warning: int = 0
    info: int = 0
    issues: list[QualityIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_issues": self.total_issues,
            "critical": self.critical,
            "warning": self.warning,
            "info": self.info,
            "issues": [
                {
                    "file": i.file,
                    "line": i.line,
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "message": i.message,
                    "symbol": i.symbol,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
        }


class QualityCheckerAgent:
    def __init__(self, workspace: Workspace | None = None):
        self.workspace = workspace
        thresholds = workspace.cfg.complexity_thresholds if workspace else ComplexityThresholds()
        self.max_function_lines = thresholds.lines_of_code
        self.max_complexity = thresholds.cyclomatic_complexity
        self.min_variable_name_length = 2

    async def check_quality(self, files: list[FileInfo], path: str) -> QualityReport:
        report = QualityReport()

        for file in files:
            file_path = file.path
            content = file.content if file.content else ""
            language = detect_language(file_path)

            if not content or language == Language.UNKNOWN:
                continue

            issues = await self._check_file(file_path, content)
            report.issues.extend(issues)

        report.issues.sort(
            key=lambda x: (x.severity == "critical", x.severity == "warning"), reverse=True
        )
        report.total_issues = len(report.issues)
        report.critical = sum(1 for i in report.issues if i.severity == "critical")
        report.warning = sum(1 for i in report.issues if i.severity == "warning")
        report.info = sum(1 for i in report.issues if i.severity == "info")

        return report

    async def _check_file(self, file_path: str, content: str) -> list[QualityIssue]:
        lines = content.split("\n")
        issues = []
        issues.extend(self._check_variable_names(file_path, lines))
        try:
            issues.extend(self._check_function_length(file_path, lines))
            issues.extend(self._check_function_complexity(file_path, content))
            issues.extend(self._check_complexity(file_path, lines))
        except (SyntaxError, ValueError) as error:
            issues.append(
                QualityIssue(
                    file=file_path,
                    line=getattr(error, "lineno", None) or 1,
                    issue_type="parse_error",
                    severity="warning",
                    message=f"Metrics unavailable: {getattr(error, 'msg', str(error))}",
                )
            )
        issues.extend(self._check_naming_conventions(file_path, lines))
        return issues

    def _check_variable_names(self, file_path: str, lines: list[str]) -> list[QualityIssue]:
        issues = []
        loop_vars = {"i", "j", "k", "n", "x", "y", "z", "_"}
        common_short_vars = {"a", "b", "c", "n", "m", "p", "q"}

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            issues.extend(
                self._check_python_variables(
                    file_path, line_num, line, stripped, loop_vars, common_short_vars
                )
            )

        return issues

    def _check_python_variables(
        self,
        file_path: str,
        line_num: int,
        line: str,
        stripped: str,
        loop_vars: set,
        common_short_vars: set,
    ) -> list[QualityIssue]:
        issues = []

        var_patterns = [
            (r"\b([a-z][a-z0-9_]*)\s*=", "assignment"),
            (r"\bdef\s+\w+\s*\(([^)]+)\)", "parameter"),
            (r"\b([a-z][a-z0-9_]*)\s*:", "type_annotation"),
        ]

        for pattern, context in var_patterns:
            matches = re.finditer(pattern, stripped)
            for match in matches:
                var_name = match.group(1)

                if context == "parameter":
                    params = match.group(1)
                    for param in params.split(","):
                        param = param.strip().split("=")[0].split(":")[0].strip()
                        if param and self._is_bad_variable_name(
                            param, loop_vars, common_short_vars
                        ):
                            issues.append(
                                QualityIssue(
                                    file=file_path,
                                    line=line_num,
                                    issue_type="bad_parameter_name",
                                    severity="warning",
                                    message=f"Parameter '{param}' has an unclear name",
                                    symbol=param,
                                    suggestion=f"Consider using a more descriptive name like '{param}_value' or '{param}_data'",
                                )
                            )
                elif var_name and self._is_bad_variable_name(
                    var_name, loop_vars, common_short_vars
                ):
                    issues.append(
                        QualityIssue(
                            file=file_path,
                            line=line_num,
                            issue_type="bad_variable_name",
                            severity="warning",
                            message=f"Variable '{var_name}' has an unclear name",
                            symbol=var_name,
                            suggestion="Consider using a more descriptive name",
                        )
                    )

        return issues

    def _is_bad_variable_name(self, name: str, loop_vars: set, common_short_vars: set) -> bool:
        if not name or not name[0].isalpha():
            return False  # dunders, _private, *args, non-identifiers
        if name in loop_vars or name in common_short_vars:
            return False  # conventional short names (i, j, n, a, b, ...) are fine
        letters = sum(c.isalpha() for c in name)
        if any(c.isdigit() for c in name) and letters / len(name) < 0.4:
            return True  # digit-heavy gibberish
        if len(name) <= 2:
            return True  # too short to be descriptive
        return bool(_GIBBERISH_NAME_RE.match(name.lower()))

    def _check_function_length(self, file_path: str, lines: list[str]) -> list[QualityIssue]:
        issues = []
        for function in measure_functions("\n".join(lines), file_path):
            func_name = function.qualified_name
            func_length = function.lines_of_code
            if func_length <= self.max_function_lines:
                continue
            severity = "critical" if func_length > self.max_function_lines * 2 else "warning"
            issues.append(
                QualityIssue(
                    file=file_path,
                    line=function.line,
                    issue_type="long_function",
                    severity=severity,
                    message=(
                        f"Function '{func_name}' is {func_length} lines "
                        f"(max {self.max_function_lines})"
                    ),
                    symbol=func_name,
                    suggestion="Consider breaking this function into smaller functions",
                )
            )
        return issues

    def _check_function_complexity(self, file_path: str, content: str) -> list[QualityIssue]:
        issues = []
        for sym in measure_functions(content, file_path):
            cc = sym.cyclomatic_complexity
            if cc < self.max_complexity:
                continue
            severity = "critical" if cc >= self.max_complexity * 2 else "warning"
            issues.append(
                QualityIssue(
                    file=file_path,
                    line=sym.line,
                    issue_type="high_complexity_function",
                    severity=severity,
                    message=(
                        f"Function '{sym.qualified_name}' has cyclomatic complexity {cc} "
                        f"(max {self.max_complexity})"
                    ),
                    symbol=sym.qualified_name,
                    suggestion="Consider extracting branches into smaller functions",
                )
            )
        return issues

    def _check_complexity(self, file_path: str, lines: list[str]) -> list[QualityIssue]:
        issues = []

        for line_num, complexity in sorted(line_decisions("\n".join(lines)).items()):
            if complexity > 3:
                issues.append(
                    QualityIssue(
                        file=file_path,
                        line=line_num,
                        issue_type="high_complexity_line",
                        severity="info",
                        message=f"Line has {complexity} branching conditions",
                        suggestion="Consider extracting logic to separate functions",
                    )
                )

        return issues

    def _check_naming_conventions(self, file_path: str, lines: list[str]) -> list[QualityIssue]:
        issues = []
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("def "):
                func_name = extract_python_function_name(stripped)
                if func_name and not func_name[0].islower() and not func_name.startswith("_"):
                    issues.append(
                        QualityIssue(
                            file=file_path,
                            line=line_num,
                            issue_type="naming_convention",
                            severity="info",
                            message=f"Function '{func_name}' should use snake_case",
                            symbol=func_name,
                            suggestion=f"Consider renaming to '{to_snake_case(func_name)}'",
                        )
                    )
            elif stripped.startswith("class "):
                class_name = extract_class_name(stripped)
                if class_name and not class_name[0].isupper():
                    issues.append(
                        QualityIssue(
                            file=file_path,
                            line=line_num,
                            issue_type="naming_convention",
                            severity="info",
                            message=f"Class '{class_name}' should use PascalCase",
                            symbol=class_name,
                            suggestion=f"Consider renaming to '{to_pascal_case(class_name)}'",
                        )
                    )
        return issues

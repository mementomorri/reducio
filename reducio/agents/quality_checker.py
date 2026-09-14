"""Quality findings from real Python bindings and shared AST metrics."""

import ast
import re
from dataclasses import asdict, dataclass, field

from reducio.metrics import functions_from_tree, line_decisions
from reducio.models import AppConfig, FileInfo, Language
from reducio.repo import detect_language, matches
from reducio.utils.code_utils import to_pascal_case, to_snake_case
from reducio.workspace import Workspace

_GIBBERISH_NAME_RE = re.compile(r"^(?:[a-z]+\d+[a-z]+\d+|x\d+[a-z]+\d*)")
_CONVENTIONAL = set("ijknxyz_abcmpq")


@dataclass
class QualityIssue:
    file: str
    line: int
    issue_type: str
    severity: str
    message: str
    symbol: str = ""
    suggestion: str = ""
    suppression_reason: str = ""


@dataclass
class QualityReport:
    total_issues: int = 0
    critical: int = 0
    warning: int = 0
    info: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    suppressed_issues: list[QualityIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self) | {"suppressed_count": len(self.suppressed_issues)}


class QualityCheckerAgent:
    def __init__(self, workspace: Workspace | None = None):
        self.cfg = workspace.cfg if workspace else AppConfig()
        self.thresholds = self.cfg.complexity_thresholds

    async def check_quality(self, files: list[FileInfo], path: str) -> QualityReport:
        issues = []
        for file in files:
            if not file.error and detect_language(file.path) == Language.UNKNOWN:
                continue
            try:
                issues.extend(self._check_file(file))
            except (SyntaxError, ValueError) as error:
                issues.append(
                    QualityIssue(
                        file.path,
                        getattr(error, "lineno", None) or 1,
                        "parse_error",
                        "warning",
                        f"Metrics unavailable: {getattr(error, 'msg', str(error))}",
                    )
                )
        active: list[QualityIssue] = []
        suppressed: list[QualityIssue] = []
        settings: dict[str, str] = {key: value for key, value in self.cfg.quality_rules.items()}
        for issue in issues:
            if issue.issue_type == "parse_error":
                active.append(issue)
                continue
            setting = settings.get(issue.issue_type)
            if setting and setting != "off":
                issue.severity = setting
            if setting == "off":
                issue.suppression_reason = "Rule disabled by quality_rules"
            for pattern, rules in self.cfg.quality_ignores.items():
                if issue.issue_type in rules and matches(issue.file, [pattern]):
                    issue.suppression_reason = f"Ignored by quality_ignores: {pattern}"
                    break
            (suppressed if issue.suppression_reason else active).append(issue)
        issues = sorted(
            active,
            key=lambda i: (
                ("critical", "warning", "info").index(i.severity),
                i.file,
                i.line,
                i.issue_type,
                i.symbol,
            ),
        )
        return QualityReport(
            total_issues=len(issues),
            issues=issues,
            suppressed_issues=suppressed,
            critical=sum(i.severity == "critical" for i in issues),
            warning=sum(i.severity == "warning" for i in issues),
            info=sum(i.severity == "info" for i in issues),
        )

    def _check_file(self, file: FileInfo) -> list[QualityIssue]:
        tree, path = file.tree, file.path
        issues = []

        def add(node, kind, severity, message, symbol="", suggestion=""):
            issues.append(
                QualityIssue(path, node.lineno, kind, severity, message, symbol, suggestion)
            )

        for function in functions_from_tree(tree, path):
            for attribute, maximum, kind, label, inclusive in (
                ("lines_of_code", self.thresholds.lines_of_code, "long_function", "lines", False),
                (
                    "cyclomatic_complexity",
                    self.thresholds.cyclomatic_complexity,
                    "high_complexity_function",
                    "cyclomatic complexity",
                    True,
                ),
            ):
                score = getattr(function, attribute)
                if score > maximum or (inclusive and score == maximum):
                    critical = score > maximum * 2 or (inclusive and score == maximum * 2)
                    issues.append(
                        QualityIssue(
                            path,
                            function.line,
                            kind,
                            "critical" if critical else "warning",
                            f"Function '{function.qualified_name}' has {score} {label} (max {maximum})",
                            function.qualified_name,
                            "Consider extracting smaller functions",
                        )
                    )

        for line, score in sorted(line_decisions(tree).items()):
            if score > 3:
                issues.append(
                    QualityIssue(
                        path,
                        line,
                        "high_complexity_line",
                        "info",
                        f"Line has {score} branching conditions",
                        suggestion="Consider extracting logic",
                    )
                )

        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
                valid = name.lstrip("_")
                is_class = isinstance(node, ast.ClassDef)
                valid_name = bool(valid) and (
                    valid[0].isupper() and "_" not in valid if is_class else valid.islower()
                )
                if not valid_name and valid:
                    replacement = to_pascal_case(valid) if is_class else to_snake_case(valid)
                    add(
                        node,
                        "naming_convention",
                        "info",
                        f"{'Class' if is_class else 'Function'} '{name}' should use {'PascalCase' if is_class else 'snake_case'}",
                        name,
                        f"Consider renaming to '{replacement}'",
                    )
            name = _binding_name(node)
            key = (getattr(node, "lineno", 0), name)
            if name and key not in seen and _bad_name(name):
                seen.add(key)
                parameter = isinstance(node, ast.arg)
                add(
                    node,
                    "bad_parameter_name" if parameter else "bad_variable_name",
                    "warning",
                    f"{'Parameter' if parameter else 'Variable'} '{name}' has an unclear name",
                    name,
                    "Consider using a more descriptive name",
                )
        return issues


def _binding_name(node: ast.AST) -> str:
    match node:
        case ast.arg(arg=name) | ast.Name(id=name, ctx=ast.Store()):
            return name
        case ast.ExceptHandler(name=name) | ast.MatchAs(name=name) | ast.MatchStar(name=name):
            return name or ""
        case ast.MatchMapping(rest=name):
            return name or ""
        case ast.alias(asname=alias, name=qualified):
            return alias or qualified.split(".")[0]
        case _:
            return ""


def _bad_name(name: str) -> bool:
    if name in _CONVENTIONAL or name.startswith("_") or name.isupper():
        return False
    return (
        len(name) <= 2
        or bool(_GIBBERISH_NAME_RE.match(name.lower()))
        or (any(c.isdigit() for c in name) and sum(c.isalpha() for c in name) / len(name) < 0.4)
    )

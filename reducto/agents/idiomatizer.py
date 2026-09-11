"""
Idiomatizer agent for transforming code to idiomatic patterns (Python heuristics).
"""

import ast
import re

from reducto.agents.base import BaseAgent, ModelRewriteError
from reducto.models import (
    FileChange,
    IdiomatizeRequest,
    Language,
    PlanDiagnostic,
    PlanningProvenance,
    RefactorPlan,
)
from reducto.repo import detect_language
from reducto.session import SessionStore


class IdiomatizerAgent(BaseAgent):
    def __init__(self, workspace=None, llm_router=None, session_store: SessionStore | None = None):
        super().__init__(workspace, llm_router, session_store)

    async def idiomatize(self, request: IdiomatizeRequest) -> RefactorPlan:
        self._begin_plan(request.allow_fallback)
        changes = []
        idioms = 0
        for file in request.files:
            try:
                change, count = await self._idiomatize_file(file)
            except ModelRewriteError:
                break
            if change:
                changes.append(change)
                idioms += count
        return self._finalize_plan(
            changes,
            f"Found {idioms} opportunities for idiomatic improvements in {len(changes)} file(s).",
            "idiomatize",
        )

    async def _idiomatize_file(self, file) -> tuple[FileChange | None, int]:
        content, path = self._file_content_path(file)
        if detect_language(path) != Language.PYTHON:
            return None, 0
        try:
            ast.parse(content)  # can't safely rewrite (or validate) a file that doesn't parse
        except SyntaxError:
            self.diagnostics.append(
                PlanDiagnostic(
                    code="invalid_source", file=path, message="Skipped invalid Python source"
                )
            )
            return None, 0
        if self._llm_enabled():
            try:
                change = await self._llm_rewrite(
                    content,
                    path,
                    "Rewrite the following Python module to be more idiomatic and concise without changing behaviour.",
                    "LLM idiomatic rewrite",
                )
                return change, int(change is not None)
            except ModelRewriteError:
                if not self.allow_fallback:
                    raise
        change, count = self._idiomatize_python(content, path)
        self.provenance.append(
            PlanningProvenance(
                file=path, engine="heuristic", outcome="proposed" if change else "unchanged"
            )
        )
        return change, count

    def _idiomatize_python(self, content: str, path: str) -> tuple[FileChange | None, int]:
        """Collect every idiom as a line span and emit one whole-file change.

        Spans are applied to a copy of the file in reverse so earlier line
        numbers stay valid, and the resulting diff is file-relative (the old
        per-snippet changes produced diffs that applied at line 1 — see ROADMAP P0).
        """
        lines = content.split("\n")
        spans = []  # (start, end, replacement, description)
        i = 0
        while i < len(lines):
            result = self._try_python_idiom(lines[i], lines, i)
            if result:
                original, modified, description = result
                consumed = original.count("\n") + 1
                spans.append((i, i + consumed, modified, f"L{i + 1}: {description}"))
                i += consumed
            else:
                i += 1
        if not spans:
            return None, 0
        new_lines = list(lines)
        for start, end, replacement, _ in reversed(spans):
            new_lines[start:end] = replacement.split("\n")
        return (
            FileChange(
                path=path,
                original=content,
                modified="\n".join(new_lines),
                description="; ".join(desc for *_, desc in spans),
            ),
            len(spans),
        )

    def _try_python_idiom(self, line: str, lines: list[str], idx: int) -> tuple | None:
        return (
            self._filtered_list_comp(lines, idx)
            or self._dict_comp(lines, idx)
            or self._simple_list_comp(lines, idx)
            or self._compare_to_none(lines, idx)
            or self._truthiness(lines, idx)
            or self._or_chain_to_in(lines, idx)
        )

    @staticmethod
    def _is_boolean_line(line: str) -> bool:
        return line.strip().startswith(("if ", "elif ", "while "))

    @staticmethod
    def _references(var: str, *exprs: str) -> bool:
        """True if `var` appears as a name in any expr — unsafe to fold into a comprehension.

        A `for/append` loop whose value, iterable, or filter reads the accumulator
        (e.g. order-preserving dedup: `if v not in u: u.append(v)`) changes behaviour
        when rewritten as `[v for v in t if v not in u]`, because the comprehension sees
        an empty `u`. Refuse those.
        """
        pat = re.compile(rf"\b{re.escape(var)}\b")
        return any(pat.search(e) for e in exprs)

    def _truthiness(self, lines: list[str], idx: int) -> tuple | None:
        line = lines[idx]
        if not self._is_boolean_line(line):
            return None
        new = re.sub(r"len\(([^()]+)\)\s*>\s*0", r"\1", line)
        new = re.sub(r"len\(([^()]+)\)\s*==\s*0", r"not \1", new)
        if new == line:
            return None
        return line, new, "Use truthiness instead of a len() comparison"

    def _or_chain_to_in(self, lines: list[str], idx: int) -> tuple | None:
        line = lines[idx]
        m = re.match(r"(\s*)(if|elif|while)\s+(.+?):\s*$", line)
        if not m:
            return None
        parts = m.group(3).split(" or ")
        if len(parts) < 2:
            return None
        var, values = None, []
        for part in parts:
            pm = re.match(r"\s*([\w.]+)\s*==\s*(.+?)\s*$", part)
            if not pm or (var is not None and pm.group(1) != var):
                return None
            var = pm.group(1)
            values.append(pm.group(2).strip())
        new = f"{m.group(1)}{m.group(2)} {var} in ({', '.join(values)}):"
        return line, new, "Use 'in' for repeated equality checks"

    def _simple_list_comp(self, lines: list[str], idx: int) -> tuple | None:
        if self._is_for_append_pattern(lines, idx):
            return self._convert_to_list_comp(lines, idx)
        return None

    def _filtered_list_comp(self, lines: list[str], idx: int) -> tuple | None:
        if idx + 2 >= len(lines):
            return None
        for_m = re.match(r"for\s+(\w+)\s+in\s+(.+?):", lines[idx].strip())
        if_m = re.match(r"if\s+(.+?):", lines[idx + 1].strip())
        app_m = re.match(r"(\w+)\.append\((.+)\)", lines[idx + 2].strip())
        if not (for_m and if_m and app_m):
            return None
        if self._references(app_m.group(1), if_m.group(1), app_m.group(2), for_m.group(2)):
            return None
        indent = len(lines[idx]) - len(lines[idx].lstrip())
        comp = (
            f"{' ' * indent}{app_m.group(1)} = "
            f"[{app_m.group(2)} for {for_m.group(1)} in {for_m.group(2)} if {if_m.group(1)}]"
        )
        return (
            "\n".join(lines[idx : idx + 3]),
            comp,
            "Convert filtered for-loop to list comprehension",
        )

    def _dict_comp(self, lines: list[str], idx: int) -> tuple | None:
        if idx + 1 >= len(lines):
            return None
        for_m = re.match(r"for\s+(\w+)\s+in\s+(.+?):", lines[idx].strip())
        assign = re.match(r"(\w+)\[(.+?)\]\s*=\s*(.+)", lines[idx + 1].strip())
        if not (for_m and assign):
            return None
        d = assign.group(1)
        # Only a dict literal supports comprehension rewrite; lists use index assignment too.
        if not any(re.match(r"\s*" + re.escape(d) + r"\s*=\s*\{\}\s*$", ln) for ln in lines[:idx]):
            return None
        indent = len(lines[idx]) - len(lines[idx].lstrip())
        comp = (
            f"{' ' * indent}{d} = "
            f"{{{assign.group(2)}: {assign.group(3)} for {for_m.group(1)} in {for_m.group(2)}}}"
        )
        return f"{lines[idx]}\n{lines[idx + 1]}", comp, "Convert for-loop to dict comprehension"

    def _compare_to_none(self, lines: list[str], idx: int) -> tuple | None:
        line = lines[idx]
        new = re.sub(r"==\s*None", "is None", line)
        new = re.sub(r"!=\s*None", "is not None", new)
        if new == line:
            return None
        return line, new, "Use 'is'/'is not' to compare with None"

    def _is_for_append_pattern(self, lines: list[str], idx: int) -> bool:
        if idx + 1 >= len(lines):
            return False
        line = lines[idx].strip()
        if not line.startswith("for "):
            return False
        return ".append(" in lines[idx + 1].strip()

    def _convert_to_list_comp(self, lines: list[str], idx: int) -> tuple | None:
        for_line = lines[idx]
        append_line = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
        for_match = re.match(r"for\s+(\w+)\s+in\s+(.+?):", for_line.strip())
        if not for_match:
            return None
        append_match = re.match(r"(\w+)\.append\((.+)\)", append_line)
        if not append_match:
            return None
        var, iterable = for_match.group(1), for_match.group(2)
        list_var, expr = append_match.group(1), append_match.group(2)
        if self._references(list_var, expr, iterable):
            return None
        indent = len(for_line) - len(for_line.lstrip())
        list_comp = f"{' ' * indent}{list_var} = [{expr} for {var} in {iterable}]"
        return (
            f"{for_line}\n{append_line}",
            list_comp,
            "Convert for-loop with append to list comprehension",
        )

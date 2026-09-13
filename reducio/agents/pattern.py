"""AST-selected advisory patterns; named patterns optionally request a model."""

import ast
import os

from reducio.agents.base import BaseAgent, ModelRewriteError
from reducio.models import (
    FileChange,
    PatternRequest,
    PlanDiagnostic,
    PlanningProvenance,
    RefactorPlan,
)
from reducio.plan_review import advisory_path, identifier


class PatternAgent(BaseAgent):
    async def apply_pattern(self, request: PatternRequest) -> RefactorPlan:
        self._begin_plan(request.allow_fallback)
        pattern = request.pattern.lower()
        if pattern and pattern not in _DESIGN_PATTERNS:
            raise ValueError("Unknown design pattern")
        selected = [pattern] if pattern else ["strategy", "factory"]
        changes = []
        for file in request.files:
            template_used = False
            try:
                tree = file.tree
            except SyntaxError, ValueError:
                self.diagnostics.append(
                    PlanDiagnostic(
                        code="invalid_source",
                        file=file.path,
                        severity="error",
                        message="Cannot read or parse source; planning incomplete",
                    )
                )
                continue
            for name in selected:
                detect, template, subdir = _DESIGN_PATTERNS[name]
                if not detect(tree):
                    continue
                if pattern and self._llm_enabled():
                    try:
                        change = await self._llm_rewrite(
                            file.content,
                            file.path,
                            f"Refactor this Python module to use the {name} design pattern idiomatically, preserving behaviour.",
                            f"LLM {name} refactor",
                        )
                        if change:
                            change.encoding, change.operation = file.encoding, "replace"
                            changes.append(change)
                        continue
                    except ModelRewriteError:
                        if not self.allow_fallback:
                            break
                changes.append(
                    FileChange(
                        path=advisory_path(subdir, file.path, name),
                        original="",
                        modified=template(file.path),
                        operation="create",
                        description=f"Suggest {name.title()} pattern (advisory module)",
                    )
                )
                template_used = True
            if template_used or not (pattern and self._llm_enabled()):
                self.provenance.append(
                    PlanningProvenance(file=file.path, engine="template", outcome="scanned")
                )
        return self._finalize_plan(
            changes,
            f"Proposed {pattern or 'detected'} design patterns for {len(changes)} locations.",
            "pattern",
            pattern=pattern or "auto-detect",
        )


def _tree(content):
    return ast.parse(content) if isinstance(content, str) else content


def _has_complex_conditionals(content) -> bool:
    return sum(isinstance(n, ast.If) for n in ast.walk(_tree(content))) >= 5


def _has_conditional_instantiation(content) -> bool:
    return any(
        isinstance(n, ast.Return) and isinstance(n.value, ast.Call)
        for branch in ast.walk(_tree(content))
        if isinstance(branch, ast.If)
        for n in ast.walk(branch)
    )


def _has_event_handling(content) -> bool:
    names = {"emit", "trigger", "dispatch", "notify", "subscribe"}
    return any(
        (name := getattr(n.func, "id", getattr(n.func, "attr", ""))) in names
        or name.startswith("on_")
        for n in ast.walk(_tree(content))
        if isinstance(n, ast.Call)
    )


def _has_global_state(content) -> bool:
    return any(isinstance(n, ast.Global) for n in ast.walk(_tree(content)))


def _module_name(path: str) -> str:
    name, _ = os.path.splitext(os.path.basename(path))
    return identifier(name)


def _generate_strategy_template(path: str) -> str:
    module = _module_name(path)
    return f'''"""
Strategy pattern implementation for {module}.
"""

from abc import ABC, abstractmethod
from typing import Any


class {module.title()}Strategy(ABC):
    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        pass


class Context:
    def __init__(self, strategy: {module.title()}Strategy):
        self._strategy = strategy

    def set_strategy(self, strategy: {module.title()}Strategy) -> None:
        self._strategy = strategy

    def execute_strategy(self, *args, **kwargs) -> Any:
        return self._strategy.execute(*args, **kwargs)
'''


def _generate_factory_template(path: str) -> str:
    module = _module_name(path)
    return f'''"""
Factory pattern implementation for {module}.
"""

from typing import Any, Dict, Type


class {module.title()}Factory:
    _registry: Dict[str, Type] = {{}}

    @classmethod
    def register(cls, name: str, type_class: Type) -> None:
        cls._registry[name] = type_class

    @classmethod
    def create(cls, name: str, *args, **kwargs) -> Any:
        if name not in cls._registry:
            raise ValueError(f"Unknown type: {{name}}")
        return cls._registry[name](*args, **kwargs)
'''


def _generate_observer_template(path: str) -> str:
    module = _module_name(path)
    return f'''"""
Observer pattern implementation for {module}.
"""

from typing import List


class Observer:
    def update(self, subject: "Subject", *args, **kwargs) -> None:
        pass


class Subject:
    def __init__(self):
        self._observers: List[Observer] = []

    def attach(self, observer: Observer) -> None:
        self._observers.append(observer)

    def detach(self, observer: Observer) -> None:
        self._observers.remove(observer)

    def notify(self, *args, **kwargs) -> None:
        for observer in self._observers:
            observer.update(self, *args, **kwargs)
'''


def _generate_singleton_template(path: str) -> str:
    return '''"""
Singleton pattern implementation.
"""


class Singleton:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
'''


_DESIGN_PATTERNS = {
    "strategy": (_has_complex_conditionals, _generate_strategy_template, "strategies"),
    "factory": (_has_conditional_instantiation, _generate_factory_template, "factories"),
    "observer": (_has_event_handling, _generate_observer_template, "observers"),
    "singleton": (_has_global_state, _generate_singleton_template, "singletons"),
}

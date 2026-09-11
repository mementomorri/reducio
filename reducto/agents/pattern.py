"""
Pattern agent for applying design patterns.
"""

import os
import re

from reducto.agents.base import BaseAgent, ModelRewriteError
from reducto.models import FileChange, PatternRequest, PlanningProvenance, RefactorPlan
from reducto.plan_review import advisory_path, identifier
from reducto.session import SessionStore


class PatternAgent(BaseAgent):
    def __init__(self, workspace=None, llm_router=None, session_store: SessionStore | None = None):
        super().__init__(workspace, llm_router, session_store)

    async def apply_pattern(self, request: PatternRequest) -> RefactorPlan:
        self._begin_plan(request.allow_fallback)
        pattern = request.pattern.lower()
        try:
            if pattern in _DESIGN_PATTERNS:
                changes = await self._apply_design_pattern(request.files, pattern)
            elif pattern == "":
                changes = await self._detect_and_suggest_patterns(request.files)
            else:
                changes = []
        except ModelRewriteError:
            changes = []

        return self._finalize_plan(
            changes,
            f"Proposed {pattern or 'detected'} design patterns for {len(changes)} locations.",
            "pattern",
            pattern=pattern if pattern else "auto-detect",
        )

    async def _apply_design_pattern(self, files, pattern: str) -> list[FileChange]:
        detect, template_fn, subdir = _DESIGN_PATTERNS[pattern]
        changes = []
        for file in files:
            content, path = self._file_content_path(file)
            if not detect(content):
                continue
            if self._llm_enabled():
                try:
                    change = await self._llm_rewrite(
                        content,
                        path,
                        f"Refactor this Python module to use the {pattern} design pattern "
                        "idiomatically, preserving behaviour.",
                        f"LLM {pattern} refactor",
                    )
                    if change:
                        changes.append(change)
                    continue
                except ModelRewriteError:
                    if not self.allow_fallback:
                        raise
            # Every pattern writes a NEW advisory module (original=""); never overwrite the
            # source file — that discarded the original code (singleton used to do this).
            module = _module_name(path)
            changes.append(
                FileChange(
                    path=advisory_path(subdir, path, pattern),
                    original="",
                    modified=template_fn(path),
                    description=f"Extract into {pattern.title()} pattern",
                )
            )
            self.provenance.append(
                PlanningProvenance(file=path, engine="template", outcome="proposed")
            )
        return changes

    async def _detect_and_suggest_patterns(self, files) -> list[FileChange]:
        # Suggestions are written to NEW advisory modules (like the named-pattern path),
        # never with original="" against the source file — that would prepend the template
        # into the real file on apply.
        changes = []
        for file in files:
            content, path = self._file_content_path(file)
            module = _module_name(path)
            if _has_complex_conditionals(content):
                changes.append(
                    FileChange(
                        path=advisory_path("strategies", path, "strategy"),
                        original="",
                        modified=_generate_strategy_template(path),
                        description="Suggest Strategy pattern for complex conditionals",
                    )
                )
            if _has_conditional_instantiation(content):
                changes.append(
                    FileChange(
                        path=advisory_path("factories", path, "factory"),
                        original="",
                        modified=_generate_factory_template(path),
                        description="Suggest Factory pattern for conditional instantiation",
                    )
                )
            self.provenance.append(
                PlanningProvenance(file=path, engine="template", outcome="scanned")
            )
        return changes


def _has_complex_conditionals(content: str) -> bool:
    return content.count("if ") + content.count("elif ") >= 5


def _has_conditional_instantiation(content: str) -> bool:
    for pattern in ("new ", "= new ", "return new "):
        if pattern in content and "if " in content:
            return True
    if "if " in content:
        if re.search(r"return\s+\w+Handler\(\)", content):
            return True
        if re.search(r"return\s+\w+Factory\(\)", content):
            return True
        if re.search(r"return\s+\w+Client\(\)", content):
            return True
        if re.search(r"return\s+\w+\(\)", content) and "elif" in content:
            return True
    return False


def _has_event_handling(content: str) -> bool:
    return any(
        kw in content.lower()
        for kw in ("emit", "trigger", "dispatch", "notify", "subscribe", "on_")
    )


def _has_global_state(content: str) -> bool:
    return "global " in content


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

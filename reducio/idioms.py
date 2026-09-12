"""Conservative source-preserving idioms over a closed set of built-in values.

Unknown values are not type assumptions. Reflection/tracing equivalence is not promised.
"""

from __future__ import annotations

import ast
import io
import operator
import tokenize

from reducio.models import PlanDiagnostic


def value(node: ast.AST, env: dict):
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    try:
        return ast.literal_eval(node)
    except ValueError, TypeError, SyntaxError:
        pass
    if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult):
        left, right = value(node.left, env), value(node.right, env)
        if type(left) is int and type(right) is int and max(abs(left), abs(right)) <= 1000000:
            return {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}[
                type(node.op)
            ](left, right)
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, right = value(node.left, env), value(node.comparators[0], env)
        if type(left) is int and type(right) is int:
            operations = {
                ast.Eq: operator.eq,
                ast.NotEq: operator.ne,
                ast.Lt: operator.lt,
                ast.LtE: operator.le,
                ast.Gt: operator.gt,
                ast.GtE: operator.ge,
            }
            if type(node.ops[0]) in operations:
                return operations[type(node.ops[0])](left, right)
    raise ValueError("Unknown or unsupported value")


def rewrite(content: str, path: str) -> tuple[str, list[str], list[PlanDiagnostic]]:
    tree = ast.parse(content)
    raw = content.encode("utf-8")
    lines = raw.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    comments = {
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(content).readline)
        if token.type == tokenize.COMMENT
    }
    bound = {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }
    bound.update(n.arg for n in ast.walk(tree) if isinstance(n, ast.arg))
    bound.update(
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler)) and n.name
    )
    bound.update(n.rest for n in ast.walk(tree) if isinstance(n, ast.MatchMapping) and n.rest)
    bound.update(
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    bound.update(
        n.asname or n.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.alias)
    )
    dynamic = (
        any(
            isinstance(n, ast.Name) and n.id in {"exec", "eval", "globals", "locals", "vars"}
            for n in ast.walk(tree)
        )
        or "*" in bound
    )
    edits: list[tuple[int, int, bytes, str]] = []
    diagnostics = []

    def source(node):
        return ast.get_source_segment(content, node)

    def edit(first, last, replacement, description):
        if any(line in comments for line in range(first.lineno, last.end_lineno + 1)):
            raise ValueError("Comments overlap candidate")
        start = offsets[first.lineno - 1] + first.col_offset
        end = offsets[last.end_lineno - 1] + last.end_col_offset
        if any(start < old_end and end > old_start for old_start, old_end, *_ in edits):
            raise ValueError("Overlapping edit")
        edits.append((start, end, replacement.encode(), description))

    def skip(node):
        diagnostics.append(
            PlanDiagnostic(
                code="unsafe_idiom",
                file=path,
                message=f"L{node.lineno}: skipped candidate; behavior-preserving prerequisites not established",
            )
        )

    def loop(statements, index, env, function):
        node = statements[index]
        if dynamic or index == 0 or not isinstance(node.target, ast.Name) or node.orelse:
            raise ValueError()
        prior = statements[index - 1]
        if (
            not isinstance(prior, ast.Assign)
            or len(prior.targets) != 1
            or not isinstance(prior.targets[0], ast.Name)
        ):
            raise ValueError()
        accumulator = prior.targets[0].id
        initial = ast.literal_eval(prior.value)
        if type(initial) not in (list, dict) or initial:
            raise ValueError()
        variable = node.target.id
        candidates = {accumulator, variable}
        parameters = {n.arg for n in ast.walk(function.args) if isinstance(n, ast.arg)}
        prior_names = set()
        for statement in statements[: index - 1]:
            for n in ast.walk(statement):
                if isinstance(n, ast.Name):
                    prior_names.add(n.id)
                elif isinstance(n, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler)):
                    prior_names.add(n.name)
                elif isinstance(n, ast.MatchMapping):
                    prior_names.add(n.rest)
                elif isinstance(n, ast.alias):
                    prior_names.add(n.asname or n.name.split(".")[0])
        # Rebinding an existing value can change finalizer timing, even if the
        # name is never read after the loop. Both destination names must be fresh.
        if candidates.intersection(parameters | prior_names):
            raise ValueError()
        if accumulator == variable or any(
            isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(function)
        ):
            raise ValueError()
        if any(
            isinstance(n, ast.Name) and n.id == variable
            for statement in statements[index + 1 :]
            for n in ast.walk(statement)
        ):
            raise ValueError()
        if any(
            isinstance(n, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for n in ast.walk(function)
            if n is not function
        ):
            raise ValueError()
        body = node.body
        predicate = None
        if len(body) == 1 and isinstance(body[0], ast.If) and not body[0].orelse:
            predicate, body = body[0].test, body[0].body
        if len(body) != 1:
            raise ValueError()
        keys = None
        statement = body[0]
        if (
            type(initial) is list
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
        ):
            call = statement.value
            if not (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == accumulator
                and call.func.attr == "append"
                and len(call.args) == 1
                and not call.keywords
            ):
                raise ValueError()
            expression = call.args[0]
        elif (
            type(initial) is dict
            and isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
        ):
            target = statement.targets[0]
            if not (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == accumulator
            ):
                raise ValueError()
            keys, expression = target.slice, statement.value
        else:
            raise ValueError()
        expressions = [
            node.iter,
            expression,
            *([predicate] if predicate else []),
            *([keys] if keys else []),
        ]
        if any(
            isinstance(n, ast.Name) and n.id == accumulator
            for expr in expressions
            for n in ast.walk(expr)
        ):
            raise ValueError()
        if (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and "range" not in bound
            and not node.iter.keywords
        ):
            iterable = range(*(value(arg, env) for arg in node.iter.args))
        else:
            iterable = value(node.iter, env)
        if type(iterable) not in (range, list, tuple) or not 0 < len(iterable) <= 1000:
            raise ValueError()
        # Every expression is evaluated only by the closed interpreter above, never eval().
        for item in iterable:
            if type(item) not in (int, bool, str, bytes, type(None)):
                raise ValueError()
            local = {variable: item}
            if predicate is not None and type(value(predicate, local)) is not bool:
                raise ValueError()
            value(expression, local)
            if keys is not None:
                hash(value(keys, local))
        expr = source(expression)
        if keys is not None:
            expr = f"{source(keys)}: {expr}"
        opening, closing = ("[", "]") if keys is None else ("{", "}")
        condition = f" if {source(predicate)}" if predicate else ""
        edit(
            prior,
            node,
            f"{accumulator} = {opening}{expr} for {variable} in {source(node.iter)}{condition}{closing}",
            "Convert verified loop to "
            + ("list comprehension" if keys is None else "dict comprehension"),
        )

    def expression_edit(node, env, boolean_context=False):
        if dynamic:
            return
        scalar = (int, float, bool, str, bytes, type(None))
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            right = node.comparators[0]
            if (
                isinstance(right, ast.Constant)
                and right.value is None
                and isinstance(node.ops[0], (ast.Eq, ast.NotEq))
            ):
                if type(value(node.left, env)) not in scalar:
                    raise ValueError()
                op = "is" if isinstance(node.ops[0], ast.Eq) else "is not"
                edit(
                    node,
                    node,
                    f"{source(node.left)} {op} None",
                    "Use identity for a known built-in value",
                )
            elif (
                boolean_context
                and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name)
                and node.left.func.id == "len"
            ):
                call = node.left
                if "len" in bound or len(call.args) != 1 or call.keywords or value(right, env) != 0:
                    raise ValueError()
                if type(value(call.args[0], env)) not in (list, tuple, dict, set, str, bytes):
                    raise ValueError()
                if not isinstance(node.ops[0], (ast.Gt, ast.Eq)):
                    raise ValueError()
                prefix = "not " if isinstance(node.ops[0], ast.Eq) else ""
                edit(
                    node, node, f"{prefix}({source(call.args[0])})", "Use known built-in truthiness"
                )
        elif boolean_context and isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            parts = node.values
            if not all(
                isinstance(p, ast.Compare)
                and len(p.ops) == 1
                and isinstance(p.ops[0], ast.Eq)
                and isinstance(p.left, ast.Name)
                for p in parts
            ):
                raise ValueError()
            name = parts[0].left.id
            if (
                not all(p.left.id == name for p in parts)
                or type(value(parts[0].left, env)) not in scalar
            ):
                raise ValueError()
            if not all(
                isinstance(p.comparators[0], ast.Constant)
                and type(p.comparators[0].value) in scalar
                for p in parts
            ):
                raise ValueError()
            edit(
                node,
                node,
                f"{name} in ({', '.join(source(p.comparators[0]) for p in parts)})",
                "Use membership for known immutable values",
            )

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(function)):
            skip(function)
            continue
        env: dict = {}
        for index, statement in enumerate(function.body):
            try:
                if isinstance(statement, ast.For):
                    loop(function.body, index, env, function)
                node = getattr(statement, "test", None) or getattr(statement, "value", None)
                if node is not None and not isinstance(statement, ast.While):
                    expression_edit(node, env, isinstance(statement, ast.If))
            except ValueError, TypeError, OverflowError:
                skip(statement)
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                try:
                    env[statement.targets[0].id] = ast.literal_eval(statement.value)
                except ValueError, TypeError:
                    env.clear()
            else:
                env.clear()
    result = raw
    for start, end, replacement, _ in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    updated = result.decode("utf-8")
    ast.parse(updated)
    return updated, [description for *_, description in edits], diagnostics

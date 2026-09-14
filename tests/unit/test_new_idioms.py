"""The two added idioms must preserve observed behavior and reject uncertainty."""

import pytest

from reducio.idioms import rewrite


@pytest.mark.parametrize(
    "source,fragment",
    [
        ('def f():\n    name = "world"\n    return "Hello {" + name + "}!"\n', "f'"),
        ('def f():\n    n = 42\n    return "Value: " + str(n)\n', "!s}"),
        (
            'def f():\n    d = {"key": 4}\n    if "key" in d:\n        return d["key"]\n    else:\n        return None\n',
            '.get("key", None)',
        ),
        (
            'def f():\n    d = {}\n    key = "key"\n    if key in d:\n        return d[key]\n    return 99\n',
            ".get(key, 99)",
        ),
        (
            'async def f():\n    d = {}\n    if "k" in d:\n        return d["k"]\n    else:\n        return\n',
            '.get("k", None)',
        ),
    ],
)
def test_safe_rewrites_preserve_results(source, fragment):
    modified, descriptions, _ = rewrite(source, "a.py")
    assert descriptions and fragment in modified
    before, after = {}, {}
    exec(source, before)
    exec(modified, after)
    if source.startswith("async"):
        import asyncio

        assert asyncio.run(before["f"]()) == asyncio.run(after["f"]())
    else:
        assert before["f"]() == after["f"]()
    assert rewrite(modified, "a.py")[0] == modified


@pytest.mark.parametrize(
    "source",
    [
        'def f(name):\n    return "hi " + name\n',
        'def f(n):\n    return "n=" + str(n)\n',
        'def f():\n    n = 4\n    return "n=" + str(n)\nstr = lambda n: "other"\n',
        'def f():\n    n = "x"\n    return "a" + n  # preserve this comment\n',
        'def f(d):\n    if "k" in d:\n        return d["k"]\n    return None\n',
        'def f():\n    d = {}\n    if "k" in d:\n        return d["k"]\n    return side_effect()\n',
        "def f():\n    d = {}\n    if side_effect() in d:\n        return d[side_effect()]\n    return None\n",
        'def f():\n    d = {}\n    if "k" in d:\n        return d["other"]\n    return None\n',
        'def f():\n    d = {}\n    if "k" in d:\n        print("side effect")\n        return d["k"]\n    return None\n',
        'def f():\n    d = {}\n    if "k" in d:\n        return d["k"]\n    return [1]\n',
        'def f():\n    return "x" + "y"\n',
        'def f():\n    locals()\n    name = "x"\n    return "hi " + name\n',
    ],
)
def test_unsafe_or_irrelevant_candidates_are_unchanged(source):
    assert rewrite(source, "a.py")[0] == source


@pytest.mark.parametrize(
    "encoding,bom,newline",
    [("utf-8", b"", "\r\n"), ("utf-8", b"\xef\xbb\xbf", "\n"), ("latin-1", b"", "\n")],
)
async def test_new_idiom_saved_plan_preserves_encoding(tmp_path, encoding, bom, newline):
    from reducio.models import AppConfig
    from reducio.services import App

    source = (
        f'# coding: {encoding}\ndef f():\n    name = "café"\n    return "Hi " + name\n'.replace(
            "\n", newline
        )
    )
    file = tmp_path / "a.py"
    file.write_bytes(bom + source.encode(encoding))
    service = App(str(tmp_path), AppConfig())
    plan = await service.idiomatize(str(tmp_path))
    assert plan.changes and plan.complete
    assert service.apply_plan(service.sessions.load_plan(plan.session_id)).success
    assert file.read_bytes().startswith(bom + f"# coding: {encoding}{newline}".encode(encoding))
    assert file.read_bytes().endswith(newline.encode())

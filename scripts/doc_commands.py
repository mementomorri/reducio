"""Parse every documented `reducio …` command against the importable CLI, without running it.

Standalone (stdlib + installed reducio) so release parity can run it inside a clean venv:
    python -I scripts/doc_commands.py <checkout-with-docs>
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.M | re.S)


def documented_commands(root: Path) -> list[tuple[str, str]]:
    found = []
    for path in [root / "README.md", *sorted((root / "docs").glob("*.md"))]:
        if path.is_file():
            for lang, body in FENCE.findall(path.read_text()):
                if lang in ("bash", "sh", "shell", "console", ""):
                    found += [(path.name, line) for line in _reducio_lines(body)]
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        text = re.sub(r"^\s*(- )?run: ", "", path.read_text(), flags=re.M)
        found += [(path.name, line) for line in _reducio_lines(text)]
    return found


def _reducio_lines(text: str) -> list[str]:
    lines = (line.strip().removeprefix("$ ") for line in text.replace("\\\n", " ").splitlines())
    return [line for line in lines if line.startswith("reducio ")]


def parse(line: str) -> None:
    """Resolve (sub)commands and validate options/arguments; raises on drift."""
    from typer.main import get_command

    from reducio.cli import app

    for part in line.split("&&"):
        # --help is eager and exits; it is valid everywhere, so drop it before parsing.
        args = [a for a in shlex.split(part, comments=True)[1:] if a != "--help"]
        command, name = get_command(app), "reducio"
        while hasattr(command, "commands") and args:
            name, *args = args
            command = command.commands[name]
        if not hasattr(command, "commands"):  # a bare group (`reducio --help`) only shows help
            command.make_context(name, args).close()


def main(root: Path) -> int:
    commands = documented_commands(root)
    failures = []
    for source, line in commands:
        try:
            parse(line)
        except BaseException as error:  # click reports usage errors via SystemExit subclasses
            failures.append(f"{source}: {line}: {type(error).__name__}: {error}")
    print("\n".join(failures) or f"{len(commands)} documented commands parse")
    return 1 if failures or not commands else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))

"""Bounded GitHub Actions annotations; no API token or PR write access needed."""

from reducio.models import CompareResult


def _escape(text: str, parameter: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if parameter else text


def github_annotations(result: CompareResult) -> list[str]:
    messages = []
    for change in sorted(
        result.changes,
        key=lambda c: (
            not c.new_hotspot,
            -(c.cyclomatic_delta or 0),
            c.after.file if c.after else c.before.file if c.before else "",
        ),
    ):
        function = change.after
        if not function or not (change.new_hotspot or change.status in ("regressed", "mixed")):
            continue
        text = f"{function.qualified_name}: {change.status}; CC {function.cyclomatic_complexity}, cognitive {function.cognitive_complexity}; Δ CC {change.cyclomatic_delta}, Δ cognitive {change.cognitive_delta}"
        if change.new_hotspot:
            text += "; new hotspot"
        messages.append(
            f"::warning file={_escape(function.file, True)},line={function.line},title=reducio complexity::{_escape(text)}"
        )
    return messages[:10]

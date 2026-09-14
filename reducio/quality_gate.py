"""Quality severity policy shared by CLI reports and library callers."""

LEVELS = ("none", "info", "warning", "critical")


def comparison_failed(result) -> bool:
    if result.gate_threshold == "none":
        return False
    return any(
        c.new_hotspot
        or (result.gate_threshold == "regressions" and c.status in ("regressed", "mixed"))
        for c in result.changes
    )


def evaluate_gate(result: dict, threshold: str) -> dict:
    if threshold not in LEVELS:
        raise ValueError("Unknown quality gate threshold")
    failed = threshold != "none" and any(
        result.get(level, 0) > 0 for level in LEVELS[LEVELS.index(threshold) :]
    )
    return {"gate_threshold": threshold, "gate_failed": failed}

"""Reward function (course-guided: Bespoke state+response check, ART-E tiers).

state check    = original oracle outcome_score (weighted checks over the final workspace), 0..1
response check = agent must not tamper with inputs (in/ hashes unchanged)
tiers          = integrity violation (-1)  <  partial score (0..1)  <  perfect (1.0 + tiny speed bonus)

The speed bonus applies ONLY at full marks so it cannot be farmed (ART-E's repeated-tool-call hack).
Infrastructure failures (harness errors, timeouts) get reward None and are excluded from learning.
"""
from __future__ import annotations

PERFECT_BONUS = 0.05
SPEED_BUDGET_SEC = 300.0


def reward(att: dict) -> float | None:
    err = att.get("error") or ""
    if "harness_error" in err or err == "timeout":
        return None  # infra failure: do not blame the agent (AWM lesson)
    if att.get("integrity_violation"):
        return -1.0
    s = float(att["score"])
    if s >= 0.999:
        return 1.0 + PERFECT_BONUS * max(0.0, 1.0 - att.get("elapsed", SPEED_BUDGET_SEC) / SPEED_BUDGET_SEC)
    return s


def group_advantages(rewards: list[float | None]) -> list[float | None]:
    vals = [r for r in rewards if r is not None]
    if len(vals) < 2:
        return [None] * len(rewards)
    mean = sum(vals) / len(vals)
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    return [None if r is None else ((r - mean) / std if std > 1e-9 else 0.0) for r in rewards]

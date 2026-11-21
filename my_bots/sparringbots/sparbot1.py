"""
always raises
"""

import random  # noqa: F401  (seeded per match, so a seeded match replays exactly)


def decide(game_state: dict) -> dict:
    if game_state.get("type") == "warmup":     # one call before hand 1; load things here if you like
        return {"action": "check"}

    # ── Your strategy goes here. This example is deliberately simple. ──────────
    return {"action": "raise", "amount": game_state["min_raise_to"]}

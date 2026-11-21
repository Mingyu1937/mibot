"""
only plays pairs TT+ or AK/AQ
"""

import random  # noqa: F401  (seeded per match, so a seeded match replays exactly)


def decide(game_state: dict) -> dict:
    if game_state.get("type") == "warmup":     # one call before hand 1; load things here if you like
        return {"action": "check"}

    # ── Your strategy goes here. This example is deliberately simple. ──────────
    cards = game_state["your_cards"]
    ranks = [c[0] for c in cards]
    is_premium = (
        (ranks[0] == ranks[1] and ranks[0] in "AKQJT")
        or (set(ranks) in [{"A", "K"}, {"A", "Q"}])
    )
    if is_premium:
        return {"action": "raise", "amount": game_state["min_raise_to"]}
    if game_state["can_check"]:
        return {"action": "check"}
    return {"action": "fold"}

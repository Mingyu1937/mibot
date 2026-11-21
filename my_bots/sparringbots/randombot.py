"""random legal-ish actions"""
import random
def decide(game_state):
    if game_state.get("type") == "warmup":
        return {"action": "check"}
    r = random.random()
    if r < 0.15:
        return {"action": "fold"} if not game_state["can_check"] else {"action": "check"}
    if r < 0.65:
        return {"action": "call"}
    if r < 0.95:
        return {"action": "raise", "amount": game_state["min_raise_to"] + int(game_state["pot"] * random.random())}
    return {"action": "all_in"}

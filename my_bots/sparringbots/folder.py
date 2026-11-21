"""checks when free, otherwise folds"""
def decide(game_state):
    if game_state.get("type") == "warmup":
        return {"action": "check"}
    return {"action": "check"} if game_state["can_check"] else {"action": "fold"}

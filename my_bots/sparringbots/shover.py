"""always all-in"""
def decide(game_state):
    if game_state.get("type") == "warmup":
        return {"action": "check"}
    return {"action": "all_in"}

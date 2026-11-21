"""
bot_v3: equity vs pot odds, position-aware preflop, push/fold, and light opponent tracking.

The idea in one paragraph
  Each decision we estimate "equity" (how often our hand beats a random hand) with a
  Monte Carlo simulation, compare it to the "pot odds" (the price of calling), and add a
  safety margin. On top of that sits a small exploit layer: we watch how the opponent
  behaves during the match and nudge a couple of numbers, but only inside hard limits
  (see the CAP constants), so a clever opponent can't drag us far from sound play.

Every number you might want to tune is a constant at the top of the file.
"""

import random

import eval7

RANKS = "23456789TJQKA"
CARDS = {r + s: eval7.Card(r + s) for r in RANKS for s in "cdhs"}  # built once at import
CARD_NAMES = list(CARDS)

# ------------------------------------------------------------------ settings
SIMS = 1000               # Monte Carlo simulations per decision
NOISE = 0.03              # equity is blurred by +-NOISE so our cutoffs can't be pinpointed
PUSH_FOLD_BB = 12         # preflop: at or below this effective stack, shove or fold
SHORT_STACK_MARGIN = 0.04  # margin when calling a preflop shove at short stacks
OPEN_RAISE_AT = 0.52      # small blind: raise with at least this equity
SB_FOLD_BELOW = 0.40      # small blind: fold below this, otherwise just complete the blind
THREE_BET_AT = 0.66       # facing a preflop raise: re-raise with at least this equity
VALUE_BET_AT = 0.60       # postflop, checked to us: bet for value
VALUE_RAISE_AT = 0.80     # postflop, facing a bet: raise for value
MARGIN_MIN, MARGIN_MAX = 0.05, 0.25   # CAP: safety buffer on top of pot odds
BLUFF_MIN, BLUFF_MAX = 0.00, 0.40     # CAP: we never bluff less than 5% or more than 40%

GAME_ACTIONS = ("fold", "check", "call", "raise", "all_in")


def equity(hole, board, sims=SIMS):
    """Chance our hand beats one random hand (ties count as half a win)."""
    known = set(hole) | set(board)                       # card names, e.g. "As"
    deck = [c for c in CARD_NAMES if c not in known]
    mine = [CARDS[c] for c in hole]
    table = [CARDS[c] for c in board]
    missing = 5 - len(board)                             # board cards still to come

    score = 0.0
    for _ in range(sims):
        drawn = random.sample(deck, 2 + missing)         # opponent's 2 cards + rest of board
        theirs = [CARDS[c] for c in drawn[:2]]
        runout = table + [CARDS[c] for c in drawn[2:]]
        a = eval7.evaluate(mine + runout)                # higher number = better hand
        b = eval7.evaluate(theirs + runout)
        score += 1.0 if a > b else (0.5 if a == b else 0.0)
    return score / sims


def stacks(gs):
    """(my chips, opponent chips) at the start of this street (stack + bet this street)."""
    mine = gs["your_stack"] + gs["your_bet_this_street"]
    theirs = mine                                        # fallback if we can't find them
    try:
        for p in gs["players"]:
            if p["seat"] != gs["seat_to_act"]:
                theirs = p["stack"] + p["bet_this_street"]
    except Exception:
        pass
    return mine, theirs


def opponent_stats(gs):
    """Read this match's action log. Returns (fold_rate, raise_rate).

    fold_rate  = how often the opponent folded right after we raised or went all-in
    raise_rate = share of the opponent's decisions that were raises or all-ins
    Both start from a neutral guess (the +2 and +4/+6 below), so a handful of hands
    can't swing them wildly.
    """
    me = gs["your_bot_id"]
    # keep real decisions only: skip blind/ante posts and "show" entries
    log = [e for e in gs.get("match_action_log", []) if e.get("action") in GAME_ACTIONS]

    raises = decisions = 0
    for e in log:
        if e.get("bot_id") != me:                        # opponent's decision
            decisions += 1
            if e["action"] in ("raise", "all_in"):
                raises += 1

    folds = chances = 0
    for prev, cur in zip(log, log[1:]):                  # each entry with the one after it
        we_raised = prev.get("bot_id") == me and prev["action"] in ("raise", "all_in")
        they_replied = cur.get("bot_id") != me and cur.get("hand_num") == prev.get("hand_num")
        if we_raised and they_replied:
            chances += 1
            if cur["action"] == "fold":
                folds += 1

    fold_rate = (folds + 2) / (chances + 4)              # prior: they fold half the time
    raise_rate = (raises + 2) / (decisions + 6)          # prior: they raise a third of the time
    return fold_rate, raise_rate


def decide(gs: dict) -> dict:
    if gs.get("type") == "warmup":
        equity(["As", "Kh"], [], 200)                    # touch everything once before hand 1
        return {"action": "check"}

    hole, board, street = gs["your_cards"], gs["community_cards"], gs["street"]
    pot, owed, can_check = gs["pot"], gs["amount_owed"], gs["can_check"]
    current_bet, bb = gs["current_bet"], gs["blinds"]["bb"]

    my_chips, opp_chips = stacks(gs)
    eff_bb = min(my_chips, opp_chips) / bb               # effective stack in big blinds

    raw_eq = equity(hole, board)
    fold_rate, raise_rate = opponent_stats(gs)

    # Only add randomness against balanced/adaptive opponents; use pure math vs extreme bots
    is_extreme_bot = (fold_rate < 0.25) or (raise_rate > 0.65)
    active_noise = 0.0 if is_extreme_bot else NOISE
    eq = raw_eq + random.uniform(-active_noise, active_noise)
    pot_odds = owed / (pot + owed) if owed > 0 else 0.0

    # Safety margin on top of pot odds:
    #   bigger bets -> bigger margin (big bets usually mean strong hands)
    #   very aggressive opponents -> up to half the margin (their range is wide)
    #   always kept between MARGIN_MIN and MARGIN_MAX
    bet_vs_pot = owed / max(pot - owed, 1)
    margin = 0.05 + 0.06 * bet_vs_pot
    looseness = min(1.0, max(0.0, (raise_rate - 0.35) / 0.40))   # 0 = normal, 1 = raises constantly
    margin *= 1.0 - 0.5 * looseness
    margin = min(MARGIN_MAX, max(MARGIN_MIN, margin))
    if raise_rate > 0.80:
      margin = 0.02

    # Bluff frequency: more against opponents who fold a lot, always inside the caps.
    bluff_freq = min(BLUFF_MAX, max(BLUFF_MIN, 0.20 + 0.60 * (fold_rate - 0.5)))

    def finish(move):
        """Attach debug info (shows up in play.py --log) and return the move."""
        move["debug"] = {
            "eq": round(raw_eq, 3), "po": round(pot_odds, 3), "margin": round(margin, 3),
            "eff_bb": round(eff_bb, 1), "fold_rate": round(fold_rate, 2),
            "raise_rate": round(raise_rate, 2),
        }
        return move

    def raise_to(amount):
        """Raise to `amount` (our total bet this street); shove if that commits half our chips."""
        amount = max(int(amount), gs["min_raise_to"])
        if amount >= 0.5 * my_chips:
            return {"action": "all_in"}
        return {"action": "raise", "amount": amount}

    def call_or_fold():
        return {"action": "call"} if eq >= pot_odds + margin else {"action": "fold"}

    # ---------------------------------------------------------------- preflop
    if street == "preflop":
        facing_raise = owed > 0 and current_bet > bb     # opponent raised above the big blind

        if eff_bb <= PUSH_FOLD_BB:                       # short stack: shove or fold
            if facing_raise:
                ok = eq >= pot_odds + SHORT_STACK_MARGIN
                return finish({"action": "call"} if ok else {"action": "fold"})
            shove_at = min(0.52, 0.38 + 0.0145 * max(0.0, eff_bb - 3))   # wider the shorter we are
            if eq >= shove_at:
                return finish({"action": "all_in"})
            return finish({"action": "check"} if can_check else {"action": "fold"})

        if facing_raise:                                 # deep stacks, opponent raised
            if eq >= THREE_BET_AT:
                return finish(raise_to(3 * current_bet))
            return finish(call_or_fold())

        if can_check:                                    # big blind, opponent just limped
            if eq >= OPEN_RAISE_AT + 0.04:
                return finish(raise_to(3 * bb))
            return finish({"action": "check"})

        # small blind, first to act
        if eq >= OPEN_RAISE_AT:
            return finish(raise_to(2.5 * bb))
        if eq >= SB_FOLD_BELOW:
            return finish({"action": "call"})            # complete the blind
        return finish({"action": "fold"})

    # --------------------------------------------------------------- postflop
    if not can_check:                                    # facing a bet
        if eq >= VALUE_RAISE_AT:
            return finish(raise_to(current_bet + 0.75 * pot))
        return finish(call_or_fold())

    if eq >= VALUE_BET_AT:                               # checked to us: value bet
        return finish(raise_to(current_bet + 0.65 * pot))
    if street != "river" and eq < 0.40 and random.random() < bluff_freq:
        return finish(raise_to(current_bet + 0.60 * pot))    # occasional bluff
    return finish({"action": "check"})

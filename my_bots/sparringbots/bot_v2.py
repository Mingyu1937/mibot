"""
bot_v2: equity vs pot odds, plus the things that matter in a heads-up freezeout.

Core idea (same as before)
  equity   = how often our hand wins vs a random opponent hand (Monte Carlo, eval7)
  pot odds = chips we must pay / (pot + chips we must pay)
  Call when equity beats the pot odds plus a safety margin.

What's new compared with a plain equity bot
  1. Preflop is position-aware: the small blind (button) raises about half its
     hands instead of just limping, and the big blind defends by pot odds.
  2. Push/fold: when the effective stack is under ~12 big blinds we either
     shove or fold preflop (blinds rise every 20 hands, so this happens a lot).
  3. The calling margin grows with the size of the bet we face (big bets
     usually mean strong hands).
  4. Commitment rule: if a raise would put in half our stack, just go all-in.
  5. A small amount of bluffing on the flop/turn when checked to.
"""

import random

import eval7

RANKS = "23456789TJQKA"
CARDS = {r + s: eval7.Card(r + s) for r in RANKS for s in "cdhs"}  # built once
CARD_NAMES = list(CARDS)

SIMS = 1000          # Monte Carlo simulations per decision (~5-10 ms)
PUSH_FOLD_BB = 12    # preflop: below this effective stack (in big blinds) shove or fold
BLUFF_FREQ = 0.25    # how often we bluff on the flop/turn when checked to with a weak hand


def equity(hole, board, sims=SIMS):
    """Chance our hand wins vs one random hand (ties count as half a win)."""
    known = set(hole) | set(board)               # strings are safe to put in a set
    deck = [c for c in CARD_NAMES if c not in known]
    mine = [CARDS[c] for c in hole]
    table = [CARDS[c] for c in board]
    missing = 5 - len(board)                     # board cards still to come

    score = 0.0
    for _ in range(sims):
        drawn = random.sample(deck, 2 + missing)
        theirs = [CARDS[c] for c in drawn[:2]]
        runout = table + [CARDS[c] for c in drawn[2:]]
        a = eval7.evaluate(mine + runout)
        b = eval7.evaluate(theirs + runout)
        score += 1.0 if a > b else (0.5 if a == b else 0.0)
    return score / sims


def stacks(gs):
    """(my chips, opponent chips) at the start of this street (stack + bet this street)."""
    mine = gs["your_stack"] + gs["your_bet_this_street"]
    theirs = mine  # fallback if we can't find the opponent
    try:
        for p in gs["players"]:
            if p["seat"] != gs["seat_to_act"]:
                theirs = p["stack"] + p["bet_this_street"]
    except Exception:
        pass
    return mine, theirs


def decide(gs: dict) -> dict:
    if gs.get("type") == "warmup":
        equity(["As", "Kh"], [], 200)            # touch everything once before hand 1
        return {"action": "check"}

    hole, board, street = gs["your_cards"], gs["community_cards"], gs["street"]
    pot, owed, can_check = gs["pot"], gs["amount_owed"], gs["can_check"]
    current_bet, bb = gs["current_bet"], gs["blinds"]["bb"]

    my_chips, opp_chips = stacks(gs)
    eff_bb = min(my_chips, opp_chips) / bb       # effective stack in big blinds

    eq = equity(hole, board)
    pot_odds = owed / (pot + owed) if owed > 0 else 0.0

    # Calling margin: demand more equity against bigger bets.
    bet_vs_pot = owed / max(pot - owed, 1)       # size of their bet relative to the pot before it
    margin = 0.05 + 0.06 * min(bet_vs_pot, 1.5)

    def finish(move):
        move["debug"] = {"eq": round(eq, 3), "po": round(pot_odds, 3), "eff_bb": round(eff_bb, 1)}
        return move

    def raise_to(amount):
        """Raise to `amount` (total this street); shove if it commits half our chips."""
        amount = max(int(amount), gs["min_raise_to"])
        if amount >= 0.5 * my_chips:
            return {"action": "all_in"}
        return {"action": "raise", "amount": amount}

    def call_or_fold():
        return {"action": "call"} if eq >= pot_odds + margin else {"action": "fold"}

    # ---------------------------------------------------------------- preflop
    if street == "preflop":
        facing_raise = owed > 0 and current_bet > bb   # opponent raised above the big blind

        if eff_bb <= PUSH_FOLD_BB:                     # short stack: shove or fold
            if facing_raise:
                return finish(call_or_fold())
            shove_at = min(0.52, 0.38 + 0.0145 * max(0.0, eff_bb - 3))   # wider the shorter we are
            if eq >= shove_at:
                return finish({"action": "all_in"})
            return finish({"action": "check"} if can_check else {"action": "fold"})

        if facing_raise:                               # deep stacks, opponent raised
            if eq >= 0.75:
                return finish(raise_to(3 * current_bet))
            return finish(call_or_fold())

        if can_check:                                  # big blind, opponent just limped
            if eq >= 0.58:
                return finish(raise_to(3 * bb))
            return finish({"action": "check"})

        # small blind, first to act: raise good hands, complete/fold the rest
        if eq >= 0.52:
            return finish(raise_to(2.5 * bb))
        return finish(call_or_fold())

    # --------------------------------------------------------------- postflop
    if not can_check:                                  # facing a bet
        if eq >= 0.80:
            return finish(raise_to(current_bet + 0.75 * pot))
        return finish(call_or_fold())

    if eq >= 0.60:                                     # checked to us: value bet
        return finish(raise_to(current_bet + 0.65 * pot))
    if street != "river" and eq < 0.40 and random.random() < BLUFF_FREQ:
        return finish(raise_to(current_bet + 0.60 * pot))   # occasional bluff
    return finish({"action": "check"})

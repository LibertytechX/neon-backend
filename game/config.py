"""
Server-authoritative game configuration.

This is the single source of truth for outcomes. The frontend keeps its own
copy for visuals (glyphs/colors), but PAYOUTS and WEIGHTS here decide money.
Keep weights/payouts in sync with the frontend's symbols if you want the UI's
"expected" odds to match what the server actually pays.
"""

CURRENCY = "CRD"
REELS = 4

# value = payout multiplier base, weight = relative frequency on a reel.
# Rarer symbols (low weight) carry higher value. The house edge is the gap
# between these weighted odds and the payout table below.
SYMBOLS = [
    {"glyph": "⚡", "value": 5, "weight": 5},
    {"glyph": "◆", "value": 8, "weight": 4},
    {"glyph": "★", "value": 12, "weight": 3},
    {"glyph": "❖", "value": 15, "weight": 3},
    {"glyph": "♦", "value": 20, "weight": 2},
    {"glyph": "7", "value": 50, "weight": 1},
]

# win = round(bet * symbol.value * PAYOUTS[match_count]); missing count = no win.
PAYOUTS = {4: 1.0, 3: 0.4, 2: 0.12}

PHASE_MULTIPLIERS = [1, 2, 4, 8]
PHASE_NAMES = ["PHASE 1", "PHASE 2", "PHASE 3", "BONUS"]

# bet size -> highest phase the player may climb to on the gamble ladder.
BET_TIERS = [
    {"bet": 10, "maxPhase": 0},
    {"bet": 25, "maxPhase": 1},
    {"bet": 50, "maxPhase": 2},
    {"bet": 100, "maxPhase": 3},
]

RISK_ODDS = 0.5  # probability a RISK gamble step succeeds


def bet_tier(bet):
    for t in BET_TIERS:
        if t["bet"] == bet:
            return t
    return None


def max_phase_for_bet(bet):
    t = bet_tier(bet)
    return t["maxPhase"] if t else 0


def public_config():
    """Config payload safe to return to the frontend."""
    return {
        "currency": CURRENCY,
        "reels": REELS,
        "symbols": SYMBOLS,
        "payouts": {str(k): v for k, v in PAYOUTS.items()},
        "phaseMultipliers": PHASE_MULTIPLIERS,
        "phaseNames": PHASE_NAMES,
        "betTiers": BET_TIERS,
        "riskOdds": RISK_ODDS,
    }

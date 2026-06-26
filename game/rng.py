"""
Provably-fair outcome engine.

Every outcome is derived deterministically from:
    HMAC-SHA256(key=server_seed, msg="<client_seed>:<nonce>:<cursor>")

The server commits to a hashed server_seed up front (SHA-256). After the seed
is rotated, the raw server_seed is revealed so a player can recompute every
reel and risk result and confirm nothing was tampered with.

This module is pure (no Django imports) so it's trivially unit-testable.
"""
import hashlib
import hmac
import secrets


def new_server_seed():
    return secrets.token_hex(32)


def server_seed_hash(server_seed):
    return hashlib.sha256(server_seed.encode()).hexdigest()


def _float_stream(server_seed, client_seed, nonce):
    """Yield an endless stream of uniform floats in [0, 1)."""
    cursor = 0
    while True:
        msg = f"{client_seed}:{nonce}:{cursor}".encode()
        digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).digest()
        for i in range(0, 32, 4):  # 8 four-byte words per HMAC block
            yield int.from_bytes(digest[i:i + 4], "big") / 4294967296.0
        cursor += 1


def build_pool(symbols):
    pool = []
    for idx, sym in enumerate(symbols):
        pool.extend([idx] * int(sym.get("weight", 1)))
    return pool


def spin_reels(symbols, reels, server_seed, client_seed, nonce):
    """Deterministically choose `reels` weighted symbol indices."""
    pool = build_pool(symbols)
    stream = _float_stream(server_seed, client_seed, nonce)
    return [pool[min(int(next(stream) * len(pool)), len(pool) - 1)] for _ in range(reels)]


def best_match(reels):
    """Return (count, symbol_index) for the most frequent symbol.

    Ties are broken toward the lowest symbol index, matching the frontend's
    countMax (which scans ascending and keeps the first strict maximum).
    """
    counts = {}
    for r in reels:
        counts[r] = counts.get(r, 0) + 1
    best_count, best_sym = 0, reels[0]
    for sym in sorted(counts):
        if counts[sym] > best_count:
            best_count, best_sym = counts[sym], sym
    return best_count, best_sym


def win_amount(reels, symbols, payouts, bet):
    count, sym = best_match(reels)
    mult = payouts.get(count)
    win = round(bet * symbols[sym]["value"] * mult) if mult else 0
    return win, count, sym


def risk_succeeds(server_seed, client_seed, nonce, step, odds):
    """Deterministic 50/50 (or `odds`) for the RISK gamble at a given step."""
    msg = f"risk:{client_seed}:{nonce}:{step}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).digest()
    val = int.from_bytes(digest[:4], "big") / 4294967296.0
    return val < odds

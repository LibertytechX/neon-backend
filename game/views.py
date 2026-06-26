"""
NEON RUSH game API.

Flow (server-authoritative outcomes, external-authoritative balances):
  POST /api/session  -> {userId}            : commit a provably-fair seed, read balance
  POST /api/spin     -> {userId, bet}       : debit bet on the external backend, decide reels+win
  POST /api/risk     -> {roundId}           : decide a 50/50 gamble step
  POST /api/bank     -> {roundId}           : credit the pot on the external backend
  POST /api/rotate   -> {userId}            : reveal old seed, start a new one (provably fair)
  GET  /api/verify   -> ?roundId            : inputs (+ revealed seed) to recompute a round
  GET  /api/config   :                        public game config
  GET  /api/health   :                        liveness
"""
import json

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import config as gconf
from . import rng
from .external import ExternalError, charge, credit, get_balance
from .models import PlayerSeed, Round


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _err(message, status=400, **extra):
    return JsonResponse({"error": message, **extra}, status=status)


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return None


def _check_token(request):
    """If a shared secret is configured, require it on play endpoints."""
    secret = settings.SESSION_SHARED_SECRET
    if not secret:
        return True
    return request.headers.get("X-Session-Token") == secret


def _get_seed(user_id, client_seed=None):
    seed, created = PlayerSeed.objects.get_or_create(
        user_id=user_id,
        defaults={
            "server_seed": rng.new_server_seed(),
            "client_seed": client_seed or rng.new_server_seed()[:16],
        },
    )
    if created:
        seed.server_seed_hash = rng.server_seed_hash(seed.server_seed)
        seed.save(update_fields=["server_seed_hash"])
    if client_seed and client_seed != seed.client_seed:
        seed.client_seed = client_seed
        seed.save(update_fields=["client_seed"])
    return seed


# --------------------------------------------------------------------------
# meta endpoints
# --------------------------------------------------------------------------
def health(request):
    return JsonResponse({"ok": True, "mock_external": settings.MOCK_EXTERNAL})


def config(request):
    return JsonResponse(gconf.public_config())


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------
@csrf_exempt
def session(request):
    if request.method != "POST":
        return _err("POST required", 405)
    if not _check_token(request):
        return _err("unauthorized", 401)
    data = _body(request)
    if data is None:
        return _err("invalid JSON")
    user_id = str(data.get("userId") or "").strip()
    if not user_id:
        return _err("userId required")

    seed = _get_seed(user_id, data.get("clientSeed"))
    try:
        balance = get_balance(user_id, token=request.headers.get("X-Session-Token"))
    except ExternalError as exc:
        return _err(f"balance backend error: {exc}", 502)

    return JsonResponse({
        "userId": user_id,
        "balance": balance,
        "currency": gconf.CURRENCY,
        "serverSeedHash": seed.server_seed_hash,
        "clientSeed": seed.client_seed,
        "nonce": seed.nonce,
        "config": gconf.public_config(),
    })


# --------------------------------------------------------------------------
# spin
# --------------------------------------------------------------------------
@csrf_exempt
def spin(request):
    if request.method != "POST":
        return _err("POST required", 405)
    if not _check_token(request):
        return _err("unauthorized", 401)
    data = _body(request)
    if data is None:
        return _err("invalid JSON")

    user_id = str(data.get("userId") or "").strip()
    if not user_id:
        return _err("userId required")
    try:
        bet = int(data.get("bet"))
    except (TypeError, ValueError):
        return _err("bet must be an integer")
    if gconf.bet_tier(bet) is None:
        return _err("invalid bet")

    token = request.headers.get("X-Session-Token")
    seed = _get_seed(user_id, data.get("clientSeed"))

    # affordability pre-check only if a balance-read endpoint is configured;
    # otherwise the charge endpoint is the source of truth for affordability.
    try:
        balance = get_balance(user_id, token=token)
    except ExternalError as exc:
        return _err(f"balance backend error: {exc}", 502)
    if balance is not None and balance < bet:
        return _err("insufficient balance", 402, balance=balance)

    # advance the provably-fair nonce and compute the outcome
    seed.nonce += 1
    seed.save(update_fields=["nonce"])
    nonce = seed.nonce
    reels = rng.spin_reels(gconf.SYMBOLS, gconf.REELS, seed.server_seed, seed.client_seed, nonce)
    win, count, sym = rng.win_amount(reels, gconf.SYMBOLS, gconf.PAYOUTS, bet)

    rnd = Round.objects.create(
        user_id=user_id, bet=bet, reels=reels, count=count, symbol=sym,
        base_win=win, phase=0, pot=win,
        status=Round.ACTIVE if win > 0 else Round.CLOSED,
        server_seed_hash=seed.server_seed_hash, client_seed=seed.client_seed, nonce=nonce,
    )

    # debit the bet on the external backend (charge/token)
    try:
        charge(user_id, bet, f"neon{rnd.id.hex}b", token=token)
    except ExternalError as exc:
        rnd.delete()
        seed.nonce -= 1
        seed.save(update_fields=["nonce"])
        return _err(f"debit declined: {exc}", 402)

    # the charge endpoint doesn't return a balance; derive it if we read one above
    balance_out = (balance - bet) if balance is not None else None

    return JsonResponse({
        "roundId": str(rnd.id),
        "reels": reels,
        "count": count,
        "symbol": sym,
        "win": win,
        "pot": win,
        "phase": 0,
        "maxPhase": gconf.max_phase_for_bet(bet),
        "balance": balance_out,
        "serverSeedHash": seed.server_seed_hash,
        "nonce": nonce,
    })


# --------------------------------------------------------------------------
# risk (gamble ladder)
# --------------------------------------------------------------------------
@csrf_exempt
def risk(request):
    if request.method != "POST":
        return _err("POST required", 405)
    if not _check_token(request):
        return _err("unauthorized", 401)
    data = _body(request)
    if data is None:
        return _err("invalid JSON")
    round_id = str(data.get("roundId") or "").strip()
    if not round_id:
        return _err("roundId required")

    try:
        rnd = Round.objects.get(id=round_id)
    except (Round.DoesNotExist, ValueError):
        return _err("round not found", 404)
    if rnd.status != Round.ACTIVE:
        return _err("round not active", 409, status=rnd.status)

    max_phase = gconf.max_phase_for_bet(rnd.bet)
    if rnd.phase >= max_phase:
        return _err("phase ceiling for this bet", 409, atCap=True, phase=rnd.phase)

    seed = PlayerSeed.objects.get(user_id=rnd.user_id)
    if seed.server_seed_hash != rnd.server_seed_hash:
        return _err("seed rotated mid-round", 409)

    step = rnd.risk_steps + 1
    won = rng.risk_succeeds(seed.server_seed, rnd.client_seed, rnd.nonce, step, gconf.RISK_ODDS)
    rnd.risk_steps = step
    if won:
        rnd.phase += 1
        rnd.pot *= 2
    else:
        rnd.pot = 0
        rnd.status = Round.BUSTED
    rnd.save(update_fields=["risk_steps", "phase", "pot", "status", "updated_at"])

    return JsonResponse({
        "roundId": str(rnd.id),
        "won": won,
        "phase": rnd.phase,
        "pot": rnd.pot,
        "atCap": rnd.phase >= max_phase,
        "status": rnd.status,
    })


# --------------------------------------------------------------------------
# bank (collect)
# --------------------------------------------------------------------------
@csrf_exempt
def bank(request):
    if request.method != "POST":
        return _err("POST required", 405)
    if not _check_token(request):
        return _err("unauthorized", 401)
    data = _body(request)
    if data is None:
        return _err("invalid JSON")
    round_id = str(data.get("roundId") or "").strip()
    if not round_id:
        return _err("roundId required")

    try:
        rnd = Round.objects.get(id=round_id)
    except (Round.DoesNotExist, ValueError):
        return _err("round not found", 404)
    if rnd.status != Round.ACTIVE:
        return _err("round not active", 409, status=rnd.status)

    amount = rnd.pot
    token = request.headers.get("X-Session-Token")
    balance = None
    if amount > 0:
        try:
            balance = credit(rnd.user_id, amount, f"neon{rnd.id.hex}w", token=token)
        except ExternalError as exc:
            return _err(f"credit failed: {exc}", 502)
    else:
        try:
            balance = get_balance(rnd.user_id, token=token)
        except ExternalError:
            balance = None

    rnd.status = Round.BANKED
    rnd.save(update_fields=["status", "updated_at"])

    return JsonResponse({"roundId": str(rnd.id), "amount": amount, "balance": balance})


# --------------------------------------------------------------------------
# provably-fair: rotate seed + verify
# --------------------------------------------------------------------------
@csrf_exempt
def rotate(request):
    if request.method != "POST":
        return _err("POST required", 405)
    if not _check_token(request):
        return _err("unauthorized", 401)
    data = _body(request)
    if data is None:
        return _err("invalid JSON")
    user_id = str(data.get("userId") or "").strip()
    if not user_id:
        return _err("userId required")

    try:
        seed = PlayerSeed.objects.get(user_id=user_id)
    except PlayerSeed.DoesNotExist:
        return _err("no seed for user", 404)
    if Round.objects.filter(user_id=user_id, status=Round.ACTIVE).exists():
        return _err("settle active rounds before rotating", 409)

    old_seed, old_hash = seed.server_seed, seed.server_seed_hash
    # reveal the old seed on every round that used it, so they become verifiable
    Round.objects.filter(user_id=user_id, server_seed_hash=old_hash).update(server_seed=old_seed)

    seed.server_seed = rng.new_server_seed()
    seed.server_seed_hash = rng.server_seed_hash(seed.server_seed)
    seed.nonce = 0
    seed.rotated_at = timezone.now()
    if data.get("clientSeed"):
        seed.client_seed = str(data["clientSeed"])
    seed.save()

    return JsonResponse({
        "revealedServerSeed": old_seed,
        "previousServerSeedHash": old_hash,
        "newServerSeedHash": seed.server_seed_hash,
        "clientSeed": seed.client_seed,
    })


def verify(request):
    round_id = request.GET.get("roundId", "").strip()
    if not round_id:
        return _err("roundId required")
    try:
        rnd = Round.objects.get(id=round_id)
    except (Round.DoesNotExist, ValueError):
        return _err("round not found", 404)

    out = {
        "roundId": str(rnd.id),
        "bet": rnd.bet,
        "reels": rnd.reels,
        "win": rnd.base_win,
        "clientSeed": rnd.client_seed,
        "nonce": rnd.nonce,
        "serverSeedHash": rnd.server_seed_hash,
        "status": rnd.status,
    }
    if rnd.server_seed:
        # seed has been revealed (rotated) — return it + a server recomputation
        recomputed = rng.spin_reels(gconf.SYMBOLS, gconf.REELS, rnd.server_seed, rnd.client_seed, rnd.nonce)
        out["serverSeed"] = rnd.server_seed
        out["recomputedReels"] = recomputed
        out["verified"] = recomputed == rnd.reels
    else:
        out["serverSeed"] = None
        out["note"] = "Rotate the seed (POST /api/rotate) to reveal serverSeed and verify."
    return JsonResponse(out)

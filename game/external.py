"""
Adapter to the Liberty hustleback balance backend (owns the real player balances).

It exposes three operations to the game:
  * get_balance(user_id)          -> int | None   (optional read; None if no endpoint)
  * charge(user_id, amount, ref)  -> debit a bet  (POST charge/token)
  * credit(user_id, amount, ref)  -> credit a win -> new balance (POST credit/earning)

Real endpoints (from Liberty):
  POST /payment/other-games/charge/token/   {user_id, amount, unique_reference}
      -> {"status":"success","data":{"amount_charged":..,"unique_reference":..}}
  POST /payment/other-games/credit/earning/ {user_id, amount, unique_reference}
      -> {"status":"success","data":{"balance_after":..,"amount_credited":..}}

Header auth: x-api-key: <service key>.  amount is always a positive integer.

MOCK_EXTERNAL=True keeps balances in local SQLite so the whole loop runs offline.
"""
import logging

import requests
from django.conf import settings
from django.db import transaction

logger = logging.getLogger("game.external")


class ExternalError(Exception):
    """Raised when the balance backend is unreachable or declines a call."""


# --------------------------------------------------------------------------
# Mock implementation (local SQLite) — used when settings.MOCK_EXTERNAL
# --------------------------------------------------------------------------
def _default_balance():
    import os
    return int(os.environ.get("MOCK_START_BALANCE", "1000"))


def _mock_get(user_id):
    from .models import MockBalance
    row, _ = MockBalance.objects.get_or_create(user_id=str(user_id), defaults={"balance": _default_balance()})
    return int(row.balance)


@transaction.atomic
def _mock_move(user_id, delta):
    from .models import MockBalance
    row, _ = MockBalance.objects.select_for_update().get_or_create(
        user_id=str(user_id), defaults={"balance": _default_balance()}
    )
    new_balance = int(row.balance) + int(delta)
    if new_balance < 0:
        raise ExternalError("insufficient balance")
    row.balance = new_balance
    row.save(update_fields=["balance"])
    return new_balance


# --------------------------------------------------------------------------
# Real implementation (HTTP to hustleback)
# --------------------------------------------------------------------------
def _headers():
    h = {"Content-Type": "application/json"}
    if settings.EXTERNAL_API_KEY:
        h[settings.EXTERNAL_API_KEY_HEADER] = settings.EXTERNAL_API_KEY
    return h


def _coerce_user(user_id):
    """hustleback expects an integer user_id; pass through if non-numeric."""
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return user_id


def _post(path, user_id, amount, ref):
    url = settings.EXTERNAL_BASE_URL.rstrip("/") + path
    payload = {"user_id": _coerce_user(user_id), "amount": int(amount), "unique_reference": ref}
    try:
        r = requests.post(url, json=payload, headers=_headers(), timeout=settings.EXTERNAL_TIMEOUT)
    except requests.RequestException as exc:
        logger.exception("external POST %s failed", path)
        raise ExternalError(str(exc))
    if r.status_code >= 400:
        # surface the backend's message (e.g. insufficient funds) without leaking internals
        try:
            msg = r.json().get("message", r.text[:200])
        except ValueError:
            msg = r.text[:200]
        raise ExternalError(f"{r.status_code}: {msg}")
    try:
        body = r.json()
    except ValueError:
        raise ExternalError("non-JSON response from balance backend")
    if str(body.get("status", "")).lower() not in ("success", "ok", "true", ""):
        raise ExternalError(body.get("message", "declined"))
    return body.get("data", {}) or {}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _dig(obj, dotpath):
    """Traverse a dot-separated key path into a nested dict."""
    for key in dotpath.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def get_balance(user_id, token=None):
    """Read the player's token balance from hustleback. Returns None if no endpoint configured."""
    if settings.MOCK_EXTERNAL:
        return _mock_get(user_id)
    if not settings.EXTERNAL_BALANCE_PATH:
        return None
    url = settings.EXTERNAL_BASE_URL.rstrip("/") + settings.EXTERNAL_BALANCE_PATH
    try:
        r = requests.get(url, params={"user_id": _coerce_user(user_id)}, headers=_headers(),
                         timeout=settings.EXTERNAL_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        data = body.get("data") or body
        raw = _dig(data, settings.EXTERNAL_BALANCE_FIELD) if settings.EXTERNAL_BALANCE_FIELD else data.get("balance")
        return int(float(raw)) if raw is not None else None
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        logger.exception("external get_balance failed")
        raise ExternalError(str(exc))


def charge(user_id, amount, ref, token=None):
    """Debit a bet. Raises ExternalError if declined (e.g. insufficient funds)."""
    if settings.MOCK_EXTERNAL:
        _mock_move(user_id, -int(amount))
        return True
    _post(settings.EXTERNAL_CHARGE_PATH, user_id, amount, ref)
    return True


def credit(user_id, amount, ref, token=None):
    """Credit a win. Returns the new balance (balance_after) when provided."""
    if settings.MOCK_EXTERNAL:
        return _mock_move(user_id, int(amount))
    data = _post(settings.EXTERNAL_CREDIT_PATH, user_id, amount, ref)
    bal = data.get("balance_after")
    return int(bal) if bal is not None else None

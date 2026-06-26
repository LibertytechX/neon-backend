import uuid

from django.db import models


class MockBalance(models.Model):
    """Local stand-in for the external balance backend (MOCK_EXTERNAL mode only)."""
    user_id = models.CharField(max_length=128, unique=True)
    balance = models.BigIntegerField(default=1000)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_id}: {self.balance}"


class PlayerSeed(models.Model):
    """Provably-fair seed pair + nonce counter for a player."""
    user_id = models.CharField(max_length=128, unique=True)
    server_seed = models.CharField(max_length=64)        # revealed on rotation
    server_seed_hash = models.CharField(max_length=64)   # committed up front
    client_seed = models.CharField(max_length=128, default="")
    nonce = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"seed[{self.user_id}] nonce={self.nonce}"


class Round(models.Model):
    """One spin and its gamble ladder — the authoritative audit record."""
    ACTIVE = "active"        # spin won; gamble (risk/bank) still open
    CLOSED = "closed"        # spin had no win
    BANKED = "banked"        # player collected the pot
    BUSTED = "busted"        # player lost the pot on a risk

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.CharField(max_length=128, db_index=True)
    bet = models.IntegerField()
    reels = models.JSONField()
    count = models.IntegerField()
    symbol = models.IntegerField()
    base_win = models.IntegerField()
    phase = models.IntegerField(default=0)
    pot = models.IntegerField(default=0)
    risk_steps = models.IntegerField(default=0)
    status = models.CharField(max_length=8, default=ACTIVE)

    # provably-fair snapshot
    server_seed_hash = models.CharField(max_length=64)
    client_seed = models.CharField(max_length=128)
    nonce = models.BigIntegerField()
    server_seed = models.CharField(max_length=64, default="")  # filled on settle

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"round[{self.id}] {self.user_id} bet={self.bet} {self.status}"

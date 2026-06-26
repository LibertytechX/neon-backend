import json

from django.test import Client, TestCase

from . import config as gconf
from . import rng
from .models import MockBalance, PlayerSeed, Round


class RngTests(TestCase):
    def test_deterministic(self):
        a = rng.spin_reels(gconf.SYMBOLS, 4, "seed", "client", 1)
        b = rng.spin_reels(gconf.SYMBOLS, 4, "seed", "client", 1)
        self.assertEqual(a, b)

    def test_nonce_changes_outcome(self):
        a = rng.spin_reels(gconf.SYMBOLS, 4, "seed", "client", 1)
        b = rng.spin_reels(gconf.SYMBOLS, 4, "seed", "client", 2)
        self.assertNotEqual(a, b)  # vanishingly unlikely to collide

    def test_best_match_and_win(self):
        win, count, sym = rng.win_amount([2, 2, 2, 2], gconf.SYMBOLS, gconf.PAYOUTS, 25)
        self.assertEqual(count, 4)
        self.assertEqual(sym, 2)
        self.assertEqual(win, round(25 * gconf.SYMBOLS[2]["value"] * 1.0))

    def test_hash_commit(self):
        s = rng.new_server_seed()
        self.assertEqual(len(rng.server_seed_hash(s)), 64)


class ApiFlowTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.uid = "user-123"

    def post(self, path, payload):
        return self.c.post(path, data=json.dumps(payload), content_type="application/json")

    def test_session_creates_seed_and_balance(self):
        r = self.post("/api/session", {"userId": self.uid})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["balance"], 1000)
        self.assertEqual(len(data["serverSeedHash"]), 64)
        self.assertTrue(PlayerSeed.objects.filter(user_id=self.uid).exists())

    def test_full_win_and_bank_updates_balance(self):
        self.post("/api/session", {"userId": self.uid})
        # spin until we get a win (deterministic per nonce, so just loop a few)
        win_round = None
        for _ in range(40):
            r = self.post("/api/spin", {"userId": self.uid, "bet": 25}).json()
            if r["win"] > 0:
                win_round = r
                break
        self.assertIsNotNone(win_round, "expected a win within 40 spins")
        bal_after_bet = win_round["balance"]
        bank = self.post("/api/bank", {"roundId": win_round["roundId"]}).json()
        self.assertEqual(bank["amount"], win_round["win"])
        self.assertEqual(bank["balance"], bal_after_bet + win_round["win"])

    def test_insufficient_balance(self):
        MockBalance.objects.create(user_id="poor", balance=5)
        self.post("/api/session", {"userId": "poor"})
        r = self.post("/api/spin", {"userId": "poor", "bet": 25})
        self.assertEqual(r.status_code, 402)

    def test_bet_deducted(self):
        self.post("/api/session", {"userId": self.uid})
        before = MockBalance.objects.get(user_id=self.uid).balance
        r = self.post("/api/spin", {"userId": self.uid, "bet": 25}).json()
        self.assertEqual(r["balance"], before - 25)

    def test_risk_capped_by_bet(self):
        self.post("/api/session", {"userId": self.uid})
        # bet 10 -> maxPhase 0 -> risk should be rejected on any win
        for _ in range(60):
            r = self.post("/api/spin", {"userId": self.uid, "bet": 10}).json()
            if r["win"] > 0:
                rr = self.post("/api/risk", {"roundId": r["roundId"]})
                self.assertEqual(rr.status_code, 409)
                return
        self.skipTest("no win in 60 spins to test the cap")

    def test_verify_after_rotate(self):
        self.post("/api/session", {"userId": self.uid})
        spin = self.post("/api/spin", {"userId": self.uid, "bet": 25}).json()
        # settle any active round so rotation is allowed
        if Round.objects.filter(user_id=self.uid, status=Round.ACTIVE).exists():
            self.post("/api/bank", {"roundId": spin["roundId"]})
        self.post("/api/rotate", {"userId": self.uid})
        v = self.c.get("/api/verify", {"roundId": spin["roundId"]}).json()
        self.assertIsNotNone(v["serverSeed"])
        self.assertTrue(v["verified"])

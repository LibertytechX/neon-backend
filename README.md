# NEON RUSH — Game Backend (Django)

Server-authoritative outcome engine for the `<neon-slot>` game. It **decides every
spin and gamble result** (so players can't cheat the client) and **orchestrates
balances** by talking to your separate balance backend — it never owns the money
itself.

```
Frontend (<neon-slot>)  ──userId──▶  THIS backend  ──debit/credit──▶  Your balance backend
                        ◀─reels,win─               ◀────balance─────
```

- **Outcomes:** provably-fair RNG (HMAC-SHA256) with a configurable house edge.
- **Balances:** read on session, debited on spin, credited on bank — all via your
  external backend. Our DB only stores rounds, seeds, and an audit trail.
- **Storage:** SQLite by default (Postgres optional).
- **Deploy:** Docker / Procfile / gunicorn ready.

---

## Quick start (local, no external backend needed)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # defaults run in MOCK_EXTERNAL mode
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

In `MOCK_EXTERNAL=true` (the default) balances live in local SQLite, so you can
play the entire loop with zero external setup. Test it:

```bash
curl -X POST localhost:8000/api/session -H 'content-type: application/json' -d '{"userId":"demo-1"}'
curl -X POST localhost:8000/api/spin    -H 'content-type: application/json' -d '{"userId":"demo-1","bet":25}'
```

Run the test suite:

```bash
python manage.py test          # 10 tests: RNG determinism, full win→bank, debit, cap, verify
```

---

## Balance backend (Liberty hustleback)

Already wired in [`game/external.py`](game/external.py) to your two endpoints
(auth via `x-api-key`, positive `amount`, unique `unique_reference` per call):

| Game action | Your endpoint | Returns |
|---|---|---|
| Debit a **bet** | `POST /payment/other-games/charge/token/` | `{status, data}` |
| Credit a **win** | `POST /payment/other-games/credit/earning/` | `{status, data:{balance_after}}` |

The game sends a unique reference per transaction: `neon<roundId>b` for the bet
debit and `neon<roundId>w` for the win credit — use these for idempotency.

To go live, set in `.env`:

```bash
MOCK_EXTERNAL=false
EXTERNAL_BASE_URL=https://hustleback.libertydraw.com
EXTERNAL_API_KEY=<your x-api-key>
```

**Notes**
- The **charge** endpoint enforces affordability (no separate balance-read endpoint
  was provided). A declined charge → the game returns `402` and the spin is voided.
- Only **credit** returns the new balance (`balance_after`); the debit does not, so
  after a spin the displayed balance is the frontend's local figure until the next
  credit re-syncs it. **If you have a balance-read endpoint**, set
  `EXTERNAL_BALANCE_PATH` and the backend will use it on session + after spins.

---

## API

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /api/health` | — | `{ok, mock_external}` |
| `GET /api/config` | — | symbols, payouts, bet tiers, phase multipliers |
| `POST /api/session` | `{userId, clientSeed?}` | `{balance, currency, serverSeedHash, clientSeed, nonce, config}` |
| `POST /api/spin` | `{userId, bet}` | `{roundId, reels, count, symbol, win, pot, phase, maxPhase, balance, nonce}` |
| `POST /api/risk` | `{roundId}` | `{won, phase, pot, atCap, status}` |
| `POST /api/bank` | `{roundId}` | `{amount, balance}` |
| `POST /api/rotate` | `{userId, clientSeed?}` | `{revealedServerSeed, previousServerSeedHash, newServerSeedHash}` |
| `GET /api/verify` | `?roundId` | inputs + (after rotate) `serverSeed` & recomputation |

Money timing: **bet is debited on `/spin`**, **win is credited on `/bank`** (the pot
is held server-side through the RISK ladder; a bust pays nothing).

---

## Wire the frontend to it

In your landing page, point the component's hooks at this API:

```html
<script src="https://cdn.jsdelivr.net/gh/dtekluva/neon2@v1/neon-slot.js"></script>
<neon-slot id="slot" currency="CRD"></neon-slot>
<script>
  const API = "https://your-game-backend.example.com/api";
  const el  = document.getElementById("slot");
  const userId = window.MY_USER_ID;          // you provide this at init
  let roundId = null;

  // 1) init: read the authoritative balance
  const s = await fetch(`${API}/session`, {method:"POST", headers:{'content-type':'application/json'},
                        body: JSON.stringify({userId})}).then(r=>r.json());
  el.setBalance(s.balance);

  // 2) spin: the server decides the reels & win, and debits the bet
  el.resolveSpin = async (bet) => {
    const r = await fetch(`${API}/spin`, {method:"POST", headers:{'content-type':'application/json'},
                          body: JSON.stringify({userId, bet})}).then(x=>x.json());
    roundId = r.roundId;
    el.setBalance(r.balance);                // authoritative balance after the debit
    return { reels: r.reels, win: r.win };
  };

  // 3) risk: the server decides each 50/50 climb
  el.resolveRisk = async () => {
    const r = await fetch(`${API}/risk`, {method:"POST", headers:{'content-type':'application/json'},
                          body: JSON.stringify({roundId})}).then(x=>x.json());
    return { won: r.won };
  };

  // 4) bank: the server credits the pot
  el.addEventListener("bank", async () => {
    const r = await fetch(`${API}/bank`, {method:"POST", headers:{'content-type':'application/json'},
                          body: JSON.stringify({roundId})}).then(x=>x.json());
    if (r.balance != null) el.setBalance(r.balance);
  });
</script>
```

---

## Provably fair

Each spin/risk outcome = `HMAC-SHA256(server_seed, "<client_seed>:<nonce>:<cursor>")`.
The server commits `sha256(server_seed)` up front (`serverSeedHash`). Call
`POST /api/rotate` to reveal the old `server_seed` and start a new one; then
`GET /api/verify?roundId=...` returns the seed + a recomputation so anyone can
confirm the reels weren't tampered with.

---

## Deploy

**Docker**

```bash
docker build -t neon-backend .
docker run -p 8000:8000 --env-file .env neon-backend   # runs migrate then gunicorn
```

**Procfile** (Heroku/Render/Railway): `release` runs migrations, `web` runs gunicorn.

**Postgres:** set `POSTGRES_DB/USER/PASSWORD/HOST/PORT` and uncomment
`psycopg2-binary` in `requirements.txt`.

**Production checklist**
- `DJANGO_DEBUG=false`, a real `DJANGO_SECRET_KEY`, set `DJANGO_ALLOWED_HOSTS`.
- `MOCK_EXTERNAL=false` + your balance backend configured.
- Lock CORS: `CORS_ALLOW_ALL=false` + `CORS_ALLOWED_ORIGINS=https://yourdomain`.
- Set `SESSION_SHARED_SECRET` and have the frontend send `X-Session-Token`, **or**
  better: validate a per-user token issued by your balance backend (the current
  build trusts `userId` from the client — fine for play-money, tighten for value).
- Put it behind HTTPS.

## Security notes
- The client sends `userId`. For anything with real value, require a signed
  session token (see checklist) so a user can't spin as someone else.
- Bet debit + round insert aren't a single distributed transaction; `ref` (round
  UUID) is provided so your backend can dedupe/settle idempotently.

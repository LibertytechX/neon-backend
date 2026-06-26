# NEON RUSH — Deploy & Push Guide

How to ship changes to the live game backend.

---

## The two repos

| App | Repo | What it is |
|---|---|---|
| **Backend** (this repo) | `git@github.com:LibertytechX/neon-backend.git` | Django outcome engine + hustleback wallet integration. Runs on the droplet behind nginx. |
| **Embed / frontend component** | `git@github.com:dtekluva/neon2.git` | The `<neon-slot>` web component (`neon-slot.js`). Served to players via jsDelivr CDN (`@v1`), embedded in the host site. |

The frontend embeds the component and points its API base at the backend:

```js
const API = "https://game.libertydraw.com/api";
```

---

## Live deployment

| | |
|---|---|
| **URL** | `https://game.libertydraw.com` (also `www.`) |
| **Server** | `root@207.154.208.93` (Ubuntu 24.04 droplet) |
| **App dir** | `/opt/neonslot` |
| **Service** | `neon.service` (systemd → gunicorn on `127.0.0.1:8000`, user `neon`) |
| **Web** | nginx reverse-proxy, TLS via Let's Encrypt (auto-renew) |
| **Env / secrets** | `/opt/neonslot/.env` (chmod 600 — **never committed**) |
| **DB** | SQLite at `/opt/neonslot/db.sqlite3` |

---

## Push a change (local → GitHub → server)

**1. Commit & push from your machine** (in this `backend/` dir):

```bash
git add -A
git commit -m "your change"
git push origin main
```

**2. Pull & restart on the server:**

```bash
ssh root@207.154.208.93 'cd /opt/neonslot && git pull && \
  .venv/bin/pip install -r requirements.txt && \
  .venv/bin/python manage.py migrate --noinput && \
  .venv/bin/python manage.py collectstatic --noinput && \
  systemctl restart neon'
```

**3. Verify:**

```bash
curl -s https://game.libertydraw.com/api/health
# {"ok": true, "mock_external": false}
```

---

## Service management (on the server)

```bash
systemctl status neon          # is it running?
systemctl restart neon         # restart after a change
journalctl -u neon -n 50 --no-pager   # recent logs / tracebacks
systemctl reload nginx         # after editing nginx config
nginx -t                       # test nginx config before reload
```

---

## Editing config / secrets

Secrets live only in `/opt/neonslot/.env` on the server (not in git). After editing:

```bash
ssh root@207.154.208.93 'nano /opt/neonslot/.env && systemctl restart neon'
```

Key flags:
- `MOCK_EXTERNAL=false` — **live** wallets (charge/credit hit real hustleback balances).
- `DJANGO_DEBUG=false` — production.
- `DJANGO_ALLOWED_HOSTS` — locked to the domain + IP.
- `CORS_ALLOW_ALL=true` — open. To lock down: set `CORS_ALLOW_ALL=false` and
  `CORS_ALLOWED_ORIGINS=https://your-host` then restart.

---

## TLS

Certbot auto-renews. Manual check / dry run:

```bash
ssh root@207.154.208.93 'certbot certificates && certbot renew --dry-run'
```

---

## First-time server setup (already done — for reference / rebuild)

```bash
apt update && apt install -y nginx python3-venv python3-pip certbot python3-certbot-nginx
git clone https://github.com/LibertytechX/neon-backend.git /opt/neonslot
useradd --system --home /opt/neonslot --shell /usr/sbin/nologin neon
cd /opt/neonslot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# create /opt/neonslot/.env (see .env.example), chmod 600
.venv/bin/python manage.py migrate --noinput
chown -R neon:neon /opt/neonslot
# systemd unit: /etc/systemd/system/neon.service  (gunicorn neonslot_api.wsgi --bind 127.0.0.1:8000 --workers 2)
systemctl enable --now neon
# nginx site: /etc/nginx/sites-available/neon  (proxy / -> 127.0.0.1:8000, server_name game.libertydraw.com www.game.libertydraw.com)
ln -sf /etc/nginx/sites-available/neon /etc/nginx/sites-enabled/neon && rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d game.libertydraw.com -d www.game.libertydraw.com --redirect -m you@example.com --agree-tos -n
ufw allow OpenSSH && ufw allow "Nginx Full" && ufw --force enable
```

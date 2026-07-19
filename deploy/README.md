# Deploying aigov.bg to a Hetzner server

Target: a small Hetzner Cloud VM (CX22 is plenty), Debian 12 / Ubuntu 24.04,
with the `aigov.bg` DNS A-record pointed at it. Everything below runs as root
unless stated otherwise.

## 1. Clone and install

```bash
git clone <your-repo-url> /opt/aigov
cd /opt/aigov
bash deploy/install.sh
```

`install.sh` is idempotent and:

- installs git, curl, caddy, node/npm;
- creates the system user `aigov` and `/var/www/aigov`;
- installs `uv` for the `aigov` user and syncs Python deps;
- installs + enables both systemd timers
  (`aigov-ingest.timer` hourly, `aigov-session.timer` 07:15 & 16:15 Sofia);
- appends `deploy/Caddyfile` to `/etc/caddy/Caddyfile` (auto-HTTPS) and reloads;
- runs the first site build into `/var/www/aigov`.

## 2. Log in the claude CLI (one manual step)

The cabinet sessions run `claude -p` as the `aigov` user:

```bash
su - aigov
npm install -g @anthropic-ai/claude-code   # if not already installed
claude                                     # complete the login once
exit
```

Without this the ingest keeps working (it is plain Python) but sessions fail —
tasks stay in `tasks/pending/` until the login is fixed.

## 3. Verify

```bash
systemctl list-timers 'aigov-*'                 # both timers scheduled
systemctl start aigov-ingest.service            # manual ingest run
su - aigov -c 'cd /opt/aigov && deploy/run-session.sh --dry-run'  # fake-brain rehearsal
curl -I https://aigov.bg                        # 200 from Caddy
```

The dry-run rehearses enqueue → session → publish → site build with zero
token cost, then `aigov status` prints the queue and published state.

## 4. Operations

- Update code: `cd /opt/aigov && git pull && bash deploy/install.sh`.
- Logs: `journalctl -u aigov-session.service -n 100` (same for ingest).
- Failed tasks: `ls tasks/failed/` — each has `reason.txt`; re-queue by
  moving the directory back to `tasks/pending/` after fixing the cause.
- The queue (`tasks/`) and `data/` are ephemeral; `published/` is the only
  content that matters — back it up (it is also committed to git by the
  publish workflow if you choose to run it from CI later).

## Cost model

- Ingest: free (pure Python, hourly).
- Cabinet sessions: 2×/day batch runs of the `claude` CLI under your
  existing Claude subscription — no API keys, no per-token billing.
- The site is static files behind Caddy: no runtime cost.

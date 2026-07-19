#!/usr/bin/env bash
# One-shot server install for aigov.bg (Debian/Ubuntu, run as root).
# Idempotent: safe to re-run after a git pull.
#
#   bash deploy/install.sh
#
# Assumes the repo is (or will be) at /opt/aigov. See deploy/README.md for
# the full Hetzner walkthrough, including claude CLI login.
set -euo pipefail

REPO=/opt/aigov
WWW=/var/www/aigov

echo "== 1. system packages =="
apt-get update -qq
apt-get install -y -qq git curl caddy nodejs npm >/dev/null

echo "== 2. aigov user + directories =="
id -u aigov &>/dev/null || useradd --system --create-home --shell /bin/bash aigov
mkdir -p "$WWW"
chown aigov:aigov "$WWW"

if [ ! -d "$REPO/.git" ]; then
    echo "ERROR: clone the repo to $REPO first (git clone <url> $REPO)" >&2
    exit 1
fi
chown -R aigov:aigov "$REPO"

echo "== 3. uv + python deps (as aigov) =="
su - aigov -c 'command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'
su - aigov -c "cd $REPO && ~/.local/bin/uv sync --no-dev"

echo "== 4. systemd units =="
cp "$REPO"/deploy/aigov-ingest.service /etc/systemd/system/
cp "$REPO"/deploy/aigov-ingest.timer /etc/systemd/system/
cp "$REPO"/deploy/aigov-session.service /etc/systemd/system/
cp "$REPO"/deploy/aigov-session.timer /etc/systemd/system/
chmod +x "$REPO"/deploy/run-ingest.sh "$REPO"/deploy/run-session.sh "$REPO"/site/build.sh
systemctl daemon-reload
systemctl enable --now aigov-ingest.timer aigov-session.timer

echo "== 5. caddy =="
if ! grep -q "aigov.bg" /etc/caddy/Caddyfile 2>/dev/null; then
    cat "$REPO"/deploy/Caddyfile >> /etc/caddy/Caddyfile
fi
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy

echo "== 6. first build =="
su - aigov -c "cd $REPO && AIGOV_WWW=$WWW bash site/build.sh"

echo
echo "Done. Remaining manual step: log the 'claude' CLI in as the aigov user"
echo "(su - aigov; claude), otherwise cabinet sessions will fail."
echo "Timers: systemctl list-timers 'aigov-*'"

#!/usr/bin/env bash
# Build the static site from ../published/ and deploy it.
#
# Usage: site/build.sh [target_dir]
#   target_dir defaults to $AIGOV_WWW, then /var/www/aigov.
#   If the target's parent does not exist (e.g. local dev), the build stops
#   after `astro build` and dist/ holds the result.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

npx astro build

TARGET="${1:-${AIGOV_WWW:-/var/www/aigov}}"
if [ -d "$(dirname "$TARGET")" ]; then
  mkdir -p "$TARGET"
  # rsync-like replace: clear old build, copy the new one
  rm -rf "${TARGET:?}"/*
  cp -r dist/* "$TARGET"/
  echo "deployed to $TARGET"
else
  echo "target parent $(dirname "$TARGET") missing — build left in site/dist/"
fi

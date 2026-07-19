#!/usr/bin/env bash
# Hourly data collection (free, pure Python — no LLM involved).
# Invoked by aigov-ingest.timer. Repo root autodetected from this script.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

uv run aigov ingest

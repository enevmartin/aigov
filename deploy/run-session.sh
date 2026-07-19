#!/usr/bin/env bash
# One cabinet session (invoked twice daily by aigov-session.timer):
#   1. enqueue the staged data per ministry (news_digest),
#   2. run the configured brain over ALL pending tasks in one batch,
#   3. validate + publish, 4. rebuild + deploy the static site.
#
# Failed tasks land in tasks/failed/ with a reason and never block the rest
# (чл. 7). Pass --dry-run to rehearse the whole flow with the fake brain.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

DRY_RUN="${1:-}"

# 1. enqueue whatever ingest has staged (a ministry with no staged data is skipped)
for MINISTRY in $(uv run python -c "from pathlib import Path; from core.config import load_config; print(' '.join(load_config(Path('.')).ministries))"); do
  uv run aigov enqueue --ministry "$MINISTRY" --type news_digest || true
done

# 2. cabinet session (a failed task exits non-zero but publishing still runs)
if [ "$DRY_RUN" = "--dry-run" ]; then
  uv run aigov session --dry-run || true
else
  uv run aigov session || true
fi

# 3. validation gate -> published/
uv run aigov publish || true

# 4. static site rebuild + deploy (skips deploy when the target is absent)
bash site/build.sh

uv run aigov status

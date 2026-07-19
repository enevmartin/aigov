# aigov.bg — AI e-government of Bulgaria

Every ministry is an AI agent (a "minister") that collects public data
(statistics, news, open data), generates analyses and reports **in Bulgarian**,
and publishes them to a static public dashboard. The full Council of
Ministers (18 ministries, verified against the official administrative
register) is declared; ministries activate one flag at a time.

## Architecture (ports and adapters)

Three invariants no code ever violates (see CLAUDE.md — the constitution):

1. **`core/` never imports from `brains/`** and contains zero LLM-provider
   code. The core speaks only through the file-based task contract; the
   session loop receives its brain through an injected resolver.
2. **`site/` reads only `published/`** — static JSON/Markdown artifacts, no
   APIs, no databases.
3. **`ministries/` are declarations only** — YAML + prompt files, zero
   executable code.

Swapping the brain is a one-line change in `config.yaml`
(`brain: claude_code | openclaw | api`) — and each ministry may override it
individually, so two ministries can run on different brains in the same
cabinet session:

```yaml
ministries:
  - slug: finance
    enabled: true
    brain: claude_code   # optional per-ministry override
```

```
aigov/
├── config.yaml          # brain selection, cabinet roster, schedules
├── core/                # ingest, file queue, contracts, session, publish, CLI
├── brains/              # adapters: claude_code (implemented), openclaw, api (skeletons w/ real exporters)
├── ministries/          # declarative: ministry.yaml + prompts/ per ministry (18 + PM)
├── site/                # Astro static dashboard (reads ../published/)
├── published/           # validated artifacts + index.json + system/health.json
├── data/                # ephemeral: raw/ (git-ignored), staging/
├── deploy/              # systemd timers, install.sh, Caddyfile
└── tests/               # pytest incl. deterministic fake brain + grand e2e
```

## Task types (all situations)

| Type | Trigger | Output |
|---|---|---|
| `news_digest` | daily | news.json + short review |
| `analysis` | new statistical data | report.md + aggregates.json |
| `weekly_report` | Sunday | consolidated week from the ministry's own publications |
| `crisis_brief` | keyword spike detected by **pure-Python** scan in ingest | short brief with mandatory `confidence` + `trigger_keywords` |
| `joint_report` | on demand / schedule | "prime minister" composes ONLY from already-published reports (2+ contributors) |
| `signal_triage` | citizen signals (phase 3; schema ready) | signals.json — anonymized aggregate stats only, `total == sum(buckets)` enforced |
| `data_quality_alert` | ingest failure/anomaly (core-generated, no LLM) | event in published/system/health.json |

Detections and triggers are deterministic Python in the core; the LLM is
called only for the analysis itself. The publish gate (`core/publish`)
validates every artifact against the pydantic contract per type — invalid
output lands in `failed/` with a reason, never in public.

## Failure semantics

- A brain-failed task is retried once in the next session; the second
  failure parks it in `failed/` + raises a `task_failed` health event.
- A session that dies mid-run (e.g. exhausted Pro limit) resumes from the
  first unprocessed task — checkpointing through the queue itself
  (`running/` tasks stale >2h are reclaimed).
- A source failing 3 consecutive times becomes `degraded` in
  `published/system/health.json` (rendered at `/system`) without blocking
  the other sources. One bad task never blocks the others.

## Portable ministers

One declaration exports to any orchestration:

```bash
uv run aigov export --ministry finance --brain claude_code  # .claude/agents/finance.md subagent
uv run aigov export --ministry finance --brain openclaw     # AgentSkill package (ClawHub-ready)
uv run aigov export --ministry finance --brain api          # system prompt + tools JSON
```

Exporters live in each brain's package and are real even where the runner
is still a skeleton.

## Development

```bash
uv sync                    # install deps (Python 3.12+)
uv run pytest              # tests never call a real LLM (deterministic fake brain)
uv run ruff check .
uv run mypy core brains
uv run aigov status        # ingest | enqueue | session [--dry-run] | publish | status | export
bash deploy/run-session.sh --dry-run   # rehearse a full cabinet session, zero tokens
```

Reports, prompts and the site are in Bulgarian; code, commits and this README
are in English. Deployment (Hetzner, systemd timers, Caddy): `deploy/README.md`.

## Legal guardrails

- Every report cites its sources (URL + retrieval date) — schema-enforced.
- Minister prompts explicitly forbid claims about specific individuals,
  political insinuations, and unverifiable accusations.
- Citizen signals are never published raw — aggregate statistics only,
  enforced by the SignalStats schema.
- Scraping: robots.txt respected, ≥1.5s rate limit, honest User-Agent with
  contact. All ministry sources live-verified (2026-07-20); unreachable ones
  are declared `enabled: false` with the reason.

# aigov.bg — AI e-government of Bulgaria

Every ministry is an AI agent (a "minister") that collects public data
(statistics, news, open data), generates analyses and reports **in Bulgarian**,
and publishes them to a static public dashboard.

## Architecture (ports and adapters)

Three invariants no code ever violates:

1. **`core/` never imports from `brains/`** and contains zero LLM-provider
   code. The core speaks only through the file-based task contract.
2. **`site/` reads only `published/`** — static JSON/Markdown artifacts, no
   APIs, no databases.
3. **`ministries/` are declarations only** — YAML + prompt files, zero
   executable code.

Swapping the brain is a one-line change in `config.yaml`
(`brain: claude_code | openclaw | api`).

```
aigov/
├── config.yaml          # brain selection, ministries, schedules
├── core/                # ingest, file queue, contracts, publish, CLI
├── brains/              # adapters: claude_code (implemented), openclaw, api (skeletons)
├── ministries/          # declarative: ministry.yaml + prompts/ per ministry
├── site/                # Astro static dashboard (reads ../published/)
├── published/           # validated artifacts: {ministry}/{date}/report.md + aggregates.json + news.json
├── data/                # ephemeral: raw/ (git-ignored), staging/
├── deploy/              # systemd timers, install.sh, Caddyfile
└── tests/               # pytest: contracts, queue, publish, e2e with a fake brain
```

## The task contract

A task is a directory in `tasks/pending/{task_id}/` containing `task.yaml`,
`input/` data, and `expected.schema.json`. A brain — any brain — processes it
and leaves `report.md`, `aggregates.json` (and `news.json` for digests) in
`tasks/done/{task_id}/output/`. `core/publish` validates the output against
the schema, rejects invalid results into `failed/` with a reason, and moves
valid ones into `published/`. Brains never write to `published/` directly.

## Development

```bash
uv sync                  # install deps (Python 3.12+)
uv run pytest            # tests never call a real LLM (deterministic fake brain)
uv run ruff check .
uv run mypy core
uv run aigov status      # CLI: ingest | enqueue | publish | status
```

Reports, prompts and the site are in Bulgarian; code, commits and this README
are in English.

## Legal guardrails

- Every report cites its sources (URL + retrieval date).
- Minister prompts explicitly forbid claims about specific individuals,
  political insinuations, and unverifiable accusations.
- Citizen signals (phase 2) are never published raw — aggregate statistics only.

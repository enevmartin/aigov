# aigov.bg — AI e-government of Bulgaria

Every ministry is an AI agent (a "minister") that collects public data
(statistics, news, open data), generates analyses and reports **in Bulgarian**,
and publishes them to a static public dashboard. The full Council of
Ministers (18 ministries, verified against the official administrative
register) is declared; ministries activate one flag at a time.

**aigov.bg is an independent civic AI experiment. It is NOT affiliated with
the government of the Republic of Bulgaria** — the site carries this
disclaimer on every page, and every minister persona is an obvious AI figure.

## Architecture (ports and adapters)

Three invariants no code ever violates (see CLAUDE.md — the constitution):

1. **`core/` never imports from `brains/`** and contains zero LLM-provider
   code; the session loop receives its brain through an injected resolver.
2. **`site/` reads only `published/`** — static JSON/Markdown artifacts.
3. **`ministries/` are declarations only** — YAML + prompt files, zero code.

Swapping the brain is a one-line change in `config.yaml`, per ministry if
needed — two ministries can run on different brains in the same session.
`aigov export` turns any ministry declaration into a Claude Code subagent,
an OpenClaw AgentSkill package, or a system-prompt+tools JSON.

## The pipeline (trust built in)

```
ingest (pure Python, hourly)          detections are code, not AI
  └─ tasks/pending/{id}/              file contract: task.yaml + input/
       └─ cabinet session             brain per task; batch run, 2×/day
            └─ REVIEW (second reading) same brain, different hat: sources,
               approve / revise (≤1)   numbers vs aggregates, guardrails
                 └─ core/publish       pydantic gate; unreviewed/invalid
                      └─ published/    never goes public
                           └─ site     Astro static build
```

- **Review stage:** no report is published unreviewed. Approve stamps
  `reviewed: true, reviewer:` into the front-matter (stamped by core, not
  by the brain); revise sends the task back with actionable notes (max 1
  revision, then failed + health event).
- **Institutional memory:** every published `aggregates.json` lands in a
  local DuckDB archive (git-ignored, rebuildable); the PUBLIC archive is
  `published/{ministry}/timeseries.json` — full history for the dashboard.
  Analyses receive `history.json` (their own trend) as input; crisis briefs
  use a short history as context against false alarms.
- **Corrections are first-class:** `aigov correct <ministry> <date>`
  publishes a separate correction carrying `corrects:`; the original gains
  a `corrected_by.json` sidecar and is NEVER edited (byte-identical,
  verified by test). Corrected numbers replace same-date archive points.
- **Observability:** `published/system/sessions.json` records ministry,
  type, brain, duration and token usage per task; `/system` renders the
  ministry × type × brain breakdown, source degradation and the event log.

## Task types

| Type | Trigger | Output |
|---|---|---|
| `news_digest` | daily | news.json + short review |
| `analysis` | new statistical data | report.md + aggregates.json |
| `weekly_report` | Sunday | consolidated week from own publications |
| `crisis_brief` | keyword spike (pure-Python detector) | brief with mandatory confidence + trigger keywords |
| `joint_report` | on demand | "PM" composes ONLY from published reports (2+ contributors) |
| `plan` | quarterly | the minister's priorities — checkable in 3 months |
| `correction` | `aigov correct` | separate publication; original inviolable |
| `signal_triage` | phase 4 (schema ready) | anonymized aggregates only |
| `review` | automatic after every task | review.json verdict (never published) |
| `data_quality_alert` | core-generated, no LLM | event in system/health.json |

Published layout: `published/{ministry}/{date}/{type}/…` (one task = one
publication; same-day publications never clobber each other).

## The site

Astro, fully static, Bulgarian, dark mode, self-hosted IBM Plex (Cyrillic):

- **Home** — "Състоянието на България днес": KPI band with deltas, active
  crisis briefs, latest reports, the cabinet (incl. "подготвя се" cards)
- **Ministry** — persona, KPI hero, interactive full-history charts
  (zoom, 1м/6м/1г/всички), tabs Анализи | Седмични | Дайджести | Поправки
- **/analizi** — all reports, client-side search + filters
- **/planove** — ministers' quarterly plans + the project roadmap
- **/danni** — every series browsable + downloadable (JSON/CSV), source
  status, full methodology
- **/za-proekta** — what/how/who + the disclaimer
- **/system** — health, sessions, breakdowns
- RSS feed, sitemap, OG image, semantic HTML, `lang="bg"`

## Development

```bash
uv sync                    # Python 3.12+, deps incl. duckdb
uv run pytest              # 213 tests, zero LLM calls (deterministic fake brain)
uv run ruff check . && uv run mypy core brains
uv run aigov --help        # ingest | enqueue | session [--dry-run] | publish |
                           # status | export | correct
bash deploy/run-session.sh --dry-run   # full cabinet rehearsal, zero tokens
cd site && npm install && npx astro build
```

Reports, prompts and the site are in Bulgarian; code, commits and this README
are in English. Deployment (Hetzner, systemd timers, Caddy): `deploy/README.md`.

## Legal guardrails

- Every report cites its sources (URL + retrieval date) — schema-enforced,
  double-checked by the review stage.
- Minister prompts explicitly forbid claims about specific individuals,
  political insinuations, and unverifiable accusations.
- Citizen signals are never published raw — aggregate statistics only.
- Scraping: robots.txt respected, ≥1.5s rate limit, honest User-Agent.
  All sources live-verified; unreachable ones declared `enabled: false`
  with the reason.
- History is inviolable: originals are never edited — corrections stand
  beside them, visibly linked in both directions.

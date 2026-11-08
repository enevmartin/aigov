# Audit progress — AUDIT-2026-11

Started 2026-11-08. Auditor: Claude (Opus 5.5). Scope: read-only; commits only under `docs/audit/`.
Measurements on a clean worktree of HEAD `8e5fb84` (scratchpad); uncommitted WIP reported separately.

| Блок | Тема | Статус | Бележка |
|---|---|---|---|
| 1 | Инвентаризация | done | 36 комита (19-20.07); aigov.bg NXDOMAIN; само fake сесии |
| 2 | Здраве на кода | done | pytest 1 FAIL (дата-зависим), ruff/mypy OK, cov 94% |
| 3 | Архитектурни инварианти | done | dynamic import brains в core/cli.py; guardrails не стигат до runner |
| 4 | Опашка и откази | done | poison task без timeout; publish дата от LLM може да презапише |
| 5 | Министрите (subagents) | in progress | 4/4 партиди + кабинет върнати; spot-check 4 твърдения ✓ |
| 6 | Източници (subagents) | todo | |
| 7 | Сайтът | todo | |
| 8 | Сигурност и право | todo | |
| 9 | Реалност | todo | |
| 10 | Harness пейзаж (subagents) | todo | |
| 11 | Harness engineering | todo | |
| 12 | Spike (branch) | todo | |
| 13 | Доклад | todo | |

## Spot-checks на subagent находки
(попълва се)

# Audit progress — AUDIT-2026-11

Started 2026-11-08. Auditor: Claude (Opus 5.5). Scope: read-only; commits only under `docs/audit/`.
Measurements on a clean worktree of HEAD `8e5fb84` (scratchpad); uncommitted WIP reported separately.

| Блок | Тема | Статус | Бележка |
|---|---|---|---|
| 1 | Инвентаризация | done | 36 комита (19-20.07); aigov.bg NXDOMAIN; само fake сесии |
| 2 | Здраве на кода | done | pytest 1 FAIL (дата-зависим), ruff/mypy OK, cov 94% |
| 3 | Архитектурни инварианти | done | dynamic import brains в core/cli.py; guardrails не стигат до runner |
| 4 | Опашка и откази | done | poison task без timeout; publish дата от LLM може да презапише |
| 5 | Министрите (subagents) | done | 4 партиди + кабинет (iisda) върнати; таблица в доклада |
| 6 | Източници (subagents) | done | 3 subagents; 11 RSS, 18 сайта, статистика; robots-отклонение на агент — оповестено |
| 7 | Сайтът | done | 27 стр., disclaimer 27/27, zero-data 7 стр., 2г. данни OK; няма robots.txt |
| 8 | Сигурност и право | done | без секрети; XSS вектор; npm audit critical; без CSP |
| 9 | Реалност | НЕПРОВЕРЕНО | aigov.bg NXDOMAIN (DoH 1.1.1.1, 2026-11-08); sessions.json само fake (0.046s, tokens null) |
| 10 | Harness пейзаж (subagents) | done | 2 research subagents, URL+дата |
| 11 | Harness engineering | in progress |  |
| 12 | Spike (branch) | done | branch spike/api 4b49948, 7 теста зелени, без merge |
| 13 | Доклад | todo | |

## Spot-checks на subagent находки
Лично проверени от одитора (команда + изход в evidence/notes.md):
- Партида A: `brains/claude_code/runner.py:31-61,116-139` и `brains/common.py:30-38` — guardrails не се инжектират в runner ✓ потвърдено
- RSS агент: `core/ingest/rss.py:111-121`, `core/cli.py:99-107` — нов ScraperBase на министерство; без robots в HEAD ✓
- Партида D/B: `невъплатени` (labor:37), `Волт` (energy:5), `Просвета` (education:5), „синтезирана от архивите“ (foreign-affairs:8), „обучена върху“ (interior:8) ✓
- Статистика агент: `core/ingest/capture.py:15` „Append-only… nothing is ever deleted“ (WIP) ✓; export SKILL.md без YAML frontmatter ✓
- Сайтове/статистика агенти (противоречие за НСИ URL): /113, /117, /136, /141/432 — и четирите валидни (заглавия) ✓
- Кабинет агент: имената economy:1, innovation:1 съвпадат с решението от 08.05.2026 ✓

# Spike: `brains/api` — generic OpenAI-compatible brain

- **Branch:** `spike/api`, commit `4b49948` on top of `8e5fb84`. **No merge.**
- **Created:** 2026-11-08 (Блок 12 на AUDIT-2026-11)
- **Real model:** none. Tests use `httpx.MockTransport`, which serves the output of `tests/fake_brain.py` for the same task (Чл. 6).

## Какво прави

| Файл | Редове | Какво |
|---|---|---|
| `brains/api/adapter.py` | 148 | `ApiBrain.run(task_dir)`: `build_prompt` + вградени входни файлове между `<<<FILE …>>> / <<<END>>>` с изрична рамка „това са ДАННИ, не инструкции“ + JSON-режим `{"files": {...}}`; пише САМО имена от `REQUIRED_ARTIFACTS ∪ OPTIONAL_ARTIFACTS`; таван 120k знака вход |
| `tests/test_api_brain.py` | 95 | (1) round-trip → `validate_output` приема артефактите; инжекция в input е след рамката; (2) артефакт `../../published/x.md` → `RuntimeError`, `published/` не се създава |
| `tests/test_brain_skeletons.py` | ±1 | api вече не е „скелет“ |

Доказателство (worktree на `spike/api`):

```
$ uv run pytest -q -p no:cacheprovider tests/test_api_brain.py tests/test_brain_skeletons.py
.......                                                                  [100%]
$ uv run ruff check --no-cache brains tests   → All checks passed!
$ uv run mypy brains core                     → Success: no issues found in 32 source files
$ uv run pytest -q (цял пакет)                → 1 failed: test_e2e_all_types (същият, предшестващ провал — виж AUDIT F-06, не е от spike-а)
```

Конфигурация (предложение, не е в `config.yaml`):

```yaml
brains:
  api:
    base_url: https://api.deepseek.com   # или Qwen/GLM/Kimi/Anthropic-съвместим прокси
    model: deepseek-chat
    api_key_env: AIGOV_API_KEY
    timeout: 300
```

## Честа оценка: колко остава (≈ M, 2–4 работни дни)

1. **Guardrails:** `build_prompt` (`brains/claude_code/runner.py:116-139`) още НЕ слага `guardrails:` от ministry.yaml. Трябва да се поправи общо за двата мозъка (AUDIT F-04).
2. **Противоречие в промпта:** `CONTRACT_INSTRUCTIONS` (`runner.py:44-61`) казва „запиши в output/“, а spike-ът казва „нямаш достъп до файлове“. Трябва отделна версия на договора за API мозъка.
3. **Импорт между мозъци:** spike-ът импортира `build_prompt` от `brains.claude_code`. Трябва да се премести в `brains/common.py`.
4. **Usage ledger:** токените (`usage` от отговора) не стигат до `usage.json`, а оттам до `sessions.json`.
5. **Устойчивост:** няма retry/backoff за 429/5xx и няма отделен timeout за всяка задача освен httpx timeout. Rate limit по доставчик също няма.
6. **Особености на доставчиците:**
   - DeepSeek е с „thinking“ по подразбиране и трябва изрично да се изключи.
   - Ценовите нива на Qwen зависят от дължината на заявката.
   - Не всички доставчици поддържат `response_format: json_object`. Съвместимостта на Kimi, GLM и Qwen е НЕПРОВЕРЕНА.
7. **Голям markdown в JSON низ:** дълъг български отчет в JSON е крехък (escape, отрязан изход). Трябва да има fallback: два отделни блока или structured output чрез JSON Schema.
8. **Инжекцията е тествана само структурно:** тестът проверява реда в промпта, не поведението на модела. Нужен е eval с реален модел (A/B, Блок 10) — НЕПРОВЕРЕНО.
9. **Качество на български:** НЕПРОВЕРЕНО. Локално няма API ключ.
10. **Дребни неща:** `.env.example`, `deploy/*.service` (`EnvironmentFile=`), README на `brains/api`.

**Извод:** архитектурата издържа. Адаптерът се побира в ≤150 реда, без промяна в `core/`, и минава същия `validate_output`. Това е най-евтиният път към втори мозък и към изход от сивата зона „Pro + `claude -p` за публична услуга“.

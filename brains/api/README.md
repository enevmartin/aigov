# api brain (skeleton)

Direct LLM API adapter — planned for cheap high-volume work (daily news
digests) with DeepSeek as primary and Kimi as fallback, while `claude_code`
keeps the deep analyses. **Not implemented** — `brain: api` fails loudly.

## How it will plug in

Implementing this brain touches ONLY this directory:

1. `config.yaml` already declares the knobs:

   ```yaml
   brains:
     api:
       model: deepseek-v4-flash
       fallback: kimi-k2.6
   ```

   Keys come from `.env` (`DEEPSEEK_API_KEY`, `KIMI_API_KEY`) — never from
   the repo.

2. `ApiBrain.run(task_dir)` will:
   - build the prompt with `brains/claude_code/runner.py::build_prompt`
     (it is declaration-driven and provider-free — reuse it);
   - call the chat-completions endpoint via `httpx` with a JSON-structured
     response format matching the contract models
     (`core/contracts`: Report front-matter, Aggregates, NewsDigest);
   - fall back to the `fallback` model on error/timeouts;
   - write `output/report.md`, `output/aggregates.json`
     (+ `output/news.json` for digests) itself, then return
     `ArtifactSet.from_output_dir(...)`.

3. Switch `brain: api` in `config.yaml` — or later, per-task-type routing
   (cheap API for `news_digest`, claude_code for `analysis`) as a small
   extension of the session driver. Everything else is untouched (чл. 1).

## Definition of done

- `run_cabinet_session(config)` processes pending tasks with mocked HTTP in
  tests (`httpx.MockTransport`), green `uv run pytest`.
- Publish gate rejects any malformed model output (already enforced by
  `core/publish` — no trust in the model required).
- `.env.example` documents the keys (already present, commented).

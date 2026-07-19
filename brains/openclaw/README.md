# openclaw brain (skeleton)

Adapter for an [OpenClaw](https://openclaw.ai)-style local agent gateway.
**Not implemented** — `brain: openclaw` fails loudly today.

## How it will plug in

The contract is already fixed; implementing this brain touches ONLY this
directory:

1. `config.yaml` carries the endpoint (already declared):

   ```yaml
   brains:
     openclaw:
       gateway: localhost:18789
   ```

2. `OpenClawBrain.run(task_dir)` will:
   - build the prompt exactly like `brains/claude_code/runner.py::build_prompt`
     (reuse it — it is ministry-declaration driven, not provider-specific);
   - submit it to the gateway with the task directory mounted/passed as the
     working directory, mapping each ministry to an AgentSkill built from
     `ministries/{slug}/prompts/`;
   - wait for completion and verify `output/report.md`,
     `output/aggregates.json` (+ `output/news.json` for digests) exist;
   - return `ArtifactSet.from_output_dir(task_dir / "output")`.

3. Switch `brain: openclaw` in `config.yaml`. Nothing else changes: the
   queue, contracts, publish gate, site and systemd units are untouched
   (чл. 1 от конституцията).

## Definition of done

- `run_cabinet_session(config)` processes pending tasks end-to-end.
- `uv run pytest` green with a mocked gateway (no live gateway in tests).
- `aigov session --dry-run` still uses the fake brain (no tokens).

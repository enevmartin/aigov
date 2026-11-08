# Notes
## B1
- 36 commits, all 2026-07-19..20 (git log --date=short). Phases: P1 3eb8ff5..9efbb14, P2 f606520..978ae01, P3 ae0e9d1..8e5fb84
- Lines (git ls-files|xargs cat|wc -l): core 2545/20f, brains 689/14f, ministries 6269/220f, site/src 2983/17f, tests 2776/21f(125 test funcs), deploy 229/9f
- 20 dirs in ministries (18 + government + _template); 9 TaskTypes core/contracts/models.py:19,289-298
- WIP uncommitted: 5 M + 8 untracked (capture.py, robots.py, deploy/windows, sources.yaml, test_capture.py, IDEAS/PLAN/RECON)
- only branch main; no stash
- aigov.bg: NXDOMAIN via 1.1.1.1 DoH Status 3 (2026-11-08) => no deploy
- published/: only finance 2026-07-20 news_digest, sessions.json 1 session duration 0.046 tokens null => fake
- tasks/* empty
## B5 cabinet agent: 18 ministries + PM match iisda.government.bg/ras/governing_bodies/ministers (2026-11-08). Structure decision 2026-05-08 ДВ43: e-gov merged into МИДТ (innovation), economy renamed "икономиката, инвестициите и индустрията". Check repo names.
## B5 batch A (finance, government, health, environment, agriculture) — spot-checked runner.py:31-61,116-139 & common.py:34-38 CONFIRMED
- No pydantic model for ministry.yaml; only tests/test_ministries.py:15 key checks
- build_prompt (runner.py:116-139) does NOT inject ministry `guardrails:` list (exporters do: common.py:34-38) → ministry-specific rules (finance "Никакви инвестиционни съвети" ministry.yaml:66) never reach claude -p. Duplicate persona logic runner vs common.py.
- report.md prompt not in PROMPT_FILES (runner.py:31-41) = dead
- No prompt-injection clause anywhere (grep only runner header)
- _template lacks crisis_keywords block (4/5 ministries have)
- correction.md lacks (a)(b) persons/political ban; signals.md lacks (b); news.md (a) weak "отвъд цитираното"
- data.egov.bg declared in health/env/agri but sources.yaml:125-135 blocked robots Disallow /; minfin CF blocked sources.yaml:146-156
- config.yaml:25 "Активни са само 3" but 4 enabled
- crisis substring no stemming core/ingest/crisis.py:41-47; finance "срив на лева" stale (euro since 2026-01-01); env "замърсяване" daily false alarm (2/5); agri "чума по животните" never matches real names (2/5)
- gov/health/env/agri prompts byte-identical to _template; health medical-advice ban only in persona :8
- news.md:16-18 finance creates placeholder NewsItem when nothing relevant
- personas: Финвест, Съветник, Вита, Терра, Агра — invented, OK
- table: finance T 8/3 | government T 0/0 | health T 6/3 | environment T 5/2 | agriculture F 5/0 ; e ✗ all
## B6 RSS agent (spot-checked rss.py:112-121, cli.py:99-107, no robots in HEAD core/)
- 11 feeds all 200 valid RSS2.0. STALE: economic.bg/rss/ustojchivost.xml newest 2026-10-07 (32 days) — one of 2 feeds of LIVE environment ministry
- mediapool /rss redirects to /feed/; fetched 3x per run (finance/health/env) for identical content
- health.json generated 2026-07-20, sources [] events [] → never recorded source health
- HEAD: robots.txt never consulted for RSS (rss.py:116-121); robots.py untracked WIP
- rate limit: per ScraperBase instance; collect_rss creates new instance per call (rss.py:112), cmd_ingest per ministry (cli.py:99,107) → back-to-back mediapool requests ~0s apart (finance last=mediapool, health first=mediapool) violates ≥1.5s & mediapool Crawl-Delay 1. Redirect hop bypasses limiter (scraper_base.py:75 follow_redirects)
- UA admin@aigov.bg (scraper_base.py:17-19) — domain aigov.bg NXDOMAIN → contact address undeliverable!
- WIP capture.py compliant: per-host HostThrottle 2s (181-206), robots per host (269-271); robots.py ignores Crawl-delay/Content-Signal; capture_all min_interval no floor (340)
- dnevnik/capital: Content-Signal ai-train=no, use=reference; block ClaudeBot etc; finance ministry.yaml:14 comment says tollbit-excluded (outdated)
- actualno, 24chasa, economic.bg others OK
## B2 test failure
- 1 failed: tests/test_e2e_all_types.py::test_every_task_type_reaches_published at :119. finance_days=['2026-07-20','2026-11-08']; fixture hardcodes ids/created 2026-07-20 (:82,:85) while session publishes under today → correct targets finance_days[0]=2026-07-20 which lacks news_digest → "no news_digest publication at published/finance/2026-07-20". Time bomb: passes only when run on 2026-07-20. Suite red on main since 2026-07-21.
## B5 batch C (culture F 4/3, youth-sport F 4/4, justice F 4/3, regional F 5/5, transport F 5/5); all prompts byte-identical to template
- sources.data not consumed by anything: cmd_ingest reads only rss (cli.py:103); opendata.download_dataset never called from core
- crisis: 0 hits /13 phrases on 105 real RSS items from data/raw 2026-08-10 → main risk is MISSING events (low recall)
- justice "конституционна криза" political (1/5); youth-sport "допинг скандал" → named athletes (Art 5); transport "блокирани пътища" weather/protest noise; youth-sport persona "енергичен" vs "спокоен" :6/:8
- culture, justice gov sites enabled:false (SSL)
- per-source enabled flag exists in ministry.yaml data entries; rss.py:117 honours enabled
## B2 tools: ruff All checks passed; mypy Success 32 files; coverage TOTAL 94% (1342 stmts, 78 miss), no module <70%; pytest 1 failed (rest passed) ~33s
## B5 batch B (economy F 6/6, energy F 5/5, innovation F 4/4, tourism F 5/5, education F 5/4): all prompts identical to template
- persona name risks: energy "Волт" = party Volt; education "Просвета" = textbook publisher brand; tourism "Роза" human-like
- persona описание (with "AI фигура") not published to roster (publisher.py:246-253); site shows "AI министър „X"" (index.astro:143,169)
- economy "стачка","фалит" generic; innovation "кибератака" daily
## B5 batch D (labor F 5/5, foreign F 4/4, interior F 4/4, defense F 4/4, _template)
- labor "невъплатени заплати" non-word → dead
- foreign persona "синтезирана от архивите" & interior "обучена върху публичната статистика" = false provenance claims
- news.md:22 "отвъд цитираното от източника" lets named suspects through (interior risk)
- CONTRACT_INSTRUCTIONS (runner.py:44-61) tells every task to write aggregates.json, conflicts with review.md:20 (only review.json) & signal_triage
- _template slug: template ≠ dir; tests skip _* (test_ministries.py:22) → template never validated
- defense "мобилизация" political FP; "нарушено въздушно пространство" dead; no дрон
- OPEN: does claude -p in task dir pick up repo CLAUDE.md (Чл.2 git add -A push)?
## B3
- core/cli.py:236 importlib.import_module(f"brains.{name}") and :323 f"brains.{brain}.exporter" → dynamic string import of brains from core (Чл.1.1 literal violation; documented as composition root cli.py:4-6, 221-226); core/__init__.py:3 claims NEVER
- core/cli.py:232 production code imports tests.fake_brain (dry-run) 
- no LLM-provider code in core except cli.py:399 help text
- ministries: 0 non yaml/md files (git ls-files)
- brains/ no writes to published (grep)
- site/src/lib/published.ts:13-16 PUBLISHED_ROOT ../../../published only fs reads (191-192,242-243)
- runner.py:101-108: subprocess [claude,-p,prompt,--output-format,json] cwd=task_dir, NO timeout, NO --permission-mode/--allowedTools/--model → (a) unattended Write may be denied → task fails (НЕПРОВЕРЕНО Чл.6); (b) cwd inside repo → repo CLAUDE.md (Чл.2 git add -A, push) loaded as context for brain; brain has filesystem reach to published/ (inv. 5 by prompt only, not sandbox)
- brain-swap touchpoints outside brains/+config: deploy/aigov-session.service:12-13 (claude login, PATH .local/bin), deploy/install.sh:53-54, deploy/README.md:25-32,64-65, no EnvironmentFile for API keys; cosmetic: core/cli.py:399, site planove.astro:23, za-proekta.astro:28 ; CLAUDE.md Чл.6
## B10 claude agent (URLs 2026-11-08)
- support.claude.com/en/articles/15036540: "Update June 15, 2026: We've paused the previously-announced changes... claude -p ... still draw from your subscription limits." Oct 7 2026: Max/Ultra/Team monthly API credits; Pro not.
- Pro 5h + weekly limits (articles/8325606, 11145838); Consumer terms anthropic.com/legal/consumer-terms ban automated access except API key or explicitly permitted; code.claude.com/docs/en/legal-and-compliance: "Developers building products or services... should use API key authentication" → gray zone for 24/7 public service. setup-token CLAUDE_CODE_OAUTH_TOKEN documented (code.claude.com/docs/en/authentication.md)
- pricing platform.claude.com/docs/en/about-claude/pricing: Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50, batch -50%. 1155 tasks/mo → Sonnet single-shot $46-92, +batch ≈$30-35; agentic ≈$120-250 (assumption)
- Managed Agents beta (managed-agents-2026-04-01), $0.08/session-hour, scheduled deployments; poor fit
- routines (code.claude.com/docs/en/routines.md) research preview, fresh GitHub clone, min 1h — poor fit (data/ gitignored)
- /goal (code.claude.com/docs/en/goal.md): prompt-based Stop hook, Haiku evaluator sees conversation only; works in -p; does not change permission mode
- Rec: keep CLI-on-Pro for now; build api brain (Sonnet 5.5 + batch + caching) as production path
## B3.8 export: 2×3 OK — finance/health × claude_code (.claude/agents/X.md 21997 bytes, has guardrails incl. "Никакви инвестиционни"), openclaw (export/openclaw/X/{SKILL.md,skill.json,prompts/}), api (export/api/X.json keys name,model,fallback,system_prompt,tools); outputs gitignored (.gitignore:41-42). Export includes guardrails; live runner does not → inconsistency
## B4
- filequeue.py:107,144 os.rename atomic; enqueue via hidden staging (81-107) ✓; fail() rename then write reason (132-136) non-atomic (minor)
- STALE_AFTER 2h session.py:35; requeue_stale filequeue.py:165-181 tested test_queue.py:105,118 test_failures.py:113,121 ✓
- retry: MAX_ATTEMPTS 2 session.py:34, _handle_failure 56-80 → record_event task_failed ✓; test_failures.py:59
- POISON TASK: subprocess no timeout (runner.py:101-108); systemd TimeoutStartSec=1800 kills whole session (aigov-session.service); task stays running → requeue_stale (no attempts bump, filequeue.py:178-179) → next session re-runs first → hangs again → infinite loop, blocks all other tasks. Violates Чл.7.
- release() keeps output/ from failed attempt (session.py no rmtree of output) → retry may inherit partial output
- one bad output never blocks others: test_failures.py:135 ✓ (publish loop continue)
- publish: target dir date = max(date from LLM artifacts) publisher.py:155-157; copy2 overwrite (158-160) → no check date==task date; LLM front-matter date can overwrite an EXISTING older publication silently (breaks "original never edited"); same-day same-type second publish overwrites first. Non-atomic multi-file copy into published/.
- timeseries idempotent: store.py:49-62 DELETE+INSERT ✓ (test_archive.py:100-107)
- corrections: sidecar _link_correction, original not edited (publisher.py:166-168), test_corrections.py ✓ — but see overwrite hole above
## B6 stats agent (spot-checked capture.py:15 append-only, export SKILL.md no frontmatter)
- No statistics source parsed by any code; opendata.download_dataset only caller tests/test_ingest.py:174 (dead code)
- NSI CPI URL (finance/ministry.yaml:37, sources.yaml:98) redirects to inflation CALCULATOR; GDP URL (:41) redirects to homepage (soft 404). Correct: nsi.bg/statistical-data/117, /141/432; machine-readable Eurostat prc_hicp_minr (HICP proxy), namq_10_gdp (2026-Q2 2.8% y/y)
- BNB rates HTML 200, data 06.11.2026; better ?download=xml; label "централни курсове" outdated after euro (finance/ministry.yaml:30); interest XLSX served text/plain → capture would save .txt
- data.egov.bg robots Disallow: / (whole host incl /api) — declared in 18 ministry yamls
- health.json no stats monitoring
- EPHEMERALITY VIOLATED: capture.py:15 (WIP) "Append-only... nothing is ever deleted"; data/raw 21 files all 2026-08-10, 90 days old; data 1.1M (raw 502K, archive.duckdb 524K)
- Windows scheduled task aigov-capture LastRunTime 2026-11-06 LastTaskResult=1 — failing; data\logs missing (run-capture.ps1:41-45)
## B10 alt agent (URLs 2026-11-08)
- Hermes Agent v0.23.0 2026-11-05 MIT, github.com/NousResearch/hermes-agent; agentskills.io compatible; `hermes chat -q` headless
- Export gaps vs agentskills.io/specification: no YAML frontmatter (name/description), name≠dir (skill.json aigov-{slug}-minister vs dir {slug}), invented skill.json, contract instructions & schemas missing, prompts not linked from SKILL.md, exporter in brains/openclaw not generic
- OpenClaw v2026.11.1 (2026-11-05), Foundation 2026-07-08 MIT; ~700+ advisories (github.com/openclaw/openclaw/security/advisories), ClawHavoc Feb 2026; Claude subscription routing prohibited (code.claude.com/docs/en/legal-and-compliance); `openclaw agent exec --cwd --json` headless, sandbox off default; repo README gateway premise outdated
- Prices (official pages): DeepSeek V4.1 Flash $0.30/$1.20 (off-peak -50%), V4 Pro $1.32/$3.96; Kimi K3.1 Pro $2/$10 (K2.x retiring Dec 2026 — config.yaml fallback kimi-k2.6 dead!); GLM-5.3 $1.40/$4.40; Qwen3.7-plus $0.40/$1.60, 3.8-flash $0.15/$0.47
- monthly (1140 tasks, 22.8M in): DS Flash off-peak $4.8, DS Pro $20-39, Qwen plus $12.8, GLM $42, Kimi K3.1 $68
- BG quality НЕПРОВЕРЕНО; no API keys locally → live BG test НЕПРОВЕРЕНО
- Agent Skills adopted: Hermes, OpenClaw, Codex, Gemini CLI (.agents/skills) → one SKILL.md export portable
- Rec: primary claude_code short-term; build brains/api OpenAI-compatible generic adapter; fix exporter to agentskills; China-hosted decision under Чл.5
## B7
- astro build HEAD: 27 pages, 19.8s, 1.8M, 0 errors (npx astro build --outDir dist0)
- disclaimer "Независим граждански AI експеримент. НЕ е свързан с правителството" 27/27 (grep -rL → none missing)
- zero data (empty published/): 7 pages built, no errors; home links only to sections (no broken ministry links)
- 2y synthetic (3 ministries × 3 series × 1460 pts): 27 pages OK; finance/index.html 458 KB vs 14 KB → inline series JSON grows linearly
- fake-brain data with example.bg links rendered on danni/index.html, finance/index.html, finance/2026-07-20/index.html → if deployed as-is, site shows fake publication
- NO robots.txt in dist; sitemap.xml, rss.xml, og.png present; lang="bg"; og:title/description/type/locale; 0 <img> without alt; prefers-color-scheme:dark in CSS
- external hosts in HTML: only github.com (31) + example.bg (8, fake data); fonts self-hosted @fontsource (package.json)
- dist contains content-assets.mjs, content-modules.mjs (Astro artifacts, harmless)
- build.sh: npm ci each session + rm -rf TARGET/* then cp (non-atomic deploy, site empty window)
- Lighthouse НЕПРОВЕРЕНО (no lighthouse/chrome headless run)
## B8
- git log -p --all secret regex (sk-, ghp_, api_key=, password=, token=, PRIVATE KEY): 0 real hits; word hits only package names/comments
- .env.example lists DEEPSEEK_API_KEY, KIMI_API_KEY, OPENCLAW_GATEWAY, AIGOV_USER_AGENT; .gitignore covers .env, .env.*, data/raw, data/staging, archive.duckdb, tasks, export, site/dist ✓
- STORED XSS: published.ts:245 marked.parse(LLM report) unsanitized → DayView.astro:80 set:html. analizi.astro:87 JSON.stringify(searchIndex) inside <script> via set:html — "</script>" in a title breaks out. Caddy (deploy/Caddyfile) no CSP, no HSTS (Caddy auto-HTTPS ✓, nosniff, XFO DENY, Referrer ✓)
- Prompt injection chain: RSS title/summary → input → news.md (no "data not instructions") → claude -p with tools, cwd inside repo → report.md → publisher schema-only validation (no content filter) → marked → set:html. Review = same model, sees report only.
- Signals: no intake (cli.py:158-164 "phase 3"). SignalStats (models.py:218-247) category str no max length, note free str, count≥0 allows count=1 buckets → raw text/PII smuggling possible; SIGNAL_TRIAGE optional report.md publishable (models.py:307)
- GDPR: no form, no personal data collected today; no privacy policy page (grep none). НЕПРОВЕРЕНО whether future form planned
- deploy: units User=aigov ✓, no hardening (NoNewPrivileges/ProtectSystem/ReadWritePaths); aigov owns /opt/aigov AND /var/www/aigov (install.sh:21-26) → brain process can write site directly; install.sh curl|sh uv; firewall: no notes in deploy/README.md
- npm audit (site): astro <=7.3.1 critical (GHSA-j687-52p2-xcff, GHSA-26w7-cxv4-gfx2 RCE AVIF, …), devalue high, echarts <6.1.0 moderate XSS GHSA-fgmj-fm8m-jvvx, js-yaml high, nanoid high; npm outdated astro 5.18.2→7.4.7, echarts 5.6.0→6.1.0, marked 12.0.2→18.1.3
- pip-audit: certifi 2026.6.17 PYSEC-2026-4320 fix 2026.10.18; outdated duckdb 1.5.4→2.0.0, polars 1.42.1→2.1.0
- Legal: page titles "Министерство на финансите — aigov.bg" (dist finance/index.html <title>) → in SERP looks official; disclaimer in footer only; domain aigov.bg unregistered (NXDOMAIN) → squatting risk + UA contact admin@aigov.bg undeliverable
## B6 sites agent (spot-check NSI URLs: /113 "Инфлация и ИПЦ", /117 "ИПЦ", /136 "БВП", /141/432 "БВП производствен метод" — all valid, both agents consistent)
- AUDIT DEVIATION: agent made 1 homepage request each to mpes.government.bg, data.egov.bg, aop.bg despite robots Disallow:/ and ~2.5s instead of Crawl-delay 60 (mc) / 10 (tourism) → disclose
- No ministry website collected (cli.py:104 rss only); data `enabled:false` decorative
- minfin.bg/bg/news 403 Cloudflare but finance enabled; mpes.government.bg robots Disallow:/ (note "проверен" wrong); mon.bg now 200 (note says 403); mig.government.bg stale since 24.09.2026; justice JS-rendered; mfa feed bot wall
- usable feeds now: me.government.bg/rss.html (11 items, 08.11), tourism.government.bg/bg/rss.xml (Crawl-delay 10), nsi.bg/nsi_rss.xml (08.11), parliament.bg/feed/news (50 items; sources.yaml "blocked: SPA" wrong), dv rss_newspaper.jsp, mrrb /bg/rss/ (1 item)
- robots.py no Crawl-delay support (mc 60s, tourism 10s) 
- suggestions per ministry (Eurostat/NSI/НЗОК/ИАОС/АЗ/IBEX…) table in agent report — copy into report

# Recorded tier-2 payloads

Recorded on 2026-11-10 through `core.net.PoliteClient` (robots.txt checked first,
UA with bot@aigov.bg). Official public records of the National Assembly.

- `parliament_bills.xml` — https://www.parliament.bg/feed/bills, trimmed to 3 items.
- `bill_167635.json` — https://www.parliament.bg/api/v1/bill/167635 (the site's own
  JSON API; the HTML page is an SPA shell with no text). It contains the names of
  the sponsoring MPs on purpose: tests prove `redact` strips them before any model
  sees the document (чл. 5).

# Category: Cost/performance opportunities

Weekly-cadence category (run via `recommend.md`), for the one project
this run is about — things that cost real money or time *repeatedly*,
as opposed to `health.md`'s `llm-observability`/`resource-usage`
categories, which check whether something is broken *right now*. This
one asks "is this working as designed but still wasteful."

- **Redundant LLM calls**: query the project's trace backend (its
  `CLAUDE.md` says where; filter to this project's service names) for
  call sites with unusually high call volume relative to what the
  triggering workflow should need — a longer window than health's daily
  24h, since the pattern you're looking for is a steady-state habit, not
  a today-specific spike, but capped at the backend's actual retention
  (check its config rather than assuming a number). **Pass explicit
  `start`/`end` bounds on every query** — without them a trace backend
  typically returns only a short recent window regardless of retention,
  which reads as "no data" and produces false negatives. A retry loop
  calling the LLM instead of retrying a cheaper deterministic step, or
  two call sites doing overlapping work, are real findings; a
  legitimately busy call site isn't.
- **Missing caching**: a call site (LLM, HTTP, or otherwise) computing
  or fetching the same thing repeatedly with no cache, where this
  project's own existing cache patterns (a `*_cache.py` module, a page
  cache in a fetching service) show it's a recognized, idiomatic thing
  to add here — not a new pattern, an underapplied one.
- **Expensive queries**: a database or metrics query (the project's
  database, its trace/log/metrics stores) that scans more than it needs
  to for what it's answering — cite the actual query and why it's
  wasteful, not a general "add an index" guess.
- **Resource headroom trends**: over the metrics store's actual
  retention (check its live config — its retention flag — rather than
  assuming), for this project's containers, is anything trending toward
  a real ceiling — not a today-snapshot the way `health.md`'s
  resource-usage category checks, but the longest trajectory actually
  available worth planning around.

Every finding needs a concrete number or observation behind it (an
actual call count, an actual query, an actual trend line) — not "this
seems like it could be slow." Report: the finding, the evidence, and a
rough sense of the win if addressed. Flag anything genuinely small and
bounded (e.g. "add one cache lookup here, the pattern already exists")
as a candidate for `propose.md`; bigger ones are recommendations only.

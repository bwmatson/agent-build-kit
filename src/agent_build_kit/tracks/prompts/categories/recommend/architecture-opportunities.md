# Category: Architecture opportunities

Weekly-cadence category (run via `recommend.md`) — the most
"thinking," least mechanical of the four `recommend.md` categories, for
the one project this run is about. Two parts: an internal-evidence pass
and a rotating external-research topic (the one category here with real
web access).

## Part 1: internal evidence

Read this project's `docker-compose.yml` top comment block if it has one
(the service map/rationale), its `CLAUDE.md` (including any cross-repo
sections — what it depends on elsewhere in the workspace, its exported
interface, known consumers, contracts it must keep stable), and skim a
few service READMEs before forming an opinion — this category needs
real context, not a grep sweep. The boundary between repos is fair game
when the evidence is on this project's side of it. Look for:

- **Scaling bottlenecks**: a single point (a service, a shared resource
  like a database instance, a queue) that everything funnels through
  and would struggle under real load — not hypothetically, only if
  there's a concrete reason to think so (e.g. something already
  documented as a known constraint, or a pattern that's clearly
  single-threaded/serialized where the workload isn't).
- **Awkward coupling**: two services that know more about each other's
  internals than a clean interface would require — e.g. one reaching
  past an API into another's implementation details, or a change in one
  historically requiring a matching change in another with no shared
  contract enforcing it.
- **Explicitly-flagged temporary states**: CLAUDE.md and service READMEs
  sometimes say things like "for now," "pilot," "not yet," "should
  eventually" — grep for this kind of language and check whether the
  "eventually" has already arrived (the pilot succeeded, or the
  workaround has outlived its reason) without anyone circling back.
- **Genuine architectural wins already in reach**: a change that's
  bigger than a bug fix but smaller than a redesign, with a clear
  before/after that's easy to argue for.

## Part 2: rotating research topic

Research one topic per run (not all of them — that's the point of
rotating) and check it against what this project actually does. Fixed
list, in order. Each applies only to a project that actually has the
thing — skip any topic that doesn't apply to this run's project, and
say in one line why it was skipped:

1. **Event-driven architecture / message broker patterns** — when the
   project produces to or consumes from a message broker alongside plain
   HTTP calls. Is a broker still the right call here, and is the split
   (what goes through it vs. what doesn't) still sound by current
   practice?
2. **Multi-agent / LLM agent orchestration patterns** — when the project
   hosts an LLM agent, an agent-to-agent protocol, or tool integration
   (MCP or similar). How are current systems structuring agent-to-agent
   and agent-to-tool boundaries, and does anything here look dated or
   like it's fighting its own framework?
3. **LLM observability and cost-tracking practices** — when the project
   runs an LLM gateway or exports LLM traces. Beyond what its tracing
   already captures (see `health.md`'s llm-observability category), what
   do current practices recommend for tracing, evaluation, and cost
   attribution across LLM call sites?
4. **Knowledge graph / RAG architecture** — when the project runs a
   retrieval service (graph-based or otherwise). Is its approach still
   favored for this kind of workload, or has the field moved toward
   something else worth knowing about (not necessarily switching to)?
5. **Container orchestration at single-host scale** — when several
   Compose projects share one host, wired together by an external
   network and a host-port registry. Is Compose still appropriate at
   this scale, and are there lighter-weight patterns worth adopting
   short of moving to a full container scheduler?
6. **Zero-downtime / blue-green deployment patterns** — when the project
   has its own redeploy mechanism (a hand-rolled reverse proxy, a
   script, a skill describing the procedure). How does it compare to
   established tooling for the same problem, and is the custom-build
   tradeoff still the right one?
7. **Anti-bot / browser automation architecture** — when the project
   drives real browsers to fetch pages past anti-bot measures. This is
   a fast-moving cat-and-mouse space; what's changed recently that's
   worth knowing?

**Picking which topic**: read this project's recent recommend run-log
entries (in the run-log directory the parent prompt named) for this
category's "Research topic this run:" line (see the reporting shape
below) and pick the next applicable topic after the most recently
covered one, wrapping around after 7. If this project has no prior
entry with one, start at the first topic that applies to it.

**Researching it**: use `WebSearch`/`WebFetch` to find *current*
material — recent discussions, posts, docs reflecting how the space
looks now, not just foundational documentation that hasn't changed in
years. The point is "latest patterns or issues," not a textbook summary.

**Reporting it**: start this part of your findings with `**Research
topic this run:** <N>. <topic name>` (exact shape — future runs parse
this line for rotation), then what you found externally, then how it
compares to what this project actually does, then any recommendation. Same
evidence bar as Part 1 — cite what you actually found (a specific
pattern, a specific known issue, a specific source), not a generic
"consider modernizing" gesture. If the research turns up nothing that
actually applies here, say so plainly rather than forcing a
recommendation to justify the topic.

## Reporting

This category is the one most prone to generating impressive-sounding
but unfounded opinions — every finding (both parts) must cite something
concrete (a specific file, a specific comment, a specific pattern
observed twice, a specific external source) as evidence, not general
software-architecture platitudes. If you don't have real evidence for
something, don't report it just to have something to say. Report: the
observation, the concrete evidence for it, and roughly how big a change
it'd take to address. Essentially never actionable in `propose.md`'s
bounded sense — that's expected for this category specifically.

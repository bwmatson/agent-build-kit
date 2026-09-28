# Category: Technical debt / code smells

Weekly-cadence category (run via `recommend.md`) — a deliberate look at
the one project this run is about, not a routine check.
`convention-adherence.md` (the weekly `improve.md` category) already
checks adherence to *documented* rules; this is broader and fuzzier —
things nobody wrote a rule for yet, but that are worth a maintainer's
attention:

- **TODO/FIXME/XXX/HACK comments**: grep for them across this project's
  repo. Which ones look genuinely stale or forgotten (reference
  something already resolved, or predate a since-completed refactor) vs.
  still-live and worth surfacing?
- **Duplicated logic across services**: the same pattern hand-rolled in
  2+ places that could plausibly move into the project's shared package
  (whichever one its `CLAUDE.md` names — and note when the shared
  package belongs to another repo in the workspace, since moving code
  there is a cross-repo change) — but only flag it if the duplication
  is real and non-trivial (a few lines of boilerplate matching a
  documented convention, like an API-key check that has since moved
  into a shared helper, isn't itself new debt — check whether it's
  already been addressed before flagging it again). Deliberate
  cross-repo copies are not debt: a component the `CLAUDE.md` says
  exists once per repo on purpose (each trimmed to its own service)
  stays that way.
- **Files that have grown unwieldy**: a module that's ballooned into
  doing several unrelated things, where splitting it would genuinely
  help readability — not just "this file is long," but "this file is
  long AND doing 3 different jobs badly."
- **Repeated patterns worth extracting**: the same non-trivial shape
  (not just similar-looking code, an actual repeated *decision* or
  *algorithm*) implemented independently 3+ times.

Be conservative — technical debt framing is easy to overreach with
("this whole thing could be cleaner"). Only report something concrete
enough that a specific person reading it would immediately understand
what to do and roughly how big it is. Report: what you found, where,
and a rough sense of whether it's a quick fix or a real undertaking.
Note separately if anything is small/bounded enough for `implement.md`
to actually do in one pass (most won't be — that's fine, say so).

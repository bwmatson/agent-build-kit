## What was checked, and where

Read-only, `agent-build-kit` `origin/main` at `95f59753` after `git fetch`.

- `pipeline/work_graph.py`: `NEEDS_LINE` 146-150 (the optional `merged` group), `Need` 751-757 (`merged: bool`), `group_needs` 760-780,
  `merged_needs` 785-789, `merged_needs_warnings` 792-801, the own-change error 430-438 (`own_merged_lines`).
- `pipeline/units.py`: `REVIEWED` 90; `waiting_on` 815-858 (same repo needs `REVIEWED`, other repo `landed`); `blocked` 893-901; `dependency_wait`
  903-911 (appends ` to merge` for another repo); `Unit.needs` 149.
- `cli/pipeline.py`: `cmd_tick` 1143-1190; `_tick` 1212; `run_round` 1628; `release_gated` and `requeue_wait_ended` 2051-2111; `_requeue_ended_wait`
  2114-2134; the start gate 1974-1976; the `failed, waiting on` status line 2823; `link_needs` 3415-3470; `declared_needs` 3576-3604; `merged_needs_warnings`
  call 5578.
- `pipeline/diagram.py`: the dependency edges 164-176 (`==>|needs|` for a `Needs:` dependency, `-.->` across repos) and the legend text 254-262.
- `pipeline/unit_store.py`: `set_needs` 1217; history entries (`state`, `at`, `cause`, `note`) 1404; `StoredUnit.history` 364. `pipeline/unit_size.py:98-107` and
  `pipeline/archive.py:90-97` already read the `merged` history entry's `at`.
- `forges/base.py:466` `merge_commit(repo, pr) -> str | None`, implemented by `github.py:797`, `azure_devops.py:891`, `local.py:350`.
- The planning repo: `runs/units.json` (state of every unit named below) and `grep` of `openspec/changes/*/tasks.md`.
- UNVERIFIED, for the builder: that every forge's `merge_commit` is a commit reachable from the default branch after a squash or rebase merge (the
  GitHub value `merge_commit_sha` is); that the tick poll is the single place a unit becomes `merged` (a `merged` history entry is also written by
  `adopt`/adopted merges); and where `inst` finds the kit checkout (the directory above `agent_build_kit` when it is a git work tree).

## Kinds on every edge

Every dependency edge has a **kind**: `review` (a planned dependent stacks on the parent's branch once the parent is in review) or `merge` (the dependent
waits until the parent is merged and a later tick has it, below). One small function, `edge_kind(unit, parent, repos)` in `pipeline/units.py`, gives it,
and it is `merge` in exactly three cases, otherwise `review`:

1. **The edge crosses repositories** (reason `another repository`). `dependency_wait` already waited for the merge there (`units.py:845-852`, `903-911`);
   this makes it the same predicate and the same wait-end rule as every merge edge. An author cannot write a looser cross-repo kind: a plain `Needs:` to a
   group of another repository is read as `merge`, with an info note from `abk tags` and `abk check` (`<file>:line N: info: group G: Needs: <change> group
   <n> is in another repository, so it waits for the merge`), and `link_needs` stores it in `merge_needs`.
2. **The author wrote `merged`** on the `Needs:` line (`merge_needs`, recomputed from `tasks.md` by `link_needs` every tick; reason `the Needs: line says
   merged`). It is binding: nothing else can make it `review`, and the planner, which writes plain edges only, cannot loosen it (below).
3. **The unit is waiting as a failed unit** (reason `a failed unit resumes after the fix is merged`): a unit in `failed` state, or planned with a stored
   gated requeue (a failed unit a person requeued while it waited, which `requeue()` parks as `planned`/`gated`), whose edge is to the parent it waits
   on. Whatever the author's kind and whichever repository the parent is in, its wait ends at the parent's merge plus the next tick that loads it, never at
   "in review". This is the rule that went wrong on 2026-10-21: the dependents were failed units whose fixes were only in review. A *planned* dependent
   with a plain same-repo `Needs:` still starts on the parent's branch once the parent is in review.

There are no other sources. Rules that made an edge `merge` for kit-repo parents across changes, or for an e2e-test unit of a repo with no `dev_stack`,
were considered and left out: authors choose `merged` for those (guidance below), so the cost of serialising falls only on the edges that need it.

**The planner.** It keeps writing plain `depends_on` edges and has no field for a kind. A planner edge to a parent that the author's `Needs:` also names
as `merged` is `merge`: `edge_kind` reads `merge_needs`, which the planner never writes, so a plan cannot weaken it, and a replan neither clears nor
recomputes it (`link_needs` rebuilds it from `tasks.md` each tick, after planning, as it rebuilds `needs`). A started unit's `merge_needs` is kept like its
dependencies. A kind chosen by the planner is future work (below).

**What a person sees.** `abk status` appends `(merge: <reason>)` to the wait text of a merge edge; the graph labels the edge (below).

## Not in this change

A merge kind chosen by the planner: the person has no criteria for it yet, so the plan JSON, `parse_plan`, the prompt and the join checks are untouched.
Future work, waiting for criteria. Also not here: forced merge for edges into the kit's own code, and for e2e-test units without a dev stack (an author
writes `merged`); when the kit checkout is pulled.

## The two kinds, and the spelling

Plain `Needs:` keeps its meaning exactly. The second kind is the existing word `merged` after the group number, not a new keyword. Reasons:

- The grammar already parses it into `Need.merged`, `declared_needs` already sees it, and 21 lines in live changes were written by authors who meant
  "after the merge"; making the word mean what they wrote costs nothing and rejects nothing (`abk tags` has accepted it throughout).
- It reads as what it is: `Needs: kit-fix group 1 merged — the tick must run the fix`. The cross-repo wait is already described as "must merge first".
- Alternatives rejected: `Needs-merge:` (a second line type for `NEEDS_LINE`, the cycle check, `joins`, `flakes` and `untouched_failures` to learn
  about); `Needs: ... after-merge` (a new word where an existing one is free). A flag on the unit rather than the line would hide the intent from review.

`merged` stays recognised only straight after the group number, as now, so a reason such as "Needs: x group 2 — merged later" is unaffected. The
word is recorded on `Need.merged` (already there); `merged_needs_warnings` and its call at `cli/pipeline.py:5578` are removed, and the deprecation sentences
in the docs and skill are replaced. A merge line on the change's own group stays an error (the groups of one change are ordered).

## When a merge Needs is met

For a `Needs:` marked merge and its parent unit P (looked through the satisfied and replaced chain as `waiting_on` already does):

1. P is `MERGED`, or `SATISFIED` with its work landed (`satisfied_landed`, as the cross-repo rule uses). Same-repo or not: in review is not enough.
2. If P's repo is the kit's own repo (the checkout the tick records, below; this is the mechanism for the merge kind, not guidance to authors), the merge is in the running code, by one of:
   - **sha test (primary):** P records `merge_sha`, the tick record has `kit_head`, and `git merge-base --is-ancestor <merge_sha> <kit_head>` in the kit
     checkout succeeds. The sha unknown to the checkout is "not yet" (the checkout has not fetched it).
   - **tick-count fallback**, only when `merge_sha` or `kit_head` is unknown (an installed kit that is not a git work tree, a forge that returns no
     merge commit): the current tick's number is greater than P's `merged_tick`.
3. A unit already `MERGED` whose record has no `merge_sha` and no `merged_tick` (everything merged before this change) is treated as loaded for both tests: no
   history is rewritten and no unit is delayed.

If P's repo is any other repo (every cross-repo edge is a merge edge), the sha test does not apply and the **tick rule** does: the current tick's number
is greater than P's `merged_tick`, so a merge seen by the running tick is acted on by the next one. This is uniform on purpose: one wait-end rule for
every merge edge, and a dependent's worktree is built from the fetched default branch whichever tick builds it, so the extra tick costs a few minutes.
The tick rule is also the fallback of the sha test.

**The kit's repo.** The tick resolves the directory the `agent_build_kit` package was imported from, takes `git rev-parse --show-toplevel` of it, and
compares it (resolved) with each configured repo's `path`; at most one matches. If none matches the sha test never applies and nothing is delayed beyond
(1).

### Why the tick records its code, and not a time

Three ways to know "the tick has the merge" were weighed:

| Rule | Verdict |
|---|---|
| Tick start time later than the parent's merge time | Needs the merge time. The history `at` is when the poll saw the merge, not when it happened, and the forge's `mergedAt` is not stored. Worse, it assumes the checkout was pulled between the merge and the start: with the person's "pull main at the beginning of each tick" the pull of tick N+1 runs inside it, after its modules loaded, so a merge made after tick N's pull and seen by N+1's poll satisfies "N+1 started later" but is not in N+1's code. Wrong in the unsafe direction. |
| Tick counter only (`merged_tick < current`) | Same flaw with the pull at the start, and wrong when no pull happens at all. Kept only as the fallback. |
| Kit HEAD sha at tick start contains the merge commit | Exact: it asks the question directly, independent of clocks, of when or whether anything pulls, and of a merge that landed between the poll and the start. Costs one `git rev-parse` at start and one `merge-base --is-ancestor` per gated pair. |

So the sha test is primary. The tick record also holds the number and the start time because the status command, a separate process, needs "the last
tick" to say whether the next tick is the one that will load the merge.

**The record.** `cmd_tick` writes `<state_dir>/tick.json` `{number, started_at, kit_root, kit_head}` once, after the planning sync and before the first
round, for a real tick only (a dry run reads the last record and writes nothing); `number` is the previous number plus one. The write is atomic
(write and rename). A tick that cannot read the checkout's HEAD writes `kit_head: null`. A process-local copy is passed down as the "loaded code" so
`waiting_on` stays a function of its arguments; the unit store gets two fields and two setters:

- `merge_sha: str | None`, set where a unit is first set `merged` (with `forge.merge_commit(repo, pr)`, once, on the merge, not recomputed);
- `merged_tick: int | None`, the record's number at that moment.
- `merge_needs: tuple[str, ...]`, with `set_merge_needs`, set by `link_needs` beside `needs`.

An older store loads (all three default empty).

### Mid-tick

The tick record is fixed at start. A parent seen merged by this tick's poll has a `merge_sha` that cannot be in `kit_head` (the head was read before
the poll; at best the merge preceded it and was pulled, which the ancestor test then rightly accepts), or `merged_tick` equal to this tick's number
(fallback), so the dependent stays planned and a failed dependent stays failed. The next tick reads the new HEAD, sees the merge commit in it
if the checkout was fast-forwarded, and releases the dependent in that tick's first round. If the checkout was not fast-forwarded the dependent waits
with a distinct status (below) and nothing is lost: it is not failed and not consumed.

## `waiting_on` and its callers

`waiting_on(unit, graph)` gains an optional `loaded: LoadedCode | None` (default: the tick record read from disk, so the status command, graph page and
dry run need no change in signature). `LoadedCode` is a frozen pydantic model: `number`, `kit_root`, `kit_head`, with `contains(merge_sha) -> bool |
None`. After the dependency loop, `waiting_on` also visits every id in `unit.merge_needs`, and holds a dependency whose `edge_kind(unit, parent, repos)` is `merge` until rule (1) and (2) are met (the dependency loop itself
asks `edge_kind` for each linked edge instead of testing the repository); a parent is appended if not already listed. It does so even when the target is not in `depends_on` (a `Needs:` the chain implies is recorded in `needs` but not linked,
`direct_dependencies`); for a merge need that implied edge draws nothing but the wait must still hold. A parent the plan dropped (`BUILDS_NOTHING`)
or that is closed never waits (as today); a closed parent of a failed unit ends its wait as `wait_ended: closed` (unchanged).

`blocked`, `dependency_wait`, the start gate (`cli/pipeline.py:1974-1976`), `requeue()`'s `gated` parking (it asks `waiting_on`), `release_gated`, the
diagram's `failed_waiting`/`second_parent_wait` text and `requeue_wait_ended` all call `waiting_on`; none needs another test. A merge need has the same
effect in each: no start, and a requeue made while it is unmet is parked `planned` with cause `gated` and released when `waiting_on` empties.
`release_gated`'s own delivery happens in the round whose poll saw the merge only if the dependency is met by rule (2) at that tick; by design it is not,
unless the kit's checkout had already been pulled before the tick began.

**Failed unit, wait-end rule.** `requeue_wait_ended` records `waited_on` while `waiting_on` is non-empty and requeues when it is empty and every recorded
parent is `REVIEWED`. Because `edge_kind` makes every edge of a failed unit `merge`, `waiting_on` is non-empty until rule (1)+(2), so nothing changes in
that function except the note: the
history says `its wait ended (waiting on <change> group <n> is now merged)` as now, and for a merge need appends `and loaded by tick <number>`. The
condition `parent.state in REVIEWED` can stay; it is true of a merged parent. That
archived change said a wait ends when the prerequisite is in review; this change ends it at the merge plus the next tick, for every kind and repository.
A person or a track that writes a fix change a failed unit waits on needs no `merged` line: the failed-wait rule already waits for the merge. Not a loop and not twice: the record is
cleared by the requeue, as there.

**Cross-repo.** Every cross-repo edge is a merge edge: `MERGED`/`landed` as today, plus rule (2) (the sha test for the kit's repository, the tick rule
for any other), for a planned and a failed dependent alike.

**Already started units.** The check gates a start and a requeue, as `waiting_on` does. A merge `Needs:` added after a unit is running or in review
does not stop it and does not send it back; the existing `upstream_went_back` mechanism is untouched.

## What `abk status` and the graph say

- `dependency_wait(units, repo=...)` (`units.py:903-911`) names each wait by its reason: `waiting for <change> group <n> to merge` when the parent is
  not yet merged (a cross-repo parent already says it; a merge-kind same-repo parent now does too), `waiting for the next tick to load <change> group <n>'s
  merge` when the parent is merged and the last tick record does not contain it but the kit checkout's current HEAD does (the next tick will), and
  `waiting for the kit checkout to include <change> group <n>'s merge` when neither the last tick's code nor the current HEAD has it. The same strings
  appear in the planned line, in the pipeline log, in `failed, waiting on <unit>: ...` (`cli/pipeline.py:2823`) and in the graph node's name suffix.
- `link_needs` writes `merge_needs` next to `needs`. The graph draws `dependency in unit.merge_needs` as `==>|needs, merge|`, ahead of the thick
  `==>|needs|` test (a merge edge is also a needs edge) and keeps the cross-repo dashed edge for dependencies that are not `Needs:`. The legend
  sentence (`diagram.py:254-262`) and `docs/unit-graph.md:92` name the new label. The graph page (`unit-graph-page`) is generated from the same diagram text and needs
  no code of its own: its test over the label is part of group 4.

## Existing `merged` lines

`grep` of the live changes finds 21 `Needs: ... merged` lines in 13 changes (the archived ones are not read by the pipeline): abk-telemetry (2),
dry-guidance (2), flaky-tests, init-asks-which-runtime, init-writes-changelog-conventions (2), pipeline-environment (2),
process-tests-fake-the-github-api, <redacted>-drops-consumer-config (2), tier2-failures-in-untouched-tests-are-fixed-once,
tier2-replays-unchanged-calls, ui-chat-editing (3), unit-graph, usage-report (2). In `runs/units.json` every dependent unit they sit in is `merged`
(`pipeline-environment/4` is `unplanned`) and every parent unit is `merged`; a merged dependent is not started or requeued, so no unit changes
behaviour or is delayed when the word starts to mean something. Two machine-written families also contain the word in docs only:
`docs/architecture.md:1316` and `:1340` show the flake and pre-existing-failure `Needs:` lines as `group 1 merged`, whereas the code writes plain lines
(`pipeline/flakes.py:202`); those two sentences are corrected, not the behaviour. (`dry-guidance`, `ui-chat-editing` also end a reason with "(merged)";
that is part of the reason, as the grammar says.)

**Migration step.** A check, run by the first tick that has this change and repeatable as `abk tags --all` output: for each live `Needs:` merge line, if
the dependent unit is not finished (`planned`, `failed`, `held`) and the parent unit is not merged, the log prints one line `<unit>: now waits for
<parent> to merge (Needs: ... merged in tasks.md)`; nothing is edited or requeued. Today the list is empty. A later-written `merged` line is a
deliberate request and needs no migration. A test builds the units of the planning repo's recorded plan and asserts no unfinished unit gains a wait.

## Guidance: generic in the skills, repo-specific in the kit's AGENTS.md

The authoring skill is shipped to every installation, so it carries only what is true for any repo. The kit-specific rule lives in the kit repo's own
guidance.

**Generic (the `abk-authoring` skill source, the `abk-pipeline` skill source and `docs/architecture.md`).** No mention of the kit's own code or of any
installation.
- A plain `Needs:` is right for ordinary stacked work in one repo: the dependent builds on the parent's reviewed branch.
- Write `merged` when the dependent's tests or behaviour need the parent's code in the default branch (for example a product fix found by an e2e unit,
  or a group that exercises a setting or command the parent adds), or when an e2e group runs against a stack built from the default branch.
- A cross-repo `Needs:` is a merge edge automatically (a plain one is read as `merged`).
- A fix change that a failed unit waits on needs no `merged` line, whoever wrote it: the failed-wait rule already waits for the merge.
- Three generic example lines:

```
Needs: inventory-api group 2 merged — this group's e2e test calls the endpoint that group adds, which main must serve
Needs: retry-setting group 1 merged — the tests set the new retry limit, so the setting must be in the default branch
Needs: shared-types group 2 — builds on the types this group adds; stacking on its branch is enough
```

**Repo-specific (agent-build-kit's `AGENTS.md`, section "Code changes go through the spec process").** A bullet is added, in that section's style (a bold
lead-in, plain sentences, no installation named, as the repo's rule on names requires): when the parent's change alters this repo's own tick, requeue, wait-end, plan, graph, build, usage or gate code, a dependent that must run on it (a unit waiting on a fix, a unit whose tests
exercise it) writes `Needs: ... merged`, because a tick loads the kit's code once, at its start, so a merge during a tick reaches only the next. One
example line, with a generic change name. `CLAUDE.md` only loads `AGENTS.md`, so it needs no edit.

**How authors reach it.** A spec author working in a planning repo that manages the kit reads the kit's `AGENTS.md` through the kit repo's own guidance
(it is the file agents load in that checkout), and a planning repo may point to it from its own conventions; the kit's skills do not repeat it, because
no other repo is the pipeline an installation runs on, so the rule is about this repo alone and says nothing general about "the repo the pipeline runs from".

Recorded failures' fix changes (flaky tests, pre-existing failures) keep their pipeline-written plain lines.

## Risks

- A parent whose merge commit the checkout never fetches holds its dependents; the status says so (third string above) and `abk doctor` may mention it
  later. Not this change.
- A tick that overlaps another (timer-started while one runs) has its own record; the later one overwrites `tick.json`. Both read their own process
  copy for scheduling, so the file only informs the status.
- The sha rule trusts the HEAD it read at start; a checkout switched to another branch mid-tick is outside the model.

## Costs worth knowing

- Only the edges that need it wait for a merge: cross-repo edges (as before, plus one tick), an author's `merged` edges, and a failed unit's wait. Ordinary
  same-repo stacked work, in the kit's repository too, still starts on the parent's branch in review.
- A failed unit now waits for the fix's merge, not its review, so a fix that sits in review for days holds the unit for days; that is the point.
- A cross-repo dependent waits one extra tick after the parent merges, on top of the merge it always waited for.

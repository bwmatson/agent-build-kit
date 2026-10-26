# Design

The code facts below were read in agent-build-kit: `NEEDS_LINE`, `Need` and `group_needs` in
`pipeline/work_graph.py`; `Unit.merge_before`, `through_satisfied`, `base_of`, `waiting_on`,
`unmet_gates`, `waiting_on_me` and `ready_units` in `pipeline/units.py`; `link_needs`,
`gate_sent_back`, `release_gated` and the requeue path in `cli/pipeline.py`; `set_merge_before` and
`StoredUnit` in `pipeline/unit_store.py`; `render_mermaid` and the legend in `pipeline/diagram.py`;
`wait_on_fix` in `pipeline/flakes.py`; `build_upstream_incomplete` and `build_base_moved` in
`pipeline/wiring.py`.

## What a formal Needs becomes

Nothing special. `link_needs` still turns a `Needs:` line into a `depends_on` entry. With no
`merge_before`, `waiting_on` already says what is wanted: a same-repo parent must be in review,
merged or satisfied; a cross-repo parent must have merged (or be satisfied with its work landed).
`base_of` then picks the parent in review as the dependent's base, so the dependent starts on the
parent's branch. This change deletes the second kind of edge rather than adding a rule.

Removed with it: `Unit.merge_before`, `UnitStore.set_merge_before`, the first loop of `waiting_on`
(the "gated dependency is judged as itself" loop), the `merge_before` skips in `through_satisfied`
and the text of `base_of`, and `unmet_gates`.

Cross-repo: unchanged and stated plainly. A stack cannot span repos, so a cross-repo `Needs:`
parent must merge before the dependent starts, whatever the qualifier. Writing `merged` on one adds
nothing.

## 1. The existing `merged` keyword: accepted as a no-op, with a warning

Chosen: accept, warn, change nothing. Rejecting it would make `abk tags` fail on 21 open changes
(35 lines), and the tick's planner refuses a change with task-group problems ("not planning ...:
run `abk tags`"), so a hard reject would stop planning them all until someone rewrote every line.
Several of those changes have units already running. A no-op with a warning is reversible and
cannot stall the pipeline.

- `NEEDS_LINE` keeps recognising the word, so it is not read into the reason. `Need` loses its
  `merged: bool` field and `group_needs` reports the line's use of the word separately (for
  example a `deprecated_merged` flag), which only the validator reads.
- `abk tags` and `abk check` print a warning per line, naming the change, the group and the line:
  `Needs: ... merged` is deprecated; the dependent now starts on the parent's branch once the
  parent is in review. A warning does not change the exit status and does not stop planning.
  (`abk tags` has only errors today; the builder adds a warning channel to the validator rather
  than overloading `ValidationError`.)
- The keyword is removed for good one release later; the spec only requires the warning.

Migration: the last task rewrites the lines by dropping the word `merged`. Count, from
`grep -rniP '^Needs:\s*[a-z0-9-]+\s+group\s+\d+\s+merged(\s|$)' --include=tasks.md` over
`openspec/changes/*` excluding `archive`: **35 lines in 21 changes** (one to four lines each; the command lists them by file). The edit is by hand, done in the last task,
and it is safe to do: `specification_text` strips every `Needs:` line before hashing, so rewriting
them re-plans nothing. Where a line's reason sentence says "merged", the author rereads it: some
reasons ("so they are serialised", "go first") stay true as ordering, others ("must already be
pushed", "must already accept OTLP metrics") describe something only the trunk has and the author
decides whether to keep the dependency or to move the work into one change. A migration warning
the tick never fixes for itself keeps the person in the loop.

## 2. Stored units that carry `merge_before`

`link_needs` recomputes the gate from `tasks.md` every tick (`held` is built from the `gated` map
only, not unioned with the stored value) and has the guard `if unit.id not in wanted and not
unit.merge_before: continue`. So today, once the qualifier is dropped from a line, the next tick
clears the stored value. After this change there is nothing to recompute: the field is gone.

The trap is load, not recompute. `Unit` is `Frozen` with `extra="forbid"`, and `UnitStore` loads
every record with `StoredUnit.model_validate` and turns an unknown key into a "corrupt store"
error. Every existing record has a `merge_before` key (usually `[]`). Dropping the field without a
tolerance would make the next tick refuse to read the store. Rule: the store pops `merge_before`
from a record before validating it, and never writes it. No unit is changed by this other than the
key disappearing at its next write; a unit that was waiting for a merge is waiting on
`waiting_on` alone from the tick the new code runs (a same-repo parent in review releases it
then, which is the intended effect). The replan report no longer prints "waits for" lines.

## 3. Started units that gain, or already have, a Needs

Today a merge gate on a started unit is deliberately inert: a running unit is not disturbed, a
failed or held one requeues to `planned/gated` and waits for the merge, an in-review one sent back
parks `gated`. A gate is not a base, so the unit stays on the trunk.

An ordinary dependency is a base. A unit that started on the trunk and then gains a same-repo
parent in review has `base_of` change from the trunk to the parent's branch. The existing
machinery handles that base change for each state, and nothing new has to be built for it; the
points to confirm are marked.

- **Not started / planned**: `waiting_on` holds it until the parent is in review, then it starts
  on the parent's branch. Unchanged.
- **Failed or held (requeue)**: the requeue command must still not resume a unit past an unmet
  dependency. The `gated` requeue path stays, but is fed by `waiting_on` itself (the check the
  scheduler uses) instead of `unmet_gates`, so a requeue with the parent not yet reviewed (or a
  cross-repo parent not yet merged) leaves the unit `planned` with the cause `gated`, thread,
  branch and feedback kept, and `release_gated` (which already tests `waiting_on`) delivers the
  recorded mode once nothing is left to wait for. Once resumed, the unit restacks on `base_of`,
  the parent's branch, by the resume's restack step. **The builder must confirm with a test** that
  a resumed unit whose branch is on the trunk is rebased onto the new base and its pull request
  retargeted; if the restack handler needs the base recorded on the unit, the requeue records it.
- **Running**: not interrupted by `link_needs`; it only logs once that the unit now depends on the
  parent. The run notices at its next check. `build_upstream_incomplete` stops it with
  `upstream_went_back` while the parent is not yet in review, and `build_base_moved` stops it with
  `base_changed` once the parent is in review and its base would now be the parent's branch. That
  is the same path an ordinary stacked unit takes when its parent goes back, and the unit resumes
  through `waiting_on` and the restack. This is a behaviour change from the gate, which never
  stopped a running unit. **Decision the builder must confirm**: if stopping an in-flight unit is
  judged too risky, the fallback is that a dependency first linked to a unit that has already
  begun is not consulted by those two checks for the run in progress (the run keeps its start-time
  base) and applies from the unit's next start; this needs the link to be remembered per run and is
  not specified here, so the default is the machinery above.
- **In review**: not moved. A pull request that is ready for review on the trunk is left alone
  when a `Needs:` is added; `follow_predecessors` only reacts to a parent whose branch is changing.
  The new base applies when the unit is next sent back for rework and readmitted: it waits until
  the parent is in review, then restacks onto the parent's branch. (This replaces `gate_sent_back`,
  which parked such a unit `gated` for an unmerged gate; `upstream_went_back` and `waiting_on`
  cover the same case, and `gate_sent_back` is removed or reduced to a cross-repo merge wait.)

Should a started unit keep waiting for the parent to *merge*, as the old gate did, to avoid
restacking an in-flight unit? No, except cross-repo. The restack and `base_moved` paths exist for
this and run all the time for ordinary stacked units whose parent is reworked; keeping a second
rule for started units would keep `merge_before` alive for them and the whole point is to delete it.
The risk (a restack conflict on an in-flight unit) is the framework's existing `restack_conflict`
hold, which names the conflict and waits for a person.

The flaky-test parking also uses this path. `wait_on_fix` writes `Needs: <fix> group 1 merged —
flaky test <test>` for a unit whose checks met a flake, so it waits for the fix to land. That line
is written by the framework, so it stops writing `merged`: the unit waits until the fix is in
review and is then restacked onto the fix's branch, which carries the fix, so the unit no longer
meets the flake. **The builder must confirm** this with a test (a parked unit resumes when the fix
is in review, restacked onto it) and update the flaky-tests tests that assert the written line.
If the fix is in another repo, the cross-repo rule holds the unit until it merges.

## 4. Thick edge: formal Needs only

The planner's own inferred dependencies stay as they are: a solid arrow (same repo) or dashed
(cross-repo) with no label. A `Needs:` dependency is drawn with the thick arrow and the label
`needs`: `==>|needs|`. Without `merge_before` the diagram needs to know which edges came from a
`Needs:` line. The unit records this as the subset of `depends_on` that `link_needs` linked, as
`needs: tuple[str, ...]` written by `link_needs` and recomputed each tick from `tasks.md` exactly as
`merge_before` is, so removing a line removes the mark. It has no effect on scheduling: only
`diagram.py` and the unit page read it. (The store tolerates and drops an unknown `needs` the
same way, since it did not exist before.) The legend and `docs/unit-graph.md` say: a thick edge
labelled `needs` is a dependency written as a `Needs:` line; it releases the dependent once the
parent is in review, same repo, or merged, other repo. A cross-repo `Needs:` edge keeps the thick
style (the label is what says it is formal); its wait for the merge is already stated by the
legend's dashed-edge line.

## 5. Needs on the change's own group stays rejected

Today `abk tags` rejects `merged` on a `Needs:` that names the change's own group ("says nothing
-- the groups of one change are ordered already"). That rule stays as it is, and keeps its error
even though a `merged` elsewhere is only a warning: the line is both deprecated and wrong. The plain
form on an own group is not rejected today and one open change has such a line, so widening the
error would stop that change planning; this change does not widen it, and states the existing
rule only. (Widening is a separate change that would rewrite that line first.)

## 6. Interaction with the other scheduling changes

- `blocked-units-free-their-slot` and `start-order-by-stack-age` read `waiting_on`/`blocked`
  and `waiting_on_me`/`depends_on`; `waiting_on_me` ignores `merge_before` today. No edit is
  needed. What changes is the data: a dependent whose parent is in review is no longer blocked,
  so it holds a slot, starts, and sorts by its stack age on the parent's branch. The caps (build
  cap, stack depth cap, rebase cap) apply as for any stack, which is a stronger limit than before
  for chains of `Needs:`; a long `Needs:` chain is held at the depth cap exactly like a long
  planner chain.
- Unit priority inheritance (`effective_priority`, through `waiting_on_me`) is unchanged: a
  `Needs:` dependent already raised its parent's priority, merge gate or not.
- `ready_units` has no merge-gate branch of its own; it calls `waiting_on`.

## Doc and skill text

`docs/unit-graph.md` (the merge-gated row and the scheduling text), `docs/cli.md` (requeue and
`gated`), the `abk-authoring` skill (the `merged` paragraph) and the `abk-pipeline` skill (the
"`Needs: ... merged` line" paragraph and the graph legend), the `render_mermaid` legend, and a
changelog entry. The cause `gated` stays: it now means "waiting on a dependency or a fix".

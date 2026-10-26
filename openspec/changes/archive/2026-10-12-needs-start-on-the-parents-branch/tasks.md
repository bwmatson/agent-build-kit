# Tasks

Acceptance: none — scheduling, validation and diagram behaviour over the unit store and a fake host; tier-1 tests prove it.

Priority: 2

## 1. [agent-build-kit] [tier1] A Needs line starts the dependent on the parent's branch

Done when a same-repo `Needs:` dependent starts on the parent's branch once the parent is in review, a cross-repo one waits for the merge, a stored merge gate no longer holds a unit, and the word `merged` after a `Needs:` is warned about and changes nothing.

- [x] 1.1 Test: a unit with a same-repo `Needs:` parent in review is ready, its base is the parent's branch, and with the parent planned, running, failed or held it waits; a parent sent back for rework pauses a dependent as any dependency does; an edit that changes only a `Needs:` line makes no planner call and applies on the next tick.
- [x] 1.2 Test: a `Needs:` on a cross-repo parent in review still waits, and is released when the parent has merged or is satisfied with its work landed.
- [x] 1.3 Test: `abk tags` and `abk check` print one warning per `Needs: ... merged` line, naming the change, group and line, exit zero and do not stop planning; the word is not part of the reason; a `Needs: ... merged` on the change's own group is still an error.
- [x] 1.4 Test: a stored unit that carries a non-empty `merge_before` is released by the next tick once its parent is in review, because `link_needs` no longer sets or keeps a gate from the word `merged`.
- [x] 1.5 Make `link_needs` treat a `Needs:` line, with or without `merged`, as a plain dependency and clear any stored gate; keep the word recognised in `NEEDS_LINE` so it is not read into the reason, report its use separately for the validator, and add a warning channel to `abk tags` and `abk check`.

## 2. [agent-build-kit] [tier1] A Needs line added to a started unit is an ordinary dependency

Done when a `Needs:` added to a failed, held, running or in-review unit follows the ordinary dependency rules, `abk requeue` gates on `waiting_on`, and the flaky-test parking writes an unqualified `Needs:`.

- [x] 2.1 Test: a `Needs:` added to a failed or held unit with an unmet parent leaves it `planned` with the cause `gated` on requeue, keeps thread, branch and feedback, names the group it waits for, is listed by `abk status` as waiting on that group, and resumes in the requeued mode, restacked onto the parent's branch with its pull request retargeted, when the parent is in review.
- [x] 2.2 Test: a `Needs:` added to a running unit does not stop the step in progress, is logged once, and the unit then stops through the upstream and base checks and resumes by the ordinary path; an in-review unit is not moved when one is added, and on rework waits for the parent and restacks onto it.
- [x] 2.3 Test: a unit parked for a flaky test by `wait_on_fix` gets an unqualified `Needs:` on the fix, resumes when the fix is in review, restacked onto its branch.
- [x] 2.4 Feed the `gated` requeue and its release (`release_gated`, `gate_sent_back`) from `waiting_on` instead of `unmet_gates`, and write the flaky `Needs:` in `wait_on_fix` without `merged`; update the flaky-tests tests that assert the written line.

## 3. [agent-build-kit] [tier1] The merge gate is removed and the graph marks a Needs dependency

Done when `merge_before` and every merge-gate branch are gone, a store that still carries `merge_before` loads, the graph draws `==>|needs|`, the docs, skills and changelog say so, and the existing `Needs: ... merged` lines are rewritten.

- [x] 3.1 Test: a store whose records carry `merge_before` (empty and non-empty) loads, the unit then waits on `waiting_on` alone, and the next write has no `merge_before` key.
- [x] 3.2 Test: the unit graph draws a `Needs:` dependency as `==>|needs|`, the planner's own edges unlabelled and not thick, and the legend and `docs/unit-graph.md` say so; removing the line removes the mark at the next tick.
- [x] 3.3 Remove `merge_before` and the merge-gate branches (`waiting_on`, `through_satisfied`, `base_of`, `unmet_gates`, `set_merge_before`, the replan "waits for" line, the unit page's `merge_gates`); drop the field when the store loads a record; record `needs` edges in `link_needs` for the graph.
- [x] 3.4 Update `docs/unit-graph.md`, `docs/cli.md`, the `abk-authoring` and `abk-pipeline` skills and the `render_mermaid` legend, and add a changelog entry.
- [x] 3.5 In the planning repo, rewrite the 35 `Needs: ... merged` lines of the 21 open changes to drop the word `merged`, rereading each reason; run `abk tags` over every open change and confirm no warning is left.

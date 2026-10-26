# Tasks

Acceptance: none — hold-and-split is a configuration rule, a pure verdict step, store transitions, a plan check and a tick step, each proved by a unit-test over fake units, fake plans, temporary git repositories and temporary state directories; a split of a real unit needs a real planner and reviewer model, and that is what the soak criterion in the last group measures on the installation that builds this framework.

Priority: 1

## 1. [agent-build-kit] [unit-test] The buffer and rounds settings

Done when `review.ceiling_buffer` and `review.split_rounds` load with their defaults and ranges, a buffered `auto` ceiling at the reviewer's reading limit fails loading, and `abk doctor` warns about a buffered ceiling near the limit and about zero rounds with review enabled. Estimate: about 280 changed lines.

Needs: units-are-sized-by-review-tier group 11 — the per-tier ceilings, the sizing digest and the tier a plan sizes by exist first
Needs: tests-are-stubbed-checked-and-committed-per-group group 10 — a piece can take a group's commit pair only when the build commits per group

- [x] 1.1 Test: in `tests/config/test_review_split_settings.py`, with no settings the buffer is 0.2 and the rounds 2, a buffer of 1.5 or -0.1 fails naming the key and value, rounds of 3 or -1 fail likewise, an `auto` ceiling of 9000 with the default buffer fails naming the ceiling, the buffer and the limit, and the same check applies to a repo's merged ceilings naming the repo.
- [x] 1.2 Test: in `tests/cli/test_doctor_review_split.py`, `abk doctor` prints the buffered ceilings, warns for an `auto` ceiling of 7000 with the default buffer, warns for zero rounds with review enabled, and is silent for the defaults.
- [x] 1.3 Add the two settings and their validation to the review section, and the doctor checks.

## 2. [agent-build-kit] [unit-test] The verdict's size step

Done when the verdict returns hold-and-split, with the tiers, the lines, the ceiling and the drivers as groups, for a unit over its earned tier's buffered ceiling and keeps its verdict otherwise. Estimate: about 360 changed lines.

- [x] 2.1 Test: in `tests/pipeline/test_verdict_size.py`, a table of units: a unit planned `auto` that earns `full` is held at 950 lines and not at 800, one earning `light` is held over 2400 and not at 2400, a unit planned and earning `light` at 2500 is held with no drivers, a repo's override is the ceiling used, a unit under every ceiling keeps its tier and reason, a waived unit is not held, the result is the same on a second computation, and no step makes a model call.
- [x] 2.2 Test: in `tests/pipeline/test_verdict_drivers.py`, a driver naming group 3 is group 3, a driver naming a file that group 3's task text names is group 3, one naming a file no group names is dropped and a verdict whose drivers all drop carries none, and a driver outside the unit's groups is dropped.
- [x] 2.3 Add the size step to the verdict taking the ceilings in effect, the buffer, the changed lines and the unit's groups with their task text.

## 3. [agent-build-kit] [unit-test] A unit over its tier is held as too big, which is neither a failure nor a review round

Done when a review round, whether it approves the unit or asks for another, whose verdict is hold-and-split leaves the unit held at that round with the new cause and holder and the request on it, a round that holds the unit for a person is not also held by size, with the review round and rework rounds unchanged, a failure to compute the step lets the unit go on, and the flag off never runs it. Estimate: about 330 changed lines.

- [x] 3.1 Test: in `tests/graph/test_hold_too_big_for_tier.py`, with a fake verdict saying hold-and-split, a round that approves and a round that asks for changes each hold the unit at once with the cause and the size holder and start no rework round, a round whose reply holds the unit for a person is held for that reason and not by size, the request holding the tiers, lines, ceiling and drivers is stored, `review_round` and the rework count are as before, the unit is not failed, and no push or pull request is made.
- [x] 3.2 Test: in `tests/graph/test_hold_too_big_for_tier_safety.py`, a verdict that raises is logged and the unit goes on as in shadow mode, and with `review.enabled` false the size step is never asked.
- [x] 3.3 Test: in `tests/pipeline/test_unit_store_split_fields.py`, the request, the rounds used, the waiver, `split_from` and `superseded_by` round-trip through the store, `upsert` keeps them, and a record written before they existed loads with their defaults.
- [x] 3.4 Add the cause and the holder, the stored fields, and the hold in the review step on a hold-and-split verdict.

## 4. [agent-build-kit] [unit-test] A unit held for its size raises no card, and a person's requeue waives the size

Done when a unit held by size and waiting for a split raises no card while the same unit held for a person does, and a person's requeue of a unit held for its size records that the size is waived. Estimate: about 200 changed lines.

- [x] 4.1 Test: in `tests/notify/test_card_too_big_for_tier.py`, a unit held by size and waiting for a split raises no card, and the same unit held for a person with the review holder and the same cause does.
- [x] 4.2 Test: in `tests/cli/test_requeue_size_waived.py`, `abk requeue` of a unit held for a person for its size records that its size is waived, the next review's verdict skips the size step, a requeue of a unit held for another reason records nothing, and the record survives a restart.
- [x] 4.3 Add the waiver in the requeue, and the card rule.

## 5. [agent-build-kit] [unit-test] A split's pieces have ids of their own and a held unit can be superseded in the store

Done when a unit made by a split has an id that extends its parent's, nothing that reads an id's last segment as an integer breaks, `UnitStore` can supersede a unit in one write, closing it with the cause and its pieces, adding the pieces and re-pointing what depended on it, and its branch is kept under a ref. Estimate: about 360 changed lines.

- [x] 5.1 Test: in `tests/pipeline/test_unit_ids_of_pieces.py`, the number of `app/3-s2-s1` is 3, an acceptance unit `app/5` follows `app/3-s1` in `earlier_units`, a piece's branch is `spec/app/3-s1`, the run-log and transcript names of `app/3` and `app/3-s1` are found each by its own id and not the other's, and the ordinary ids behave as before.
- [x] 5.2 Test: in `tests/pipeline/test_unit_store_supersede.py`, superseding writes in one step the pieces as planned units with the dependencies given, the old unit closed with the cause and pieces, and every dependent's dependency and `Needs:` target re-pointed to the last piece, a unit that already depended on it by a satisfied unit is re-pointed through it, a failed write leaves the store as it was, and superseding a unit that is not held by size is refused.
- [x] 5.3 Test: in `tests/pipeline/test_superseded_branch_ref.py`, over a temporary repository the branch's tip is kept at `refs/spec-driven/superseded/<unit id>` with the branch lock held, the remote branch is untouched, and a branch whose lock a live process holds is left alone with nothing changed.
- [x] 5.4 Make the id readers take the leading integer and the suffix, add the superseded cause and the store operation, and keep the ref.

## 6. [agent-build-kit] [unit-test] A superseded unit's pull request is closed and its readers treat it as closed

Done when a superseded unit's pull request is closed after a comment naming the pieces, and archiving, the poller, slots, taken groups and the status each treat it as the design says. Estimate: about 330 changed lines.

- [x] 6.1 Test: in `tests/pipeline/test_superseded_readers.py`, a superseded unit's groups are not taken and not required to still be in `tasks.md`, it occupies no slot, nothing waits on it after the re-pointing, a change whose pieces merged is ready to archive, a plan using its id is not accepted by the store's upsert, and the status and graph show it as closed with its pieces named.
- [x] 6.2 Test: in `tests/pipeline/test_superseded_close.py`, a comment naming the pieces, the lines, the ceiling and the tier is posted before the pull request is closed, a failed close is kept and retried on a later pass, the poller's closed event for the pull request leaves the unit closed with the cause superseded, and the retry clears the record once it is closed.
- [x] 6.3 Teach archiving, the closed event and the close retry to treat a superseded unit as the design's table says.

## 7. [agent-build-kit] [unit-test] The planner takes a split request

Needs: fix-flaky-tests-runtimes-test-policy-agent-harness-py-test-a-41a62277 group 1 — flaky test tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory

Done when the planner's instructions and the planner round accept a split request, the instructions give the unit's groups in order with the pins, tiers and ceilings and the retired ids, and a split plan round passes only the held unit's groups to the planner with every other group as built. Estimate: about 330 changed lines.

- [x] 7.1 Test: in `tests/pipeline/test_planner_pins_prompt.py`, with a split request the instructions name the unit's groups in order, the pinned groups and the two tiers, the ceilings of each, the piece ids to use, say to chain the units and keep the order, and list the retired ids; with no drivers they ask only that each unit come under its ceiling; and without a split request the instructions are as before.
- [x] 7.2 Test: in `tests/pipeline/test_planner_split_round.py`, a split plan round passes only the held unit's groups to the planner with every other group as built, applies the ceiling and flag checks at each piece's tier, and a single driver group alone over the earned ceiling raises the too-large error.
- [x] 7.3 Add the split request input to the planner round, the instructions and the parse.

## 8. [agent-build-kit] [unit-test] A split's plan is checked against the pins, the shape and the retired ids

Needs: fix-flaky-tests-runtimes-test-policy-agent-harness-py-test-a-41a62277 group 1 — flaky test tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory

Done when the plan check refuses a plan that mixes drivers with other groups, uses a wrong tier, breaks the order, names a wrong id, breaks the chain or reuses a retired id, and a correct split of a unit with a driver in the middle is accepted. Estimate: about 360 changed lines.

- [x] 8.1 Test: in `tests/pipeline/test_planner_check_pins.py`, a driver group beside another group is refused naming the unit and both groups, a driver unit at the planned tier is refused naming the earned tier, a unit of other groups at the earned tier is refused, two adjacent drivers in one unit within the earned ceiling are accepted, two drivers with a group between them in one unit are refused, and with no drivers every unit must be at the earned tier.
- [x] 8.2 Test: in `tests/pipeline/test_planner_check_split_shape.py`, pieces that do not partition the unit's groups into contiguous runs in order are refused, ids other than the parent's with `-s<k>` are refused, a first piece that does not depend on what the held unit depended on is refused, a later piece that does not depend on the one before is refused, a piece depending on another unit of the change is refused, and the correct split of groups 1 to 5 around driver 3, chained at the planned, earned and planned tiers, is accepted.
- [x] 8.3 Test: in `tests/pipeline/test_planner_retired_ids.py`, a plan of any change that uses the id of a superseded unit is refused naming it, and a change with no superseded unit is unaffected.
- [x] 8.4 Add the pins check and the split shape check beside the group check, and the retired-id check.

## 9. [agent-build-kit] [unit-test] The tick splits units held by size and counts the rounds

Done when each tick, after planning, takes each unit held by size in priority order and asks for a split, records a round for every attempt that succeeds or fails and none for an outage, supersedes the unit with the pieces on success, leaves it held by size to try again on failure, and holds it for a person when the rounds are used. Estimate: about 350 changed lines.

- [x] 9.1 Test: in `tests/cli/test_split_held_units.py`, with a fake planner, a unit held by size is replaced by pieces that are planned with the dependencies of the held unit, the held unit is closed with the cause and its pull request is closed, its dependents depend on the last piece, and the tick says what was done.
- [x] 9.2 Test: in `tests/cli/test_split_rounds.py`, a refused plan, an invalid reply and a plan that ignores the pins each record one round and leave the unit held by size for the next tick, an outage records none, a lineage with `split_rounds` used is held for a person naming `2 of 2`, `split_rounds: 0` makes no planner call, and a piece inherits its parent's count so a piece of a first split has one round left.
- [x] 9.3 Add the split step to the tick after planning and linking, the rounds and the hold when they are used, and the supersession call with the pieces.

## 10. [agent-build-kit] [unit-test] A unit that cannot be split is held for a person and later plans keep the pins

Done when a unit that cannot be split is held for a person with the reason, every later plan of the change is given and held to the pins of its superseded units, and a split is not attempted while the usage guard refuses planning or a live process holds the branch lock. Estimate: about 340 changed lines.

- [x] 10.1 Test: in `tests/cli/test_split_held_for_a_person.py`, a unit of one group, a driver group alone over the earned ceiling, a unit that carries groups of another change, and a unit with a started dependent are each held for a person with the review holder and a note naming the reason, with no round used for the first and the last, and a card is raised.
- [x] 10.2 Test: in `tests/cli/test_plan_keeps_pins.py`, an ordinary plan of a change with a superseded unit whose pieces are unstarted is given the pins and refused if it regroups the driver, one whose pieces have started is given none, and the plan record is written only for an accepted plan.
- [x] 10.3 Test: in `tests/cli/test_split_guards.py`, a split is not attempted while the usage guard refuses planning, a branch lock held by a live process defers the split without a round, and two ticks do not split the same unit twice.
- [x] 10.4 Add the holds for a unit that cannot be split, the pins given to every plan of a change, and the usage and branch lock guards to the split step.

## 11. [agent-build-kit] [unit-test] A piece takes the commit pairs of its groups from the superseded branch when they can be reused

Needs: a-group-with-no-new-tests-gets-an-empty-tests-commit group 2 merged — this unit is the test case for that fix: its group 12 tests are green without an implementation (group 11's code already covers them), which the stubbed build stops on until a real tests commit that already passes records an empty implementation commit; it must run on the merged build code.

Done when a piece whose groups were built per group on the superseded branch has their pairs cherry-picked onto its own branch when its run is prepared and goes on from the branch, and a branch with any other commit is rebuilt, the old ref being kept either way. Estimate: about 260 changed lines.

- [x] 11.1 Test: in `tests/graph/test_piece_reuses_pairs.py`, over a temporary repository whose superseded branch holds three pairs, a piece for the third group is prepared with that pair on its branch and the build writes no agent output for it, a piece for the first two has both pairs in order, and the run goes on from the branch to its checks.
- [x] 11.2 Test: in `tests/graph/test_piece_rebuilds.py`, a superseded branch with a `fix:` commit, with a commit whose subject is no pair's, with a missing pair, or one built before per-group commits is not reused and the piece is built from scratch, and the reason is said once.
- [x] 11.3 Read the superseded branch's pairs from its ref, decide reuse from its commits alone, and pick the pairs for the piece's groups in order when the branch has no commits.

## 12. [agent-build-kit] [unit-test] A pair that does not apply ends the reuse, and a unit that is not a piece is prepared as before

Done when a pair that does not apply cleanly ends the reuse at that group, and a unit that is not a piece is prepared as before, a piece prepared twice picking its pairs once. Estimate: about 220 changed lines.

- [x] 12.1 Test: in `tests/graph/test_piece_cherry_pick_conflict.py`, a first pair that applies and a second that conflicts leaves the first on the branch, the conflicting pick aborted with a clean tree, and the agent building the second group.
- [x] 12.2 Test: in `tests/graph/test_piece_not_split_from.py`, a unit with no `split_from`, or whose parent ref is missing, is prepared exactly as before, and a piece prepared twice does not pick its pairs twice.
- [x] 12.3 Abort a conflicting pick, ending the reuse at that group, prepare a unit with no `split_from` or no parent ref as before, and do not pick a piece's pairs twice.

## 13. [agent-build-kit] [unit-test] The documents and skills describe hold-and-split

Done when `docs/configuration.md` and the `abk-config` skill document `ceiling_buffer` and `split_rounds`, `docs/architecture.md` and `docs/unit-graph.md` describe the size hold, the superseded unit and the split step, `docs/cli.md` and the `abk-pipeline` skill say what a unit held by size and a unit held for a person for its size mean and what `abk requeue` does with one, the `abk-authoring` skill says a group the reviewer names as a driver is split out by the pipeline and `tasks.md` need not change, and a document test keeps them from drifting. Estimate: about 360 changed lines.

- [x] 13.1 Test: in `tests/docs/test_hold_and_split_docs.py`, the configuration document and the `abk-config` skill name both settings and their defaults and the reading limit, the architecture and graph documents name the superseded cause, the hold cause and the ref, `docs/cli.md` and the `abk-pipeline` skill name the two holds and the waiver, and the `abk-authoring` skill names drivers and says `tasks.md` is not changed by a split.
- [x] 13.2 Update the documents and the three skills' text, and add a changelog entry saying a unit over its tier's buffered ceiling is replaced by smaller units, what a person sees and when.

## 14. [agent-build-kit] [unit-test] Per-tier sizing is on by default

Done when `review.enabled` defaults to true, a workspace with no `review` section sizes units by tier and applies the verdict's size step with auto-land still off, setting it false returns every unit to `max_unit_lines` and computes no verdict, `abk init`'s template and the documents say true, and the changelog records the soak figures the design asks for. Estimate: about 150 changed lines.

- [x] 14.1 Test: in `tests/config/test_review_enabled_default.py`, a workspace with no `review` section reports `enabled` true with the ceilings 5000, 2000 and 750 in effect and no class allowed to auto-land, an explicit false holds every unit to the `full` ceiling and computes no verdict, and `abk init`'s template and `docs/configuration.md` state the default as true.
- [x] 14.2 Change the default, the template and the documents, remove the earlier tests' assumption that the flag is off where they rely on the default, and add the changelog entry with the units built, how many were split, how many ended held for a person and the planner-accuracy reading, taken from the installation that ran the soak; the group is not built until those figures meet the criterion in the design.

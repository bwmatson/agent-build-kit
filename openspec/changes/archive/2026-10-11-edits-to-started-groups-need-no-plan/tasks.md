# Tasks

Acceptance: none — the planner is faked at its boundary as in the existing planning tests; the behaviour is decided by files, the store and a planner reply, and no consumer sees a new surface.

Priority: 2

## 1. [agent-build-kit] [tier1] Record an edit to started groups without asking the planner

Done when a change whose every group belongs to a started unit is recorded as planned with no model call, a tag change under a started unit is reported and not recorded, and `abk replan` prints the outcome.

- [x] 1.1 Test: editing the text of a failed (or held, in-review) unit's only group makes no planner call, records the new hash as planned with no attempts, and a requeued unit reads the edited text; a tick after the edit makes no call.
- [x] 1.2 Test: editing the text of a merged unit's group is recorded the same way, with no call.
- [x] 1.3 Test: a change with one unstarted group left still calls the planner, with the started groups passed as built.
- [x] 1.4 Test: a changed repo, tier or flag on a started unit's group is reported with the unit and the way out, the unit is not rewritten, and the plan is not recorded as done; a restored tag, or `abk requeue --restart` and the new tags, ends the report.
- [x] 1.5 Test: renumbering or deleting a started group is refused with the existing message and no call is made.
- [x] 1.6 Test: `abk replan <change>` for such a change prints that nothing was asked of the planner and why, exits 0, and for a tag change prints the report and exits 1.
- [x] 1.7 In `plan_all`, compute the unclaimed groups after the hash check and tag validation; with none, compare the started units' stored repo, tier and flag with their groups' tags, then record the hash and return `planned`, or report the differences and record nothing; print the outcome in `abk replan`.

## 2. [agent-build-kit] [tier1] Tell the planner which groups are taken and keep why a plan was refused

Done when the prompt states the rule and marks taken groups, a planner that claims one is still refused, and the refusal reason is stored and shown by a bare `abk replan`.

- [x] 2.1 Test: building the prompt with a fake in-flight unit that builds a group includes the explicit rule that built groups are never claimed, and the change text marks that group's heading `(built by <unit id>)` and no other.
- [x] 2.2 Test: a planner fake that returns a unit claiming a built group is still refused, and no unit is stored for it (extends `test_a_built_group_cannot_be_silently_rebuilt`).
- [x] 2.3 Test: a refused plan stores the unit ids the planner returned and the refusal reason in the plan record, not the model text, and a bare `abk replan` shows the reason beside the plan state.
- [x] 2.4 Test: a successful plan, and a record-only plan, store no reason, and a refusal's reason is cleared by the next success.
- [x] 2.5 Add the rule to the planner prompt, mark taken groups in the change text `build_prompt` sends, store the returned ids and reason in `record_plans`, and show the reason in the `abk replan` listing.
- [x] 2.6 Document it in the planning paragraph of `docs/architecture.md` and in `docs/cli.md`, and add a changelog entry.

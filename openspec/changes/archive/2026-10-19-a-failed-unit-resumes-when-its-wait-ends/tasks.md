# Tasks

Acceptance: none — the trigger, the mode rule and the delivery are exercised over a unit store and a fake host; tier-1 tests prove each case and nothing a consumer drives changes.

Priority: 1

## 1. [agent-build-kit] [unit-test] A failed unit requeues itself once when its wait ends

Done when a failed unit that waited on another unit is requeued once, in a mode chosen from its record, the moment its wait ends; a held unit, a closed prerequisite and a plain failure are left; `global_limits.wait_end_requeue` overrides or turns it off; and the status says so. It builds only on code already in the main branch (the `global_limits` block, `failed_waiting`, `release_gated`, `requeue`) and touches no document, so it depends on no unbuilt unit. Estimate: about 330 changed lines.

- [x] 1.1 Test: a failed unit waiting on a `Needs:` parent is recorded as waiting by a pass, and when the parent merges the next pass requeues it once; its history note reads `requeue: its wait ended (waiting on <change> group <n> is now merged)`, naming each prerequisite, and its thread, branch, feedback and guidance are kept.
- [x] 1.2 Test: the unit that fails again after the requeue and waits on nothing is not requeued by the next passes; the same record is acted on once however many passes run.
- [x] 1.3 Test: a second prerequisite added to the failed unit later starts a new record, a new wait and a second automatic requeue when it ends; a prerequisite joining while the first still holds keeps one record and one requeue.
- [x] 1.4 Test: a held unit is not requeued when its prerequisite merges and carries no record; a unit released to failed afterwards is judged afresh; a failed unit with no wait, no `Needs:` and no dependency change is untouched by any number of passes.
- [x] 1.5 Test: when the prerequisite is closed and the wait ends, the unit stays failed, is not requeued, prints `wait ended: <prerequisite> closed, requeue to retry` in the status, and a later `abk requeue` clears the line.
- [x] 1.6 Test: the mode follows the record: a saved tier 2 or tier 1 failure with feedback is a rework; an environmental cause (toolchain, environment, host, network or service unavailable) is a resume even with feedback; no saved failure, or a source of review, CI or conflict, is a resume; a person's note stays in the guidance and does not change the mode, and a rework shows it ahead of the saved failure.
- [x] 1.7 Test: `global_limits.wait_end_requeue` `resume` and `rework` force that mode (`rework` with nothing saved falls back to resume), `off` leaves today's behaviour (nothing recorded, nothing requeued, no status line), an unknown value is refused when the config loads, and the default is `auto`.
- [x] 1.8 Test: with a usage pause active the requeue is delivered to the thread and no build starts until the pause ends; a branch held by another run leaves the unit failed with its record and the next pass requeues it; the requeue is not held by `max_units_in_progress` and a planned unit never started still waits for room.
- [x] 1.9 Test: a unit parked planned and gated by the failure-fix or flaky-test mechanism, and one a person requeued while it waited, are not touched by the step and resume by their own path; the status line counts only requeues from the wait's end and reads `failed units resumed when their wait ended: N today`, left out at zero.
- [x] 1.10 Add `waited_on` and `wait_ended` to the unit store with their setters, `global_limits.wait_end_requeue` to `LimitsConfig` as a `StrEnum`, and the `because` keyword to `requeue`'s delivery for the history note; a store written before the fields loads.
- [x] 1.11 Add `requeue_wait_ended` to `cli/pipeline.py` after `release_gated` in `run_round`: record, detect, choose the mode by the rule, deliver through `requeue`, clear the record; add the status lines.

## 2. [agent-build-kit] [unit-test] The documents, the skills and the changelog describe the automatic requeue when a wait ends

Priority: 3

Done when `docs/cli.md`, `docs/architecture.md`, `docs/configuration.md`, the `abk-config` and `abk-pipeline` skills and the changelog say that a failed unit requeues itself once when its wait ends and how `global_limits.wait_end_requeue` changes it. The code group does not wait on this group; it is a separate group so the documents, which other unbuilt changes also edit, do not hold the requeue step back. Estimate: about 130 changed lines.

- [x] 2.1 Update `docs/cli.md` (`abk requeue`: automatic requeue when a wait ends), `docs/architecture.md`, `docs/configuration.md` and the `abk-config` skill (`global_limits.wait_end_requeue`), the `abk-pipeline` skill, and add one changelog bullet under `## Unreleased` as `AGENTS.md`'s Changelog section says; narrow the "never requeued" sentences the earlier change's unit wrote in the docs.

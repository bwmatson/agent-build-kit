# Tasks

Acceptance: none — the requeue is decided over a fake unit store, a fake held set and the fake `resume_thread` the requeue tests use; no model or host is reached, so a scripted run of the command would only repeat them.

Priority: 0

## 1. [agent-build-kit] [unit-test] A unit parked on a split is requeued for rework, or refused for what it is parked on

Priority: 0

Done when `abk requeue UNIT --rework` (with or without a note) and `--restart` accept a unit that is `planned` with cause `split_held` or non-empty `parked_splits`, has no pull request and is not in flight, deliver the requeue as for any unit with a thread (the person's note stored as guidance; with no thread the guidance stored and the unit `planned` with cause `requeued`), clear `parked_splits`, `parked_sha`, `parked_snapshot`, the `split_held` cause and the wait record only after a delivery, write a history entry naming the splits it was parked on and the note, and run from `prepare`; a plain requeue is refused while a parked split is held with the parked-on message and behaves as the release does when none is; running, in-review, merged, in-flight and pull-request units are still refused. Estimate: about 240 changed lines.

- [x] 1.1 Test: `tests/cli/test_requeue_parked_unit.py` asserts, over a fake store and a fake `resume_thread`, that `requeue(...)` of a `planned` unit with cause `split_held`, `parked_splits` `["acp"]`, a `parked_sha`, a `parked_snapshot` and a branch, in mode `rework` with a note, is accepted (exit 0) and delivered exactly once with `requeue=RequeueReason.FROM_FAILURE` and the note as guidance, that its `parked_splits` is empty, `parked_sha` and `parked_snapshot` are `""`, its cause is no longer `split_held` and its history entry names `acp` and starts with the note; that `--note-file` does the same; that `rework` with no note is accepted for a parked unit with no saved failure and stores an automatic guidance that names `acp`; that `restart` is accepted, clears the unit's feedback and stores a note when given; and that a second `requeue` of the same unit is not accepted as parked (it is `planned` with cause `requeued`, no park).
- [x] 1.2 Test: the same file asserts a plain requeue (mode `resume`) of a unit parked on `acp` while `acp` is held delivers nothing, changes nothing and says "is parked on e2e-test split acp (held: <reason>)" and "--rework" and "release"; that with `acp` released (or `rest`-only holds) it is delivered `RequeueReason.RESUME` and the no-thread fallback sets `planned`/`requeued`, the same as `release_split_held`; that a plain requeue with a note is still refused as before; that a unit parked on two splits, one held, is refused naming both; and that a unit whose group's `Split:` moved away from its stored split is refused a plain requeue with a line saying the pass reworks it.
- [x] 1.3 Test: the same file asserts the refusals stay: a `running` unit, an `in_review` unit, a `merged` unit, a plain `planned` unit with no park and an `unplanned` unit with parked splits are refused with the message they had before and nothing changed; a parked unit whose `pr` is set is refused naming the pull request; a parked unit whose delivery raises `BranchBusy` (a step holds the branch) is refused with "is being built" and keeps its park, cause and every field it had, and a later requeue once the branch is free is accepted.
- [x] 1.4 Test: `tests/graph/test_requeue_parked_unit_run.py` asserts, over the fake graph the requeue tests use, that a parked unit delivered the rework requeue with a note runs the agent again from `prepare` as a rework (the guidance is stored and read by the run) and does not go to the e2e step first, and that the same holds for `restart`.
- [x] 1.5 Make the requeue accept the parked unit: extend `requeue_refusal` and the checks after it in `requeue()` for the cases above (the web UI's action goes through the same function), skip the "no saved failure" refusal for a parked unit, store the automatic guidance when a rework has no note, deliver through `resume_thread`, then clear the park with `set_parked(unit.id)` and write the history entry; a plain requeue is judged by `parked_holds`; no new `RequeueReason` member, wait reason or command.

## 2. [agent-build-kit] [unit-test] The status after a requeue and the help text say a parked unit can be requeued

Priority: 0

Done when `abk status` after the requeue lists the unit as a requeued planned unit and no longer as waiting for the split, with its history note, `abk requeue --help` and the command's docstring say a unit parked on a held split is requeued with `--rework` (note) or `--restart`, and the plain requeue refusal message is the one scenario text. Estimate: about 80 changed lines.

- [x] 2.1 Test: `tests/cli/test_status_requeued_parked_unit.py` asserts `abk status` before the requeue has the "waiting for e2e-test split acp" line for the unit and after a rework requeue has none, shows the unit as queued/requeued with the history entry naming `acp` and the note, and leaves another unit parked on `acp` on its line.
- [x] 2.2 Test: `tests/cli/test_requeue_help_parked.py` asserts the `abk requeue` parser's help and `cmd_requeue`'s docstring name a unit parked on a held split and the options that accept it, and that `--note`'s help no longer says "failed or held" only.
- [x] 2.3 Update the `requeue` parser help (`help="give a failed or held unit another go"` and the `--rework`/`--note` help) and `cmd_requeue`'s docstring, and keep the web UI's requeue action on the same message.

## 3. [agent-build-kit] [unit-test] The documents, the skill and the changelog say a parked unit can be requeued

Priority: 0

Done when `docs/cli.md` (`abk requeue`), `README.md`'s command table and the `abk-pipeline` skill source (`src/agent_build_kit/skills/abk-pipeline/SKILL.md`, the `split_held` paragraph and the requeue rows) say a unit parked on a held split is requeued with `--rework` and a note or `--restart`, that a plain requeue is refused while the split is held, and what is still refused, and the changelog has one bullet under `## Unreleased`. Estimate: about 70 changed lines.

- [x] 3.1 Test: `tests/docs/test_requeue_parked_unit_documented.py` asserts `docs/cli.md`'s `abk requeue` section and the `abk-pipeline` skill name a parked unit, `--rework`, the refusal of a plain requeue while the split is held and the refusals that stay (running, in review, merged, pull request), and that `CHANGELOG.md` has the bullet once under `## Unreleased`.
- [x] 3.2 Update `docs/cli.md` (the `abk requeue` section: replace "a planned or merged one has nothing to retry" with the parked-unit rule), `README.md`'s requeue row and `docs/architecture.md`'s parked-unit paragraph.
- [x] 3.3 Update the `abk-pipeline` skill (the `split_held` paragraph: what a person does for a mis-tagged test, and the requeue rows) and add one changelog bullet under `## Unreleased` as the repository's changelog section says: written for the person, one bullet, a two-space continuation, no unit names or numbers.

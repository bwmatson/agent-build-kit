## Context

**E2e-test splits.** This change is about e2e-test splits: named subsets of a repo's e2e-test tests that a repo declares and that can be held. The directory name `tier2-tests-are-tagged-by-runtime`
stays because renaming it would orphan the stored units (their ids, branches and run records name it); its title, README, proposal and the groups that have not started say splits.
Groups 1 to 5, 7 and 12 were built with runtime names, groups 8 and 10 were running when the model was generalised, and `tier2-splits-replace-runtime-tags` migrates all of them. Read
the sections below with this table: the decisions stand, the names are the old ones.

| Written below | Now |
| --- | --- |
| runtime, `runtime_<name>` tag, the base group | split, its marker (the kit's choice), `rest` |
| `tests.runtimes_blocked`, `runtimes_allowed`, `e2e_runtimes` | `tests.e2e_splits.<name>` with `hold: true`, `hold: false`, and the declared splits themselves |
| blocked set, `e2e-blocked.json`, `abk e2e-test block`/`unblock` | held set, `e2e-held.json`, `abk e2e-test hold`/`release` |
| `--until` on `block` | none: a hand-set hold ends only with `release`; a deadline exists only on a `gate` entry |
| source `command`, `provider`, `availability` | source `command`, `gate` |
| the provider on a runtime (`<redacted>_provider`) | `gate.provider`, `gate.command` on a split (`a-runtimes-provider-has-usage-windows`) |
| the check by the kit's collection plugin | the listing check of `abk e2e-test check`; the plugin stays as the kit's own convenience |

A runtime's model backend can be down for a reason that is nobody's bug (an exhausted budget). E2e-test has no way to leave one runtime's tests out, so such a run fails, is
recorded as a failure on the base, and the open-fix gate holds every full-scope run of the repo behind a fix change that cannot be written. This change adds the tag, the selection,
the block, the parking and the per-runtime record, and tags the kit's own live tests.

## What was checked, and where

Read-only against agent-build-kit `origin/main` (`de6527ef`, which holds group 3 of `tier2-runs-on-a-schedule`); paths are under `src/agent_build_kit/`. Every reference below
was re-read at that commit; where it differs from the plan this change was written from, it says so under "Differences from the plan".

- `profiles/python_uv.py`: `e2e_commands(repo, *, marker)` (598) is `uv run pytest -m <marker> …` once at the root or once per member that has tests; `acceptance_commands(…, marker,
  exclude_marker, root_extras)` (624) builds `-m "<marker> and not <exclude>"` over the changed `tests/integration/` files grouped per member; `repeat_command(command, tests)` (436)
  keeps the command's options, `-m` among them, and replaces its paths with the ids; `serial_rerun_command(command, tests)` (428) keeps only the program and the ids and **drops
  `-m`** (`[*command[: program + 1], *tests, "-q"]`). `_marker_selection` (150) shows unit-test keeps the repo's own `addopts` marker; e2e-test's `-m` replaces it. `profiles/base.py`
  has `e2e_commands` and `acceptance_commands` in the `ToolchainProfile` protocol (114, 116) and the optional hooks `RepeatsTests` (159), `SelectsAffectedTests`,
  `RecordsSelectionData`; the node profile's e2e-test and acceptance commands raise "to come" (`profiles/node_npm.py` 213, 216).
- `pipeline/wiring.py`: `e2e_scope(cwd, base, *, setting, profile, projects, marker, dev_stack, change)` (2195) is the one scope decision (dev stack script, `full` setting, a
  profile without `RepeatsTests`, no base, a scheduled change: whole; otherwise the narrowed commands per project); `E2eSession` (2264) holds `_test_env` from `verify.env`
  (2301), `_locked` (2328), `scope` (2377), `run` (2391: scope, the dev stack script, the no-test outcome, then the commands under the lock, then `_judge`), `classify` (2556: own
  by changed file or a changed `conftest.py`, otherwise untouched), `_judge` (2576: the untouched failures run once on the base in a detached worktree with
  `serial_rerun_command(ran_command, ids)` at 2614) and `_run_on_dev_stack` (2651); `post` (2709). `build_on_preexisting` (1427) and `build_on_e2e_gate` (1465) are the
  record and gate wiring; `e2e_runs_whole` is bound at 3353.
- `graph/nodes.py`: the e2e-test node (1708) asks `r.e2e_runs_whole(...)` then `r.on_e2e_gate(unit)`, runs `r.run_e2e`, and on failure reads the verdict and parks through
  `wait_for_preexisting` (1754) when every failure is pre-existing. `hold(state, note, detail, *, cause, …)` (482) records the store state and the cause; `park_for_fix`
  (1315) is `hold(PLANNED, …, cause=GATED)` plus a stored `gated_requeue` of `RESUME`. The status is posted only in `open_pr` (about 1944, `r.post_status(sha, True)` when the unit
  is e2e-test), after `push`; the graph order is `… review → e2e-test → verify base → … → push → open pr` (`after_review`, `after_e2e`).
- `pipeline/untouched_failures.py`: `PreExisting(Recorded)` (27; `Frozen`, so extra keys are refused and a new field needs a default for old lines), `ensure_fix` (76),
  `holding_fixes` (113) gates by the entry's repo only (`repo_of.get(entry.unit) == unit.repo`), `wait_on_preexisting`, `_write_change` and the proposal text.
- `pipeline/verify.py`: `verify_change` (112) takes `profile.acceptance_commands(…, marker=repo.tests.e2e_marker, exclude_marker=repo.tests.dev_stack_marker, …)` at 150 and
  runs them after the deploy; `cli/pipeline.py` `verify_ready` skips a change with `StackBusy` ("tried again next round", nothing recorded) and records every other outcome.
- `pipeline/e2e.py`: `NO_TEST_RAN` (136), `build_snapshot` (346, the `ran_no_tests` wording at 371) and `post_status` (399); `E2eResult` has `ran_no_tests`, no parked field.
- `pipeline/e2e_schedule.py`: `PERIODS`, `scheduled_name(repo, day)`, `is_scheduled(change)` (the reserved prefix, group 3), `scheduled_date(name, repo)` (a name whose tail after
  the repo is exactly a date), `write_due`, `_open_changes`, `_archived_dates`, `_write_change`. `write_due` still has no caller (group 4 of that change wires it). `wiring.py`
  routes a scheduled change to a whole-suite run (2229) and `_scheduled_verdict` records every failure as pre-existing.
- `config.py`: `TestsConfig` (579: `root_extras`, `e2e_marker`, `e2e_unit_scope`, `e2e_schedule`, `dev_stack_marker`, `replay`) is the per-repo block;
  `WorkspaceConfig` (865) has no top-level `tests` key and every model is `Frozen` with `extra="forbid"`; `RuntimeConfig` (352) is keyed by runtime name under `runtimes`;
  `_usage_limits_only_on_claude` refuses `limits` on other runtimes (change B's concern, not this one's). The settings that have a global default put it under `global_limits`
  and the override under the repo's `tests`.
- `pipeline/pause.py`: `paused.json` and its `.lock` beside it, `is_paused` (unreadable is "not paused"), `pause_until` under `file_lock`, `atomic_write_text` in
  `pipeline/file_lock.py`: the nearest "blocked" state, global and time-boxed, and the model for the state file here. `cli/pipeline.py` `cmd_status` prints the pause first.
- `cli/policy_cmd.py` `register(sub)` and `COMMAND_MODULES` in `cli/__init__.py`: a command group is a module with `register` and a tuple entry; `needs_installation` is a
  `set_defaults` key. `runtimes/policy_apply.py`: `BACKUP_SUFFIX = ".abk-backup"`, the backup copied once, the text built by pure insertion, written through a temporary file
  beside the target by `_replace`, refusals as `ApplyRefused`; it only adds to a list.
- Tests: `pyproject.toml` registers `integration`, `local_stack` and `serial`, not `dev_stack`, and `addopts` is `-m 'not integration and not local_stack'` without strict
  markers. `tests/conftest.py` lists `pytest_plugins` (`pytester`, the replay, time-limit and time-split plugins); `no_real_agent` and `no_direct_claude` return early for a
  `local_stack` test; `tests/time_limit.py` is a plugin reading `item.get_closest_marker("local_stack")` per phase; `tests/time_split.py` requires each test of the scratch modules to
  request the scratch ledger fixture (`tests/test_e2e_time_split.py` lists the two modules by name).
- The four live files: `test_acp_build_unit.py` and `test_graph_acp_unit.py` both write `runtimes: acp: command: <<redacted>>` into the scratch `abk.yaml`, set
  `ABK_RUNTIME=acp` and the agent home, and fail (not skip) with no command; `test_telemetry_stack.py` does the same through `run_tick` and reads the stores back;
  `test_init_conventions_workspace.py` is `local_stack` with no agent. A `-m` expression naming a marker that is not registered is accepted by pytest under strict markers
  (tried on a fixture file), so a base expression may name tags a repo has not registered.

## Decisions

### The tag and the check

`runtime_<name>` for each key of `runtimes` (`runtime_claude_code`, `runtime_acp`); untagged is the base and always runs. The registered list is static in the project file; a test
ties it to the runtime registry plus the protocol runtime's name, because the protocol runtime is registered only with its extra installed. The "at most one" check is a plugin beside
`tests/time_limit.py`: at collection it reads `item.iter_markers()` (so a test, class, module or parameter tag all count), takes the distinct `runtime_*` names, and for a
`local_stack` item with two or more raises a usage error naming every such item and its tags. A parametrised scenario therefore tags each parameter and no module. Strict markers
are turned on in `addopts`; the first task of that group runs the whole default suite and registers any marker it finds unregistered.

### One expression, a listing hook for the rest

The selection is one marker expression, not one command per group: `e2e_selection(marker, blocked, *, only=None)` returns the expression, the runtimes it leaves out and
the group it runs alone. Nothing blocked gives the marker unchanged, so every command is byte-identical to today's in the normal case and a repo with no tagged test pays nothing.
`only` is `base` (the marker with every known runtime's tag excluded) or a runtime (the marker and its tag); it serves a resume and a scheduled variant. The known runtimes are the
registry's, the protocol runtime's name and the keys under `runtimes`; the name `base` is reserved and refused as a runtime. The expression is a string handed to the profile's
existing `marker` parameter, so `e2e_commands` and `acceptance_commands` keep their signatures. `serial_rerun_command` is changed to keep `-m <expression>` and nothing else of
the selection, which is the base re-run the plan asked to keep the expression.

Two things need the tests an expression selects without running them: whether a blocked runtime holds a test the run would have executed (to park or not), and which runtime a
failed test belongs to (for the record). One optional profile hook lists the identifiers an expression selects in a command, optionally narrowed to given ids, and answers
unknown when the listing fails. Parking uses it for each blocked runtime (its tag as the expression, the unit's own ids under own scope, the whole marker under full scope);
attribution uses it for each runtime's tag over the failed ids. A listing that fails parks the group (we cannot say it has no test), and an unattributed failure is the unit's own,
unrecorded: a pass that checked nothing is worse than a stop, and a guess would put an ACP failure on the base group, the bug this change exists to prevent.

A profile that cannot express a selection (no hook, the node profile whose e2e-test is not built) and a repo whose e2e-test runs through its dev stack script, which takes no
expression, run whole as they do today and say which blocked runtime they could not leave out.

### The configuration, and what "the configuration wins" means

The three settings live under a top-level `tests` block (`tests.runtimes_blocked`, `tests.runtimes_allowed`, `tests.e2e_runtimes`), which `WorkspaceConfig` does not have yet,
because a runtime's availability and the runtimes a schedule covers are installation facts, not one repo's; a repo's own `tests.e2e_runtimes` replaces the top-level list for that
repo, because which runtimes have tests worth a scheduled run differs by repo (the same pattern as the settings that have a default and a repo override). Names are validated
against the registry, the protocol runtime and the configured `runtimes` keys; `base`, a repeated name and a name in both blocked and allowed are refused when the file loads.

A conflict has to be possible for the rule to be testable. The configuration has two lists: `runtimes_blocked` (blocks, no end) and `runtimes_allowed` (never blocked, whatever the
file says). The state file `<state_dir>/e2e-blocked.json` holds an entry per runtime: `reason`, `since`, `until` (optional, written only by the provider and availability sources), `source` (`command`, `provider`, `availability`) and
`by`. The blocked set is: the configuration's blocked names, plus the file's unexpired entries, minus the configuration's allowed names. So a hand-edit that lists a runtime in
`runtimes_allowed` beats a file entry written by a command or by the provider check of `a-runtimes-provider-has-usage-windows`, and one that lists it in `runtimes_blocked` blocks it
with no file entry. The file's `source` values are defined here as a closed set because that change writes `provider` and `availability`; an entry carrying a source this code does
not know is read as blocking and shown verbatim rather than refused (UNVERIFIED: that change's wording).

An expired deadline (`until` now or earlier) lifts a file entry; reading never rewrites the file, so an expired entry stays until the next `block` or `unblock`. A file that cannot
be read blocks nothing (as an unreadable pause marker pauses nothing) and `abk doctor` fails on it; an entry for an unknown runtime is ignored and warned.

### The commands, and the one place they do not update both

`block` edits the configuration first and writes the file second, so a refusal leaves nothing half done; `unblock` the same. The text edit reuses the policy command's backup suffix
and replace technique but also removes items, so it is its own function: insertion of a missing `tests` block, a missing key or an item into a block list, an in-place edit of a
one-line flow list, deletion of an item, byte-for-byte preservation of everything else, a reparse of the result that must give the expected lists or nothing is written, and
refusals (a duplicate `tests` key, an anchor or alias, a multi-line flow list, a value that is not a list, a flow-style `tests` mapping, text that does not parse, a file that cannot
be written) each with the reason and the line to add or remove by hand. The backup is the same `.abk-backup` file `abk policy apply` makes, copied once by whichever command edits
first.

`block` takes no `--until`: a hand-set block always needs `unblock`, and it always updates both places in one operation, both or neither. The state file's optional `until` is
written only by other sources (the provider window writes the window end, the availability command a cache time) and an expired one still lifts such an entry; an entry with
`source: command` never has one. `unblock` removes a
runtime from both and says plainly when it is still blocked afterwards, by a provider or availability entry its writer may recreate (`--allow` adds the runtime to `runtimes_allowed`) or by a hand-written
configuration line it could not remove.

### Where a parked unit waits: before the push, with nothing posted

The plan said the unit "posts a pending status that says which group is parked". The graph runs e2e-test before the push and the status is posted only after it, in `open_pr`
(a host rejects a status for a commit it has not seen), so at the moment a unit parks there is no commit on the host to post to. The unit therefore parks before its push and
posts nothing; what the requirement protects, that a green never stands for tests that did not run, holds because no status is posted for the parked run and because the posting
function refuses a result with a parked runtime. The wait is visible in `abk status` instead. When the parked group runs on resume, the unit posts one status for the commit,
after both runs passed, and the pull request's e2e-test snapshot carries both runs.

A parked unit is `held` planned with a new cause (`runtime_blocked`), like a gated unit, and a store field holds the parked runtimes and the commit the passing run was on. It is a
planned unit, so it holds no place against `max_units_in_progress`. A pass step beside `release_gated` (cli/pipeline.py, the round) resumes it through the same delivery once none of
its runtimes is blocked (the configuration and the clock decide, no usage read), once per block. Resume runs only the parked group's expression; if the head is no longer the
stored commit (a restack or rework moved it), the whole selection runs. A unit parked on two runtimes waits until both are usable, so it is never released into a blocked group.
A failure in the groups that ran takes precedence: the unit fails as before and does not park.

Under full scope (a `full` setting, a script, a run that could not be narrowed, a scheduled unit) a blocked runtime that holds any test of the marker parks the unit too: a green
for a whole-suite run that skipped a runtime would be a lie. A repo that sets `e2e_unit_scope: full` therefore waits while a runtime it tests is blocked, by design.

### The record and the gate per runtime

`PreExisting` gets `runtime: str = "base"`: an entry written before reads as base, and the new field has a default because the model refuses unknown keys but fills missing ones.
`TestFailure` entries of a result carry a group; `build_on_preexisting` writes it and the written fix change's proposal names it. `holding_fixes` takes the groups the run executes (the scope
decision returns them: the base, plus each runtime the selection does not leave out, or only the `only` group) and holds only for an entry whose runtime is among them. A run that
leaves a runtime out never holds for it, and a blocked runtime's tests do not run, so they cannot be recorded or fixed: nothing in the budget case reaches `ensure_fix`.

### Post-merge verification

Verification takes the same selection. Before it deploys anything it asks the listing hook, over the change's live test files, whether a blocked runtime holds a test among them. If
so it is skipped for this round like a busy stack (`StackBusy`'s path: logged, nothing recorded, nothing deployed, tried again next round) and the change is not archived. If none, it
runs with the blocked runtimes left out. A repo with no tagged test is unaffected.

### The kit's own live tests

The runtime-neutral scenarios are parametrised with `pytest.param(..., marks=...)`, one tag per parameter and none on the module. **Narrowed:** the build, graph and telemetry tests carry only
the `claude_code` parameter in this change, because the `acp` split is held and an `acp` parameter would park the unit instead of letting it merge; their `acp` parameters, the
forbidden-command test and the session-listing test are added by `acp-variants-of-the-runtime-tests`, drafted outside `openspec/changes` until the split is released.
Parameter ids are the runtime names (`claude_code`, `acp`); test functions and modules carry `acp` only where the behaviour is ACP-only.

- `test_build_unit.py` (renamed from `test_acp_build_unit.py`): the build, the pipeline-alone-pushed and progress scenarios and the two report scenarios hold on `claude_code` (and later on `acp`). The
  run-log assertion `runtime acp has no usage window` is per runtime (a Claude run has a usage window and says another thing; the first run of the Claude variant corrects the
  expected text). The forbidden-command refusal naming its layer is ACP's: its layers are the agent's own configuration and policy, which Claude's hook does not have in the same
  form. It leaves `test_build_unit.py` here and is carried, in `test_acp_forbidden_command.py` tagged `runtime_acp` and building its own unit through the shared helper, by
  `acp-variants-of-the-runtime-tests`.
- `test_graph_unit.py` (renamed from `test_graph_acp_unit.py`): the build to review, the rework on a comment and the thread's end at merge hold on `claude_code` (and later on `acp`). The check that the agent lists
  the build's session for the working directory is ACP-only (`assert_unit_session_listed` takes the agent command); it is not called from this file here, and
  `acp-variants-of-the-runtime-tests` adds it as a per-runtime step in `test_acp_session_step.py` with a helper module whose name says acp, so no ACP-specific line sits in a neutral test.
- `test_telemetry_stack.py` keeps its name: every one of its three tests builds a unit with a real agent, so the trace and metric checks are the same on both runtimes and become
  parameters (here the `claude_code` one; the `acp` one comes with `acp-variants-of-the-runtime-tests`); the dead-collector scenario is Claude-only because a build on a second
  runtime adds no coverage of the collector, with that reason in the module's table of reasons.
- `test_init_conventions_workspace.py` stays untagged (no agent).
- One helper builds the scratch installation for a runtime: `runtimes.acp.command` and `ABK_RUNTIME=acp` with the agent home for ACP; no `runtimes` entry for Claude (the account and
  home come from the per-installation account variables); it fails, not skips, naming the setting when ACP has no command, as the files do today.

The groups that rewrite these files are e2e-test: their own-scope run executes the Claude variants for real (bounded by Claude's usage windows, which already govern every unit's start)
and, while the ACP runtime is blocked, parks the ACP variants. That is this machinery's first live use; the groups come after the groups that build it for that reason, and a
unit whose Claude tick is paused by the usage guard fails naming the pause, not skipping silently (UNVERIFIED: how the child `abk tick` of a Claude variant is admitted by the
guard when the machine's window is high).

The drift test reads the live-stack modules and fails a test that requests the scratch or agent-home helper (or reads the agent command setting) without exactly one runtime tag, and a
scenario tagged `runtime_acp` with no `claude_code` sibling and no non-empty entry in the module's table of reasons.

### The scheduled variants

The change name gains a variant suffix: `scheduled-e2e-<repo>-<date>-<variant>` with `base` or a runtime name. `scheduled_date(name, repo)` is read through a new parse that returns the
date and the variant (a name with no suffix is `base`; a repo whose name begins another's is not confused because the date is matched as the first whole token after the repo and
variants are matched against the repo's resolved list). The due check and the open check run per (repo, variant); the variants of a repo are `base` plus its resolved
`e2e_runtimes`. `write_due` stays one lock-held pass, writes one change per due (repo, variant) and reports `exists:` per open one, so a blocked variant's open change never stops the
others. `is_scheduled` keeps working: the prefix is unchanged.

The scheduled unit already runs the whole marker on the default branch and records every failure as pre-existing (`_scheduled_verdict`); the variant makes the run `only=<variant>`
through the same builder and the record carry the variant's runtime. A blocked runtime's variant parks like any unit (held planned, runtime named, change open); no new mechanism.

## Differences from the plan

- **Group numbering.** The plan's six groups, each sized about 350 lines, become nineteen; its "group 7" (scheduled variants) is groups 12 and 13 here. Every cross-change reference
  to it names the group by its number in this file: the tick wiring of `tier2-runs-on-a-schedule` should wait on group 13.
- **The pending status.** Not posted: see "Where a parked unit waits". The unit parks before the push and nothing is posted for a run with a parked group.
- **No `--until`.** An earlier version wrote a block with a deadline to the state file only; the user decided against `--until` on `block` and `block` always updates both places.
- **The scheduled unit's route (group 3 of the schedule change)** is merged (`d7b35a8e`, `is_scheduled`, `_scheduled_verdict`, `passed_note`); the plan treated it as unbuilt. Group 12 here
  carries the one `Needs` on group 2 of that change that the plan gave its group 7, and group 13 follows it in the chain, so it states none (a second `Needs` beside a same-repo predecessor only
  makes `abk check` warn that the unit can have two parents); the plan's `Needs` for group 4 of that change names group 13 here.
- **Unit /4 of `tier2-runs-on-a-schedule` is no longer planned.** The plan and the instructions for this change said it was; `runs/units.json` (read only) shows it `running` (started
  2026-10-14, feedback already saved), so the one allowed edit to that change's `tasks.md` was NOT made. The wording to add to its group 4 when it is replanned is under "The one edit not made".
- **`serial_rerun_command` is the base re-run's seam**, as the plan said, but it is used by `_judge` with the command that ran (2614), so keeping `-m` there is enough; the re-run
  needs no second hook.
- **Selection is one expression, not one command per group.** The plan's wording ("a single derived marker expression") is followed; group membership for the record is found by the
  listing hook after a failure, not by running a command per group, so a repo with no tagged tests pays no extra process.
- **The telemetry file does not split in two.** The plan said what needs only the telemetry stack runs on Claude and the ACP agent part is tagged ACP. Every test of the file builds a
  unit with a real agent, so there is no part that needs no agent; the file is parametrised over both runtimes with the dead-collector scenario Claude-only.

## Old test-file names, and what names them

Searched for `test_acp_build_unit`, `test_graph_acp_unit`, `acp_build_unit`, `graph_acp_unit` (and for `test_telemetry_stack` and `test_init_conventions_workspace`, which keep their names).

agent-build-kit `origin/main` (updated by group 14 and checked by its test; the changelog's history is exempt):

- `docs/agent-runtimes.md` (about 870 and 875): the build run and its report check, and the `pytest -m local_stack` line, name `test_acp_build_unit.py`.
- `tests/pipeline/test_scratch_change_tasks.py` (12): `from tests.integration.test_acp_build_unit import TASKS` (the import must follow the rename; `TASKS` stays in the build test).
- `tests/test_e2e_time_split.py` (200): the parametrised module list `["test_acp_build_unit.py", "test_graph_acp_unit.py"]`.
- Not renamed, so unchanged: `test_telemetry_stack.py` (`docs/agent-runtimes.md` 876 and 886, `CHANGELOG.md` 1304, `tests/test_timing_guard.py` 253, `tests/timing_hazards.py` 45) and
  `test_init_conventions_workspace.py` (`docs/init.md` 142).
- No project-file task, poe task, script, workflow or shipped skill names any of the old files (`test-local-stack` is `pytest -m local_stack`).

The planning repository, every change under `openspec/changes/` outside the archive (read only; their units read from `runs/units.json`, also read only). All are changes whose units are
merged or started, so none is edited; the wording to use is recorded here.

| Change | Where | Units | Wording |
| --- | --- | --- | --- |
| `process-tests-fake-the-github-api` | proposal, tasks 3.x | merged | history: leave |
| `acp-tests-follow-the-graph-log` | proposal, tasks | merged | history: leave |
| `acceptance-agent-gets-its-own-state-store` | design, tasks 1.10 | merged | history: leave |
| `scratch-app-ignores-its-lock` | design, tasks 1.3 | merged | history: leave |
| `unit-graph`, `init-writes-changelog-conventions` | follow-ups | merged | history: leave |
| `tier2-replays-unchanged-calls` | design (the e2e-test tests' environment) | /3 failed (started) | read `test_build_unit.py`, `test_graph_unit.py` |
| `policy-check-asks-the-agents-own-matcher` | design (the e2e-test limit and the agent setting) | /6 failed (started) | read `test_build_unit.py`; its new live test `tests/integration/runtimes/test_policy_check_agrees_with_agent_live_stack.py` starts an ACP agent and must carry `runtime_acp` |
| `dry-guidance` | tasks 4.3 ("as `test_graph_acp_unit.py` does") | /4 failed (started) | read `test_graph_unit.py`; its new live test starts an agent and must be tagged |
| `abk-web-ui`, `ui-chat-editing`, `local-forge` | tasks naming "a real Claude and a real ACP agent" / "a real agent" | /11, /5, /3 failed (started) | each such scenario is one test per runtime (a test carries one tag) |
| `planning-in-the-working-copy` | task 17 | planned (not started) | its live tests start an agent: the drift test makes the builder tag them; nothing is edited here |

Research notes under `docs/research/` that name the old files are history and are left alone.

## The one edit not made

The plan and the instructions for this change named one edit outside it: a `Needs:` line on group 4 of `tier2-runs-on-a-schedule`. Group 4's unit is `running`, not planned, so it was not
made. When that unit is replanned or its group is next edited, add to group 4:

`Needs: tier2-tests-are-tagged-by-runtime group 13 — the first scheduled run is already split by runtime`

(Group 13, not 7: see "Differences from the plan". Group 13 reaches group 2 of that change through group 12, so the two changes' groups form no cycle.)

## UNVERIFIED

- That collecting the kit's four live modules (the listing hook's `--collect-only`) works without the agent command set: their module-level conditions are skip markers and the
  fixtures are lazy, but no collection was run against them.
- How the listing hook is best written for a member with its own `--directory` and the identifiers relative to it (the same relativity `repeat_command` handles); group 2's tests fix it.
- That a Claude variant's child tick is admitted by the usage guard when the machine's window is high, and what its run-log says about usage (the build test asserts the ACP line
  `runtime acp has no usage window`; the Claude expectation is found by the first real run).
- Whether Claude's runtime refuses a forbidden command in a way that names the same layers (so the forbidden-command scenario might also run on it); it is kept ACP-only until a
  Claude run shows otherwise, with a reason in the module's table.
- The wording of `a-runtimes-provider-has-usage-windows` (written in parallel) for the state file's `source` values and its release of a provider block; this change defines
  `command`, `provider`, `availability` and reads an unknown source as blocking.
- Whether `abk requeue` or the web UI shows the new cause well; the status lines of group 9 are written for `abk status` and the dry run only.
- That `has_work` already keeps ticks going for a planned unit (it does for `PLANNED` in `NEEDS_TICKS`); group 9's test pins it.
- Whether the post-merge listing before deploy needs the checkout pulled first (the check happens after the clean-branch and pull step, before deploy; group 11 confirms).

## Direction note: the test kinds are being renamed

Added while this change is in flight; it changes nothing this change specifies. The two kinds of test, today `unit-test` and `e2e-test`,
are being renamed `unit-test` and `e2e-test` so that "tier" can mean how much review a change gets (see the risk-tiered review
design in the framework repository). The change `test-kind-names-are-accepted-both-ways` adds the layer that reads both spellings,
and group 6 and the groups after it wait for it, so they are built with the new names available.

- Names this change's specs fix (a setting, a tag, a metric) are built as the specs write them. The rename carries them; do not
  rename them by hand and do not edit the spec.
- Anything this change is free to name (a helper, a fake, a test file, a local name) uses the new words.
- If a check rejects an old spelling in a directory the rename has already converted, rename that occurrence to the new spelling,
  keep the behaviour the spec describes, and say so in the commit message. A reviewer reads the new spelling as the same setting as
  the spec's old one.

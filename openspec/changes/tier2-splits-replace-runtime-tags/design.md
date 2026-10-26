## Context

`tier2-tests-are-tagged-by-runtime` hard-wires one repo's problem into the framework. This change makes the framework generic (a repo declares splits and holds them) and migrates what is
already merged. It is written against `origin/main` of agent-build-kit at `aa6b9c17` and against the text of the two groups that are running.

## What was checked, and where

Read-only against agent-build-kit `origin/main` (`aa6b9c17`, after #352) and `runs/units.json`; paths are under `src/agent_build_kit/`. The units of `tier2-tests-are-tagged-by-runtime`
on 2026-10-14 (the second column is the group; every unit that is not merged is planned with no pull request except /7 and /9, which run, with their branches at `aa6b9c17` and no commit
yet):

| Unit | Group | State | What it built or builds |
| --- | --- | --- | --- |
| /1 | 1 | merged #336 | `tests/runtime_tags.py` (plugin, one runtime tag per `local_stack` test), `tests/runtime_tag_collection.py`, the registered `runtime_claude_code`, `runtime_acp`, `dev_stack` markers and `--strict-markers` in `pyproject.toml` |
| /2 | 2 | merged #341 | `pipeline/e2e.py`: `e2e_selection(marker, blocked, *, only, configured)`, `E2eSelection`, `selection_unavailable`, `RUNTIME_TAG_PREFIX`; `profiles/base.py`: `ListsSelectedTests.selected_tests`; `profiles/python_uv.py`: `selected_tests`, `_is_serial_split`, `serial_rerun_command` keeping `-m` |
| /3 | 3, 4 | merged #346 | `config.py`: `RuntimeTestsConfig` (`runtimes_blocked`, `runtimes_allowed`, `e2e_runtimes`), `WorkspaceConfig.tests`, `TestsConfig.e2e_runtimes`, `BASE_GROUP`, `e2e_variants`, `known_runtime_names`, `_e2e_runtime_lists`; `pipeline/e2e_blocks.py`: `BLOCKED_FILE = e2e-blocked.json`, `Block`, `Blocks`, `blocked_runtimes`, `write_block`, `SOURCE_COMMAND`, `ORIGIN_CONFIGURATION`, `ORIGIN_FILE` |
| /4 | 5 | merged #349 | `config_text_edit.py`: `add_runtime`, `remove_runtime`, `TextEdit`, `ConfigTextEditError` over `runtimes/policy_apply.backup_and_replace` |
| /11 | 12 | merged #351 | `pipeline/e2e_schedule.py`: `scheduled_name(repo, day, variant)`, `scheduled_parts(name, repo, variants)`, `write_due` per variant, `_open_changes`, `_archived_dates` |
| /6 | 7 | merged #352 | `pipeline/e2e.py`: `TestFailure.group`, `UNKNOWN_GROUP`, `E2eResult.parked`, the parked wording of `build_snapshot` and `post_status`; `pipeline/wiring.py`: `E2eSession(blocked=, only=)`, `_selection`, `_lister`, `_park`, `_groups` |
| /7 | 8 | running | the park cause `runtime_blocked`, the stored parked runtimes and commit, the resume of one group, the status guard |
| /9 | 10 | running | the runtime on `PreExisting`, the filter in `holding_fixes`, the runtime line of the fix change |
| /5, /8, /10, /12, /13 to /18 | 6, 9, 11, 13 to 19 | planned | the commands, the release pass, post-merge verification, the variant unit, the kit's tests and the documents |

The merged code is exactly what the tasks of this change name. Nothing newer than #352 on `origin/main` touches these files.

## Decisions

### Where splits are declared, and what a hold is keyed by

A split is declared at the top of `abk.yaml` under `tests.e2e_splits` and a repo's own `repos.<name>.tests.e2e_splits` replaces the top-level map for that repo, the pattern the
merged `tests.e2e_runtimes` already has. Holds are keyed by the split's name alone, installation-wide, as the merged blocks were keyed by runtime name: a split name is the
installation's vocabulary for "the tests that need X", and "X is down" holds it wherever a repo declares it. A repo that must not follow a hold sets `hold: false` on its own entry
(the configuration wins), which is what `runtimes_allowed` was. `abk e2e-test hold <split>` sets `hold: true` on every entry that declares the name (top-level and repos') and writes one
state entry; `release` removes both. This keeps the state file and the text edit simple and keeps merged behaviour; a per-repo hold key (`<repo>/<split>`) is the alternative, rejected
because a down backend does not stop at one repo's boundary.

### `rest` and the old name `base`

The untagged group the merged code calls `base` becomes `rest`, a reserved split name always declared. It can be held (`rest: {hold: true}`, the only thing a `rest` entry may carry) like
any split, which leaves out the tests of no declared split. `base` as a name is dropped from the configuration and from new scheduled changes; an existing change name with no suffix or
with `-base` reads as `rest`, because it is the same group (nothing writes either yet: `write_due` has no caller until group 4 of `tier2-runs-on-a-schedule`).

### The selector, the profile hooks

The configuration accepts one selector kind, `marker`, because it is the only one built. The profile owns the translation: the profile protocol gains the selector kinds it supports and
`expression(marker, selection)` (python: the same `-m` text the merged builder gives for the same sets), the existing optional listing hook `ListsSelectedTests.selected_tests(command,
expression, run, among)` becomes `list_tests(command, selection, run, among)`, and a third hook `registered_selectors` (python: the runner's own marker listing) serves
`abk e2e-test check`. A profile without the kinds (the node profile) is reported by `selection_unavailable` as the merged code reports a profile without the listing hook, and runs whole. A
second kind (a path glob, say) is a later change: a new `SplitConfig` key and a profile that lists it.

### Exclusive membership and the check

The listing is the mechanism: list each split's tests and `rest` (the marker without every declared split) and report any identifier in two lists. The kit's `tests/runtime_tags.py`
plugin stops being what the framework relies on and stays as the kit's repo-local convenience (a failure at collection, in the kit's own suite, before `abk e2e-test check` is run). The
check runs the profile's listings only: it starts no stack and runs no test. `abk e2e-test check` is built here, with the `e2e-test` command group's module, because the check needs it and the
command group of `tier2-tests-are-tagged-by-runtime` group 6 then adds `hold`, `release` and `status` to that module.

### The held set and the state file

The file is renamed `e2e-held.json` and nothing reads `e2e-blocked.json`. The alternative (keep the name and say "blocked" for a held split) leaves two words for one thing in code, state
and documents; the cost of the rename is zero because nothing has ever written the old file: its writers are `abk e2e-test block` (group 6, not built), the provider evaluation (not built) and
the merged tests. So there is no read of the older name and no migration; the changelog and a test say the older file is ignored. `source` is `command` for a hand-set hold and `gate`
for a hold a split's gate wrote (the merged `provider` and `availability` values become `gate`); `until` is written only on `gate` entries, as the merged writer already enforces for
`command`. An unknown source still reads as held and is shown as written.

The gate itself (`gate.command`, `gate.provider`, its evaluation and its cache) is built by `a-runtimes-provider-has-usage-windows`, rewritten to put the provider table under a split's
`gate`. This change defines only what a gate needs from the framework: the `gate` source and a deadline on its entry, `remove_hold` for the gate's lift, and the rule that the
configuration beats a gate. The `gate` key on `SplitConfig` is added by that change's group 1 (this change's declaration refuses it until then).

### What the migration touches in the running units

Group 8 of `tier2-tests-are-tagged-by-runtime` (unit /7) adds the cause `runtime_blocked`, the stored parked runtimes and commit, and the resume; group 10 (unit /9) adds `runtime` to
`PreExisting` with the default `base`, the `holding_fixes` filter and the runtime line of the fix change. Both are runtime-flavoured in name only: they are strings drawn from
`known_runtime_names`. Groups 7 and 8 here rename them, `Need:` those two groups so they start after the code exists, and read the older stored names (`runtime_blocked`, the parked
runtimes field, the `runtime` key, the value `base`) so a unit parked or an entry recorded between the two merges is not lost. Both running units' text was read (groups 8 and 10 of that
change's `tasks.md`); nothing in either is read from code, because neither has a commit yet. UNVERIFIED: the names those units end up using for the stored field and the cause may differ
from the tasks' words; groups 7 and 8 start by confirming them against the merged code.

### Between the groups

Each group migrates its readers and removes what no reader is left for: the old lists go with their last readers (the two held lists in group 4, `e2e_runtimes` in group 9), so no
group leaves `main` unable to load a configuration or run a test. Between groups 2 and 4 the old lists still feed the names the session leaves out and the builder refuses a name that is not a
declared split; nothing sets the lists, so no repo meets that.

## Superseded requirements of the unarchived change

`tier2-tests-are-tagged-by-runtime` is not archived, so its delta specs are not main specs and this change does not modify them; its requirements that are superseded are replaced as
follows. Its planned groups' requirements (the commands, the status lines) are rewritten in place in its own spec files by the same series that rewrites its groups; the rest are
replaced by this change's ADDED requirements and are to be reconciled before either change is archived.

| Requirement of that change (capability) | Replaced by (this change) |
| --- | --- |
| e2e-runtime-tags: one builder makes the selection; a run that cannot express it runs whole | e2e-splits: the selection is built over the declared splits |
| e2e-runtime-tags: a test names the runtime with at most one tag (the check) | e2e-splits: a test is in at most one split (the framework mechanism); the kit's plugin stays repo-local |
| e2e-runtime-blocks: the three lists; the blocked runtimes are the configuration's and the file's | e2e-splits: a repo declares its splits; e2e-holds: the held splits |
| e2e-runtime-blocks: the text edit | e2e-holds: a split's `hold` is edited as text |
| e2e-runtime-parking: a run executes the groups that can run; a unit parks; the record | e2e-split-runs |
| e2e-runtime-variants: one change per variant | e2e-split-runs: one change per declared split and `rest` |
| tier2-failures (main spec) MODIFIED: the gate's bound by a runtime's group | e2e-split-runs: the gate holds a run only for a split it executes |

The main spec `tier2-failures` is the only main requirement involved, and its modification by `tier2-tests-are-tagged-by-runtime` is text about "a runtime group"; this change states the
replacement as its own ADDED requirement instead of modifying a requirement of an unarchived change.

## The schedule's group 4

Group 4 of `tier2-runs-on-a-schedule` already `Needs:` group 13 of `tier2-tests-are-tagged-by-runtime`, which keeps its number and meaning (its text becomes "a scheduled split's unit"),
and which now `Needs:` group 9 of this change, so the first scheduled run is split by split with no edit to group 4's `Needs:` line. Its unit has started (its branch holds unmerged
commits and the unit waits for a restack), so its text is not edited; the wording it would carry if it is replanned is: "the first scheduled run is already split by split, so a held split's tests are parked
instead of recorded as failures". The same applies to its description of what a tick writes: one change per declared split and `rest`.

## Differences from the plan

- **More than six groups.** The plan listed six migration steps of about 350 lines each; sized, they are eleven groups (the selection and the exclusivity check are separate, the text edit is
  separate, parking, the park cause and the record are three, the kit's configuration and the scan are separate from the documents).
- **`abk e2e-test check` lives here, `hold`, `release` and `status` do not.** The plan had the CLI in the generic model; the three state-changing commands are group 6 of
  `tier2-tests-are-tagged-by-runtime`, which this series rewrites, and the new `e2e-test` command group is created by this change's group 3 so the check has a home.
- **The state file is renamed.** The plan left the choice open; see "The held set and the state file".
- **The gate's own configuration is not here.** `gate.command` and `gate.provider` are built by `a-runtimes-provider-has-usage-windows`; this change declares only what holds and lifts need.
- **The gate's keys.** In the plan the ramp sat under `gate.limits`; `a-runtimes-provider-has-usage-windows` (rewritten as "a split's gate") puts the four window limits in `gate.provider.limits` and the cache settings on the gate itself, so a command gate has them too. A `rest` entry may carry `hold` and `gate`.
- **A repo-level declaration.** The plan said "the repo's `tests` block"; the merged `tests` block is installation-wide with a repo override, so splits are declared there and the override
  replaces them, see "Where splits are declared".

## UNVERIFIED

- The names groups 8 and 10 of `tier2-tests-are-tagged-by-runtime` end up using (the cause, the stored field, the `PreExisting` field); groups 7 and 8 here confirm them first.
- Whether a stored `E2eResult` or a stored unit holds the `group` key and the `runtime_blocked` cause (so the aliases are needed) or only the pipeline's memory does; the aliases are
  cheap, and the tests of 6.3 and 7.3 pin them.
- Where `abk config --show` prints the `tests` block and whether the repo override is shown with its repo; group 1 reads it.
- How the python profile lists the markers the runner registers (`pytest --markers` runs in the project's environment and may print a plugin's markers too); group 3 settles the parse.
- That `runtimes/providers.py`, whose module the scan in group 10 exempts, exists when group 10 is built (it is group 2 of `a-runtimes-provider-has-usage-windows`); the scan names the
  exemption by path and passes when the module is absent.
- Whether the edit of the planned groups' delta specs of `tier2-tests-are-tagged-by-runtime` is enough to archive both changes without a conflict; the table above lists what to reconcile.

## Direction note: the test kinds are being renamed

Added while this change is in flight; it changes nothing this change specifies. The two kinds of test, today `unit-test` and `e2e-test`,
are being renamed `unit-test` and `e2e-test` so that "tier" can mean how much review a change gets (see the risk-tiered review
design in the framework repository). The change `test-kind-names-are-accepted-both-ways` adds the layer that reads both spellings,
and group 5 and the groups after it wait for it, so they are built with the new names available.

- Names this change's specs fix (a setting, a tag, a metric) are built as the specs write them. The rename carries them; do not
  rename them by hand and do not edit the spec.
- Anything this change is free to name (a helper, a fake, a test file, a local name) uses the new words.
- If a check rejects an old spelling in a directory the rename has already converted, rename that occurrence to the new spelling,
  keep the behaviour the spec describes, and say so in the commit message. A reviewer reads the new spelling as the same setting as
  the spec's old one.

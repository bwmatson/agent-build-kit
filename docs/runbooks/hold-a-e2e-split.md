# Runbook: hold an e2e-test split (and let a gate do it for you)

Follow it only after these changes are **built and merged**; nothing in it is read by the pipeline. Tick the boxes as you go.

- `tier2-splits-replace-runtime-tags` (priority 1): `tests.e2e_splits.<name>` with a `marker` and `hold` in `abk.yaml`, the implicit split `rest`, one selection for every e2e-test command,
  `abk e2e-test check`, `<state_dir>/e2e-held.json`, parking of the tests a unit cannot run, a per-split failure gate and the scheduled run split per split.
- `tier2-tests-are-tagged-by-runtime` (priority 2, "e2e-test splits"): `abk e2e-test hold|release|status`, the release pass for parked units, post-merge verification that waits, the kit's own e2e-test tests
  renamed (`test_build_unit.py`, `test_graph_unit.py`); the build, graph and telemetry tests run on `claude_code`. The `acp` parameters of the build, graph and
  telemetry tests are in the parked draft `acp-variants-of-the-runtime-tests` (section 7).
- `a-runtimes-provider-has-usage-windows` (priority 2, "a split's gate"): `gate.provider` (a provider read through its Python SDK, an installable extra of the kit that
  brings `acp`), the Claude-style window limits (pause pct, ceiling, relief fraction, resume buffer) for a provider's billing month, `gate.command`, and the doctor and status lines.

## Why

A split is a named subset of a repo's e2e-test tests. Any reason can make one split unusable for a while: a model backend whose budget is spent, a GPU host that is down, a licence server, a stack that is
too slow. Without a hold, a unit whose tests include that split fails, the failure is recorded as pre-existing, and the unit parks behind a `fix-failing-*` change that cannot fix a backend. With a
hold, the tests of that split are **parked**: the unit passes the splits that can run, waits for the split ("waiting for e2e-test split <name>"), and resumes only that split when it is released, while
other splits keep running.

## 1. Declare the splits

- [ ] In `abk.yaml`, under `tests` (top level for every repo, or under a repo's own `tests`, which replaces the top-level map for that repo), name each split and the selector of its tests:

  ```yaml
  tests:
    e2e_splits:
      claude_code: {marker: runtime_claude_code}
      acp:         {marker: runtime_acp}
  ```

  The selector is translated by the repo's toolchain profile (`marker` for the python profile). The tests in no split are `rest`, always declared and holdable (`rest: {hold: true}`).
  The names and markers are yours; `acp` and `claude_code` are what the agent-build-kit's own tests use (section 6).
- [ ] Run `abk e2e-test check` for each repo. It lists every split and `rest` with the number of tests it holds and exits non-zero when a test is selected by two splits, a selector is not registered with the
  repo's test runner, a listing fails, or the repo's profile cannot apply a declared split. A test belongs to at most one split.

## 2. Hold and release by hand

- [ ] `abk e2e-test status`: lists every split as usable or held, with the reason, the source and the origin of each hold.
- [ ] Hold a split: `abk e2e-test hold acp --reason "model backend out of budget"`. It sets `hold: true` on the split's entry in `abk.yaml` and writes the entry in `e2e-held.json` together, or neither
  if `abk.yaml` cannot be edited as text (it then prints why and the line to add by hand). There is no deadline: a hand-set hold stays until `abk e2e-test release acp`.
- [ ] The configuration wins on a conflict: a split with `hold: false` is never held by the state file or by a gate; a split with `hold: true` is always held. Edit `abk.yaml` by hand to override.
- [ ] Release it: `abk e2e-test release acp`. It removes both places and says what still holds the split (a gate that may hold it again, a configuration line it could not remove).
- [ ] Parked units resume at e2e-test for the parked split only; look at `abk status` for any unit still waiting for a split.

## 3. Let a gate hold it

A gate lives on the split (`tests.e2e_splits.<name>.gate`), writes its hold with `source: gate`, lifts it itself, and never lifts or replaces a hold set by hand or by `hold: true`.

- [ ] A command gate, for anything the provider table does not know:

  ```yaml
  tests:
    e2e_splits:
      gpu: {marker: needs_gpu, gate: {command: [./scripts/gpu-probe.sh], timeout_seconds: 30}}
  ```

  Exit 0 means usable, any other exit means held with the first line of stdout as the reason, a command that cannot run or runs past the timeout is unknown. The documents carry a generic example script.
- [ ] A provider gate, for a metered model (the provider names are the rows of the kit's provider table):

  ```yaml
  tests:
    e2e_splits:
      acp:
        marker: runtime_acp
        gate:
          provider:
            name: <provider>
            budget_usd: 200
            limits: {usage_pause_pct: 70, usage_pause_ceiling_pct: 90, usage_relief_fraction: 0.25, usage_resume_buffer_pct: 5}
  ```

  Used percent is the billing summary's metered cost over `budget_usd` over the SDK's own `[start, end)` billing window; the hold lifts itself when usage falls under the resume line or the cycle resets.
- [ ] The installation's environment must have the provider's extra: `uv sync --extra <provider>` there, or add the provider to the extras of its dependency on the kit (for example `agent-build-kit[<provider>,telemetry]`). The tick
  runs in the installation's own environment, and the provider extra includes `acp`.
- [ ] Provider credentials: the SDK's active profile in its configuration file, or the token id and token secret environment variables (never commit them).
- [ ] `abk doctor`: the gate check says whether the extra is installed, whether the SDK can read the summary (error class and message, no secrets), the used percent, the budget, when the window resets and
  which threshold applies now.
- [ ] `on_unknown` on the gate decides what an unreadable reading means (`allow` by default; `hold` writes a hold saying the usage is unknown). An unknown reading never lifts a standing hold.

## 4. The scheduled run

- [ ] Each declared split, and `rest`, gets its own `scheduled-e2e-<repo>-<date>-<split>` change, due and open on its own. A held split's change stays open (parked) while the others run.
- [ ] A split that is newly declared is due at once while the others wait out their period.

## 5. When a hold ends

- [ ] A gate hold lifts itself when the reading allows it, or at the end of the window; check `abk e2e-test status`.
- [ ] A hold by hand ends only with `abk e2e-test release`.
- [ ] Units waiting for the split start on release. Once `a-unit-in-a-held-split-is-not-started` is built, a unit whose group declares the held split (`Split: <name>`) is not started at all while the hold lasts, so no usage is spent on it; the round that sees the release starts it. Before that change is built, such a unit starts and parks at e2e-test instead.
- [ ] When `acp` is released: move `docs/drafts/acp-variants-of-the-runtime-tests` into `openspec/changes`, re-verify its code references against origin/main, run `abk check` and `abk tags`, then replan.
- [ ] Releasing a hold does not start what was down (a redeployed model, a restarted host): it only lets the split's tests be selected again. Bring the backend up first.

## 6. Worked example: the agent-build-kit's own splits

The kit's e2e-test tests carry one tag each: `runtime_claude_code` for the tests that drive Claude Code and `runtime_acp` for those that drive an ACP agent; a test with no tag needs no agent. Those marker
names are the kit's own choice. An installation declares them for the kit's repo as the `claude_code` and `acp` splits of section 1, and then:

- [ ] While the ACP agent's model backend is spent or down, `abk e2e-test hold acp --reason "..."` (or a provider gate on `acp`) parks only the `acp` tests; the Claude tests and the untagged ones keep running, so
  most capability checks still run on Claude Code.
- [ ] The kit's build, graph and telemetry tests run on Claude only until the draft in section 7 is released. What only ACP does lives in files that say `acp`.

## 7. What stays parked while `acp` is held, and releasing it

The `acp` parameters of the build test (`test_build_unit.py`), the graph test (`test_graph_unit.py`) and the telemetry test (`test_telemetry_stack.py`), the ACP forbidden-command test (`test_acp_forbidden_command.py`) and the ACP session-listing test (`test_acp_session_step.py`), are not
part of `tier2-tests-are-tagged-by-runtime`: they would park each unit that adds them instead of letting it merge. They are drafted as the change `acp-variants-of-the-runtime-tests` in
`docs/drafts/acp-variants-of-the-runtime-tests/`, outside `openspec/changes`, so the pipeline never plans them. Its `DRAFT.md` says what it needs and what to re-verify.

The step to take when `acp` is released is in section 5.

## Rollback

`abk e2e-test release <split>` (it also clears the `hold: true` line), or remove `hold` from the split's entry by hand; delete the split's `gate` to stop a gate reading; delete a split's declaration to stop selecting it by
name (its tests fall into `rest`). Tests keep their markers, which are harmless when nothing is held.

# Runbook: what a person does as changes land

For the person running a planning repo. Each section is one thing a builder cannot do: when it applies, the steps, how to check, and how to back out. Nothing in it is read by the pipeline except where a section says so. A step that only a person can do can carry a `Manual:` line in its change (`manual-steps-gate-units`), and then `abk manual list` is the single list and the tick runs the step's check for you; steps in a change that has no such line are run by hand, and the check beside each is what to run.

## 1. Daily checks

| Question | Command |
|---|---|
| What is moving, held, failed, paused? | `abk status` |
| Why is a unit held or failed? | `abk status`, then the unit's `feedback` and `history` (`runs/units.json`), and its logs in `runs/unit-logs/` |
| Is the timer running? | `systemctl --user list-timers 'abk-*-tick.timer'`; it needs `loginctl show-user $USER` to say `Linger=yes` (`sudo loginctl enable-linger <user>`) |
| Is the configuration valid? | `abk doctor` (0 failed; warnings are public-content and branch-protection notes) |
| Usage | the `abk status` usage line per account; a reading can be up to `usage_cache_minutes` old, and units already running are not stopped by a threshold |
| Output of a failed e2e unit | the `full e2e-test output` path `abk status` prints (`runs/e2e-output/`) |
| Why was a unit started or not? | `abk explain <unit>` |

Never run `abk tick` under a `timeout`: it strands units as `running` with no process.

### A unit is held "needs a person"

It is almost always something the builder cannot do:

| Cause | Action |
|---|---|
| The change's own files (`follow-ups.md`, `spec.md`, `tasks.md`) need an edit | edit them in the planning repo, commit, then `abk requeue <unit> --rework --note "..."` |
| A live or credentialed check must run | run it, then requeue with the numbers in `--note`; or move the recording into the unit's fix round |
| A sensitive file such as `.pre-commit-config.yaml` | builders install it through `abk install-config` |
| The worktree holds uncommitted changes (the unit was held or failed mid-step) | `abk attach release <unit> --commit "<message>"` keeps the work and puts the unit back to `running`; `--discard` throws it away |
| Approving a held unit | `abk approve` only records approval; a hold ends by requeue, merge or close (release is for label holds only) |

## 2. Editing `abk.yaml` or `abk.local.yaml`

The two files are a person's to change; agents and tracks are refused them. The pipeline reads both before an agent step and again after it, and a step after which either differs **fails the unit with `ConfigChanged`**, whoever made the change, naming the file and showing the difference. The file is left as it is, and the unit's work is not lost.

- **Edit with no agent step running.** Stop the timer first (`systemctl --user stop abk-<planning repo>-tick.timer`), edit, check with `abk doctor`, then start it again. A tick already running keeps its own copy of the configuration and does not notice.
- **Recover a unit that failed with `ConfigChanged`.** Its worktree usually holds the step's uncommitted work: `abk attach release <unit> --commit "<message>"`, which puts it back to `running`. If the worktree is clean, `abk requeue <unit>`.
- **A file that does not load stops every `abk` command and every tick.** `abk doctor` or any command names the key; fix it before anything else. An account accepts its own `max_units_in_progress` and `limits`, not the workspace-wide `project_limits` keys.
- Which file holds what is in [configuration.md](../configuration.md#which-file-holds-what): `abk.yaml` reads the same on every machine, and `abk.local.yaml` holds checkout paths, accounts, usage thresholds, `project_limits`, which e2e values this machine has, and holds.

## 3. After the e2e markers and dimensions have landed

Applies to a repo whose live tests are split by what they need (a runtime, a telemetry stack) and a machine that cannot run all of it. See [configuration.md](../configuration.md#testse2e_dimensions-and-testse2e_available) and [hold-a-e2e-split.md](hold-a-e2e-split.md).

1. **Declare the dimensions** (`abk.yaml`, the repo's `tests`): one entry per dimension, one marker per value, for example `runtime: {claude_code: {marker: runtime_claude_code}, acp: {marker: runtime_acp}}` and `telemetry: {otel: {marker: telemetry_otel}, local: {marker: telemetry_local}}`. A flat `e2e_splits` map that these replace is removed in the same edit.
2. **Say what this machine has** (`abk.local.yaml`): `tests.e2e_available: {runtime: [claude_code], telemetry: [local]}`, adding a value when the machine gains it, and remove any temporary `hold` that was spending nothing while the dimensions were built.
3. **Check:** `abk e2e-test status` lists each dimension with its availability; `abk e2e-test check` is clean (no test carries two values of one dimension, no marker belongs to two); `pytest --collect-only -m "<marker of an unavailable value>"` in the repo lists nothing a run would start. A scheduled run with nothing runnable is skipped, not failed.
4. **Back out:** put the previous `tests` block back; the tests keep their markers, which are harmless when nothing is held or unavailable.

## 4. A second Claude account for a repo's builds

For spreading builds over two plans, or keeping one repo's usage apart. Applies once per account.

1. **Sign in** with its own configuration folder: `CLAUDE_CONFIG_DIR=$HOME/.claude-<label> claude auth login` (a browser step), then `claude auth status` with the same variable.
2. **Name which repo uses it** (`abk.yaml`, committed): `repos.<name>.account: <label>`. It is an intent: a person without the second account falls back to the default account.
3. **Describe the account** (`abk.local.yaml`, yours): `runtimes.claude_code.accounts.<label>` with `config_dir: /home/<you>/.claude-<label>`, that plan's `limits` and its `max_units_in_progress`.
4. **Check:** `abk doctor` (the account is logged in, or it prints the login command), then watch the first unit: `abk status` shows a usage line per account, and a rate-limit pause names the account that was refused and holds only that account.
5. Have few units of that repo running when you switch; their stored sessions restart under the new account.
6. **Back out:** remove `repos.<name>.account`; units of the repo build on the default account again.

## 5. Merged changes that need nothing from you

Some changes need no person step. Re-install the skills once after pulling a kit that changed them (`abk install-skills`), and re-run `abk install-timers` only if `abk doctor` reports the timer units out of date.

Follow it only once `orchestrator-serves-a-worker-api` (registration with repositories) and `hybrid-runner` (`abk runner`, `abk.runner.yaml`, `abk runner init` and `abk runner doctor`) are built and merged. Until then the commands below do not exist; the design is [orchestration.md, "Scoped runners"](../designs/orchestration.md#scoped-runners).

# Runbook: register a runner for some repositories

Nothing in it is read by the pipeline. Tick the boxes as you go.

For the person who adds a machine that builds units. A runner builds only the repositories it is registered for, and sees nothing of the others: not their code, plans, tokens or secrets. Which repositories a machine may build is decided on the orchestrator, never on the machine.

## 1. Decide what the machine may build
- [ ] Write down the repositories this machine is allowed to build (for example, a personal machine for the kit only, a company machine for the company repositories), as their names in `abk.yaml`.
- [ ] Confirm the machine has what those repositories' work needs: a route to the orchestrator's worker API, the model accounts it will build on, and for e2e or verify work the live stack and deploy keys.

## 2. Register it on the orchestrator
- [ ] On the orchestrator's machine: `abk runner register --repo <repo> [--repo <repo> ...]`. At least one `--repo` is required, and each must be a repository the installation configures.
- [ ] Copy what it prints to the runner's machine, by a channel you trust: the one-time registration secret and the proxy's root certificate.
- [ ] `abk runner list` shows the runner with its repositories.

## 3. Write the runner's file
- [ ] On the runner's machine: `abk runner init`. It writes `~/.config/abk/abk.runner.yaml` (the config home is `XDG_CONFIG_HOME` or `ABK_CONFIG_HOME` when set; `ABK_RUNNER_CONFIG` or `--config` names another file).
- [ ] Put the secret in its own file, `~/.config/abk/runner/secret`, with mode `0600`, and the certificate at `~/.config/abk/runner/root.crt`. Never paste the secret into the YAML.
- [ ] Fill in the file: `orchestrator.url`; each account the machine builds on, with its absolute `config_dir`; and under `repos:`, for each registered repository, its `workspace_root`, its `env` values as providers (`env-file`, `yaml`, `command`) and, for verify, its deploy settings. Add `tests.e2e_available`, `unit_test_slots`, `size` and, optionally, `kinds`.
- [ ] Leave out any repository the machine is not registered for. It would be ignored, and its secrets do not belong on this machine.

## 4. Check it
- [ ] `abk runner doctor`. It checks that the paths exist, every `config_dir` is absolute, the secret file is `0600`, the orchestrator answers with the given certificate, and the file's repositories match the registration. Fix what it names.

## 5. Start its claim passes
- [ ] `abk install-timers --runner` installs the timer that starts one claim pass at a time.
- [ ] After the first pass, `abk runner list` on the orchestrator shows the capabilities the runner advertised and when.

## Moving from `abk.local.yaml`
On the machine that ran the whole pipeline before, the keys about building (account `config_dir`s, `verify.env`, deploy settings) move from `abk.local.yaml` into `abk.runner.yaml`, under the account or repository they belong to. `abk.local.yaml` keeps the orchestrator's facts. `abk runner doctor` names any building key still left in `abk.local.yaml`.

## Change what it may build
- [ ] On the orchestrator: `abk runner update <runner> --repo <repo> [--repo <repo> ...]` replaces the list. Tokens minted afterwards carry the new list.
- [ ] On the runner: add or remove the matching `repos:` entries, and remove the secrets of a repository it no longer builds. Run `abk runner doctor`.

## Drain it
A draining runner takes no more work, and each item it is running stops after its current step, saves (its commits to the forge, its session and checkpoint to the store) and goes back on the queue for another runner allowed for its repository, which continues where it stopped. A running agent step is never cut short, so a drain takes at most one step per item. There is no deadline.
- [ ] Start the drain, from either side: `abk runner drain <runner>` on the orchestrator, or `abk runner drain` on the runner's machine.
- [ ] Watch `abk runner list` on the orchestrator until the runner shows `drained`. It lists the items still finishing their step.
- [ ] If no other runner is allowed for a repository, its handed-back items wait on the queue; `abk status` shows them. Register or resume a runner for that repository to move them.
- [ ] To take it back into use: `abk runner resume <runner>` on the orchestrator. The runner itself cannot resume.
- [ ] To shut the machine down: drain it first, then shut it down once it is `drained`. If you cannot wait, shutting it down is a crash (below).

## If it crashed
You do not need to act for its units:
- [ ] `abk runner list` shows it `unresponsive` once it has missed three heartbeat intervals, with its last-seen time.
- [ ] Its items are enqueued again for another runner allowed for the repository when their leases expire. The next worker continues from the last saved step; the step that was running when the machine died runs again. An item lost three times holds its unit; `abk status` names the unit and the runners, and `abk requeue` sends it on once you know why.
- [ ] When the machine comes back, before taking new work it checks each unit it was building: one another runner has picked up, or that has finished, it lets go of (its clone is deleted once its saved work is on the forge); one nobody has picked up yet, it takes back and continues, in the same agent session when its clone and session are intact. Run `abk runner doctor` and deal with any clone it lists as unchecked.
- [ ] If the machine is gone for good, revoke it (below).

## Retire it
- [ ] Drain it first (above) if it is still running, so its items finish.
- [ ] On the orchestrator: `abk runner revoke <runner>`. The runner's tokens are refused from then on.
- [ ] On the runner: `abk install-timers --runner --remove`, then delete `~/.config/abk/abk.runner.yaml`, the secret and the certificate, and the workspaces under each `workspace_root`.

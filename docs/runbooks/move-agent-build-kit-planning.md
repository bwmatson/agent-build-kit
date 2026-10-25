# Runbook: move a framework repo's specs, state and config into its own planning repo

Follow it only after the specs below are **built and merged**. Nothing in
it is read by the pipeline. Tick the boxes as you go. The example is the kit's own planning moving into
the kit repo, but the steps are the same for any managed repo that becomes its own planning repo
(`abk.yaml`, `openspec/`, `runs/`, graph pages) as well as a managed code repo. Below, "the moving repo" is that repo,
"the old planning repo" is where its planning lives now and "the destination" is the moving repo's own checkout.

**Why:** every workspace gets one consolidated place for the moving repo's specs, and the old planning repo keeps the specs of the repos that stay.

**Decisions to make first**
- Visibility. If the moving repo is public, its specs and stored text are scrubbed of consumer names and home paths on the way in.
- State stays inside the repo and `runs/units.json` stays tracked.
- The systemd commands always run on the default branch, pulled to the latest before every run, in a
  pipeline-owned worktree of the same repo. Your working copy is never touched. Specs you write
  reach the pipeline once they are on the default branch.

## Specs that must be merged first (all built by the old planning repo's pipeline)
- [ ] `planning-in-the-working-copy` (priority 2): the pipeline worktree and sync, verify and
  commits scoped to planning paths, `planning.publish`, the worktree write fence, `locate()` in
  unit worktrees, init for "this repo is also the planning repo", CI and pre-commit scoping, docs.
- [ ] `planning-content-follows-the-public-rule` (priority 2): scrub-check on its own root, consumer
  facts out of a public `abk.yaml`, the stored-text scrub pass.
- [ ] Every unit of those specs has merged. A unit parked on a held e2e-test split cannot be requeued until
  the change `a-unit-parked-on-a-split-can-be-requeued` (priority 0) has merged; if one is parked on a split it does not need
  (for example a test file tagged for an agent it never drives), write a note that says which tag to remove, and requeue it with
  `abk requeue --rework --note-file <note> <change>/<unit>`. Check `abk status` shows it running. A unit holding only an
  `[e2e-test] [acceptance]` group can stop with "the branch holds no tests and implementation pair for group N" while
  `builders.per_group_commits` (or `stubbed_tdd_commits`) is on: wait for `a-test-only-group-commits-no-pair` to merge and requeue it once more
  (`abk requeue <change>/<unit>`).
- [ ] `a-planning-repo-can-be-split` (priority 3): `abk planning split`, used below for the copy.
- [ ] `limits-split-into-global-and-project` is **not** required, but if it is merged first, use
  `global_limits`/`project_limits` in the new `abk.yaml` (or run `abk config --migrate` after).

## 1. Before you start
- [ ] Stop **both** sets of timers of the old planning repo if both exist: any legacy per-installation timers and the generated
  `abk-<planning repo>-{tick,track-health,track-improve,track-recommend}`. If both are enabled they run the same commands; stop the legacy set regardless of this move.
  `systemctl --user disable --now <unit>.timer`, or `abk install-timers --remove` for the generated set.
- [ ] Let the moving repo's units that are running settle, or put `agent-hold` on their pull requests.
  Note which are `running`, `in_review`, `held`, `failed`: `abk status`.
- [ ] Back up `<planning repo>/runs`, `abk.yaml`, `.env` and `openspec/` (copy the working tree,
  not `HEAD`: it may hold uncommitted entries, including changes the pipeline archived or ticked).
- [ ] Check there is no unpushed or uncommitted work in `<moving repo>` you care about.

## 2. Resolve mixed and foreign content
- [ ] List the changes that belong to the moving repo and decide for each whether it moves, stays or is finished first.
  A change that spans the moving repo and another repo is finished and archived first, or one side keeps it
  (`abk planning split --allow-mixed <side>`). A unit whose repo is missing from `abk.yaml` makes `Installation.repo()` fail.
- [ ] Decide who owns each main spec: those about the moving repo move, the rest stay in the old planning repo.
- [ ] Archived changes that belong to other repos stay. The moving repo's archive entries move with their units.

## 3. Prepare the destination
- [ ] In `<moving repo>` (clean, on the default branch, current): run `abk init . --repo .` in the in-repo mode
  (writes nothing over an existing store, adds the missing `runs/` lines to `.gitignore`, adds the planning
  orientation to `AGENTS.md`/`CLAUDE.md`, installs skills once).
- [ ] New `abk.yaml` in the moving repo: only that repo (path `.`); models, limits, tracks, runtimes copied;
  **`planning.worktree_root: <worktree root>`** pinned to the old planning repo's worktree root so the existing unit worktrees
  and resumable sessions stay valid (the default would be a new directory named after the destination).
- [ ] Installation facts (the acceptance agent command, host ports, the agent home variable name and path, a key read from
  the agent's config) go in `.env` as single values (names only here; never print or commit values), and the tracked
  `abk.yaml` names each in `verify.env` with `{from: env-file, file: .env, key: NAME}` (the loader already reads it).
  Structured, user-specific config (a second variant of a section, per-user lists, dual configs) goes in the ignored
  `abk.local.yaml` beside `abk.yaml`, merged over it at load (names only; never values). The two are independent layers and
  may both be used. If the destination is public, its `abk.yaml` lists only that repo, so no other repo's name or `relationships` prose is in it.
- [ ] Copy `.env` (names only; never print or commit values).
- [ ] `abk init --register-store`: replace `.openspec-store/store.yaml` (the old id and remote point at the old planning repo).

## 4. Copy the content (dry run first)
- [ ] `abk planning split --repo <moving repo> --to <destination> --scrub` (dry run; `--scrub` when the destination is public): read the printed
  counts of active changes, archive entries, main specs and unit records, and compare them with what you expect. Check the mixed list is empty
  after step 2.
  Compare the unit counts by origin (active, archived, no change directory, left in the source). A printed
  dropped dependency or no change directory unit is expected to differ from the source and is to be read.
- [ ] Run it for real. Check the reported uncommitted files it read were expected.
- [ ] Copy by hand what the tool does not move: `docs/research` notes, the planning `.claude` skills worth keeping,
  `flakes.jsonl`, `usage-allowances.json`, the usage ledger (history only; it may quote old paths).
- [ ] Review the scrub result: grep the destination for consumer names and home paths; `abk scrub-check` passes.
- [ ] Commit in the destination (planning commit, on a branch or the default branch per `planning.publish`).

## 5. Cut over
- [ ] `abk doctor` in the destination's pipeline worktree: no failures.
- [ ] `abk --config <pipeline worktree>/abk.yaml status`: the same units and the same worktrees as before; nothing replans
  (planned hashes contain no path, so nothing should).
  The comparison of units expects the dropped dependencies the dry run printed.
- [ ] `abk install-timers` (units `abk-<destination>-*`; it creates the pipeline worktree).
- [ ] In the old planning repo: `abk planning split --remove` (or by hand) to remove what moved; remove the moving repo's
  entry from `abk.yaml` and from any `consumes`; keep its editable path dependency on the moving repo if its own
  ticks run the kit's code from there. Re-enable its timers.
- [ ] Watch two ticks: no errors, no duplicate runs, state commits appear as configured.

## 6. After
- [ ] Decide and record: protected or unprotected default branch and `planning.publish`.
- [ ] If the moving repo's `AGENTS.md` forbids a `Co-Authored-By` trailer, agents still add one to planning commits. Relax the rule for planning commits
  or stop adding the trailer.
- [ ] Add the moving repo's checkout to your other `.code-workspace` files. Other installations' timers run the kit's code from
  the working copy, so a half-edited tree affects them.
- [ ] Update the old planning repo's docs and `CLAUDE.md` to say the moved repo has its own planning.
- [ ] Delete the backup after a week of clean ticks.

## Rollback
Re-enable the old timers, restore `abk.yaml` and `runs/` from the backup, remove the destination's timers
(`abk install-timers --remove` there). Units and branches are unchanged by the move, so no unit state is lost.

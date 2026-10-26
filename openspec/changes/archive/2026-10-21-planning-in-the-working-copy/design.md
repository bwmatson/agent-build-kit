# Design

## What was checked, and where

Read-only against agent-build-kit `origin/main` (`7c42abc5`, fetched first); paths are under `src/agent_build_kit/`. The line numbers of the plan this
change comes from were re-read; where they moved, the function name is the reference.

- `cli/pipeline.py` `cmd_tick` (942): `if is_repo(inst.root) and not restore_default_branch(inst.root, default_branch_of(inst.root), log): return 1` at 949,
  before `has_work`. `pipeline/planning_repo.py`: `restore_default_branch` runs `git checkout <branch>` and says FATAL when it fails; `default_branch_of`
  reads `refs/remotes/origin/HEAD`, else `main`; `is_repo` is `git rev-parse --git-dir`.
- `tracks/runner.py`: `pull` (242) is `git checkout <branch>` then `git pull --ff-only origin <branch>`; `pull_planning` (251) honours
  `planning.self_pull` and is fatal on failure; `run_track` (789) calls it first, then `pull` for each project's own checkout. `record_planning` (413) takes the
  default branch and its head; `restore_default_branch` (424) wraps the planning one; `settle_planning` (430) restores, requires the recorded head to
  still be an ancestor of the branch (else `STOPPED`), then `commit_bookkeeping` (501): `git add -A -- <state_dir>/**/*.md + changes`, a commit limited to
  those paths, `git push origin <branch>`, on rejection `git pull --rebase --autostash origin <branch>` and one more push. `AgentRequest` carries
  `planning_repo`, `planning_state_dir`, `planning_change_dir` (about 598-610).
- `pipeline/verify.py` `verify_change`: for each repo with work it calls `_clean_default_branch(checkouts[name], ...)` (162) and then `git pull --ff-only -q`
  in the same checkout (164). `_clean_default_branch` (217) requires the current branch to equal `repo.default_branch` (a detached HEAD is
  "not on main"), then `git status --porcelain --untracked-files=no -- . :(exclude)<live_written>...` must be empty. `checkouts` is
  `Installation.checkouts`: each repo's `path` with `expanduser` and nothing else, so a repo that is the planning repo would be checked in whatever
  path `abk.yaml` names, which for a person's working copy is the very checkout this change must not touch.
- `pipeline/attach.py` `commit_planning` (157): `build_commit(fix=..., gate=planning_gate(...))(message, cwd=inst.root)`; `pipeline/wiring.py`
  `build_commit` (665) runs `git add -A` (714) after `restore_unchanged_locks`, then `unstage_untracked_locks` and `unstage_artifacts`. It is the one commit
  function for unit commits too, where `add -A` is right. `commit_planning` does not push. `serve/chat.py` (about 339-344) counts
  `changed_paths(self.installation.root)` as the planning checkout's changes for a free session.
- `hooks/policy.py` `_check_file_write` (105): the specs are read-only (`specs`), the planning repo is fenced when `_checkout_of(path) == planning_repo` (133-150) and
  only for runs that were given `planning_repo` (tracks); a unit's build run gets `ToolPolicy(specs_dir=..., branch_prefix=...)` only
  (`wiring.py` about 398) and may write anything under its own worktree. In a worktree of the planning repo, `openspec/`, `abk.yaml` and `runs/` are
  therefore writable. Agents get `ABK_CONFIG` injected (`wiring.py` about 362).
- `config.py` `locate` (906): `--config`, then `ABK_CONFIG`, then the nearest `abk.yaml` walking up from the working directory; nothing asks whether the
  directory is a unit worktree. `PlanningConfig` (109): `state_dir`, `specs_dir`, `graph_page`, `usage_page`, `worktree_root`, `self_pull`.
- `installation.py`: `worktree_root` defaults to `<data>/<root.name>/worktrees` and must not be inside the root (38-50); `state_dir`, `specs_dir`,
  `changes_dir`, `graph_page`, `usage_page` are relative to the root; `env_file` is `root/.env`; `checkouts` is as above.
- `timers.py`: `slug(root)` is the root directory's name; `unit_names`, `render`, `install`, `remove`, `installed_units`, `owner_of` all key on that name
  and on each service's `WorkingDirectory`, which `install` compares with the root it is run for (a unit pointing at a live directory that is not this
  root is `taken`). The templates `templates/systemd/abk-tick.service` and the three `abk-track-*.service` set `WorkingDirectory={planning_dir}` and
  `ExecStart=/usr/bin/env uv run abk tick` or `abk track <phase>`.
- `init/scaffold.py` `write_planning_repo` (589): `git init` only if there is no `.git`; `openspec init` only if `openspec/` is missing; every file through
  `_write(..., overwrite=False)`, so an existing `runs/units.json` is **already** never overwritten (the plan listed this as a gap; it is not) but an
  existing `.gitignore` is skipped whole and an existing `CLAUDE.md` likewise; `skills.install(planning/.claude/skills)`.
  `cli/init.py`: `_tree_clean` and `_commit` (`git add -A`, 179-196) and `clean_before` (703); `changes_dir_under(planning, "openspec")` (756);
  `cmd_install_skills` (819) targets the root and every checkout. `pipeline/stack_runner.py` `CHANGE_DIR = "{planning_repo}/openspec/changes/{change}"` (66).
- `cli/doctor.py`: `_merge_guards` (275) asks `forge.merge_guard` per repo's default branch and reports an info line for an unguarded one;
  `live_written` is checked at 729; `_skills` (1041) iterates `{"planning": inst.root, **inst.checkouts}`.
- `pipeline/archive.py` `archive_ready_changes` runs `openspec archive` and clears scratch; **nothing in the tick commits** (the documented
  "The tick commits nothing"); the archive's moves, ticked tasks, the store and the graph pages stay uncommitted until a person or a chat's planning
  commit commits them.
- The repo's own gates: `.pre-commit-<redacted>` has `check-added-large-files` excluding only `uv.lock`, trailing-whitespace, end-of-file-fixer,
  `yamllint --strict`, ruff and pyrefly; `.github/workflows/ci.yml` runs on `pull_request` and `push` to the default branch with three jobs
  (`pre-commit`, `test`, `integration`) and no path filter. The repo's `.gitignore` has `.env`, `.last-runs/`, `.claude/`, `.venv/`... and none of the
  state-directory lines the template `gitignore` carries (locks, `locks/`, `unit-logs/`, the ledger, decisions, calls, `*.pre-redact`).
- Verified by trying it in a scratch repository (git, this host): `git worktree add --detach <path> origin/main` succeeds while `main` is checked out in
  another worktree; `git checkout main` in the second worktree is refused (`'main' is already checked out at ...`); `git merge --ff-only origin/main`
  in a detached worktree with a dirty tracked file that the new commits do not touch keeps the file and fast-forwards; when the new commits do touch
  it, git aborts with `Please commit your changes or stash them` and leaves the worktree as it was.

### Differences from the plan this change comes from

- The plan's "does not write `{"units": []}` over an existing store" is already true (`_write` with `overwrite=False`). It stays as a regression test.
- The plan's "`planning.publish: branch` ... archive likewise" cannot apply to the archive: the tick commits nothing, so there is no archive commit to
  publish. `publish` governs what abk itself commits and pushes: the tracks' bookkeeping and any change a track proposes.
- Verify's checkout is the repo's path, not the planning root, and its `git pull --ff-only` fails on a detached HEAD. The plan only listed the dirty
  check; the checkout mapping and the sync in place of the pull are added (group 6).
- The unit slug and the default worktree root come from the root directory's name. With the pipeline worktree as root that name would be the same for
  every installation (`planning`), so two installations would collide on unit names and share a worktree root. Group 4 derives both from the
  repository, which the plan did not list.
- The `.env` is gitignored and not in a new worktree. The plan did not list it (group 4).
- `abk tick`, `abk track`, `abk verify` and `abk archive` refuse in a working copy when a pipeline worktree is live (group 5). The plan asked only that
  status and doctor say which is live; the refusal stops two ticks writing two stores and is the one addition beyond it.
- The plan's "a planning root that is not a worktree of a repo behaves as now" is made precise below: the new behaviour starts only when a repo listed in
  `abk.yaml` is the planning root's own repository.

## The three roles of a planning root

`planning_mode(inst)` returns one of three values (a `StrEnum`, `PlanningMode`):

- `SEPARATE`: no repo in `abk.yaml` shares the root's git repository (the same `git rev-parse --git-common-dir`), or the root is not a git repository.
  Everything behaves as today: checkout of the default branch, `pull --ff-only`, `git add -A -- <paths>` where it did, `slug(root)`.
- `WORKING_COPY`: a repo in `abk.yaml` shares the root's repository and the root is not the pipeline worktree. This is where a person works. The pipeline
  never changes its branch, files or index: tick and track do no branch check and no pull there (when they are run at all, see group 5).
- `PIPELINE_WORKTREE`: the root is the path recorded in the repository's pipeline marker.

The marker is one small file inside the repository's common git directory (`<common-dir>/abk-pipeline-worktree`) holding the absolute path of the
pipeline worktree. It is written by `abk install-timers`, read by every command, and removed by `abk install-timers --remove`. It is not in the
working tree, so nothing to commit or ignore, and it is shared by every worktree of the repository, which is how a working copy learns which
installation is live. A marker whose path is gone is reported by `abk doctor` and is not a live installation.

## The sync routine

One function, `sync_planning(inst, say) -> SyncResult`, in a new module beside `planning_repo.py`; `restore_default_branch` and `pull_planning` and its
`pull` call for the planning root are removed. `SyncResult` has an outcome (`SYNCED`, `CURRENT`, `AHEAD`, `STOPPED`, `SKIPPED`) and the one reason line.

1. `SEPARATE` and `WORKING_COPY`: `SKIPPED`, except that `SEPARATE` keeps today's behaviour exactly (that code path is kept, moved, and tested as it was).
2. `PIPELINE_WORKTREE` with `planning.self_pull: false`: `SKIPPED`, logged as today (`planning.self_pull is off`).
3. The tip is `origin/<default>` after `git fetch origin <default>` when the repository has an `origin`, else the local default branch (a repository with
   no remote, as in a scratch installation). The default branch is `default_branch_of` (origin's HEAD, else `main`) unless the in-repo repo's
   `default_branch` says otherwise (the repo entry wins, as verify's does).
4. Refuse before touching anything: an unfinished merge, rebase, cherry-pick or revert (`.git` state files of the worktree); HEAD on a branch (a stray branch
   from an agent; its name is in the reason, and it is kept).
5. HEAD equals the tip: `CURRENT`. HEAD is an ancestor of the tip: `git merge --ff-only <tip>`; this keeps tracked files the new commits do not touch and aborts
   leaving everything as it was when they do (VERIFIED above): the abort is `STOPPED` with git's own message as the reason. The tip is an ancestor
   of HEAD (the worktree holds commits not yet published, such as bookkeeping whose push was refused): `AHEAD`, logged, and the run goes on. Neither is an
   ancestor of the other: `STOPPED`, "diverged: <n> commits of its own, <m> new".
6. Untracked files in the way of the merge (an `openspec archive` output the new commits also add, a published run log, see publish) make git refuse
   the merge, which is the same abort. The `branch` publish mode removes what it published before the merge in the one case it can prove (below).

`STOPPED` makes `cmd_tick` return 1 and `run_track` return 1, each after one log line `planning sync stopped: <reason>`; nothing else of that run
happens. Nothing is stashed, reset or deleted by the routine in any outcome.

**What runs.** The service's `uv run abk tick` resolves the environment of the pipeline worktree before the tick reaches the sync, so the code of one
run is the code of the previous sync. That is also true of the separate installation that follows its own source tree, and the kit's units change that
code only when they land. UNVERIFIED: whether to sync before `uv` resolves (an `ExecStartPre` that calls the same routine) so the code is current as
well; the first version does not, and the acceptance group records which code ran.

## After a phase

`record_planning` still takes the default branch and its head before a phase, now the worktree's HEAD for `PIPELINE_WORKTREE`. `settle_planning`:

- `PIPELINE_WORKTREE`: the recorded head must be an ancestor of HEAD (else `STOPPED`, as today with "the default branch was rewritten"). If the agent left HEAD on a
  branch, the branch is kept and named, HEAD is put back detached at the recorded head, and the run goes on. Then `commit_bookkeeping`.
- `SEPARATE`: unchanged, including the checkout of the default branch.
- `WORKING_COPY`: the phase did not run there; nothing.

`commit_bookkeeping` for `PIPELINE_WORKTREE` commits on the detached HEAD and publishes by `planning.publish` (below): `direct` pushes
`HEAD:refs/heads/<default>`; a rejection fetches and rebases HEAD onto `origin/<default>` once (`git rebase --autostash`, which works on a detached
HEAD; UNVERIFIED on this git, tested in group 2) and pushes again; a second rejection is reported with the commit kept.

## Where the worktree is, and what is named from where

- The pipeline worktree is `<data>/<repo name>/planning`, `<data>` being the directory the unit worktrees' default already uses (under the user's
  `.local/share`) and `<repo name>` the directory name of the repository's **main** working tree (the parent of the common git directory; UNVERIFIED for a
  bare repository or a common directory that is not named `.git`, where the name falls back to the root's directory name and doctor says so).
  It is outside the repository, never inside the worktree root of units, and created `git worktree add --detach <path> <tip>` after a fetch.
- `slug(root)` and `Installation.worktree_root`'s default use `<repo name>` for a root that is the pipeline worktree, so units are named
  `abk-<repo name>-...` and unit worktrees sit under `<data>/<repo name>/worktrees` exactly as they would for a separate planning repo of that name.
  An explicit `planning.worktree_root` still wins. The kit's existing unit worktrees stay where they are only if `planning.worktree_root` pins them, as
  the plan's runbook does; the default is not changed for any installation that is not in-repo.
- `Installation.env_file` for a pipeline worktree is the main working tree's `.env` when the worktree has none of its own; it is read, never written or
  copied. UNVERIFIED: every reader of the `.env` (`settings.py` and the verify env providers) goes through `env_file`; the group lists the ones found.
- A relative `repos.<name>.path` is relative to the planning root. That makes `path: .` the pipeline worktree when it is the root, which is the checkout
  verify, e2e-test base runs and deploy rules must use for the in-repo repo. An absolute path that names a worktree of the same repository is mapped to
  the root when the root is the pipeline worktree (so an `abk.yaml` written in a working copy with its absolute path still works there). Other repos'
  paths are unchanged. UNVERIFIED: how many places read `repo.path` directly and not `Installation.checkouts` (24 uses of `checkouts[...]` and 37 of
  `inst.checkouts` were counted; group 4 lists the ones that read `repo.path`).
- `abk install-timers` is idempotent. Run from a working copy it creates the worktree if there is none, fetches and moves it to the tip if it
  is clean, and renders the units with `WorkingDirectory` the pipeline worktree. Run from the pipeline worktree it renders the same. A marker or a path
  that exists and is not a worktree of this repository is refused with the path named. `--remove` removes the units and the marker; the worktree is
  left in place (it may hold pipeline state) and its path is printed with the command that removes it.

## The paths

`Installation.planning_paths` is one function returning `(specs_dir, state_dir, graph_page, usage_page, abk.yaml)` as paths relative to the root, used by
verify, planning commits and the unit-worktree fence. `abk.yaml` is a planning path for the commit and the fence but not for verify's exemption: nobody
changes it on the pipeline's behalf, so a dirty one in the pipeline worktree is worth refusing on. `.env.example`, `docs/` and the rest are the repo's
code, not planning paths.

- **Verify.** For a repo whose checkout is the planning root and a root in `PIPELINE_WORKTREE` mode: the checkout is the root; HEAD detached at the default branch's
  tip (or on the default branch at it) passes the branch test; the dirty check excludes `specs_dir`, `state_dir`, the two pages (as it already excludes
  `live_written`), and what remains must be empty; `git pull --ff-only` is replaced by `sync_planning`. Any other repo is as today. A
  dirty tree outside the planning paths still refuses, naming the files.
- **Planning commit.** `build_commit` gains an optional `only` pathspec list. `commit_planning` passes `planning_paths` in an in-repo installation and
  nothing otherwise (so `add -A` as today for a separate planning repo, which holds nothing else). With `only` the commit is `git add -A -- <only>` and
  the staged check and the commit are limited to the same paths; the gate and the unlocked-lock cleanup run as before. Chat's count of "planning
  changes" and the attach lease use the same list.
- **Fence.** `ToolPolicy` gains `planning_paths: tuple[str, ...]`, empty by default, set for a unit whose repo is the in-repo repo. `_check_file_write`
  denies a path under the unit's own worktree whose path relative to it starts with one of them, with the existing `BLOCKED:` message, after the specs
  check and before the "inside the worktree" allowance. Only the top-level `abk.yaml` is denied, not one nested in a fixture. UNVERIFIED: shell commands
  that write the same files are not seen by the file-write hook (they are by the command policy only where a command names a path); the fence is the
  file tools', as the specs' read-only rule is.
- **`locate()`.** After finding a candidate `abk.yaml` by walking up, and only when neither `--config` nor `ABK_CONFIG` was given, `locate` checks whether the
  directory is a linked worktree whose checked-out branch matches the unit branch pattern of the file it found (`git.branch_prefix`, default `spec/`,
  then `<change>/<n>`). If so the file is not the installation: `locate` answers with the pipeline worktree's `abk.yaml` from the marker, or raises
  `ConfigError` naming the unit worktree and saying to pass `--config` or set `ABK_CONFIG`. UNVERIFIED: a unit worktree on a detached HEAD (a restack in
  progress) has no branch to match. No guess is made: a detached linked worktree is not recognised and `locate` behaves as today, which the
  scenario documents.

## Publish

`planning.publish` is `direct` (default) or `branch`, a `StrEnum`, read in one place. `direct` is the above. `branch`: the commit is made, the phase's
files are pushed to `planning/<run id>-<project>-<phase>` (`git push origin HEAD:refs/heads/<branch>`), a pull request to the default branch is
opened through the repo's forge by the function the unit pull requests use (UNVERIFIED which of `forges/operations.py` opens a pull request with
a given head, base and title and whether it needs a unit; the group adapts it or adds one), and the worktree's HEAD is put back at the recorded head so
the next sync is a fast-forward. The published files stay in the worktree untracked or modified. When the pull request lands, the sync's merge finds them in
the way: before a merge the routine removes an untracked file or reverts a modified one only when its content is byte-for-byte what the incoming
commits hold at that path (it was published and has landed), and otherwise stops. UNVERIFIED: whether run logs the tracks read in between would be
missing for a phase if they were moved instead; the choice is to leave them, as the scenario says.

The doctor conflict: `planning.publish: direct` with an in-repo installation whose default branch the forge reports protected (`merge_guard` returns
nothing for it today in the "guarded" case) is a failed check naming `planning.publish: branch`. A forge that cannot say is an info line, as now.

## Init

In-repo mode is recognised, not asked for: `abk init . --repo .` (or any `--repo` path in the same repository as the planning directory). It
differs from init over a separate directory in these ways only; a separate planning directory is untouched.

- The repo's path in the drafted `abk.yaml` is `.`.
- `.gitignore`: a marker-bracketed block (`# abk:planning v1` ... `# /abk:planning`) of the template's missing state-directory lines is appended once and
  refreshed in place when the template moves; lines already present in the file anywhere are not repeated; nothing else in the file is touched.
- Orientation: a marker-bracketed block (`<!-- abk:planning v1 -->`) is added to the repo's `AGENTS.md` when it exists, else `CLAUDE.md`, else
  `AGENTS.md` is created (the rule `_block_action` already uses for the changelog block); the file's own text is left byte for byte.
- No commit, whatever the tree. The files written are listed and left for the person, because the edits land in files they own. (`_tree_clean` and
  `_commit` stay for a separate planning directory.)
- Skills installed once: the root and the repo's checkout are the same path, so `install-skills` and `doctor`'s `_skills` list each distinct path once.
  The kit ignores `.claude/`; the installed copies are not tracked there, which is as designed.
- `doctor`: a repo whose path is the root is valid and not reported as a duplicate; the ignored-lines check, the marker, and the pipeline worktree are checked.
- `stack_runner.CHANGE_DIR` and `cli/init.py`'s change lookup use `planning.specs_dir`, not `openspec`.

## Gates

`.pre-commit-<redacted>` gets a top-level `exclude` of the state directory (`^runs/`), which stops the large-file check and the whitespace and
end-of-file fixers on model-written logs and the unit store, while `yamllint --strict` still checks `abk.yaml` (outside `runs/`). `ci.yml` gets a first
job `scope` that decides from the changed paths whether anything outside the planning paths (`openspec/`, `runs/`, `docs/unit_graph.md`,
`docs/unit_cost.md`) changed; `test` and `integration` run when it did and are skipped otherwise, and the `pre-commit` job always runs. A skipped job counts
as passing for a required check, which a workflow-level `paths-ignore` would not (the check would stay pending); that is why a job, not a filter.
UNVERIFIED: the exact changed-paths mechanism that works for both `pull_request` and `push` events (a `git diff` against the event's base) and what
`abk.yaml` alone should trigger (decision: the pre-commit job only, since yamllint is the check on it).

## Order

Groups 1 to 17 are independent in code: each builds on the current default branch, with the exceptions that its own tests need. They are written to
land in order; a later group that uses the earlier one's function builds on the default branch after it lands, which the planner's own ordering gives
for groups of one change. The acceptance group is last.

## UNVERIFIED, collected

1. How `uv run abk tick` interacts with a sync that moves the tree that run is already using (code one sync behind). Decision above; to be measured.
2. `git rebase --autostash` on a detached HEAD for the rejected-push retry; `git merge --ff-only` is verified, the rebase is not.
3. The repository name for a bare repository or a common directory that is not `.git`.
4. Every reader of `.env` and of `repo.path` (not through `checkouts`).
5. Which forge operation opens a pull request for a non-unit branch (publish `branch`).
6. That removing a published, landed file before the merge is enough, and that `abk status` run from the pipeline worktree is what a person wants printed
   from a working copy: it prints the live installation's path and the exact `--config` command, and nothing of the other store.
7. A unit worktree on a detached HEAD is not recognised by `locate` (stated, not solved).
8. The shape of the job that scopes CI for both events.
9. How `abk install-timers` creates the worktree when the repository's default branch has never been fetched (a fresh clone has it; a repository with no remote
   uses the local branch).
10. Shell writes to the planning paths from a unit's agent are not caught by the file-write fence.

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

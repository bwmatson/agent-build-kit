# Tasks

Acceptance: none — the work is a repository rule and its check, glob matching and ownership in real git worktrees with the existing environment fakes, and init's draft over fixture directories; tier 1 tests prove it.

Priority: 3

## 1. [agent-build-kit] [tier1] Framework code names no ecosystem

Priority: 2

Done when the repository states that framework code is language- and tool-independent and a test fails when
source outside the profiles and init names a package manager or lock file that is not on a list that only shrinks.

- [x] 1.1 Test: a fixture tree with a listed package manager in a source file outside `profiles/` and `init/`
      fails the check naming the file and line; the same text inside `profiles/` or `init/` passes; a file on the
      allowlist with no names left fails as stale; an entry on the own-tooling list with no names left fails as
      stale; a name inside a string or a comment is found.
- [x] 1.2 Test: against the real source, the check passes with the allowlist holding `cli/doctor.py` and
      `tracks/runner.py` and the own-tooling list holding `openspec.py`, `serve/server.py`, `settings.py`,
      `config.py` and `timers.py`, each with its reason.
- [x] 1.3 Add the check in a helper beside the existing guards in the tests folder, with the token list in one
      place, and reword the two docstrings in `pipeline/wiring.py` and the comment in `runtimes/acp.py` so they
      name no package manager.
- [x] 1.4 Add the section "Framework code is language- and tool-independent" to `AGENTS.md`, after "This repo
      never names an installation": the framework does not branch on a language, package manager, lock file
      name, test runner or version-control host; that knowledge lives only in toolchain profiles and the init
      detectors they provide, in the forge layer, or in `abk.yaml`; new behaviour is specified as configured argv
      lists, path patterns and hooks, with a test that uses a second ecosystem's shape beside the first; spec
      text names a package manager or lock file only as an example, never as the rule. Point the existing
      "Toolchain facts come from the profile" line at it and mention the check under the section.
- [x] 1.5 Correct the `limits.generated_files` example in `docs/configuration.md` so it no longer suggests lock
      file names are listed there, and add a changelog entry.

## 2. [agent-build-kit] [tier1] Inputs are patterns and artifacts are the pipeline's

Needs: environment-sync-leaves-no-leftovers group 1 merged — it introduces the lock paths the worktree check and the commit step take, which artifacts extend

Done when an environment can name its manifests and locks by pattern, and the directories its sync produces
neither hold a unit nor reach a commit.

- [x] 2.1 Test: input patterns with `**` match nested files; a literal path hashes as it did; a pattern matching
      nothing is recorded as missing and `abk doctor` reports it; an absolute pattern or one with `..` fails
      loading naming the field. Use a node-shaped fixture (nested manifests and one lock at the root) beside the
      Python-shaped one.
- [x] 2.2 Test: a manifest inside a path matched by `environment.artifacts` is not matched by an input pattern,
      and filling an artifact directory leaves the hash unchanged.
- [x] 2.3 Test: the comparison against the base finds a unit that added or changed a file matched by a pattern
      and not one that touched none.
- [x] 2.4 Test: a sync that creates an artifact directory that the repository does not ignore does not hold the
      next step; another uncommitted file still holds with the cause `dirty_worktree` naming only that file;
      artifacts are not committed even when the unit changed a dependency input; they are not discarded by a
      move of the branch.
- [x] 2.5 Test: a tracked file under an artifact pattern is ordinary work and `abk doctor` warns about the
      pattern; a repository with no artifacts behaves as before.
- [x] 2.6 Add the pattern matcher used by the hash, the base comparison, the lock ownership and the artifact
      ownership; add `artifacts` to the environment configuration with its validation; pass the artifact
      patterns to the worktree check and the commit step; derive the generated-file patterns from the final
      component of a lock pattern.
- [x] 2.7 Update `docs/configuration.md` and the `abk-config` skill for patterns and `artifacts`, update the
      pipeline description of the environment in `docs/architecture.md`, and add a changelog entry.

## 3. [agent-build-kit] [tier1] The environment is drafted through the toolchain profile

Needs: fix-flaky-tests-runtimes-test-acp-outcome-py-test-an-agent-th-a5668955 group 1 merged — flaky test tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed

Priority: 2

Done when `abk init` asks the profiles for the environment, the Python result is unchanged for a repository
without path sources, a repository with path sources gets a drift-checked draft that lists nothing outside it,
and a node repository gets a proposal.

- [x] 3.1 Test: init over a Python repository with a manifest and a lock file and no path source writes the
      section it wrote before; pin it against the committed expected output.
- [x] 3.2 Test: a node fixture with `package.json` and each of three lock files gets that manager's sync and
      check, the manifest and lock as inputs and the dependency directory as an artifact; a declared manager in
      `package.json` wins over the lock file; a workspaces field becomes manifest patterns.
- [x] 3.3 Test: a mixed repository asks the profile detection chose first; a profile without the hook counts as
      returning None; nothing recognised writes empty commands; a profile registered in the test is asked
      without a change to init.
- [x] 3.4 Add the optional hook to the profile protocol, move the Python detection into its profile unchanged,
      add the node profile's detection and the registry walk, and reduce `init/environment.py` to the walk, the
      unrecognised draft and the lock names. The exact sync and check argv lists per package manager are
      UNVERIFIED in the design: confirm them against each manager's documentation before writing them.
- [x] 3.5 Update `docs/toolchain-profiles.md` and `docs/init.md`, and add a changelog entry.
- [x] 3.6 Test: a repository whose manifest has a path source drafts no input that leaves the repository, the
      inputs hold only its own manifest and lock, and the draft loads through `EnvironmentConfig` with no
      deprecation warning; its `check` differs from the plain import check and contains the lock-freshness and
      environment-freshness commands before the import check; a node-shaped fake profile's draft is unchanged;
      the draft carries the explanatory comment.
- [x] 3.7 In the Python profile's draft, when the manifest has path sources, set `check` to one argv joined by a
      shell (`sh -c "<lock-freshness> && <environment-freshness> && <import check>"`; the config is argv lists, so
      a wrapper is allowed, and the tick already does check failed, sync, check again, so the first failing
      command is the signal) and keep only the repository's own manifest and lock in the inputs; the draft
      explains why in a comment. The pipeline's own environment gets the import check last; another
      environment's draft ends with the plain check. Init writes no path outside the repository, silently or
      otherwise.
- [x] 3.8 Extend the deprecation message in `config.py`'s `EnvironmentInputs` validator (merged in group 2, so
      added to and not rewritten) to name the fix: use `check` to detect drift. Update its test and
      `docs/init.md`, `docs/configuration.md`.

## From `planning-in-the-working-copy/1`

- tests/pipeline/test_planning_sync.py:224 — The new trunk test builds its own clone and repeats `publish_elsewhere`'s clone, user config, commit and push steps (tests/planning_worktree_support.py:46) instead of giving that helper a branch parameter.

## From `planning-in-the-working-copy/2`

- `settle_planning` and `commit_bookkeeping` each read `planning_mode` again for every phase. Carrying the mode on `PlanningHead`, or passing it in, would save a few git calls per phase. The builder left this out of the unit because `commit_bookkeeping` is also called without a recorded head, so changing it would change that function's signature and its callers.

## From `planning-in-the-working-copy/11`

- `is_repo` (pipeline/planning_repo.py:18) and `scratch.py:73` still run their own `rev-parse --git-dir` queries. They answer different questions: one asks whether a path is a repository at all, the other wants a relative path. So they are not copies of `git_dir`, but `is_repo` could be written as `git_dir(root) is not None` if someone wants one fewer argv.

## From `planning-in-the-working-copy/3`

- src/agent_build_kit/timers.py:528 — Task 3.4 asks for the worktree to be created, reused and removed through an injectable git runner. The new helpers (`_worktree_of_this_repository`, `_make_worktree`, `_bring_to_tip`) call `pipeline.shell.git` directly, so only the systemctl runner can be injected.
- src/agent_build_kit/timers.py:577 — `assert common is not None` guards production control flow.

## From `planning-in-the-working-copy/12`

- `abk init`'s propose step still tells the propose agent to write under `openspec/changes/`, and its dry-run line and its `wrote` line also say `openspec`, even when `planning.specs_dir` names another directory. A rerun would then propose the same change again. To fix it, pass the specs directory through `propose` into its prompts and messages. This was raised as optional in round 1 and left for its own change.

## From `planning-in-the-working-copy/4`

- src/agent_build_kit/forges/local.py:110 — The local forge's repo identity is now built from the mapped checkout. For a repo that is the planning repo, a process started in the working copy and one started in the pipeline worktree work out different identities: the hash differs, and the name is the repository's in one and `planning` in the other.

## From `planning-in-the-working-copy/13`

- src/agent_build_kit/init/scaffold.py:148 — `draft_config` checks the holding repo against `detection.path.expanduser().resolve()`, but builds the relative path from the unresolved `detection.path` (`os.path.relpath(detection.path, planning_root)`).
- src/agent_build_kit/init/scaffold.py:688 — `_rewrite` calls `_put(path, text, False)` with a bare positional bool for `dry_run`.

## From `planning-in-the-working-copy/6`

- src/agent_build_kit/pipeline/verify.py:402 — `_lacked_commits` does not check the return code of `git log`, so a failed log reads the same as 'lacks nothing'.
- src/agent_build_kit/installation.py:111 — `planning_paths` includes `CONFIG_FILENAME`, and the only caller in this unit filters it straight back out.

## From `planning-in-the-working-copy/10`

- src/agent_build_kit/runtimes/acp.py:221 — `PLANNING_NOTE` was inserted between the comment that describes `PATH_FIELDS` ("The raw-input fields an agent's file tools name their target in...") and `PATH_FIELDS` itself. That comment now sits above `PLANNING_NOTE` and reads as if it describes it.
- src/agent_build_kit/runtimes/acp.py:914 — The `_resolve_target` docstring still says the path must stay out of "the read-only specs subtree" and lists the cases that give None. It does not mention the planning paths, which the method now also returns None for.

## From `planning-in-the-working-copy/7`

- src/agent_build_kit/pipeline/wiring.py:815 — The name-only diff that feeds `git commit -- <names>` is split on newlines. Git quotes any path holding non-ASCII characters, a quote or a newline (`core.quotePath`), so `git commit` would get a pathspec that matches nothing.

## From `planning-in-the-working-copy/8`

- src/agent_build_kit/tracks/runner.py:421 — `_dirty_notes` splits `git ls-files` output on whitespace, so a state Markdown path with a space in it becomes two paths that cannot be hashed and is never excluded.
- src/agent_build_kit/tracks/runner.py:572 — A file that an earlier phase published and the current phase edits again (typically `tracked-issues.md`) is staged whole, so the later pull request still carries the earlier phase's edits to that file.

## From `planning-in-the-working-copy/9`

- src/agent_build_kit/cli/doctor.py:290 — CANNOT_TELL is defined in doctor.py, but the forges that produce the prefix (github.py:319, azure_devops.py:340) still spell out the literal "cannot tell". The contract has one producer side and one reader side, and they do not share the constant.

## From `planning-in-the-working-copy/14`

- In docs/architecture.md, the new sentence 'Nothing is stashed or reset; a file is removed only when the incoming commits hold it byte for byte …' (around line 1404) is one overlong line, unlike the wrapping of the paragraph around it. Rewrap it the next time the file is touched.

## From `planning-in-the-working-copy/15`

- src/agent_build_kit/templates/planning-orientation.md:19 — The orientation says `abk status` prints `abk --config <worktree>/abk.yaml tick`. It doesn't: `live_notice` (pipeline/planning_sync.py:129) prints that form with the command the person just ran, so `abk status` shows `abk --config <live>/abk.yaml status`. It does name the path, and the reader swaps in `tick`.

## From `planning-in-the-working-copy/16`

- tests/forges/test_local_forge_merge.py:172 — `rewrite_pull` reads `local-prs.json` again, with its own path and its own `stored[next(iter(stored))][0]` lookup. It does not build on `stored_pull` (line 167), which sits right above it.

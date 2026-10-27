# Proposal

## Why

`uv run pytest tests -n auto -m "not integration and not local_stack"` on the main branch fails nine tests (re-run on `origin/main` at `679e9a0a`). One of them (`tests/docs/test_skills_say_who_merges.py[abk-config]`) failed on a stale installed skill copy and is not in scope. Of the other eight:

- **Five read the specification folder.** Each enumerates files its own way (`tests/repo_docs.py:repo_markdown` walks the root with `rglob`, `tests/installation_leaks.py:files` walks `SCANNED` directories by `rglob`, `tests/test_live_test_names.py:tracked_files` uses `git ls-files`), and none knows the repository now holds `openspec/` (1364 tracked files, 1060 of them archive entries). The guards that police the documents (`test_no_document_names_a_removed_key_outside_the_migration`, `test_no_markdown_file_states_a_person_merges_every_pull_request`, `test_no_tracked_file_names_an_old_module`) fail on text that records, as history or as a requirement, the very thing they forbid. The leak scan's home-path and dated-anecdote tests fail on neutral tilde examples and three dated lines in `openspec/`; the `public-leak-test` specification says that scan reads planning content, so the content, or a rule too coarse for it, is what is wrong.
- **Two read a person's ignored `.env`.** `tests/test_telemetry.py::test_off_by_default_init_is_false_and_no_otel_module_is_imported` starts a subprocess in the checkout's directory, where `Settings` reads `./.env`; `tests/cli/test_telemetry_push_dashboard.py::test_without_a_url_it_names_the_setting_and_fails` calls `main`, which locates the checkout's `abk.yaml` and loads the `.env` beside it (`installation.py:load_config`). CI has no `.env`, so only a developer's machine fails.
- **`runs/` is out of scope.** The leak scan's two other failures (`test_no_issue_or_pr_number_anecdotes`, and the `runs/units.json` hits in `test_no_home_paths_in_text`) and the `runs/verified.json` hits of the old-module-name guard come from the pipeline's state files, which the change `pipeline-state-lives-outside-the-repo` moves out of the repository. They go away when that change merges.

Nothing makes the next guard written do better: each one picks its own walk, and the next one will read `openspec/changes/archive` too.

## What Changes

- **One helper, `tests/tracked_files.py`**, yields the tracked files a guard reads, parameterised by the top-level folders and root files it needs and by whether it reads the specification folder. The planning folders come from `planning.specs_dir` (and, so that a state folder still inside the repository is left out, `planning.state_dir`) of the checkout's `abk.yaml`, not from literals in the guards. Every repo-wide guard reads its files through it, and a meta-test fails a test module that walks the root by hand.
- **The three document guards skip planning content** (history and requirements, not documents). The decision and its evidence are per guard in `design.md`.
- **The leak scan keeps reading `openspec/`**, as `public-leak-test` requires, and changes in two ways: a tilde-relative path in the specification folder is not a home path (an absolute `/home/<name>` or `/Users/<name>` still is), and the three dated lines are reworded.
- **The stored-text scrub learns issue and pull-request references** (`name#N`), in `abk scrub-store` and in the `--scrub` pass of `abk planning split`, as a safety net: no committed text holds one today outside the state files.
- **The suite is cut off from the checkout's `.env`**: an autouse fixture makes the env-file lookup treat the checkout's own `.env` as absent, and the telemetry subprocess runs in a temporary directory.
- Docs: the contributor guide's two-checks paragraph, the `scrub-store` section of `docs/cli.md`, and the changelog.

## Impact

- Capabilities: `repo-wide-guards` (new); `public-leak-test` (one requirement modified); `stored-text-scrub` (one requirement added).
- agent-build-kit: `tests/tracked_files.py` (new), `tests/repo_docs.py`, `tests/installation_leaks.py`, `tests/old_test_kind_names.py`, `tests/test_live_test_names.py`, `tests/conftest.py`, `tests/test_telemetry.py`, `src/agent_build_kit/scrub_terms.py`, `split/scrubbing.py`, `cli/scrub_store_cmd.py`, three lines under `openspec/`, `AGENTS.md`, `docs/cli.md`, `CHANGELOG.md`.
- Not in this change: editing archived history to satisfy a document guard; any rewrite or exemption of the pipeline's state files (`runs/units.json`, `runs/verified.json`), which leave the repository with `pipeline-state-lives-outside-the-repo`; making `abk doctor`'s `public content` check read `openspec/`.

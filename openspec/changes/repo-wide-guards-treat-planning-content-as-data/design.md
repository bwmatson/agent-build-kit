# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` (origin/main at `679e9a0a`), and the failing tests re-run in the working copy. Paths are under `src/agent_build_kit/` unless they start with `tests/`.

- **How each guard enumerates files.**
  - `tests/repo_docs.py:repo_markdown` (`rglob("*.md")` over the root, skipping hidden and vendored folders) serves `tests/docs/test_review_docs_status.py` and `tests/docs/test_no_human_merges_every_pr.py`.
  - `tests/installation_leaks.py:files` (`SCANNED = src, tests, docs, web, openspec` by `rglob`, plus `ROOT_FILES` including `runs/units.json`) serves every test in `tests/test_no_installation_leaks.py`; `tests/test_leak_scan_planning_content.py` runs the same scan over a non-git temporary tree.
  - `tests/test_live_test_names.py:tracked_files` (`git ls-files -z`, every tracked file but `CHANGELOG.md`).
  - `tests/old_test_kind_names.py:candidates` (`SCANNED = src, tests, web/src, docs, scripts, .github` plus root `*.md`) does not reach `openspec/` or `runs/` and passes today.
- **What the eight failures hit, by area** (counted by re-running each guard):

| Guard | Archive | Active changes | Main specs | Nature of the hits |
|---|---|---|---|---|
| removed key named outside the migration | 32 files | 0 | 10 files | History and requirements that name `review.enabled` / `max_unit_lines` to record their removal |
| "a person merges every PR" | 9 | 1 | 2 | The old rule quoted by the change that replaced it; the spec that defines the guard; a plain sentence in a design about the local forge |
| old test-module name | 3 | 20 | 0 | The rename's own change records naming the old names (two more hits are in `runs/verified.json`, below) |
| home path | 10 lines | 2 | 5 lines | 22 of 23 are tilde-relative examples or `~/<redacted>`; 3 name the kit's own checkout as `~/agent-build-kit`; 2 more hits are in `runs/units.json` (below) |
| issue or PR reference | 0 | 0 | 0 | none under `openspec/`; the only two hits are stored notes in `runs/units.json` (below) |
| dated anecdote | 2 | 1 | 0 | two "checked on a date" lines and a quoted log line carrying a timestamp |

All three dated hits are under `openspec/`; none are timestamps in `runs/`.

**The interim red from `runs/` content.** `runs/units.json` (two home-path records, two records with `repo#N`) and `runs/verified.json` (old module names) also trip the leak scan and the old-module-name guard. The pipeline's state is moving out of the repository (`pipeline-state-lives-outside-the-repo`), so this change adds no exemption, rewrite or scrub of those files, and nothing here depends on a `runs/` path. Until that change merges the leak scan may still flag `runs/units.json`; the red disappears when it merges. The helper still works with a state folder inside the repository: it leaves `planning.state_dir` out of every guard that does not name it, and the leak scan keeps naming `runs/units.json` as a root file, as it does today.

- **What already enforces the public-content rule for planning content, and what it covers.**
  - `tests/test_no_installation_leaks.py` (this suite) reads `openspec/`, `abk.yaml` and, today, `runs/units.json` for home paths, foreign slugs, `word#N` references and dated anecdotes. `openspec/specs/public-leak-test/spec.md` makes that mandatory; `AGENTS.md` ("Two checks keep it that way") says the same. It is structural and term-free.
  - `abk scrub-check --target DIR` (`cli/scrub.py:scan`, terms from `scrub_terms.terms_for`) greps a checkout's `.md`, `.json`, `.yaml` and the other text suffixes, so it reads `openspec/` and `runs/`; it knows an installation's own words (repo names, owners, directories, the home user name) and nothing about shapes. It is run by hand from an installation's planning repo.
  - The `abk planning split --scrub` pass (`split/scrubbing.py`, `split/copy.py:_passes`) applies `terms_for` and `scrub_text` to moved files and `with_text` to moved records, once, at the split.
  - `abk scrub-store` (`cli/scrub_store_cmd.py:25`, `HOME_PREFIX`) rewrites home prefixes in stored text on request.
  - `abk doctor`'s `public content` check (`cli/doctor.py:_public_content`, 961) reads only the tracked `abk.yaml` and the ignored files (`scrub.local`, the overlay, `*.pre-redact`). It does not read `openspec/` or `runs/` and is not meant to.
  - Gap: nothing handles an issue or pull-request reference in text the scrub passes touch. The owner scrub replaced `owner/` with `<redacted>/` and left `example/app#15` in two stored notes, and `abk scrub-store` only knows home paths. The leak scan catches such a reference, but nothing removes it.

## Decisions, per guard

The rule that separates the two kinds of guard: a guard that polices **documents and code** (a removed key, an old rule, an old module name) reads what a reader of the repository is meant to follow; planning content is the record of how it got there, and a requirement in a specification may name the thing it forbids. A guard that polices **what is public** reads everything that is published, planning content included.

| Guard | Decision | Evidence |
|---|---|---|
| removed key outside the migration | (a) skip planning content | 42 of 42 files are archive entries and specifications that describe the removal; the document set the guard is for (`docs/`, `README.md`, `AGENTS.md`, the skills) has no hit |
| "a person merges every PR" | (a) skip planning content | 12 of 12 hits are the quoted old rule, the spec that defines this very guard, or a sentence about the local forge; documents and the skills have none |
| old test-module name | (a) skip planning content | the 23 `openspec/` files are the change records of the rename, which cite the old names by necessity; code, tests and documents have none (the `runs/verified.json` hits go with the state files) |
| home path | (c) narrower rule in `openspec/`, the full rule everywhere else | A tilde-relative path names no user: the tilde hits in `openspec/` are specifications of how a `~/` value is handled, and the three `~/agent-build-kit` lines name the kit's own checkout. An absolute `/home/<name>` or `/Users/<name>` still fails there |
| issue or PR reference | (b) keep the rule, close the scrub gap | No hit under `openspec/`; the pass is extended as a safety net so a stored note or a split cannot carry one (the two existing hits belong to the state files, above) |
| dated anecdote | (b) keep the rule, reword | Three lines; "checked on a date" is the story-instead-of-rule shape the rule exists to stop, and rewording costs less than an exception |
| removed-key / old-module-name / old test-kind (`old_test_kind_names.py`) | unchanged result, moved onto the helper | It lists its folders explicitly and reads no planning content already |

Skipping is by path, not by file name: the planning paths are the checkout's `planning.specs_dir` and `planning.state_dir`, so a repository that keeps its specifications elsewhere is skipped the same way.

## The helper

`tests/tracked_files.py` (support modules in `tests/` are flat, snake-case, imported as `from tests.<name> import ...`, e.g. `tests/repo_docs.py`, `tests/installation_leaks.py`):

- `planning_dirs(root) -> PlanningDirs`: the two planning folders, read from `root/abk.yaml`'s `planning.specs_dir` and `planning.state_dir` (when it is set; a later change makes it optional) with the defaults of `config.PlanningConfig` (`openspec`, `runs`; read without loading the whole configuration, which depends on the environment). A missing or unreadable `abk.yaml` gives the defaults.
- `guarded_files(root=ROOT, *, under=(), names=(), suffixes=None, specs=False) -> list[Path]`: the tracked files below each folder in `under` (empty means the whole tree), the root files in `names` that exist, filtered by `suffixes` when given. The specification folder is left out unless `specs=True`; the state folder is always left out (a guard that needs one of its files names it in `names`). Tracked means `git ls-files`; where `root` is not inside a git repository (the temporary trees the scan's own tests build) it walks the tree instead. Hidden folders, `node_modules`, `.venv`, `__pycache__`, `dist` and the built web UI are always skipped. Sorted, so a failure lists the same way twice.

It is a function of paths only, so a test of it builds a temporary tree with `abk.yaml` (and one with a renamed specification folder) and does not need the repository.

`installation_leaks.files` keeps its `SCANNED`, `TEXT`, `SELF` and `ROOT_FILES` but reads through `guarded_files(..., specs=True)`. `repo_markdown` and `tracked_files` read through it with `specs=False`. `old_test_kind_names.candidates` reads through it for its folders.

### The meta-test

`tests/test_repo_wide_guards_use_the_helper.py` follows `tests/test_atomic_write_guard.py` and `tests/test_one_definition_per_pattern.py`: it parses each module under `tests/` and fails, naming `path:line`, a module that enumerates the checkout by hand, meaning a `"ls-files"` argument, or `.rglob(`/`.glob(` called on `ROOT`, `REPO_ROOT` or a name bound from `Path(__file__).parents[...]`, unless the module imports `tests.tracked_files` or is on a short list with a reason (modules that walk only `src/` or `tests/`: `test_atomic_write_guard.py`, `test_secret_leak_guards.py`, `test_one_definition_per_pattern.py`, `test_record_metric_guard.py`, `test_verdict_readers_guard.py`, `test_test_helpers_defined_once.py`, `timing_hazards.py`, `tracked_files.py` itself). The detection is a function over source text, so the meta-test is itself tested against a synthetic module that walks the root and one that uses the helper. The builder lists the exemptions by running the meta-test and reading what it names; it does not add an exemption for a guard that reads documents or planning content.

## The scrub gap

`scrub_terms.py` gets `ISSUE_REFERENCE` (the pattern of `installation_leaks.ANECDOTE`, defined once and imported by the test, per `tests/test_one_definition_per_pattern.py`) and `scrub_references(text)` replacing a match with `<ref>`. It is applied by `abk scrub-store` (counted and rewritten with the home paths, a second run finds nothing) and by the split's text pass. A `<redacted>/repo#15` reference becomes `<redacted>/<ref>`. A unit-store note written at runtime is left alone: the pipeline's own note legitimately names a pull request number while it is live. This change does not run the scrub over the committed store; those records leave the repository with the state files.

## Environment isolation

`.env` is read in two places in the code: `Settings(env_file=".env")` (`settings.py:28`, relative to the process directory) and `installation.env_file_for(root)` (`installation.py:52-60`), called by `load_config` (273) and `Installation.env_file` (121). The two failing tests show one path each:

- The subprocess test runs `python -c` with a scrubbed environment but inherits the working directory (the checkout), so `Settings` reads the checkout's `.env`. Running it from another directory passes (verified). The fix is `cwd=tmp_path` in the test.
- The `push-dashboard` test calls `main`, which `locate`s the checkout's `abk.yaml` from the working directory and `reload`s the settings from the `.env` beside it, after the test's own `reload(None)`. Running the whole file from another directory passes (verified). A global `chdir` is not the fix: three tests in `tests/hooks/test_policy.py` fail when the suite is not run from the checkout, so they need it. The fix is an autouse fixture in `tests/conftest.py` that wraps `installation.env_file_for` so that a result resolving to the checkout's own `.env` becomes a path that does not exist (the wrapper is a function in a support module, `tests/checkout_env.py`, so it is tested without writing a real `.env`). With the fixture loaded, the file passes with a `.env` present (verified with a throwaway plugin).

Roots under a temporary directory have no `.env` and pass through unchanged. The module-level `settings` object, built at import from the working directory, may hold `.env` values from import time; the tests that need a clean one already `reload(None)`, and no further fixture is added until a test shows it is needed.

## Risks

- A planning path added to the skip list hides a real leak from a document guard. Only the document guards skip; the leak scan reads the specification folder, and `abk scrub-check` reads everything.
- The tilde exemption lets `~/<real-name>` in a specification pass. The home-user name and checkout directories are `abk scrub-check` terms, and a tilde path names no user.
- The kit is public: every example in the tasks and the tests is neutral (`app`, `example`, `~/work/trees`).

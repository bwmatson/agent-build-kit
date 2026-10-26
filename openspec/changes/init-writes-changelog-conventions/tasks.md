# Tasks

Acceptance: group 2 runs the real command over a scratch workspace and checks what it
left in each repo.

## 1. [agent-build-kit] [unit-test] Init writes the changelog conventions into each repo

Needs: changelog-setting-and-check group 1 merged — the setting, the packaged text and the loader this writes and reads

Done when init writes the block, the changelog and the merge rule into each repo with the
feature on, idempotently, without touching anything else, and shows it in the dry run.

- [x] 1.1 Test: the block is appended to an existing `AGENTS.md` leaving the rest
      byte-identical; goes into `CLAUDE.md` when only it exists; a new `AGENTS.md` (and no
      `CLAUDE.md`) is created when neither exists; CRLF files keep their endings.
- [x] 1.2 Test: a second run changes nothing; a block with an older stamp or different
      body has only its marked text replaced; a repo with its own changelog section outside
      the markers gets no block; mismatched markers are reported and left alone.
- [x] 1.3 Test: the changelog is created at the configured path when absent and an
      existing one is never edited; a path other than `CHANGELOG.md` is honoured.
- [x] 1.4 Test: `.gitattributes` is created with the rule when absent, the rule is
      appended (with a final newline added if missing) when the file lacks it, nothing
      changes when it is present, a conflicting `merge=` for the path is reported and left,
      and no other line changes.
- [x] 1.5 Test: a repo with the setting off is skipped by all three actions.
- [x] 1.6 Test: `--dry-run` prints one line per repo and action and writes nothing;
      doctor warns on a repo with a changelog and no union rule.
- [x] 1.7 Write `write_code_repo_conventions`, its three actions and their results, add
      the planned-work lines and the doctor check, and call it from `abk init`.
- [x] 1.8 Document the step, its idempotence and the opt-out in `docs/init.md` and
      `docs/architecture.md`, and add a changelog entry.

## 2. [agent-build-kit] [e2e-test] [acceptance] Init on a scratch workspace

Needs: process-tests-fake-the-github-api group 3 merged — e2e-test runs the whole `local_stack` suite, and
two ACP tests in it fail against the real GitHub host until they use the fake one

Done when the real `abk init` run over a scratch workspace leaves each repo as the spec
says and a second run changes nothing.

- [x] 2.1 Test (`local_stack`): init over a scratch workspace with three code repos (one
      with an `AGENTS.md`, one with only a `CLAUDE.md`, one with neither and no changelog)
      leaves each with the block in the right file, a changelog and the merge rule, creates
      no `CLAUDE.md` in the third, and a second run reports nothing to do and writes
      nothing.
- [x] 2.2 Write the acceptance run, which runs `abk init` with `--yes --skip-research --skip-propose` (no prompts, no model
      calls) over the scratch workspace, and document how to run it.

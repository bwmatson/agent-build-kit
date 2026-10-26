# Tasks

Acceptance: none — a command's argument handling is proved by tier-1 tests

## 1. [agent-build-kit] [tier1] `abk tags` says what to pass when given nothing

Priority: 4

Done when `abk tags` with no change and no `--all`, or with both, prints one usage line to standard error and exits 2
with no traceback, and `abk tags --all` and `abk tags <change>` are unchanged.

- [x] 1.1 Test: `abk tags` with neither a change nor `--all` exits 2, prints `abk tags: name a change, or pass --all
      for every change` to standard error, and its output contains no `Traceback` and no `TypeError`.
- [x] 1.2 Test: `abk tags <change> --all` exits 2, prints `abk tags: give a change or --all, not both` to standard
      error, checks nothing, and shows no traceback.
- [x] 1.3 Test: `abk tags --all` and `abk tags <change>` print and exit as they did, and a missing change still reports
      its missing tasks file; `abk tags --help` names `--all`.
- [x] 1.4 Add the check at the top of `cmd_tags` and the help text on the `tags` parser.
- [x] 1.5 Add a changelog entry.

# Tasks

Acceptance: none — the rules are decided by tests over a table of spellings and the probe by a fake agent that attempts the table; the live policy check against a real agent runs once, and is announced, after the agent-side list is extended, and is not a unit test.

Priority: 1

## 1. [agent-build-kit] [tier1] The rules and the policy check cover the spellings of a command

Done when a forbidden command is refused whichever global options its tool is given, the table of spellings is the one place they are listed, and the probe attempts the table and reports each class and spelling it was refused or not.

- [x] 1.1 Test: `tests/pipeline/test_command_policy_spellings.py` parametrizes `check_command` over the table's judge rows for the amend, push-to-default-branch and force-push classes (plain, `-C <path>`, `-c k=v`, `--no-pager`, `--git-dir=`, `--work-tree=`, the combination) and asserts each is refused with the class's own reason; the two-token `--git-dir <dir>` and `--work-tree <dir>` forms and `HEAD:main`, `master` and `+main` landings are rows too.
- [x] 1.2 Test: the same file asserts the host CLI's merge is refused with `-R <repo>`, `--repo <repo>`, `--repo=<repo>` between `gh` and `pr`, and that a `gh api` request that merges a pull request is refused with `-X PUT` before and after the path and with `--method`, while `gh api` reads (a comment list, a check list) and `gh -R <repo> pr view` are allowed.
- [x] 1.3 Test: the same file asserts a forbidden command behind a wrapper or a directory change is refused for each spelling the table lists (`env X=1`, `command`, `sudo`, `sudo -u root`, `cd <dir>;`), and that `git -C <dir> reset --hard` and `git -C <dir> branch -D x` are refused.
- [x] 1.4 Test: the same file asserts the rules do not over-block: `git -C <dir> log`, `git -C <dir> status`, `git --no-pager diff`, `git -C <dir> push origin <the unit's own branch>`, a commit message that mentions `gh pr merge`, and `--no-verify` and `core.hooksPath` through a global option are judged as before.
- [x] 1.5 Test: `tests/pipeline/test_command_spellings_table.py` asserts the table lists, for each class, the spellings of design.md (names and commands), every probe row is refused by `check_command` in a probe worktree's branch, and the plain commands of the other classes are unchanged.
- [x] 1.6 Test: `tests/runtimes/test_acp_probe_spellings.py` runs the fake probe agent with an agent that refuses every command and asserts every class and spelling of the table is attempted exactly as written, the report is ok with a result per spelling in table order, and one prompt was sent in one session whose command list has as many entries as the table.
- [x] 1.7 Test: the same file runs a fake agent that refuses the plain spelling of a class and lets the `-C` one through and asserts the report is not ok, names the class and that spelling, and lists the other spellings of the class as refused; and one that runs every command unasked reports every spelling unenforced.
- [x] 1.8 Test: `tests/runtimes/test_policy_check_spellings.py` asserts a cached report written before this change (no per-spelling results) loads and is reused within 15 minutes, a second check inside that window sends no second prompt, and a check after it asks again.
- [x] 1.9 Test: `tests/hooks/test_policy_spellings.py` runs every judge row of the table through the policy hook's entry and asserts each is denied, so the runtime that answers without a prompt is shown to hold for each spelling.
- [x] 1.10 Add the normalization of the tools' global options in `pipeline/command_policy.py`, used by `_check_segment` after `_strip_wrappers` and by `_skips_commit_hooks` and `_git_target` in place of their own loops, and read `git --help` on the machine to confirm the short list in design.md, correcting the design where it differs.
- [x] 1.11 Add the raw-API merge to the forge that owns the host CLI as data beside `denied_commands` (a default of none for every other forge) and apply it in `forges.denies`; confirm the stripping of a wrapper's option values (`sudo -u root`) and fix `_strip_wrappers` if 1.3 shows it fails.
- [x] 1.12 Add the table of spellings beside `command_policy`, make `PROBE_CLASSES` and `_probe_prompt` read it, add `results` to `PolicyReport`, report per class and spelling from `_probe`, and keep `unenforced` as the labels so existing readers are unchanged.

## 2. [agent-build-kit] [tier1] Doctor and init name the spelling; documentation

Done when `abk doctor` and `abk init` print an unrefused spelling by class and by spelling through one rendering, and the documentation states the cost and the table.

- [x] 2.1 Test: `tests/cli/test_doctor_policy_spellings.py` runs `abk doctor` with a runtime whose report leaves one spelling of one class unrefused and asserts it fails, prints the class and that spelling, groups the class's other spellings as refused and prints the configured fix; with every spelling refused it passes.
- [x] 2.2 Test: `tests/cli/test_init_policy_spellings.py` asserts `abk init` prints the same finding through the same function, asks before running the fix, and that a check that could not run prints a note and caches nothing, as before.
- [x] 2.3 Add one rendering of a policy report by class and spelling in the module doctor and init both use, and call it from both; read `cli/doctor.py` and `cli/init.py` first and correct design.md section 4 where they differ.
- [x] 2.4 Document it in `docs/agent-runtimes.md` (the policy section: the table, one prompt of N commands, once per 15 minutes, the table and not the model deciding the spellings, the bounded subset and why) and `docs/cli.md` (the doctor row), and add a changelog entry under Unreleased.

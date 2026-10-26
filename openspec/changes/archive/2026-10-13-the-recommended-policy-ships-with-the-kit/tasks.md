# Tasks

Acceptance: none — everything is decided by tests over fixture configurations in a scratch agent home and by a reference matcher over the table's own samples; whether a real agent then refuses the spellings is the live policy check, which spends model tokens and is run by a person as the confirmation after applying, not asserted by a unit.

Priority: 1

## 1. [agent-build-kit] [tier1] The recommended policy is one table in the kit

Needs: init-asks-which-runtime group 4 merged — the policy step this change gives a built-in fix, and the known-agent table the later groups put descriptors on

Done when the kit ships the recommended policy as data in the runtimes package — per class its globs, refused and allowed
samples, the classes it does not cover and the dialect — with a reference matcher, and tests that hold every glob to the
samples, the list to the policy check's probe rows and to the command rules, and nothing yet reads it from a command.

The commands stay written once in `pipeline/command_spellings.py`; the table points at its rows. Test files mirror the
source folders (`tests/runtimes/`, `tests/pipeline/`).

- [x] 1.1 Test: `tests/runtimes/test_recommended_policy.py` matches every refused sample of every class (the spelling rows that
      carry the glob reader, plus the extra samples: `git amend`, `refs/heads/main`, a quoted refspec, the GraphQL
      merge mutation) against that class's globs with the reference matcher and asserts each matches at least one, including the same command behind a git option, a repository option and a compound command.
- [x] 1.2 Test: the same file matches every allowed sample (a push of the unit's own branch whose name contains `main` or
      `master`, a pull request view, create and checks, a raw-API read, `git -C <dir> log`, a leased push, the repository's
      own test commands) against every glob of every class and asserts none matches.
- [x] 1.3 Test: the same file asserts every spelling the policy check attempts (`probe_rows()`) for a class the recommendation covers
      matches one of that class's globs, so a list the check would reject cannot be shipped, and names any covered class
      whose probe row is not refused.
- [x] 1.4 Test: `tests/pipeline/test_recommended_policy_agrees_with_rules.py` judges each refused sample the command rules forbid
      with `check_command` in a unit's branch and asserts it is refused; a sample only a glob refuses is listed by name in the
      table and the test asserts that list is exact.
- [x] 1.5 Test: `tests/runtimes/test_recommended_policy_dialect.py` asserts the matcher is case-insensitive, collapses runs of
      whitespace, matches a segment after `&&`, `||`, `|`, `;` and a newline, anchors at the command's start (a wrapper
      prefix is not matched), and that `*` crosses spaces and slashes and `[ +:"']` is a character class.
- [x] 1.6 Test: the same file asserts the list has no duplicate and no blank entry, is returned in table order with a caller's extra
      patterns after it and none repeated, and equals a literal list written in the test (so the table's helpers cannot
      drop a pattern without a visible diff).
- [x] 1.7 Test: the same file asserts the classes the policy check attempts that the table has no glob for are listed with a reason, and
      that each documented false positive and each documented gap still behaves as documented (a glob that starts catching a
      gap fails).
- [x] 1.8 Add the glob reader to `Reader` in `pipeline/command_spellings.py` and mark the rows the globs are expected to refuse
      (not the wrapper and directory-change rows); run the matcher over the rows and record in
      `docs/agent-runtimes.md` any row the shipped globs miss and the decision taken.
- [x] 1.9 Add `runtimes/recommended_policy.py`: frozen pydantic models, closed sets as `StrEnum`, the classes by their policy-check
      labels, the globs built with small helpers (the refspec endings and the program prefix written once), the refused
      and allowed samples, the uncovered classes with reasons, the known false positives, `DIALECT`, `matches` and
      `patterns(extra)`.
- [x] 1.10 Document it: `docs/agent-runtimes.md` gains a "recommended policy" section (what the table is, its classes, the dialect and
      that the matcher is an approximation of an agent's own, the classes with no glob and why, the superset rule), and an
      entry is added under Unreleased in `CHANGELOG.md` (later groups of this change fold into the same bullet).

## 2. [agent-build-kit] [tier1] `abk policy patterns` and `abk policy show`, and the installation's extra patterns

Done when `abk policy patterns` prints the recommended globs in three formats without an installation, `abk policy show`
prints the recommendation per class, the classes it does not cover, its false positives and its dialect, and an
installation can list `runtimes.<name>.policy_extra`; nothing yet reads an agent's configuration.

- [x] 2.1 Test: `tests/cli/test_policy_cmd_patterns.py` runs `abk policy patterns` with no installation and asserts every
      recommended glob is printed, one per line, in table order, exit 0, and no file is written.
- [x] 2.2 Test: the same file asserts the JSON array and the YAML sequence output load back (with `json` and the YAML loader the
      repository already depends on) to the identical list, including patterns holding quotes, brackets, colons and `*`.
- [x] 2.3 Test: the same file asserts a class filter prints only that class's globs in table order, and an unknown class exits 2
      naming the classes there are.
- [x] 2.4 Test: the same file asserts that with an installation whose runtime lists extra patterns, asking for extras prints them
      after the kit's with no duplicate, and without asking prints the kit's alone.
- [x] 2.5 Test: `tests/test_config_policy_extra.py` asserts an installation file with `runtimes.<name>.policy_extra` loads, a blank
      or non-string item fails at load naming the key, and a file without the key loads unchanged.
- [x] 2.6 Test: `tests/cli/test_policy_cmd_show.py` asserts `abk policy show` prints each class with its globs, the classes with no
      glob and the reason, the documented false positives and the dialect, writes nothing and starts no agent, and says the
      check is run by `abk doctor`.
- [x] 2.7 Add `cli/policy_cmd.py` with `patterns` (formats `glob`, `json`, `yaml-list`, `--class`, `--extra`) and the
      recommendation half of `show`, registered like the other commands, the installation optional; add `policy_extra` to
      `RuntimeConfig` with its validation.
- [x] 2.8 Document it: `docs/cli.md` (`abk policy patterns|show`, the formats, exit codes), `docs/configuration.md` and the
      abk-config skill (`runtimes.<name>.policy_extra`), and fold the commands into the changelog bullet.

## 3. [agent-build-kit] [tier1] The apply engine and the first known agent's applier

Done when a known-agent row can carry an apply descriptor, one engine merges the recommended list into that agent's
configuration under the rules of the design (add only, by splicing lines into the original text so every other byte is
unchanged, idempotent, backup once, atomic, refuses what it cannot read or cannot insert, nothing when the agent is absent),
the first known agent's row carries its descriptor, and no command calls it yet.

The engine never re-dumps a document: the parse only finds the list and computes what is missing, and the write is text
inserted into the original. The engine takes the resolved home directory as an argument and never reads the environment; its tests use a scratch home
and a neutral fixture row, and the one test file that names the first agent sits under `tests/runtimes/`.

- [x] 3.1 Test: `tests/runtimes/test_policy_apply.py` merges into a fixture configuration holding two rules of the operator's and some
      recommended patterns, and asserts the missing patterns follow the existing entries in table order with the operator's
      two unchanged and first; a list under an existing section that lacks it, and a missing section, get a block of their
      own (see 3.2a); a deny key with no value gets its items on the lines right after it.
- [x] 3.2 Test: the same file has one parametrised test, fed each of these inputs with the first agent's shape (or the neutral row
      for the same key path), asserting that `_removed_lines(before, after)` is empty (the diff holds only added lines), that
      every line of `before` appears in `after` unchanged and in order, and that a second run writes nothing and makes no
      second backup: `k: ~` and `n: null` beside the list; `k: True`; `key:    value    # c`; a multi-line plain scalar
      (`note: this is a long` then a continuation line); mixed indentation, as `a:\n    b: 1\napprovals:\n  deny:\n    - 'mine *'\nlst:\n- q`
      and `approvals:\n  deny:\n  - a\nmodel:\n    name: x\n    list:\n        - y`; a trailing `...`; a directive and `---` at
      the top; bare `off`, `on` and `yes` as values; a list indented differently from its neighbours; comments between
      and after the items; a quoted scalar; a last item with a trailing comment; a file with no final newline; and CRLF
      line endings (every inserted line ends in CRLF). A case where the list's neighbouring items are single-quoted,
      double-quoted or plain asserts the new items copy the style, and a pattern that is not plain-safe in a plain list is
      single-quoted.
- [ ] 3.2a Test: the same file asserts the inserted blocks: a missing list under an existing mapping lands after that mapping's
      last entry at its siblings' column; a missing list under a key with no value lands right under it, one step deeper;
      a missing section is appended at the end of the top-level mapping before a trailing `...`, which stays last; an
      empty file and one holding only comments take the block; a deeper key path (`tools.deny`) creates each missing level.
      Each case asserts the removed lines of the diff are empty and that the result parses to the original plus the
      block.
- [ ] 3.2b Test: the same file asserts each of these refuses, naming the file, the key path and why, changes nothing (no write,
      no backup), and exits as the other refusals do: a deny list written inline (`deny: [a, b]` and `deny: []`), a
      single string (`deny: "mine *"`, also plain), `deny: ~` and `deny: null`, an alias or anchored value, a section that
      is a flow mapping, and a file of several documents or whose top level is not a mapping. It asserts a spliced text
      that does not parse back to the original plus the added patterns is refused and not written (the engine's own
      verification, driven by a forced fault), and that `--toolset` over a flow list changes only that key's line, over a
      block list only that list's lines, and over a missing list inserts it, with every other line unchanged.
- [x] 3.3 Test: the same file asserts a second run reports nothing to change, writes nothing and makes no second backup, and that
      the first write copies the original to `<file>.abk-backup` which a later write (after a hand edit) does not overwrite.
- [x] 3.4 Test: the same file asserts a file that does not parse refuses naming it and writes nothing (no backup, no temporary), a
      list that is a number and a parent that is not a mapping refuse naming the file and key path (inline and string lists are 3.2b's), and an absent file says
      so, names the variable that moves it and creates no file or directory.
- [x] 3.5 Test: the same file asserts the write goes through a temporary file in the same directory and keeps the file's mode, and a
      write forced to fail after the temporary was made leaves the original and no temporary behind.
- [x] 3.6 Test: the same file resolves the home from the descriptor's variable (set to a scratch directory) and from the default
      when unset, reads and writes only that directory, and asserts the person's real home is not touched.
- [x] 3.7 Test: the same file runs a second neutral row (another file name, another key path, another scalar version) through the
      same engine with no change to it, extras given by the caller are merged once after the kit's, and a toolset replaces the
      list at its path (as text, touching only that list's lines) only when requested, shown as from-to, and a row with none refuses the request.
- [x] 3.8 Test: `tests/runtimes/test_known_agent_apply_row.py` asserts every descriptor in the known-agent table is complete (home
      variable, default home, file, a format with a writer, key path, verification note) and fails naming a row that is not;
      the first agent's row carries one, rows not verified carry none, and its fixture adds the patterns by insertion and keeps
      a quoted `off` quoted and every other line identical.
- [x] 3.9 Test: the language-independence and no-leak guards pass with the table's rows and the descriptor (agent names only in the
      table's rows and tests under `runtimes/`); the builder adjusts the descriptor's default home or the guard's
      exemption for the table as the design records.
- [x] 3.10 Add the optional descriptor to the known-agent row type and its first row's data in the protocol runtime's module, and
      `runtimes/policy_apply.py`: read, find, merge, splice (text inserted into the original; the document is never dumped),
      verify by parsing the spliced text, diff, backup, atomic write, over the descriptor, with a writer registry whose
      only member is the YAML splicer, and the toolset option.
- [x] 3.11 Add the YAML parser dependency (used read-only, to locate the list and verify the result) with a compatible range, and
      regenerate the lock; document it in `docs/agent-runtimes.md` (an "applying the recommended policy" paragraph: the merge rule,
      the backup, what it never does: re-dump the file, touch another line, or rewrite an inline or string list, which it refuses
      with the reason; how to add an agent's row) and fold it into the changelog bullet.

## 4. [agent-build-kit] [tier1] `abk policy apply`, a configuration-aware `show`, and doctor's fix text

Done when `abk policy apply` shows the diff, asks, writes and names the live check without running it, `abk policy show`
compares a known agent's configuration with the recommendation, and `abk doctor` prints the kit's own fix when the
installation has none.

- [x] 4.1 Test: `tests/cli/test_policy_cmd_apply.py` runs `abk policy apply` against a scratch home needing patterns and asserts the
      diff is printed before the write, a yes writes and prints the backup path and the count and exits 0, a no writes
      nothing (no backup, no temporary) and exits 1, and `--yes` takes the place of the yes.
- [x] 4.2 Test: the same file asserts `--dry-run` prints the diff and writes nothing and exits 0, nothing to change asks nothing
      and exits 0, `--dry-run --yes` is a usage problem, and an agent with no applier exits 2 printing the patterns command.
- [x] 4.3 Test: the same file asserts an absent configuration, one that does not parse and a wrong-shaped list each exit 2 naming
      the file and the key, with no file written, and a runtime whose enforcement is built in says there is nothing to apply
      and exits 0.
- [x] 4.4 Test: the same file asserts the output after a write names the command that runs the live check and says it spends model
      tokens, and a recording fake runtime shows no agent was started.
- [x] 4.5 Test: the same file asserts `--toolset` shows the toolset changing from the current list to the recommended one and writes
      both on a yes, its absence leaves the toolset as it was while stating the recommendation and the current value, and
      the flag on a row with no toolset exits 2 saying so.
- [x] 4.6 Test: the same file asserts `--agent NAME` selects a row when the runtime's command is a wrapper the table does not
      recognise and an unknown name exits 2 naming the known rows, and that an installation's extras are applied after
      the kit's.
- [x] 4.7 Test: `tests/cli/test_policy_cmd_show_config.py` asserts that for an agent with a descriptor `show` names the missing
      recommended patterns by class, counts the entries that are not the kit's, shows the toolset recommendation against
      the current value, changes no file, says an absent or unparseable configuration is so naming the path while still
      printing the recommendation, says the kit cannot read an agent with no applier, and starts no agent.
- [x] 4.8 Test: `tests/cli/test_doctor_policy_fix_text.py` asserts a failing doctor prints the installation's fix when set, else the
      apply command for an agent with an applier, else the patterns command then the key to set, and the installation's own
      fix stays first when both exist.
- [x] 4.9 Add `apply` to `cli/policy_cmd.py` and the configuration half of `show`, resolve the agent from the runtime's command or
      `--agent`, ask through the existing prompt helper, and change `fix_for` in `runtimes/policy_check.py` to the order the
      design gives.
- [x] 4.10 Document it: `docs/cli.md` (`abk policy apply`, flags, exit codes, the toolset flag and why it is separate), the
      `docs/agent-runtimes.md` policy section (doctor's new fix text), the abk-config skill where it names `policy_fix`, and
      fold the command into the changelog bullet.

## 5. [agent-build-kit] [tier1] `abk init`'s policy step offers the kit's recommended policy

Done when the policy step of `abk init` (and `abk init --policy-only`), finding a class unrefused with no configured fix and
an agent that has an applier, offers the kit's recommended policy as the fix: the diff, a confirmation, the applier's output,
the check again and the report of what is now refused; the installation's own fix still wins; assume-yes does not run it
unasked.

Test fakes: the earlier change's fake check (per-class, per-spelling results), a scratch agent home, and a fake prompt.

- [x] 5.1 Test: `tests/cli/test_init_policy_builtin_fix.py` asserts with a class unrefused, no configured fix and an agent with
      an applier the step shows the configuration path and the diff and asks before applying, a yes applies it and the check
      runs again with each class and spelling printed refused or not and no pass claimed that was not observed, and a no writes
      nothing, states the missing guarantee and exits 1 under `--policy-only`.
- [x] 5.2 Test: the same file asserts a configured `policy_fix` is the one offered when both exist, `--policy-fix` still records
      and runs the person's own, and with the kit's fix applied one spelling still unrefused is named as such with the note
      that the agent's matcher, not the list, may be what lets it through.
- [x] 5.3 Test: the same file asserts `--yes` without the authorising flag runs no fix, names the unrefused classes and exits 1,
      with the flag applies without asking, and that a token-spending check is asked about first as before.
- [x] 5.4 Test: the same file asserts an absent agent configuration says it was not found, offers nothing to apply and prints the
      patterns command; an agent with no applier lists printing the patterns among its choices; and after the kit's fix the
      toolset is unchanged and the output names the command that applies it.
- [x] 5.5 Add the built-in fix to the policy step in `cli/init.py` where the earlier change's step reaches its fix, with the
      precedence of the design, sharing the code path of the end of `cmd_init` and `--policy-only`, and the patterns
      command among the unknown-agent choices.
- [x] 5.6 Document it: `docs/cli.md` (what the step offers, `--yes` and the authorising flag with the built-in fix),
      `docs/init.md` where it describes the policy step, `docs/agent-runtimes.md` ("a machine with the kit and the agent and
      nothing else"), the abk-pipeline skill where it lists init's policy flags and the new command, and fold the step into
      the changelog bullet.

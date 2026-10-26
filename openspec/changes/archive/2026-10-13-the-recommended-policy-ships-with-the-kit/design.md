# Design

## What was checked, and what was not

Read-only, in the agent-build-kit checkout at `main` (090100c) and in the first known agent's own repository (its
uncommitted working tree, which holds the 38-pattern list).

- **VERIFIED, the agent-side list and its script.** The list is a JSON file with `approvals.deny` (38 globs) and
  `platform_toolsets.acp` (`file`, `terminal`, `todo`). The 38 are, per class: merge (`gh pr merge`, `gh pr merge *`,
  `gh pr * merge[ *]`, `gh * pr merge[ *]`); amend (`git commit *--amend*`, `git * commit *--amend*`, `git amend`,
  `git amend *`); push to `main` or `master` (a refspec shape `*[ +:"']main`, with a trailing ` *`, with a trailing quote,
  and `*heads/main` in the same three endings, for `git push` and for `git * push`); the raw-API merge
  (`gh api *pulls/*/merge*`, `gh * api ...`) and the GraphQL merge mutation (`gh api graphql *mergePullRequest*`,
  `gh * api graphql ...`). The script merges the list into the agent's `<redacted>` under its home (a home variable, else a default directory) with a comment-preserving
  YAML round trip: it appends the deny patterns the file lacks (exact string comparison, an operator's own rules stay, a
  single string value becomes the list's first item), **sets** `platform_toolsets.acp` to the policy's list outright, leaves
  every other key and comment, refuses a section that is not a mapping or a list that is not a list, writes through a
  temporary file in the same directory and `os.replace` (keeping the file mode), and says "nothing changed" on a second
  run. It has no backup and no dry run, and its library is pinned to the agent's own version so both writers agree on
  the output. Its YAML resolver is a 1.1 one (so `off` stays quoted).
- **VERIFIED, the agent-side tests.** Its matcher approximation lowercases the glob and each variant, tries
  `fnmatch.fnmatchcase` against the whole command and each segment of a split at `&&`, `||`, `|`, `;` and newlines (and the
  whitespace-collapsed forms), and its documented properties are the dialect used below. Cases are three tables: forbidden
  (per class, including the raw-API and GraphQL merges and refspecs such as `HEAD:refs/heads/main`, quoted `'HEAD:main'`),
  legitimate (a leased push to a `spec/` branch whose name merely contains `main`, `gh pr view`, `gh api` reads,
  `git -C <dir> log`, a commit message mentioning `amend`), and known gaps (configuration given with `-c` or the
  environment, all-branch pushes, a bare `git push`, an abbreviated option). A live-stack test applies the list to a scratch
  home and runs the same tables through the installed agent's own loader and matcher.
- **VERIFIED, the kit.** `pipeline/command_spellings.py` is the table the probe and the judge's tests read: `SPELLINGS`,
  class label to `Spelling(name, command, readers)` rows, `Reader` is `JUDGE` or `PROBE`, and `probe_rows()` flattens the
  probe's rows (`runtimes/acp.py` builds `PROBE_CLASSES` from it). The class labels are abk's own words. The five classes
  with spellings: amending a commit; pushing to the default branch; a force push to the default branch; merging a pull
  request; merging through the host's raw API. A hard reset and force-deleting a branch have judge-only rows; the probe
  also attempts plain commands for skipping the commit gate, clean, a recursive delete and a bare force push.
  `runtimes/policy_check.py` caches a `PolicyReport` per runtime for 15 minutes and `fix_for` returns the installation's
  `policy_fix`, else the report's advice, else the key to set. `config.RuntimeConfig` has `command`, `policy_fix`,
  `models`, `context_windows`, `limits`, schema-strict. Packaged data (templates, skills, prompts) is read with
  `importlib.resources` or beside the module, and the wheel builds `src/agent_build_kit` whole, so a data file beside a
  module ships. Machine environment is read through `settings.named_value(name, env_file)`, never `os.environ` elsewhere
  (`tests/test_no_installation_leaks.py` checks it). The only YAML dependency is `pyyaml`, which drops comments;
  `ruamel.yaml` is not in the lock.
- **VERIFIED, the guards.** The no-installation-leaks test looks for home-directory product paths and literal environment
  keys; the ecosystem-names guard forbids package-manager and manifest names in source outside `profiles/` and `init/`.
  Neither forbids an agent product's name; the convention (set by `init-asks-which-runtime`) is that product names live in
  the known-agent table's rows and tests under `runtimes/`.
- **VERIFIED, `init-asks-which-runtime` is not merged.** Unit 1 of five is running, the others planned. Its design
  (read, not edited here) puts the known-agent table in the protocol runtime's module and the guided policy step in
  group 4 (`--policy-only`, `--policy-fix`, `--run-policy-fix`, "a known agent's fix is offered", unknown agents get three
  choices). This change gives that step a fix of its own to offer, so it builds after group 4.
- **UNVERIFIED, for the builder to confirm and correct here:**
  - the table row type and the name of the module's table, which `init-asks-which-runtime` group 1 decides (the descriptor
    below is a field on that row);
  - that the 38 patterns refuse every GLOB row of the spellings table under the kit's reference matcher (the builder
    runs it; a row they miss is either a spelling to add a glob for or a row to mark as not read by the globs, and the
    finding is recorded in `docs/agent-runtimes.md`);
  - that the reference matcher agrees with the agent's own on the tables (only the agent's live-stack test shows this, so
    it is stated as an approximation in docs and the live probe is the confirmation);
  - whether the first known agent's own writer and the kit's engine produce the same bytes for a given file (they pin one
    library version there for that reason; the kit's test checks only that the engine changes nothing but the added lines);
  - the default home and file name of every agent but the first (no other row gets a descriptor until someone verifies it);
  - which other agents' configuration can hold a command deny list at all, and in which format (none is verified);
  - that `test_no_installation_leaks` accepts the descriptor's default home as written; if not, the descriptor holds the
    directory name as a relative component and the test's exemption for the known-agent table is the builder's to add;
  - whether `check_command` refuses the GraphQL merge mutation (it is a glob-only class below, so nothing here depends on
    it, but a refused sample the judge allows is a finding for a follow-up).

## 1. The recommended policy is one table

### Where it lives, and why data in Python

A module `runtimes/recommended_policy.py` (a new file; `runtimes/` already holds the policy check and the protocol
runtime, and is the package allowed to name an agent product). **Recommended: a typed Python table (frozen pydantic
models, `StrEnum` for closed sets), not a packaged JSON file.** Reasons: the class labels and sample commands it must stay
in step with are already a Python table (`command_spellings.SPELLINGS`), so one import ties them with no loader and no
second path to ship; the type checker and the repository's conventions (types are pydantic models, closed sets are enums)
apply; a malformed entry fails at import in the test run, not when a person runs `apply`. Alternatives rejected: a packaged
JSON file (a loader, a schema duplicating the model, and the samples would have to live in another file or reference
Python rows by name); a YAML file (nothing gained over JSON). The outputs a person needs as JSON or YAML come from
`abk policy patterns`, rendered from the table.

### Shape

```
ClassPolicy(label, globs, refused_samples, allowed_samples)   # frozen
RECOMMENDED: tuple[ClassPolicy, ...]                          # in the order the list prints
DIALECT: str                                                  # the documented glob dialect
matches(pattern, command) -> bool                             # the reference matcher
patterns(extra=()) -> list[str]                               # every glob, in order, no duplicates
```

- `label` is a class in abk's own words, exactly the key used by `command_spellings.SPELLINGS` where it has one, plus
  the classes only the globs cover (below), so there is one vocabulary and `abk doctor`, the probe and the policy list
  name a class identically.
- `globs` are the patterns that refuse the class across spellings, copied semantically from the 38: per class, a plain
  form and the `<program> * <subcommand>` form that puts a global option between the program and the subcommand, and for
  the push class the refspec shapes. Recommended to build them with a few small helpers (the refspec endings and the
  `git`/`git *` prefix are the only variation: `main`/`master` times six endings times two prefixes is twenty-four of the
  thirty-eight) so a branch name or an ending is written once. A test pins the generated list against a literal in the
  test file, so a change to the table shows as a diff in review and the helpers cannot silently drop a pattern.
- `refused_samples` are the commands every one of which must match at least one of the class's globs: the rows of
  `SPELLINGS[label]` that carry a new reader, `Reader.GLOB` (a row the globs are expected to refuse; the wrapper and
  directory-change rows do not carry it, since an agent folds a wrapper's name before matching and a glob anchors at the
  command's start), plus extra samples only a glob can show (`git amend`, `git push origin refs/heads/main`,
  `git push origin 'HEAD:main'`, the GraphQL merge mutation). The spellings table stays the source of every command it has
  and gains one enum member; nothing is copied.
- `allowed_samples` are commands a build run needs and no glob of any class may match: a leased push to the unit's own
  branch and branch names that merely contain `main` or `master`, `gh pr view|create|checks|list`, `gh api` reads, `git -C
  <dir> log|status|fetch`, `git commit -m` with a message that mentions a forbidden word in quotes only where the dialect
  cannot tell (see the known false positives below), and the repository's own test commands. This is the over-block
  guard the agent's own repository keeps in its tests.
- Known false positives, as data: the commit-message mention of `--amend` and the commands that only name `push` and
  `main` as words. They are listed under `known_false_positives` on the table (not in `allowed_samples`) so the docs and
  `abk policy show` state them and a test shows each still matches, so the claim cannot rot.

### The classes

The recommendation covers the classes an agent is most likely to run without asking and the kit cannot see:

| Class | Source of its commands |
|---|---|
| merging a pull request | `SPELLINGS`, plain and repository-option spellings |
| merging a pull request through the host's raw API | `SPELLINGS`, the REST merge path in both argument orders |
| merging a pull request through the host's GraphQL API | globs and extra samples only (the mutation name) |
| amending a commit | `SPELLINGS`, the seven git global-option spellings, plus `git amend` |
| pushing to the default branch | `SPELLINGS`, plus the refspec and quoting forms |
| a force push to the default branch | covered by the push class's globs; listed as its own row of the report |

The classes the probe attempts but the recommendation has **no glob for**: skipping the commit gate, a hard reset, clean,
force-deleting a branch, a recursive delete, a bare force push. The first known agent gates the dangerous ones itself
(its own approval detector asks and the kit answers); whether another agent does is **UNVERIFIED** per agent. `abk policy
show` prints these classes under "not covered by the recommendation" with the reason, so a person using `patterns` for an
agent that does not gate them knows. Extending the recommendation to them is a table edit, deliberately not decided here:
a glob for `git reset --hard` would refuse it in interactive use too, which is a policy choice for the person.

### The glob dialect

Stated in `DIALECT` and in `docs/agent-runtimes.md`, because a glob only means something against a matcher:

- fnmatch semantics: `*` matches any run of characters including spaces and slashes, `?` one character, `[...]` a
  character class (so `[ +:"']` is "one of space, plus, colon, quote").
- case-insensitive: the pattern and the command are lower-cased before matching.
- the command is matched whole and as each segment of a compound command split at `&&`, `||`, `|`, `;` and newline, and
  with runs of whitespace collapsed; a match of any of them refuses the command.
- a pattern is anchored: it must match the whole command or segment, which is why the list has both the plain form and
  the `* ` forms and why a wrapper prefix is not matched (the agent folds it first, or does not: **UNVERIFIED per agent**).

`matches` implements exactly this, and is **a reference matcher, an approximation of an agent's own** (an agent splits at
shell operators with quote awareness and unwraps subshells and prefixes; this one does not). It is for the kit's own
tests and `show`; the live probe, which asks the real agent, is the confirmation, and the docs say so.

### Who reads the table

1. `check_policy`'s probe keeps its table (`SPELLINGS` through `probe_rows()`, unchanged: the table of spellings merged by
   the earlier change is the one place a probed command is written). What changes: a test holds the two together, so the
   recommendation cannot be shipped that the check would reject: every probe row refused by a class with globs must match
   one of that class's globs, and every GLOB row too (the "shipped list is a superset of what the check requires" test).
2. The command-policy normalization tests keep reading `SPELLINGS`; a new test reads `RECOMMENDED` and runs every refused
   sample through `check_command` where the sample is a command the judge forbids, so the globs and the judge are shown to
   agree on the commands both own (the GraphQL mutation is exempt and named as such).
3. The appliers write `patterns(extra)`.
4. `abk policy patterns` and `abk policy show` print it.

## 2. Appliers, table-driven

### The descriptor

A known-agent table row (`init-asks-which-runtime` group 1) gains an optional field:

```
ApplyPolicy(
  home_env, home_default, file,        # <home>/<file>: $home_env if set, else ~/<home_default>
  format,                              # YAML today; a closed set, a writer registered per member
  deny_path,                           # key path of the deny list, e.g. ("approvals", "deny")
  yaml_version,                        # "1.2" or "1.1" (how bare scalars such as `off` are read and quoted)
  toolset,                             # optional: Toolset(path, names), a recommendation, never merged
  verified,                            # how it was checked, or "documented only"
)
```

A row without it has no applier. The first known agent's row gets one (home variable the agent reads for its home, default
`~/<the agent's directory>`, `<redacted>`, YAML 1.1, `approvals.deny`, toolset `platform_toolsets.acp` =
`file, terminal, todo`), verified against the agent's own script and tests as above and on its documentation, **not**
against a run of the kit's engine on the real agent, which is the live confirmation. Every other row stays without one
until someone verifies its file and key: a descriptor that guesses a path would edit a person's configuration on a guess.

**Formats.** The format is a closed `StrEnum` with a writer per member. Recommended: **YAML only now.** JSON and TOML are
named by the request as possibilities, but no known agent uses them, and an untested writer is a hazard on a person's
config. The seam is the registry: a row naming a format with no writer fails the table's structural test, so the first
JSON or TOML agent adds its writer and its test with its row. A neutral fixture row with a different key path
(`tools.deny`) and different file name proves the engine reads the descriptor rather than the first agent's shape.

### Where the code lives

`runtimes/policy_apply.py`: the engine (read, merge, diff, write) over a descriptor; no product name. The first agent's row
is data in the protocol runtime's module with the rest of the table, and the tests that name that agent sit under
`tests/runtimes/`, as `init-asks-which-runtime` does for the table. Everything else in the framework stays
product-neutral.

### The dependency

Leaving the operator's file exactly as it was is a requirement (a person's configuration is theirs; the first agent's file is
hand-annotated), and `pyyaml` neither keeps comments nor reports where a node sits in the text. Recommended: **add
`ruamel.yaml` as a dependency, a compatible range** (the version the first agent's own script pins, up to the next minor,
for example `>=0.18.16,<0.19`), not an exact pin: the kit is a library installed beside other tools and an exact pin would
conflict. It is used **read-only**, for two things: to parse the document (the descriptor's `yaml_version` picks the
resolver, so bare `off` reads as the agent reads it) and to learn the line and column at which each key and each list item
starts. **The kit never dumps a document.** A round trip through any library re-renders every line it parses (null and
boolean spellings, the spacing before a value, folded multi-line scalars, mixed indentation, a trailing `...`), and the set
of spellings it normalises has no fixed end, so the writer inserts text into the original and leaves every other byte alone
by construction. Rejected: re-dumping the parsed document (the approach this replaces: it rewrote operators' lines that the
merge never touched), and an optional extra (init, the default fix path, must work after a plain install). The lock is
regenerated in the same group.

### The merge rule

Given the original text, its parse and `patterns(policy_extra)`. **The parse only finds and computes; the output is the
original text with lines spliced in.**

1. **Navigate** the deny path in the parse (read-only). A section on the path that is not a mapping, or a deny value that is
   neither a list nor absent, **refuses**, names the file and the key path, and changes nothing (the script's rule). A
   document that is not one document (several `---` documents) or whose top level is not a mapping refuses the same way.
2. **Missing** is computed by exact string equality against the items the list already holds, in the table's order, after
   the operator's entries. A pattern that differs from a recommended one only in case is a different string and is added: a
   harmless duplicate, rather than guessing which the operator meant. Nothing is ever removed, reordered, edited or
   de-duplicated. Nothing missing means nothing is written and no second backup.
3. **Splice** the missing `- <pattern>` lines into the original text, one per pattern, and change no other byte:
   - *The list exists as a block list* (the key line holds only the key, a comment at most). The lines go immediately after
     the **end of the last item**: the last non-blank, non-comment line before the first later line that is indented at or
     less than the item's dash column, or that is a `---` or `...` marker, or the end of the file. A comment on the last item's
     line, comments and blank lines after it, and a trailing `...` therefore stay where they were, after the new lines. Each
     new line copies the last item's leading whitespace and the dash with the spaces after it, so the list's indentation
     and sequence-item offset are the list's own, whatever the rest of the file uses. A last item that spans lines
     (a multi-line scalar) is complete before the insertion point, never split.
   - *Quoting*: a new item is written in the style of the last item where that is safe: single-quoted stays single (a quote
     doubled), double-quoted stays double (backslash and quote escaped), plain stays plain when the pattern is plain-safe (it
     starts with no indicator character, holds no `: ` or ` #`, has no leading or trailing space, and the descriptor's
     resolver reads it back as the same string, so `off` or `on` is not plain); otherwise it is single-quoted.
   - *The key holds nothing* (`deny:` with no value, so the list is empty or null): the lines go on the lines right after
     the key line (and after any comment line directly below it that is indented deeper), single-quoted, indented one step
     deeper than the key, where a step is the offset of the first nested block in the file, else two spaces.
   - *The list is missing under an existing block mapping*: a small block of its own, the key and its items, goes after the
     end of that mapping's last entry (the same end rule, at the mapping's key column), at the column of its other keys.
     An existing section whose key holds nothing (`approvals:`) gets the block on the lines right after it, one step
     deeper.
   - *The section is missing*: the block (every missing key down the path, nested one step per level, then the items) is
     appended at the end of the file's top-level mapping: after the last content line and before a trailing `...` marker, which
     stays last. An empty file or one holding only comments gets the block as its whole content, after the comments.
   - The file's own line ending (LF or CRLF) is used for every inserted line, and a last line without a newline gets one
     before the insertion.
4. **Refuse what cannot be a pure insertion**, naming the file, the key path and why, changing nothing, exit 2 as the other
   refusals: a deny list or section written on its key line, as a flow list (`deny: [a, b]`, `deny: []`), a flow mapping, a
   single string (`deny: "mine *"`), `~` or `null`, an alias, or a tagged or anchored value. **A single string is refused**:
   making it the list's first item would rewrite the operator's own line, and a diff that removes a line the merge was not
   asked to change is exactly what this writer promises never to produce. The refusal text says to write the list as a block
   list (or hand the string over as its first item) and run it again. (The agent's own script turns such a string into the
   list's first item; that convenience is given up for the guarantee.)
5. **Verify before writing.** The spliced text is parsed again, in the same resolver. It must parse, and equal the original
   parse with the missing patterns appended to the list (and, with `--toolset`, the toolset replaced); anything else refuses
   as a defect in the merge, writes nothing, and says so. A splice the library cannot confirm is never written.
6. **Toolset**, only with `--toolset`: the path's list is set to the descriptor's names, replacing what is there. Unlike the
   deny list this *replaces* (the agent's own script treated the policy as the owner of this list); so it is shown as
   `from [...] to [...]`, never applied by default, never applied by init's built-in fix, and reported by `show` as a
   recommendation with the current value. It is still text: for a block list the item lines of that list are replaced by
   the new ones (indented and dashed like the first old item), for a flow list the bracketed value on the key line is
   replaced (a comment after it stays), for a missing or empty one it is inserted as for the deny list. The toolset list's
   own lines are the only existing lines it may change; a toolset value of any other shape (a string, an alias) refuses.
   Rationale: a deny entry only makes the agent refuse; a toolset narrows what a build run may call at all, and a person on
   an agent with their own tools needs to choose that.
7. **Diff**: a unified diff of the file text before and after; for the deny list it holds added lines only. No change, no
   write: "already up to date, nothing changed".

### Writing safely

- **Parse first.** A file that does not parse refuses, naming the file and the parser's line, and writes nothing.
- **Absent config.** When `<home>/<file>` does not exist the agent is not installed (or the home variable points
  elsewhere): the engine says "no configuration at <path>; the agent is not installed or its home is elsewhere
  (set <home_env>)" and does nothing. It never creates an agent's configuration file or directory.
- **Atomic.** The new text is written to a temporary file in the same directory, given the original's mode, and moved over
  the file; a failure removes the temporary and leaves the original.
- **Back up once.** Before the first write the original is copied to `<file>.abk-backup` beside it, only when that
  name does not exist, so the first backup is the file as the person had it and later runs never overwrite it. The path is
  printed. A dry run writes no backup.
- **Scratch home.** The home comes from the descriptor's variable through `settings.named_value` (the process environment,
  then the planning repo's `.env`), so tests and the acceptance runs set it to a temporary directory
  (`<redacted>` names the variable there) and the engine takes the resolved directory as an argument,
  never reading the environment itself.
- **Idempotent.** A second run finds nothing to add and writes nothing, no second backup.

## 3. The commands

`abk policy` has three subcommands (`cli/policy_cmd.py`, registered as the others are). `patterns` needs no installation;
`show` and `apply` use the installation's selected runtime when there is one, and `--runtime NAME` otherwise.

**The agent is chosen** from the known-agent table by the runtime entry's command (the program name of the argv, as init's
table matches it), or named with `--agent NAME` when the command is a wrapper the table cannot recognise. A runtime that
spawns no agent of the table (Claude Code, which enforces the policy through its hook) says so: nothing to apply.

- **`abk policy patterns [--format glob|json|yaml-list] [--class LABEL ...] [--extra]`**: the recommended globs, one per line
  for `glob`, a JSON array for `json`, a YAML sequence of double-quoted scalars for `yaml-list` (a quoted scalar is safe
  for the patterns' `[`, `*`, quotes and colons; a test loads the output back and compares), in table order. `--extra` adds
  the installation's `policy_extra` when an installation is present. No model call, no file written, exit 0.
- **`abk policy show`**: per class, its globs, what the class does not cover, the known false positives, and the
  dialect in one line; then, for a known agent with an applier, the agent's configuration path, whether it exists and
  parses, how many recommended patterns it has and which it lacks, the entries it has that the recommendation does not
  (the operator's own, only counted), and the toolset recommendation against its current value. For an agent with no
  applier it says so and points at `patterns`. Read-only; it **does not run the policy check** (the check spends
  tokens), and says `abk doctor` does. Exit 0, or 2 on a usage problem.
- **`abk policy apply [--runtime NAME] [--agent NAME] [--dry-run] [--yes] [--toolset]`**: resolves the agent and the file,
  prints the diff, asks "apply to <path>? [y/N]", writes (backup, atomic), prints what changed, and then offers the live
  check, which spends tokens and so is asked first, as init asks (`--yes` does not run it: the check is run by
  `abk doctor` or `abk init --policy-only`, and `apply` prints that command). **Exit codes:** 0 written or nothing to
  change, or `--dry-run` showed a diff; 1 the person declined, or the live check was run and still finds a class unrefused;
  2 a usage problem, an unparseable or wrong-shaped configuration, an absent configuration, or an agent with no applier.
  An unknown flag combination (`--dry-run --yes`) is a usage problem.

## 4. `abk init`'s policy step has a fix of its own

`init-asks-which-runtime` group 4's step: check; if a class is unrefused and a fix is configured, offer it; for an unknown
agent, offer three choices. This change adds one source of fix, with a fixed order of precedence:

1. the installation's `runtimes.<name>.policy_fix` (the person's own, unchanged; `--policy-fix` still records one);
2. else, if the selected agent has an applier, **the kit's recommended policy**: the step shows the file and the diff and
   asks "apply the kit's recommended policy? [y/N]", with the same wording as the configured fix and with its output
   shown, then re-runs the check and prints what is now refused and what is not (the report the earlier change renders);
3. else the existing choices, with one addition: the first choice (rely on the protocol layer) and the second (supply a
   fix) are accompanied by "print the recommended patterns for you to place in the agent's own configuration (`abk policy
   patterns`)", which init prints.

It never claims a pass it did not observe, and the built-in fix is never run unasked under `--yes` unless
`--run-policy-fix` is also given (the earlier change's rule, applying to the built-in fix too, and for the same reason: it
rewrites the agent's own configuration). It applies the deny list only: the toolset is not applied by init; the step
prints `abk policy apply --toolset` as a separate decision. `abk doctor`'s fix text (`fix_for`) gains a step: with no
`policy_fix`, an applier-bearing agent gets "run `abk policy apply`", else "run `abk policy patterns` and add them to the
agent's configuration", ahead of the existing "set `policy_fix`" hint.

This removes the need for the agent's own repository to be present: a machine with only the kit and the agent installed
goes from a failing check to a passing one with one command.

## 5. What the agent's own repository becomes

Recommended: **its list is retired, and what is specific to that installation moves to `runtimes.<name>.policy_extra`.**
The kit's list is the superset the check requires and carries the spellings the agent's repository found; an installation
that wants one more pattern lists it in `abk.yaml` and the engine merges the two. The repository's script becomes
redundant (the engine is a clean re-implementation of it) and its tests become the kit's tests (the three case tables map
to `refused_samples`, `allowed_samples` and the known-gap and false-positive data). Retiring is that repository's own
change; until it lands the two lists coexist, and the engine's add-only merge makes a person running both harmless.

**How drift is prevented** while both exist, and after: (a) the kit's tests hold the shipped list to every probe row and
GLOB row of the spellings table, so the list cannot fall behind the check; (b) the engine adds, never removes, so an older
list already in a person's configuration is a subset that `show` reports as missing patterns and `apply` completes;
(c) `abk doctor` runs the live check, which is what shows an agent letting a spelling through whatever the files say;
(d) the agent's repository, while it keeps a copy, may assert in its own test that its list is a subset of `abk policy
patterns --format json`; that is its follow-up, not a kit test (the kit never names or reads the other repository).

`policy_extra` is `list[str] | None` on `RuntimeConfig`, schema-strict, each item a non-blank string; a blank item fails at
config load naming the key. An extra pattern is merged and shown by `show` as the installation's, never reordered into
the kit's.

## Interactions and ordering

- **Build after `init-asks-which-runtime` group 4**: that change creates the known-agent table (its group 1), the guided
  policy step and `--policy-only` (its group 4). Only this change's later groups need the table and the step, but the
  change is built as a whole after them, as the task file says, so the order is one decision, not four.
- **The earlier change `acp-policy-covers-global-option-spellings` is merged**: its table is reused, and its `Reader` enum
  gains one member.
- **The doctor and init share one rendering** of a report by class and spelling; this change does not reprint it.
- **`policy_fix` semantics are unchanged**: an installation that sets it sees no difference.

## Testing

Tier 1 only. The engine's tests use a scratch home (a temporary directory named through the descriptor's variable, passed
explicitly) and fixture configurations: comments, a quoted `off`, operator entries, an inline list and a string deny value
(both refused), a deny key with no value, a missing list and a missing section, an absent file, an unparseable one, a
wrong-shaped section, and one parametrised test holding the byte-for-byte promise over inputs that a whole-document dump
rewrites: `k: ~` and `n: null`, `k: True`, `key:    value    # c`, a multi-line plain scalar, mixed indentation, a trailing
`...`, a directive and `---`, bare `off`/`on`/`yes`, and a list indented differently from its neighbours. Most engine tests use a **neutral fixture row** (a different file
name, a different key path, a different YAML version), so the engine is shown to read the descriptor; the first agent's
row has its own structural test under `tests/runtimes/` naming it. The glob tests are parametrized over the table's own
samples. The init step uses fakes for the check and the prompt, as the earlier change's tests do. The live check against a
real agent after applying is a person's confirmation and is not asserted (hence `Acceptance: none`).

## What stays out

Editing the agent's repository; appliers beyond the first row; JSON and TOML writers until a row needs one; globs for the
classes an agent gates itself; running the check automatically after applying; changing the 15-minute cache; and anything
about calls an agent makes without asking, which stays the agent's property and the live check's finding.

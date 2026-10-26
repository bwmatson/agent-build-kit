# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `7c42abc5`). Paths are under
`src/agent_build_kit/` unless noted; line numbers are approximate to a few lines.

- **The rule** (`AGENTS.md` ~10-35). No consumer references anywhere (repo names, owners and slugs, product names, a product's config
  directory under home, PR numbers, anecdotes); fixtures use `app`, `platform`, `example`. Two checks keep it: the structural test and
  `abk scrub-check --target <checkout>` "from its planning repo", the term list living in `abk.yaml`. The last bullet reads "Commits carry
  no `Co-Authored-By` trailer in this repo" (see the open decision below).
- **`abk scrub-check`** (`cli/scrub.py`). `terms_for(installation, *, target=None)` (~37): adds `installation.root.name` unconditionally
  (~46); for each repo skips it when `repo.path` resolves to `target` (~48-51), else adds the key, the forge identity's account, project
  and name, the checkout directory name, the file names in `deploy.live_written`, the ssh key's file name, the first path segment of each
  deploy rule and the argv words that have no `-`, `/` or `.`; then adds the `verify.env` names (~71). Terms under 3 characters and a
  fixed `GENERIC` set are dropped; the result is sorted longest first. `scan(target, terms)` (~82-95) walks `target.rglob("*")`, skips
  `SKIP_DIRS` (`.git .venv node_modules __pycache__ .pytest_cache dist build`) and any suffix outside `TEXT_SUFFIXES`, and matches
  case-insensitively line by line. `cmd_scrub_check` prints `path:line: term`, exits 1 on hits, 2 when the target is not a directory. It
  reads no local list and does not look at `.env`.
- **The structural test** (`tests/test_no_installation_leaks.py`). `SCANNED = ("src", "tests", "docs", "web")` (~20) plus `README.md`,
  `CLAUDE.md`, `CHANGELOG.md` (~64-67); `HOME_PATH` (~66) matches a tilde-slash home prefix unless followed by `.claude .local .config .cache .ssh .volta`,
  and the Linux home root followed by a letter. Other patterns: a GitHub slug whose owner is not a fixture or an upstream, an Azure organisation, an issue-number
  anecdote, a product config directory, a literal env read. `abk.yaml`, `openspec/` and `runs/` are not scanned.
- **`redact-history`** (`cli/redact_history_cmd.py` ~28-77). Reads `units.json`, the ledger, run logs and transcripts; `redaction.gather`
  builds the set of known secret *values* (`verify.env` providers, credential settings, the `redact` list); `--apply` needs the pipeline
  paused (`pause_in_force`), takes the store's own lock (`UnitStore(path).locked()`), copies the file to `<name>.pre-redact`
  (`COPY_SUFFIX`) and writes the redacted text through `atomic_write_text`. It rewrites the *file text*, not records, and knows values,
  not paths. It is labelled temporary.
- **The store** (`pipeline/unit_store.py`). Records are `StoredUnit` with `feedback`, `guidance`, `predecessor_note`, `stack_refusal` and
  `history` (a tuple of dicts with `note`); every writer is a method guarded by `_exclusive` (the store's lock), and `set_feedback` runs
  `redact_text(feedback, where="feedback")`, so known secret values are removed on the way in. No method rewrites text across records.
- **The ignore template** (`templates/gitignore`). Ignores `.env`, `.last-runs/`, `runs/*.lock`, `runs/locks/`, `runs/unit-logs/`, the
  ledger, decisions and usage-calls files, and `runs/**/*.pre-redact` (which also matches a file directly in `runs/`). The line is tied
  to the default state directory ("move this line if planning.state_dir is changed"). It has no `abk.local.yaml` or `scrub.local`.
- **Loading** (`config.py`). `locate` (~906) finds the file; `load(path)` (~924) does `yaml.safe_load`, `WorkspaceConfig.model_validate`
  (strict, `extra="forbid"`) and three checks. `installation.py` `load_config` (~213) reloads settings from `<path.parent>/.env` first, so
  a runtime selected there is the one `load` checks. Providers: `from: literal | env-file | yaml | command` (`config.py` ~725-755); the
  `env-file` provider takes `file` (a path) and `key`, resolved by `installation._resolve` (~184) with the same dotenv reader
  (`verify._env_file`) that reads a repo's credentials. So a secret value can already come from an ignored `.env`; what cannot is the
  provider *itself*, whose `file` path is a committed home path, and the literal values and prose.
- **Where consumer facts sit in a typical file.** `verify.env` literals (an agent command, host ports and URLs of a consumer's live
  stack), `env-file` and `yaml` providers whose `file` is an absolute path under home, `deploy.live_written` and `deploy.ssh_key`
  paths, `repos.<name>.path` outside the checkout, `repos.<name>.relationships` and `description` prose naming other repos, owners and
  products, `consumes`. `abk init` writes `openspec/<redacted>`'s `context:` from `templates/openspec_context.md` (a `{repos}` list built
  from `description` and `relationships`, `init/scaffold.py` ~544), so the same prose is copied into a second tracked file.
- **Doctor** (`cli/doctor.py`). Checks are functions returning `Check` values built by `_ok/_info/_warn/_fail` (`_verify_env` ~545,
  `_gaps` ~701, `_ssh_keys` ~502); `_forge_access` (~235) already makes the one network call per owner. Skill `abk-config` and
  `docs/configuration.md` say machine-local values go in `.env` and everything about an installation in `abk.yaml`.
- **Origin of the planning repo.** `git remote get-url origin` is offline and returns the owner segment; forges expose the account of a
  repo through `forge.identity(repo)`, so owners are comparable without a network call. Whether the repo is public is a code-host fact.

## Decisions

### What the scrub terms are

One function, `scrub_terms.terms_for(installation, *, target=None) -> list[str]`, moved out of `cli/scrub.py` (which re-exports it, so the
command and the test names do not change). It is the **only** place the term set is defined. The set, in the order it is built:

1. **The planning root's directory name**, unless the root *is* `target` (resolved paths equal). Rationale: a checkout that is its own
   planning root names itself by its directory; a different root's name identifies the installation.
2. **Every repo except the target's own**: key, forge identity parts (account, project, name), checkout directory name. A repo whose
   `path` resolves to `target` stays skipped. Unchanged.
3. **Deploy facts**: `live_written` file names, the ssh key's file name, the first segment of each rule prefix, the argv words. Unchanged.
4. **`verify.env`**: the variable names (unchanged), plus the *literal* values (a `from: literal` value of 4 or more characters that is not
   all digits and not in `GENERIC`), and for `env-file` and `yaml` providers the first directory below the home directory of `file`,
   and the file's own name. Rationale: these are the agent command, ports and key files of a consumer, and they are the facts the
   plan names as leaking. Whole values are terms, not their words, so `localhost` alone is not.
5. **Home facts**: the user name of `Path.home()` (3 characters or more, not generic) and, for each configured path under home
   (`repos.*.path`, `deploy.ssh_key`, `deploy.live_written`, provider files, `planning.worktree_root`), its first directory below home
   when that directory is a dot-directory that is not on the leak test's tool allowance (`.claude .local .config .cache .ssh .volta`).
6. **The local list**, `scrub.local` in the planning root: one term per line, `#` starts a comment, blank lines ignored, the 3-character
   minimum and case-insensitivity as for every term; `GENERIC` words in it are **kept** (a person who writes one means it). A line
   starting with `!` removes a derived term, so a user name that collides with a common word can be allowed without editing code.
7. **Merged configuration.** All of 2 to 5 read the *merged* configuration (`abk.yaml` plus `abk.local.yaml`), so a fact moved into
   the overlay is still a term.

The companion `scrub_terms.scrub_text(text, terms, *, replacement="<redacted>") -> str` replaces each term, longest first,
case-insensitively, and returns the text unchanged when no term occurs. A second call on its own output finds nothing to change, so any
caller that scrubs is idempotent for free. `scan` stays in `cli/scrub.py` and takes the term list.

**How the planning split command reuses it.** `abk planning split --scrub` (a separate change) calls
`terms_for(source_installation, target=<destination checkout>)` to get the terms, and `scrub_text` over each moved file's text and each
moved unit's feedback, guidance and history notes. It adds no term of its own and keeps no second list. Because the destination is the
`target`, a term that is the destination's own name is not removed from what it receives. The split change needs `terms_for` and
`scrub_text` to exist with these signatures; it does not need `abk.local.yaml` or `abk scrub-store`.

Alternatives rejected: a committed deny list (would be the leak); terms from the leak test (it is term-free by design); learning terms
from `.env` (values are secrets, handled by redaction, and are not identities).

### Two local layers side by side: `.env` for values, `abk.local.yaml` for structure

**Decision.** There are two ignored, per-machine layers, independent of each other, and an installation may use either or both.

- **`.env`** holds single values one would write in `abk.yaml` but not commit (an agent command, local ports, a home variable and its
  path, a key). It is read by pydantic-settings as flat `ABK_` and credential names, and by `verify.env` entries of the form
  `{from: env-file, file: .env, key: NAME}`, which `installation._resolve` already reads with the dotenv reader (a relative `file` resolves
  from the config's directory, so the committed file carries no home path). It is where secrets and single values go.
- **`abk.local.yaml`** holds structured, user-specific configuration merged over `abk.yaml` at load: a second variant of a section, a
  per-user list, dual configurations of one tool for several people. (A specification of one such use, several accounts of an agent
  runtime in one planning repo, is handled outside this change.)
- **Where both could carry a fact**, the loader reads each for what it is: a `verify.env` entry's *value* comes from the file its
  provider names (`.env` for `from: env-file`), and the entry itself, as a mapping, comes from the merged configuration, so the overlay
  can add or replace the entry while `.env` holds the value. The settings layer (`ABK_` names) reads `.env` and the environment only, never
  the overlay. One layer can sometimes replace the other; neither is required.
- **The tracked `abk.yaml` of a public repo holds neither consumer facts nor user-specific values.** A planning repo that plans only itself
  lists no other repo in it, so no other repo's name, owner or path is in it, and no agent command is configured there; the command a
  test needs reaches it through `verify.env`.

The overlay's own design, as first specified and built by group 2:

A second file rather than only `.env`: `.env` cannot hold a mapping such as
`verify.env.<VAR>.from` or a multi-line `relationships`, and is already the home of secret *values*. A consumer value that is a secret
stays in `.env` and is named by an `env-file` provider whose `file` is in the overlay or is the planning root's own `.env` (a relative
`file` resolves from the config's directory, so the committed file can say `file: .env` and `key: <NAME>` with no home path; this is how
`from: env-file` is already resolved). Rule of thumb the docs state: a secret's value goes in `.env`; a fact about an installation
goes in `abk.local.yaml`; the committed `abk.yaml` holds only what any clone may know.

Merge rule (`config.merge_local(base, local)`): both parsed with `yaml.safe_load`; for a key in both, two mappings merge recursively, and
anything else is **replaced by the local value** (a list is replaced whole, a prose string is replaced whole). A key only in the local
file is added. A local value of `null` replaces to `null` (so a local file can switch a committed setting off). The merged mapping then
goes through the strict `WorkspaceConfig.model_validate`; a validation error names `abk.local.yaml` when the failing key path exists in
the local mapping and `abk.yaml` otherwise, so a person knows which file to open. The file's location is next to the file in force
(`<dir of abk.yaml>/abk.local.yaml`); `ABK_CONFIG_LOCAL` is **not** added (one location, nothing to forget). A missing file is the
normal case and costs nothing; an unreadable or non-mapping one is a `ConfigError`.

Writers never touch it: `abk policy apply`, `abk project init` and `abk init` edit the file in force only, and a `repos.<name>` entry
added by init goes to `abk.yaml` (a public checkout lists only itself there; the facts about other repos are the person's to put in the
overlay). `abk config --show` prints the merged document and, on stderr, `local: <keys>` listing the top-level keys the overlay set, so
nothing is hidden and nothing is printed that is secret (providers print as they do today, never values). `abk config --path` prints both
paths when the overlay exists.

Redaction: `redaction.sources` and `installation.verify_env` read `installation.config`, which is the merged configuration, so a value
from an overlay provider is redacted and resolved like any other with no change to them; the test pins that.

### The doctor check, exactly

A new check `public content` (a `warn`, never `fail`), run only when `abk.yaml` is tracked by git (`git ls-files --error-unmatch`
inside the planning root's repository; a planning repo that is not a git repository, or an untracked file, reports `ok: not tracked`).
It reads the **committed file's text itself** (`yaml.safe_load` of the file, not the loader), so it reads exactly what is committed. It warns, one line per finding with the key path and the fix, for:

1. a `repos.<name>.path` that resolves outside the git toplevel of the planning root (`.` and paths inside the checkout are fine);
2. any string value in the file that contains a home-directory path (`HOME_PATH` as the leak test spells it, plus the current user's
   actual home prefix, which catches the Linux and macOS home roots);
3. a repo whose forge account (`forge.identity`) differs from the account in the planning repo's `origin` URL (parsed offline; only the
   account segment is compared, case-insensitively), when `origin` exists; a repo with `path: .` is exempt (it is the checkout itself).

Whether the repository is public is **not** decided offline. The check treats a tracked `abk.yaml` as public by default and says "if this
repository is private, ignore this" in the fix text; where `_forge_access` already holds an answer for the origin's visibility the check
may soften the message to `info`, but this change does not add a network call (see UNVERIFIED). A second finding, separate: an
`abk.local.yaml` or `scrub.local` that exists and is tracked or not ignored (`git check-ignore`) warns with the line to add.

### The leak test's new scope

`SCANNED` gains `openspec` and the root files gain `abk.yaml` and `runs/units.json` (read when present). They are checked by the existing
term-free patterns (home paths, slugs, anecdotes), and one new test: a tracked `abk.yaml` has no `repos.<name>.path` outside the
checkout and no home path. The test suite's own fixtures and the openspec content of the repo itself must pass it, which is group 1's
exit condition (so it fails first on the real content until the content is scrubbed, then passes). `runs/` other than `units.json` is not
scanned: logs and ledgers are ignored.

**The overlay and the leak test (decided).** The overlay is ignored by design, so a leak test that read it would read a file that is not
part of the repository. The test therefore reads the committed `abk.yaml` always, and `abk.local.yaml` only when it is a leak: it
exists and git tracks it or does not ignore it. Then the test fails naming the file and also scans its text and repo paths with the same
checks. An ignored, untracked overlay is never read. Outside a git repository the overlay counts as not ignored. This lands as group 7,
because group 3 was built before the overlay was reinstated.

### The store pass: `abk scrub-store`

A new command rather than a flag on `redact-history`, which is labelled temporary and is about secret *values*. It rewrites **home-directory
paths only**: the Linux and macOS home roots followed by a user directory, and a tilde-slash prefix followed by a directory not on the tool allowance; each match is replaced by
`<home>/` (the neutral token the leak test's pattern does not match, so a second run finds nothing: idempotent). Other terms are **not**
rewritten in stored text: a repo name in a unit's feedback is the unit's own subject, and removing it would corrupt the record's meaning.
(Feedback that must lose terms is a human edit by the split command.)

Mechanism: a new `UnitStore.rewrite_text(self, fn) -> list[str]` guarded by `_exclusive`, which reads every record, applies `fn` to the
text fields `feedback`, `guidance`, `predecessor_note`, `stack_refusal`, `note` of each history entry and the `note` of `close_pending`
if it has one, rebuilds the records with `model_copy(update=...)`, writes **once** through `_write`, and returns the ids changed. It
never edits the file by hand, and it does not bump any timestamp. `--apply` needs the pipeline paused (`pause_in_force`, as
`redact-history`), copies `units.json` to `units.json.pre-redact` first (one copy, an existing copy is kept, not overwritten, so the
very first original survives a second run) and then calls the method. The dry run prints `<id> <field>: <n> path(s)` and the count,
never the text. The ignore template's line `runs/**/*.pre-redact` becomes `*.pre-redact`, so the copy is ignored whatever the state
directory, and `abk doctor` warns when a `*.pre-redact` file is not ignored.

### Group order inside the change

Groups are independent (no `Needs:` between them): group 1 is the term function, group 2 the overlay, group 3 the leak test and init,
group 4 doctor, group 5 the store pass and the ignore line, group 6 the docs, and group 7 adds the overlay back to what groups 3 and 4
built without it (the leak test, doctor, the init ignore line). `Needs:` is not written because the pipeline orders groups of one change
by number.

## Open decisions (recorded, not resolved here)

- **The commit trailer.** The tool's `AGENTS.md` says "Commits carry no `Co-Authored-By` trailer in this repo". A planning repo that is
  the same repository inherits that line, while the harness that writes planning commits adds a trailer by default. Either the line is
  relaxed for planning commits (for example "except commits that touch only planning paths") or the planning commits stop carrying the
  trailer. This change does not decide: it neither edits the line nor adds a check for trailers. A person decides, and the answer is a
  one-line edit of `AGENTS.md` plus, if relaxed, a path-scoped exception in whatever hook enforces it.
- **A public repo's own slug.** The rule says no owners or slugs; a self-hosted checkout's `abk.yaml` names its own repo (with its own
  owner) in a `repos` entry. This change treats the target's own entry as allowed (it is skipped by `terms_for` already) and says so in
  the rule's text (group 5), but whether that is the intended reading of "no GitHub owners" is the maintainer's to confirm.

## Not in this change

- Removing leaks already in git history (the history is a separate, optional rewrite).
- A network check of repository visibility in doctor.
- Scrubbing run logs, transcripts and the ledger (ignored files; `redact-history` covers secret values in them).
- Rewriting terms other than home paths in stored text.
- The split command itself.

## UNVERIFIED

- Whether the forge interface exposes a repository's visibility; the check assumes it does not offline and treats the file as public.
- That `git ls-files --error-unmatch` and `git check-ignore` behave identically across the git versions the tool supports in a bare
  worktree (a linked worktree of the planning repo); the builder checks with a fixture worktree.
- Whether the real `openspec/` content passes the extended leak test without a scrub pass: not run here (read-only); group 1's first
  test is expected to fail on current content and drives the scrub.
- The user-name term (5) may collide with a word used in the tool's own text; the `!` line is the escape, and the first scan of the real
  checkout shows whether it is needed.
- The sizes: each group is estimated at 250 to 340 raw lines (the planner scales by about 1.9 and refuses above 750 calibrated); groups
  1 and 3 are the likeliest to run over and may be split at their test and implementation seam.

- Group 7's code names (`LOCAL_IGNORES` in `init/scaffold.py`, `_local_files` in `cli/doctor.py`, `leaks`, `repo_path_leaks` and `files` in
  `tests/installation_leaks.py`, `overlay_path` and `OVERLAY_FILENAME` in `config.py`) are read from origin/main as merged groups 2 to 4; the
  builder re-reads them.
- That `git check-ignore` gives the same answer for the overlay inside a temporary fixture repository as in the real one (the doctor's
  `_is_ignored` already does the same for `scrub.local`).

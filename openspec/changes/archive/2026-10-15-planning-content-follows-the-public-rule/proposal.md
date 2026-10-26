# Proposal

## Why

The build tool's own rule (its `AGENTS.md`, "This repo never names an installation") is kept by two checks, and both assume the planning
repo is a different repository from the checkout they guard. When the planning repo is the build tool's checkout, that assumption fails in
four places.

- **`abk scrub-check` flags the checkout against itself.** `terms_for` always adds the planning root's directory name
  (`cli/scrub.py`, `found.add(installation.root.name)`), so scanning a checkout that is its own planning root reports every line that
  names the tool. A repo whose checkout is the target is already skipped, the root name is not.
- **The term list is only what `abk.yaml` knows.** The terms come from the repos, owners, deploy rules and `verify.env` names in
  the file. A fact that only a person knows (a product's config directory, a hostname, a user name) cannot be added without putting it in
  the committed file, which is the leak.
- **The structural test does not look at planning content.** `tests/test_no_installation_leaks.py` scans `src tests docs web` and three
  root files. `openspec/`, `abk.yaml` and the tracked unit store are not scanned, and they are where an installation's facts live.
- **`abk.yaml` holds consumer facts by design.** A typical file carries the agent command and host ports of a consumer's live stack as
  `verify.env` literals, home-directory paths in `verify.env` providers and `live_written`, and `relationships` prose naming other repos
  and owners. All of it is correct for an installation and forbidden in a public repo.
- **Stored text quotes home paths.** Unit feedback and history notes are text written by agents and reviewers; some quote paths under a
  person's home directory. The store redacts known secret values on the way in, but not paths, and the file is tracked.

## What changes

- **Scrub-check on its own root.** When the planning root is the target, the root's name is not a term. Terms are the repos' identities
  other than the target's, the facts of the merged configuration (including values from the local overlay), the home-directory facts
  (the user name and the first directory under home of each configured path) and the lines of a gitignored `scrub.local` file in the
  planning root. The derivation is one function, `terms_for`, with a companion `scrub_text`, so any command that must remove the same
  words reuses both.
- **The leak test reads planning content.** It also scans `openspec/`, `abk.yaml`, and the tracked unit store for home paths and slugs
  (the checks that need no terms), and fails a tracked `abk.yaml` that names a `repos.<name>.path` outside the checkout.
- **Single values live in `.env`.** A value one would write in `abk.yaml` but not commit (an agent command, local ports, a home variable
  and its path, a key read from the agent's configuration) is kept in the installation's ignored `.env` and named in `verify.env` by a
  `from: env-file` entry, which the loader already reads. A planning repo that plans only itself lists no other repo in its `abk.yaml`.
  `abk init` ignores `scrub.local` and says so in its output, the planning context template and `.env.example`; the docs and the skill
  give a worked example.
- **`abk.local.yaml`.** A second, gitignored file beside `abk.yaml`, merged over it at load: mappings merge key by key, any other value
  (a scalar, a list, a prose string) is replaced. Unknown keys still fail the strict schema, naming the file they came from. `abk config`
  prints the merged configuration and says which keys the local file set. `abk init` ignores the file and says what it is for: structured,
  user-specific configuration (a second variant of a section, a per-user list), beside `.env` for single values. The two are independent
  layers and may both be used.
- **Doctor warns before a leak is committed.** `abk doctor` reports a warning when `abk.yaml` is tracked by git and names a repo path
  outside the planning repo's checkout, a home-directory path anywhere, or a repo whose owner is not the owner of the planning repo's own
  `origin`. It reports when `abk.local.yaml`, `scrub.local` or a `*.pre-redact` copy is tracked or not ignored.
- **`abk scrub-store`.** A command (dry run by default, `--apply` with the pipeline paused) that rewrites home-directory paths in a stored
  unit's feedback, guidance and history notes through the store's own methods, keeps the original beside the file as a `.pre-redact`
  copy, and finds nothing on a second run. The packaged ignore list ignores `*.pre-redact` wherever the state directory is.

## Impact

- Capabilities: `scrub-check` (new), `public-leak-test` (new), `local-config-overlay` (new), `consumer-facts-in-env` (new),
  `public-config-doctor` (new), `stored-text-scrub` (new).
- Code: `cli/scrub.py` and a new `scrub_terms.py`, `config.py` (the overlay merge), `installation.py`, `cli/config_cmd.py`,
  `cli/doctor.py`, `cli/init.py` and `init/scaffold.py`, `pipeline/unit_store.py` (one exclusive rewrite method), a new
  `cli/scrub_store_cmd.py`, `templates/gitignore`, `templates/env.example`, `templates/openspec_context.md`, the leak test, and the
  docs and the `abk-config` skill.
- Behaviour that stays: an installation with no `abk.local.yaml` and no `scrub.local` loads and scrubs as today, except that the planning
  root name is skipped only when it is the target; the term derivation for every other target is unchanged except for the added home facts.
- Not in this change: moving content out of a planning repo (the split command is a separate change that reuses `terms_for` and
  `scrub_text`); removing history that already holds a leak; deciding whether planning commits may carry an agent trailer (recorded as
  an open decision in the design).

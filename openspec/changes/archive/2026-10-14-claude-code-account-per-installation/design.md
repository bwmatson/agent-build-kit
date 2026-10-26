# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `3398012f`). Paths are under
`src/agent_build_kit/`; line numbers are approximate to a few lines.

- **The setting** (`settings.py`). `claude_home: Path | None = Field(None, validation_alias=AliasChoices("CLAUDE_CONFIG_DIR",
  "ABK_CLAUDE_HOME"))` (~73-75), the model has `env_prefix="ABK_"`, `env_file=".env"`. `reload(env_file)` (~169) builds a fresh
  `Settings(_env_file=env_file)` and copies each field onto the module-level `settings`; `Installation.activate()` calls it with the
  installation's `.env`. `.env` is never exported to the process: a `claude` started by abk inherits only what the process had.
- **The precedence, run, not assumed.** A throwaway `Settings(_env_file=<temp .env>)` in memory, with the environment varied, gave:
  neither set, `None`; `.env` holding both names, the value of `CLAUDE_CONFIG_DIR` (the first alias, whatever the order of the lines);
  `.env` with one name, that one; a process variable beats the `.env` whichever name each uses (process `ABK_CLAUDE_HOME` beat `.env`
  `CLAUDE_CONFIG_DIR`); both names in the process, `CLAUDE_CONFIG_DIR`; the name matches regardless of case in the `.env`;
  `~/x` is kept as written (not expanded), `rel/x` is kept relative, and an **empty process variable gives `Path("")`, which is
  `.`** and hides the `.env`. The alias replaces the prefix: `ABK_CLAUDE_HOME` is the literal name, there is no `ABK_CLAUDE_CONFIG_DIR`.
  The spec states the first four and fixes the last three (expanded, absolute, empty is unset).
- **The sessions page** (`serve/sessions.py` ~24): `claude_home()` is `settings.claude_home or Path.home() / ".claude"`; its callers
  are `serve/chat.py` ~282 (`claude_holders`), ~553 (`claude_file`), ~883 (the listing) and ~973 (`claude_turn`, the resume). The
  resume builds an `AgentRequest` (~526) with `environment=self.agent_environment`, so it goes through the runtime, which is where the
  variable is added.
- **The runtime** (`runtimes/claude_code.py`). `spawn` (~107-120) merges `env` over `environment` or the process's own with
  `child_environment` (`runtimes/base.py` ~137-144); `_run` (~311-322) passes `request.env` only when non-empty and `request.environment`
  when given. `build_argv` (~221) adds no account flag. `refresh_login` (~171-193) calls `run(argv, capture_output..., timeout=120)`
  with no `env=`; `usage_guard.refresh_login` (~453) just calls it. `get_usage_status` (~389) reads `read_live_usage(refresh=refresh_login)`
  then `read_cached_usage`. `detect`, `check_policy` and `setup_questions` ask for no account; `requires` is `()`, so the setting
  cannot be a required field. The helpers that start a `claude` all go through `runtime.run` (planner `_ask` ~793, restack ~947,
  tracks ~602, chat ~526, the init steps through `init/claude_call.py`'s `through(run)`), so one seam in `_run` covers them.
- **The wiring** (`pipeline/wiring.py` ~348-361) sets `request.env` from the gateway source and `CONFIG_ENV`; the Claude Code runtime
  has `passes_env = False` (a gateway key is skipped) but `request.env` is still added to the child. The account is not part of this
  wiring: the runtime adds it itself, so a call that does not come through the wiring (`refresh_login`, init) gets it too.
- **The guard** (`pipeline/usage_guard.py`). Constants `CREDENTIALS_PATH = Path.home()/".claude"/".credentials.json"` and
  `DEFAULT_ANCHOR_PATH = Path.home()/".claude.json"` (~101-102). Readers: `read_oauth_token(path=None)` (~261, the
  `CLAUDE_CODE_OAUTH_TOKEN` variable first, then the file), `token_expired(path=None)` (~435), `read_cached_usage(path=None)`
  (~730, the `cachedUsageUtilization` block, source `claude.json`), `_fresh_claude_block` (~820, reads it only when
  `usage_claude_cache_minutes > 0`), its users `decide_start` (~1285), `held_usage` (~849) and `refreshed_usage` (~866), and the stale
  fallback in `current_usage` (~817) and `held_usage` (~853), which read it whatever `usage_claude_cache_minutes` says. `MAX_ANCHOR_AGE`
  (an hour, ~119) bounds a cached-file reading. The kept reading is `usage-cache.json` in the installation's state directory
  (`_cache_file` ~487): the endpoint's payload plus `fetched_at`, and a `cooldown_until` after a 429; `_load_cache` (~495) reads it,
  `_write_cache` (~503) writes it. The endpoint is called with the access token as the bearer (`USAGE_URL`), so a reading is that
  token's account's.
- **The record and the calibration.** `usage_calls.py`: `UsageCall` (~30) is one line of `usage-calls.jsonl`, written with
  `model_dump_json` (so a `None` field is written as `null`); `consecutive_readings` (~258) pairs good readings; `cache_interval` and
  `derive_rate` read the whole record. `usage_allowances.py`: `calibrated_allowances(calls, ledger, ...)` (~94) pairs readings with the
  ledger's spends; `refresh_allowances(state_dir, ...)` (~167) is called by the tick (`cli/pipeline.py` ~1013) and keeps
  `usage-allowances.json`.
- **Doctor, install-skills, init.** `cli/doctor.py` `_runtime` (~936-1038) checks the command resolves, `runtimes.candidates`,
  policy coverage and the policy check; there is no login check. `cli/init.py` `cmd_install_skills` (~819) writes `--user` to
  `Path.home()/".claude"/"skills"`. `templates/env.example` lists the machine-level variables as commented lines; `.env.example` is
  copied by the person (step 4 of `abk init`'s closing text).
- **The status line** (`cli/pipeline.py` `cmd_status` ~520-545): `usage: <line> (<source>, <age>m old)` or `usage: unknown`.
  `abk usage` has only the `replay` subcommand (`cli/usage_cmd.py`), which prints the allowances line from the record, so the account
  is named in `abk status` only.
- **The test seams.** `tests/usage_host.py` replaces the module constants `usage_guard.CREDENTIALS_PATH` and `DEFAULT_ANCHOR_PATH`
  (and sets `CLAUDE_CODE_OAUTH_TOKEN`) so no test reads a developer's files: they stay the default paths and the seam. `FakeClaude`
  in `tests/runtimes/claude_cli.py` records the `env` each call receives in `.envs`, so an added variable is observable at tier 1.
- **Claude Code itself** (installed 2.1.296, `--help` and a run against an empty directory, no credentials involved). `claude auth`
  has `login [--claudeai|--console|--email|--sso]`, `logout` and `status [--json|--text]`. `claude auth status --json` run with
  `CLAUDE_CONFIG_DIR` set to an empty directory exited 1 and printed an object with the keys `loggedIn` (false), `authMethod`,
  `apiProvider`, `analyticsDisabled`, `projectsDirectory` and `configDirectory`; the run created `<dir>/.claude.json` (and its lock)
  and not `~/.claude.json`, which confirms the global state file lives inside the directory when the variable is set. The default
  directory holds `.credentials.json` on this machine (Linux). The keys of a logged-in answer were not read: it would have been run
  against real credentials.

## Decisions

- **One setting, no abk.yaml key.** The account is a fact of the machine and the person, not of the workspace: a checked-in key would
  put one person's directory into a file others share, and the kit keeps installation facts out of tracked files. The `.env` is the
  place `Settings` already reads, gitignored, one per installation, and the timers read it (their process has no such variable).
  A schema test pins that no `claude_home`, `config_dir` or similar key exists in abk.yaml.
- **The rules are the settings layer's own.** Nothing here builds a second resolver for the order: `claude_account.home()` reads
  `settings.claude_home`. What it adds is the reading of the value (below) and `source()`, which asks the same two places in the same
  order (`os.environ`, then the `.env`, `CLAUDE_CONFIG_DIR` before `ABK_CLAUDE_HOME`) only to say which one supplied the value; a test
  asserts `source()` and `settings` agree for every combination, so they cannot drift.
- **A module of its own, not `Installation.claude_home()`.** The consumers are leaf modules that have no `Installation`
  (`usage_guard`, `runtimes/claude_code`, `serve/sessions`), and `config.active()`/`settings` is how they already reach the
  installation. `claude_account.py` (leaf: imports `settings` only) holds `home()`, `is_default()`, `source()`, `credentials_path()`,
  `state_file()`, `skills_dir()` and `account_key()`. `serve/sessions.py`'s `claude_home()` becomes a call to it.
- **What the value means.** A leading `~` is expanded; the path must then be absolute, else a `ConfigError` naming the value, the name
  and the source says to write an absolute path (a relative one would mean a different directory under each timer and shell); an empty
  value counts as not set, the default, and no lower source is consulted (the empty process variable above would otherwise be `.`); the directory need not exist
  yet, so the login command can create it. **Unset is the only default**: a value, even one equal to `~/.claude`, is an account to
  export, because whether Claude Code with the variable set to `~/.claude` keeps its global state in `~/.claude/.claude.json` or in
  `~/.claude.json` is UNVERIFIED (see below) and abk should read the file of the run it started.
- **The export is the runtime's, in `_run`.** `ClaudeCodeRuntime._run` adds `CLAUDE_CONFIG_DIR=<home>` to the `env` it passes (over
  `request.env`, over an inherited value), and `refresh_login` gets an `env=` with the same single entry. Putting it in `_run`
  rather than in the wiring covers every caller at once and no other runtime sees it (the ACP runtime has its own agent and account;
  the gateway pair is never used with this runtime). An inherited `CLAUDE_CONFIG_DIR` can only equal the setting (the process beats
  the `.env` and `CLAUDE_CONFIG_DIR` is the first name), except an empty one, which the setting reads as not set; so no "it
  differs" line is logged, and the export is what makes a `.env` value, or `ABK_CLAUDE_HOME` alone, reach the child at all.
- **The guard's default stays the constants.** With the setting unset every reader uses `CREDENTIALS_PATH` and
  `DEFAULT_ANCHOR_PATH` as today (so `usage_host` still works unchanged and the default account is byte-identical); with it set the
  readers take `<dir>/.credentials.json` and `<dir>/.claude.json`. The path argument each reader already takes stays, and wins.
  `CLAUDE_CODE_OAUTH_TOKEN` still comes first in `read_oauth_token`: a token in the environment names its own account whatever the
  directory, and doctor warns when both are set.
- **The kept reading says whose it is.** `usage-cache.json` gains `account` (the directory as `account_key()` writes it) only when an
  account is set; `_load_cache` returns an empty record when the entry's `account` differs from the current one (absent counts as
  the default account), so a reading, a cool-down and a fallback of another account are never used, and the next write replaces
  them. `usage-calls.jsonl` rows gain `account` (null for the default), and the calibration pairs only rows after the last row of
  a different account. The call record's cache-interval and refusal figures still read every row: whether the endpoint's rate limit
  is per account or per address is UNVERIFIED, and counting all calls is the safe side.
- **A stored session of another account is already handled.** A build session id is kept per unit with no account; resuming it under
  another directory makes `claude` answer that no conversation is found, which the node maps to `SessionUnavailable` and a new
  session (`graph/nodes.py` ~614-640). This change adds no stored field: it adds a test and names the account in the existing line.
- **Doctor asks the runtime.** `_runtime` stays runtime-neutral: an optional `account_report(run, env_file)` on the runtime
  (default: nothing) is where the Claude Code runtime reports; the check names Claude Code only inside the runtime. Login is
  `claude auth status --json` run with the account's variable, read for its exit status and the `loggedIn` key only; nothing else of
  its output is printed or logged.

## What was not verified (UNVERIFIED)

- **Where the credentials of a non-default directory are stored.** On this machine's default directory the file is
  `.credentials.json`; for a directory logged in with `claude auth login` it is expected at `<dir>/.credentials.json`, but no login
  was made. Other platforms may keep them in a keychain (then the guard finds no token and falls back to the state file, and doctor's
  login check, which asks Claude Code, is the truthful one).
- **The global state file with the variable set to the default directory.** The empty-directory run shows `<dir>/.claude.json`; what
  Claude Code does when the directory is `~/.claude` itself (the legacy `~/.claude.json` or `~/.claude/.claude.json`) was not run,
  to avoid touching the default account's files.
- **That `claude auth status` prints no secret.** The logged-out answer's keys are listed above and hold no token; a logged-in
  answer was not read. The spec does not depend on it: doctor reads the exit status and `loggedIn` and prints nothing else.
- **That limits are per account.** The usage endpoint is authenticated by the account's token, so a reading is that account's; the
  documentation does not say whether the plan's limits are per account or shared across accounts of one person or organisation.
  The spec relies only on the reading belonging to the token.
- **That the usage endpoint's own rate limit is per account.** See the call record above.
- **That an organisation policy still applies in every directory.** Claude Code's managed settings are outside the config
  directory; not tested.
- **The editor extension.** It reads the variable only from its own setting; the docs say so as a statement about the extension, not
  as something this change builds.

## Risks and sizing

- A group that moves the guard's readers touches the most-tested module; the default path is unchanged and `usage_host`'s seam is
  kept, so the existing tests stay green without edits and the new ones live in their own files.
- Groups are sized to the planner's limit (about 350 raw lines, scaled by about 1.9): six groups, tests first. Groups 1 and 2
  share no code beyond `claude_account.py`, which group 1 creates; group 2's tasks use it, so its unit stacks on group 1's by
  the change's own order and needs no `Needs:`.
- No `Needs:` on another change: the changes that edit `Installation`, `config.py` and doctor's configuration check do not edit
  the functions this one adds to or the runtime check; a clash is a rebase conflict, not a dependency.

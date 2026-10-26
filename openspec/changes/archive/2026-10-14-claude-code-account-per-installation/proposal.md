# Proposal

## Why

Work on one machine may belong on two Claude Code accounts: the pipeline of one installation on one, other work on another. Claude Code
keeps an account's login, sessions, history and settings in a config directory, chosen by `CLAUDE_CONFIG_DIR`. abk cannot use that today.

- **A `.env` value never reaches `claude`.** `Settings` loads the installation's `.env` into its own object and never exports it
  (`settings.py`), a spawned `claude` inherits the process environment alone (`runtimes/base.py` `child_environment`), and the timers'
  units set only `PATH` and `VOLTA_HOME`. An account named in `.env` therefore has no effect on any run.
- **Only the sessions page reads the setting.** `Settings.claude_home` (`CLAUDE_CONFIG_DIR` or `ABK_CLAUDE_HOME`) is read by
  `serve/sessions.py` alone, so the page lists one account's sessions while the `claude --resume` it runs uses another.
- **The usage guard reads the default account.** `usage_guard.py` fixes the credentials file at `~/.claude/.credentials.json` and the
  fallback reading at `~/.claude.json`. An installation on a second account would decide its starts on the default account's
  percentages, which an interactive session keeps fresh, and the `usage_claude_cache_minutes: 0` switch turns off only the fresh block,
  not the stale fallback.
- **`refresh_login` has no environment.** The one-token refresh call (`runtimes/claude_code.py`) runs `claude -p` with no `env=`.
- **Nothing says which account is in use.** `abk doctor` checks that `claude` is on the path and nothing about a login, and no command
  names the account.

## What changes

- **One setting, stated rules.** The account is the existing `claude_home` setting with its two names, `CLAUDE_CONFIG_DIR` and
  `ABK_CLAUDE_HOME`. The rules are the ones the settings layer already applies, written down and tested: the names are aliases of one
  value, the first listed wins inside one source, the process environment beats the installation's `.env`, and neither set is the default
  directory. No abk.yaml key is added and no new precedence is invented.
- **Every `claude` is told it.** When the setting is set, the Claude Code runtime adds `CLAUDE_CONFIG_DIR=<dir>` to the environment of
  every `claude` it starts (build, rework, review, planner, restack, tracks, chat and its resume, init research and `refresh_login`),
  over an inherited value. Unset, nothing is added.
- **The guard follows the account.** The credentials, the expiry check, the fallback reading and the fresh block are read from the
  account's directory and its global state file; with an account set the default account's `~/.claude.json` is never read. The kept
  reading records its account and a reading of another is discarded; the allowance calibration restarts on a change.
- **Said where a person looks.** `abk status` names the account in its usage line; `abk doctor` says which directory is used, which
  name and source supplied it, whether it exists and is logged in, and the exact login command when it is not; `abk install-skills --user`
  writes to the account; the `.env.example` template carries the commented line.
- **Docs.** The configuration and runtime guides, the `abk-config` skill and the changelog say where the account is set and why it is
  not in abk.yaml.

## Impact

- Capabilities: `claude-account` (new: the setting, the export to every `claude`, the sessions page, install-skills, doctor, the
  template, a stored session of another account) and `usage-account` (new: the guard's readers, the kept reading, the record and the
  calibration, the status line). Both are ADDED requirements: the existing usage-pause text names `~/.claude.json`, which stays true
  for the default account, so no existing requirement is restated.
- Code, in the kit: `settings.py` (unchanged field), a new `claude_account.py`, `runtimes/claude_code.py`, `serve/sessions.py` and
  `serve/chat.py`, `pipeline/usage_guard.py`, `usage_calls.py`, `usage_allowances.py`, `cli/pipeline.py` (status), `cli/init.py`,
  `cli/doctor.py`, the init template and the docs. The ACP runtime and the gateway pair are not touched.
- Configuration: no new abk.yaml key, so no migration. The extra record field `account` is optional on read.

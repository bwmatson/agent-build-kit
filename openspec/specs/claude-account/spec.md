# claude-account Specification

## Purpose
TBD - created by archiving change claude-code-account-per-installation. Update Purpose after archive.

## Requirements

### Requirement: The Claude Code account of an installation is one setting with two names

The account the pipeline runs Claude Code on SHALL be named by one setting, the account directory, which Claude Code calls its config
directory. It SHALL be readable under two names, `CLAUDE_CONFIG_DIR` and `ABK_CLAUDE_HOME`, which are aliases of one value, from the
process environment or from the installation's `.env`, and SHALL NOT be a key of abk.yaml. The rules SHALL be the settings layer's own,
stated and not re-implemented: within one source `CLAUDE_CONFIG_DIR` is read before `ABK_CLAUDE_HOME`; a value in the process
environment wins over one in the installation's `.env`, whichever names each uses; and with neither set the account is the default
directory `~/.claude`, with Claude Code's own global state file `~/.claude.json`.

#### Scenario: Either name in the installation's `.env`

- **GIVEN** an installation whose `.env` holds `ABK_CLAUDE_HOME=<dir>` and a process environment without either name
- **WHEN** the setting is read
- **THEN** the account directory is `<dir>`, and the same holds with `CLAUDE_CONFIG_DIR=<dir>` in the `.env` instead

#### Scenario: Both names in one source

- **GIVEN** a `.env` holding `ABK_CLAUDE_HOME=<a>` and `CLAUDE_CONFIG_DIR=<b>` in either order
- **WHEN** the setting is read
- **THEN** the account directory is `<b>`, and the same holds when both names are in the process environment

#### Scenario: The process environment beats the `.env`

- **GIVEN** `CLAUDE_CONFIG_DIR=<a>` in the `.env` and `ABK_CLAUDE_HOME=<b>` in the process environment
- **WHEN** the setting is read
- **THEN** the account directory is `<b>`, and a process `CLAUDE_CONFIG_DIR` also beats a `.env` `ABK_CLAUDE_HOME`

#### Scenario: Neither set

- **GIVEN** neither name in the process environment or the `.env`
- **WHEN** the setting is read
- **THEN** the account is the default directory `~/.claude`, and nothing below treats it as an account to export

#### Scenario: No abk.yaml key names the account

- **WHEN** the configuration schema is examined, and an abk.yaml that carries `claude_home` or `config_dir` under the root or under
  `runtimes.claude_code` is loaded
- **THEN** the schema has no such field and the load fails naming the unknown key

### Requirement: The value is a directory path that may not exist yet

The setting's value SHALL have a leading `~` expanded and SHALL then be an absolute path; a relative value SHALL be refused with a
message that names the value, the name it was read under and its source, and says to write an absolute path. The directory need not
exist, so that logging in can create it. An empty value SHALL be read as not set, the default, and no lower source SHALL be consulted
in its place. A person SHALL be able to learn which name and which source supplied the value (`CLAUDE_CONFIG_DIR` or
`ABK_CLAUDE_HOME`, in the process environment or in the installation's `.env`, or the default), and that answer SHALL agree with the
value the settings layer returns for every combination of names and sources.

#### Scenario: A home-relative value

- **GIVEN** `CLAUDE_CONFIG_DIR=~/<name>` in the `.env`
- **WHEN** the account directory is read
- **THEN** it is the person's home directory joined with `<name>`, absolute, whether or not it exists

#### Scenario: A relative value is refused

- **GIVEN** `ABK_CLAUDE_HOME=accounts/second` in the process environment
- **WHEN** the account directory is read
- **THEN** it is refused with a message naming `accounts/second`, `ABK_CLAUDE_HOME` and the process environment

#### Scenario: An empty value is the default

- **GIVEN** `CLAUDE_CONFIG_DIR=` empty in the process environment and `ABK_CLAUDE_HOME=<dir>` in the `.env`
- **WHEN** the account directory is read
- **THEN** it is the default directory, and the source reported is the default

#### Scenario: The source agrees with the value

- **GIVEN** each combination of the two names in the process environment, the `.env`, both and neither
- **WHEN** the source is asked for
- **THEN** it names the same name and place whose value the setting holds, and the default when the setting holds none

### Requirement: Every `claude` the pipeline starts runs in that account

When the setting is set, the Claude Code runtime SHALL add `CLAUDE_CONFIG_DIR=<account directory>` to the environment of every
`claude` process it starts: the build, rework and review runs, the planner, the restack resolver, the tracks, the chat page's turns and
their resume, the init steps' research and `refresh_login`. The variable SHALL override one inherited from the process. With the setting
unset nothing SHALL be added and the environment SHALL be what it was before this requirement. No other runtime, and not the gateway
pair, SHALL be given the variable. `refresh_login` SHALL carry it, so a login refreshed on behalf of an account is that account's.

#### Scenario: A build run gets the variable

- **GIVEN** the setting is `<dir>` and a fake `claude` that records the environment of each call
- **WHEN** a build run is made through the runtime
- **THEN** the call's environment holds `CLAUDE_CONFIG_DIR=<dir>`, and the gateway's per-run entries, when any, are still there

#### Scenario: Every kind of call gets it

- **GIVEN** the setting is `<dir>`
- **WHEN** a planner call, a restack resolution, a track phase, a chat turn that resumes a session and an init research call are each made
- **THEN** each call's environment holds `CLAUDE_CONFIG_DIR=<dir>`

#### Scenario: The login refresh gets it

- **GIVEN** the setting is `<dir>`
- **WHEN** `refresh_login` makes its call
- **THEN** the process it starts has `CLAUDE_CONFIG_DIR=<dir>` in its environment

#### Scenario: Unset adds nothing

- **GIVEN** the setting is not set
- **WHEN** each kind of call above is made
- **THEN** no call's added environment holds `CLAUDE_CONFIG_DIR`, and each call's arguments and environment are as before

#### Scenario: The setting wins over an inherited variable

- **GIVEN** the process environment holds `CLAUDE_CONFIG_DIR=<a>` and the setting reads `<a>`, and a fake `claude` run with an inherited whole environment
- **WHEN** a call is made
- **THEN** the call's environment holds `<a>` once, and a `.env` value reaches the call although the process has none

#### Scenario: Another runtime is not given it

- **GIVEN** the setting is `<dir>` and a call is made on a runtime that is not Claude Code
- **WHEN** the request's environment is built
- **THEN** it holds no `CLAUDE_CONFIG_DIR`

### Requirement: The sessions page and its resume use the same account

The chat page SHALL list, find, hold and resume Claude Code sessions in the account directory: the directory it lists
`<account directory>/projects` from SHALL be the one the `claude --resume` it runs is started in. A session of the default account
SHALL be neither listed nor resumed while another account is set.

#### Scenario: The listing follows the setting

- **GIVEN** sessions under `<dir>/projects` and others under the default directory, and the setting `<dir>`
- **WHEN** the sessions page is listed
- **THEN** only the sessions of `<dir>` appear

#### Scenario: The resume is in the account that was listed

- **GIVEN** the setting `<dir>` and a listed session
- **WHEN** a turn on that session is sent
- **THEN** the `claude` call has `--resume <id>` and `CLAUDE_CONFIG_DIR=<dir>`, and a session of the default account answers that it is not found

### Requirement: A session stored under another account is started afresh

A build session id the pipeline keeps for a unit is not tied to an account. When the account has changed since it was stored and
`claude` answers that no conversation is found, the node SHALL treat the session as unavailable and run from its start in a new
session, as it does for any session that cannot be continued, and its line SHALL name the account directory.

#### Scenario: Resuming after the account changed

- **GIVEN** a unit with a stored session id and a fake `claude` that answers "No conversation found" to its resume under `<dir>`
- **WHEN** the node resumes
- **THEN** the node runs again in a new session, the unit is not failed, and the line says the session cannot be continued and names `<dir>`

### Requirement: Skills for the user are installed in the account

`abk install-skills --user` SHALL write the skills to the `skills` directory of the account directory when the setting is set and to
`~/.claude/skills` when it is not. The installation's and the repos' own skills directories SHALL be unchanged.

#### Scenario: A set account

- **GIVEN** the setting `<dir>`
- **WHEN** `abk install-skills --user` runs
- **THEN** the skills are written under `<dir>/skills` and nothing is written under `~/.claude/skills`

#### Scenario: No account

- **GIVEN** the setting is not set
- **WHEN** `abk install-skills --user` runs
- **THEN** the skills are written under `~/.claude/skills` as before

### Requirement: `abk doctor` reports the account and whether it is logged in

`abk doctor`'s runtime check, on a runtime that has an account to report (Claude Code), SHALL print the account directory in use and
where it came from (the name, and the process environment or the installation's `.env`, or "default"); whether the directory exists;
and whether it is logged in, by asking Claude Code (`auth status`) with the account's variable and reading its exit status and its
`loggedIn` value alone. When the directory does not exist or is not logged in it SHALL be a failure that prints the exact command
`CLAUDE_CONFIG_DIR=<dir> <claude command> auth login`. No token or other field of the answer SHALL be printed or logged. When a
`CLAUDE_CODE_OAUTH_TOKEN` is also set and an account is set, doctor SHALL warn that the token names its own account, which the usage guard
reads whatever the directory. A runtime with no account to report SHALL add no line.

#### Scenario: A logged-in account

- **GIVEN** the setting `<dir>` from the installation's `.env` as `ABK_CLAUDE_HOME`, an existing directory, and a fake `claude auth status` that exits 0 with `loggedIn` true
- **WHEN** `abk doctor` runs
- **THEN** it prints `<dir>` with `ABK_CLAUDE_HOME` and `.env`, that the directory exists and that it is logged in, and nothing else of the answer

#### Scenario: Not logged in

- **GIVEN** the setting `<dir>` and a fake `claude auth status` that exits 1 with `loggedIn` false
- **WHEN** `abk doctor` runs
- **THEN** the check fails and prints `CLAUDE_CONFIG_DIR=<dir> claude auth login` with the configured command

#### Scenario: The directory is missing

- **GIVEN** the setting names a directory that does not exist
- **WHEN** `abk doctor` runs
- **THEN** it says the directory does not exist, prints the login command, and does not run `auth status`

#### Scenario: Default account

- **GIVEN** the setting is not set
- **WHEN** `abk doctor` runs
- **THEN** it says the default account `~/.claude` is in use, and the login question is asked without a variable

#### Scenario: A token in the environment

- **GIVEN** the setting `<dir>` and `CLAUDE_CODE_OAUTH_TOKEN` in the process environment
- **WHEN** `abk doctor` runs
- **THEN** it warns that the token's account is the one the usage guard reads, and the token's value appears nowhere in the output

#### Scenario: A runtime with no account

- **GIVEN** a runtime that reports no account
- **WHEN** `abk doctor` runs
- **THEN** its runtime check has no account line

### Requirement: The `.env.example` template shows the setting and `abk init` asks nothing about it

The init template `.env.example` SHALL carry a commented line `#ABK_CLAUDE_HOME=` with a sentence saying that it names the Claude Code
account of this installation, that `CLAUDE_CONFIG_DIR` is accepted in its place, and that unset means the default. The Claude Code
runtime's setup questions SHALL gain none, because the account is not an abk.yaml fact, and `requires` SHALL stay empty so an
installation that sets nothing is unchanged.

#### Scenario: The template line

- **WHEN** `abk init` writes `.env.example`
- **THEN** the file holds the commented `ABK_CLAUDE_HOME=` line and the name is one the setting reads

#### Scenario: Nothing is asked or required

- **WHEN** the Claude Code runtime's setup questions and required fields are listed
- **THEN** no question writes an account and `requires` is empty

# Running an installation on a second Claude Code account

A how-to for anyone running one installation on a Claude Code account other than the
machine's default.

## Why the account is a directory in `.env`

An account is a Claude Code config directory. Which one to use is specific to a user and
a machine, so it goes in the installation's `.env` (git-ignored) or the process
environment, never in a checked-in file: there is no abk.yaml key for it.

## The rules

- The setting has two names, `CLAUDE_CONFIG_DIR` and `ABK_CLAUDE_HOME`, aliases of one value.
- Within a place the first listed, `CLAUDE_CONFIG_DIR`, wins.
- The process environment beats the `.env`.
- An empty value means unset, and neither set means the default account.
- A relative path is refused; write an absolute one.

## Before you start

Have few units running. A stored build session of the old account starts fresh under the
new one.

## Create and log in the account once

```bash
CLAUDE_CONFIG_DIR=$HOME/.claude-second claude auth login
CLAUDE_CONFIG_DIR=$HOME/.claude-second claude auth status
```

Do not set an API key in that shell.

## Set it

In the installation's `.env`:

```
ABK_CLAUDE_HOME=$HOME/.claude-second
```

Write the absolute path your shell expands it to. Then set the usage windows for the new plan
under `runtimes.claude_code.limits` in abk.yaml.

## What you see

`abk doctor` prints the directory, which name and place supplied it, whether it exists and
whether it is logged in, and the exact login command when it is not. `abk status` names the
account its usage line belongs to.

## Things to know

- The timers read the `.env`; a shell that exports the variable overrides it for commands you
  run by hand.
- The editor extension has its own variable (an absolute path only); its default is
  unconfirmed.
- An organisation policy can restrict which accounts may be used.
- `CLAUDE_CODE_OAUTH_TOKEN` names its own account, which the usage guard reads whatever the
  directory; `abk doctor` warns about it.

## Rolling back

Remove the line from the `.env` and the installation returns to the default account.
Units in flight start fresh again.

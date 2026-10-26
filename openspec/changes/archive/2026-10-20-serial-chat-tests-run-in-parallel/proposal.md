# Proposal

## Why

`test-suite-speed/1` added a `serial` marker for "a test that needs exclusivity", and ten modules
under `tests/serve/` carry it: `test_chat_editing`, `_commit`, `_planning_commit`, `_sessions`,
`_guards`, `_attachments`, `_permissions`, `_agent_environment`, `_spec_context` and
`_free_session_edits`. They run after the parallel pass in one process, about a minute that the
eight workers cannot take.

The stated reason is that the chat server finds who holds a session by scanning the machine's process
table for the session id on a command line, and the tests start real processes with an id on their
command line. That is only a problem when two tests name the same id. Several do: one constant is
defined in four modules (two of them serial, two under `tests/cli/`), and others differ by one digit. The
marker hides the collision for the serial modules and leaves it live for the rest. Nothing pins why any
one module is serial, and the comment beside the serial pass still says no test is serial.

## What Changes

- **Every session id a test starts a process with is unique to that test**, from a fixture, not a
  module constant, so no two tests in any worker name the same id.
- **A test that needs a process list passes a private one** through the existing `proc` parameter,
  which the holder lookup on the chat object now accepts, instead of starting real processes on the
  machine. One live case keeps the real scan covered.
- **A guard test fails when two test modules (or a module and a test support module) define the same
  constant session id.**
- **The marker comes off each module that passes repeatedly in parallel**; one that still cannot share
  a process keeps it with a one-line reason. The serial pass of the whole-suite command stays only if a
  marker remains, and its stale comment is corrected.

## Impact

- agent-build-kit: ten test modules, the chat test support code, the holder lookup's signature on the
  chat object (a new optional argument, same default), the guard test, `pyproject.toml`. No behaviour
  change for a user.

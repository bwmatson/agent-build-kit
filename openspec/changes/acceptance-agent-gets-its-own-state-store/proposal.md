# Proposal

## Why

The tier-2 acceptance tests run the real agent as a descendant of pytest (pytest, then `abk tick` or `abk serve`,
then the agent). Some agents refuse to open their production session store when the process is in a test context:
an ancestor whose argv holds an element of basename `pytest`, or a test-context environment variable. The refusal
is swallowed with a debug log and the agent runs with no session store. Nothing is persisted, the agent's
`session/list` cannot list the session, and every step that resumes a session fails with `session <id> not resumed:
the agent does not list it` (a chat turn on a build session, the adopt and commit flows of `ui-chat-editing`), or
silently falls back to a fresh full prompt (session reuse in a build). A run outside a test process is unaffected.
`AcpRuntime` is correct; the tests' environment is what is wrong, and the failure shows only at the last step.
The cause and the experiments are in `docs/research/acp-sessions-and-resume.md` (the section "Cause found").

Setting the agent's guard bypass fixes the symptom but writes every test session into the person's real session
store, with a working directory under the test temp directory and nothing to remove it. The person prefers
isolation.

## What Changes

- **A scratch agent home for a test session.** One helper in the acceptance test support builds a fresh temporary
  directory, mode 0700, to be used as the agent's home, holding symbolic links to the few configuration and
  credential files the agent needs from the real home, and returns the environment entry that points the agent at
  it. The agent opens a store of its own there, the tests' sessions persist in it, and the real store gets
  nothing. It is configured by three variables set in the workspace's `verify.env`.
- **A precondition at the first agent step.** A test that later resumes a session asserts, right after the first
  agent step, that the recorded session id is listed by the agent for its working directory, and fails there with
  a message naming the likely cause.
- **A clearer refusal (optional, same group).** When `AcpRuntime._listed` answers no, the run log says how many
  sessions the agent listed for that directory and whether a process above it has `pytest` in its argv. The
  resume logic is unchanged.

## Impact

- Capability: `test-coverage` (added requirement).
- Code, in the agent-build-kit repository, test support only plus one logging line in `runtimes/acp.py`: a helper
  module under `tests/`, its use in the acceptance fixtures, a tier-1 test for it.
- No pipeline behaviour changes. Agents with no such guard are unaffected: with the home variable unset nothing
  differs.
- Operator: three `verify.env` entries in the workspace's `abk.yaml` (design.md).
- Not fixed here: the `claude_code` tab failure of the `abk-web-ui/11` acceptance test (design.md).

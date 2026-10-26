# Tasks

Acceptance: none — test support: the helper is proven in unit-test and exercised by the existing tier-2 acceptance tests it is wired into; nothing a consumer of the tool sees changes.

Priority: 1

## 1. [agent-build-kit] [unit-test] The acceptance agent gets a scratch home and the first step proves its session is listed

Done when the acceptance fixtures start the agent with a scratch home of its own, and a test that resumes a
session fails at the first agent step, naming the cause, when the session is not listed.

- [x] 1.1 Test: `tests/test_agent_home.py`. With the three variables set and a real home holding the listed
      files, the helper makes a directory with mode 0700 holding exactly one symbolic link per listed name, each
      pointing at the real file, and nothing else; `env` is exactly `{<HOME_VAR>: <that directory>}`.
- [x] 1.2 Test: the scratch home is never the real home: a real home that resolves to the scratch directory, or
      one that contains it, fails; a link never points inside the scratch home.
- [x] 1.3 Test: with `<redacted>` unset or empty the helper returns an empty `env`, creates no
      directory and reads nothing else.
- [x] 1.4 Test: a listed file missing from the real home fails the fixture, and the message names the file and the
      real home; a name that is a directory, has a separator, or looks like the state database (`state.db`,
      `state.db-wal`, `state.db-shm`) is refused; `..._HOME` or `..._HOME_FILES` unset while the variable is set
      fails naming the missing variable.
- [x] 1.5 Test: the logged line names the linked files and never a file's contents (a link target holding a
      marker string is not in the log).
- [x] 1.6 Test: with a fake agent that speaks the protocol and lists a given session, `assert_session_listed`
      passes; with one that lists none, or others, it fails with a message that names the session, the cwd, the
      absence of a session store and the three variables.
- [x] 1.7 Test: a fake agent command that prints its own home variable to a file shows, when started the way the
      acceptance fixtures start `abk tick`, that the scratch path reached the `abk tick` process and the agent
      below it, and that the same fixture with the variable unset passes the test's environment through
      unchanged.
- [x] 1.8 Test (optional, with 1.12): when `AcpRuntime._listed` answers no, the run log holds a line with the
      count of sessions the agent listed for that cwd and whether a `pytest` process is among the ancestors; the
      answer and the resume decision are unchanged.
- [x] 1.9 Add `tests/agent_home.py`: `AgentHome` (`Frozen`), `agent_home(...)` and `assert_session_listed(...)`,
      with the hazards and the fallback in the docstring. Confirm the places design.md marks UNVERIFIED (the
      helper's home, the agent's environment on the precondition's spawn) and correct the design where the code
      says otherwise.
- [x] 1.10 Use the helper in the acceptance fixtures: the `scratch` fixtures of `tests/integration/test_acp_build_unit.py`
      and `test_graph_acp_unit.py` (add `env` to the environment of `abk tick` and `abk report`), and
      `tests/scratch_stack.py` for the serve acceptance tests where it exists; apply it to `os.environ` for a
      module whose agent is started in the test process.
- [x] 1.11 Call `assert_session_listed` after the first agent step in each acceptance test that later resumes a
      session (the chat turn on a build session, the adopt and commit flows, session reuse).
- [x] 1.12 Optional: add the log line of design.md to `AcpRuntime._listed` in `src/agent_build_kit/runtimes/acp.py`,
      leaving its return value as it is.
- [x] 1.13 Document the three variables, the fallback and the hazards in `docs/agent-runtimes.md` (the acceptance
      paragraph beside `<redacted>`) and add a changelog entry.
- [x] 1.14 Run the integration tests that resume a session with the agent configured and the three entries set
      (`test_graph_acp_unit.py`, `test_acp_build_unit.py`), and report whether the resume steps now pass. Not
      runnable offline.

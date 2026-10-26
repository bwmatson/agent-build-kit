# Design

## What was checked, and what was not

Read in the code of the agent-build-kit repository at `main`:

- The acceptance fixtures that start the agent are the module-scoped `scratch` fixtures of
  `tests/integration/test_acp_build_unit.py` and `tests/integration/test_graph_acp_unit.py`. Each builds the
  `scratch` environment as `{**process_env(github_host, ...), "ABK_CONFIG": ..., "ABK_WORKTREE_ROOT": ...,
  "ABK_RUNTIME": "acp"}` and passes it as `env=` to the `abk tick` (and `abk report`) child processes. The agent
  command comes from `<redacted>` and is written under `runtimes.acp.command` in the scratch
  `abk.yaml`. `process_env` (`tests/forges/process_host.py`) copies the test's own `os.environ`, so a variable set
  in the pytest process also reaches `abk tick` and the agent.
- The two fixtures duplicate their setup; there is no shared acceptance module on `main`. `tests/factories.py`
  holds the scratch application and repository builders. `tests/scratch_stack.py` named in the brief is not on
  `main`; it is in the unit worktree of `abk-web-ui/11`, where `test_serve_over_scratch_installation.py` is.
- `Installation.verify_env` resolves the workspace's `verify.env` and the tier-2 session passes it as the
  environment of the tier-2 test command (`wiring.py`, `E2eSession(env=...)`), so a `verify.env` entry is an
  environment variable of the pytest process.
- `AcpRuntime` adds `request.env` on top of `os.environ` for the agent process (`_run`), and
  `AcpRuntime._listed` treats a `RequestError` or an absent id as "not listed". `can_resume_session` asks the
  agent through the same code. A run's agent record carries the session id.

UNVERIFIED, and for the builder to confirm: (1) the right place for the helper. This design puts it in a new
`tests/agent_home.py`, imported by every acceptance fixture; when `tests/scratch_stack.py` has landed by then,
the helper is called from it as well and the two `scratch` fixtures are made to use it, not duplicated. (2) That
`can_resume_session` and the code it calls start the agent with `os.environ` and nothing else, so the precondition
sees the scratch home when the test process's environment holds it (see below). (3) That the in-process UI server
tests, which start the agent through the runtime in the test process, take the home variable from the process
environment as the other tests do; if the serve app rebuilds the agent's environment, the entry is passed in the
call's `request.env` instead. (4) The research note's own UNVERIFIED items, carried over: that an agent with its
guard failing lists only the sessions of its own process (follows from the listing reading memory and the store),
and whether a long build step has persistence limits of its own (compression, archiving by housekeeping).

## The agent home helper

`tests/agent_home.py` has one function, `agent_home(tmp_path_factory)`, used from a module-scoped fixture, and a
model `AgentHome` (`Frozen`) with `path`, `linked` (the names linked) and `env` (the mapping to add).

It reads three variables from the process environment, which the workspace sets through `verify.env`:

- `<redacted>`: the name of the environment variable the agent reads for its home.
- `<redacted>`: the person's real home directory for the agent.
- `<redacted>`: a comma-separated list of file names to link from the real home into the
  scratch home. Names only, no path separators.

Behaviour:

- `..._HOME_VAR` unset or empty: the helper returns an `AgentHome` with an empty `env` and creates nothing. An
  agent with no such guard behaves as before.
- Set: `..._HOME` and `..._HOME_FILES` must be set too, or the fixture fails naming the missing variable. A
  fresh directory is made under pytest's temporary directory for the module, mode 0700. Each listed name becomes a
  symbolic link to the same name in the real home. Only files are linked: a name that is a directory is refused,
  and so is a name with a separator, and so is any name that looks like the agent's state database (a name
  containing `state` and ending `.db`, or `-wal`, `-shm`), since the point is that the scratch store is its own. A
  listed file missing from the real home fails the fixture with a message naming the file and the real home.
- The scratch home is never the real home: after resolving both, the helper asserts they differ and that the
  scratch directory is not inside the real home.
- `env` is `{<HOME_VAR>: <scratch path>}`. The fixtures add it to the environment passed to `abk tick`,
  `abk serve` and any other child that may start the agent. Because the tick child inherits the test process's
  environment through `process_env`, the helper also offers the same mapping to a `pytest.MonkeyPatch` context
  for the fixtures whose agent is started in the test process (below).
- The helper may log the names it linked and the scratch path, and never a file's contents.

Hazards, stated in the helper's docstring:

- The linked credential files can be rewritten by the agent through the link (a token refresh), as in ordinary
  use; the real files are what is updated.
- The scratch homes live under pytest's temporary directory and go with its retention; nothing else removes them.
- The scratch directory holds links to secrets: mode 0700, names logged and never contents.
- A file the agent needs and the list omits shows up as the agent failing to start or to reach its model; the
  fix is to add it to the list, not to link more than is needed.

The fixtures that start the agent in the test process (the in-process UI server tests, which reach the agent
through `AcpRuntime`) cannot be handed the entry through `abk tick`'s `env=`. They apply it with a
`pytest.MonkeyPatch` context for the module, so `os.environ` holds it for the agent the runtime starts and for the
precondition's own spawn. UNVERIFIED as stated above.

### Fallback

For an agent whose home cannot be relocated (it takes no home variable), the guard's own bypass variable set in
the test environment is the fallback, with its cost documented where the helper is: the tests' sessions then
land in the person's real session store, with a working directory under the test temporary directory, and are
never removed. Leaving `..._HOME_VAR` unset and setting the bypass in the same `verify.env` is how an installation
chooses it. The helper does not set it.

## The precondition

`assert_session_listed(runtime, session_id, cwd)` in the same module asks the agent, through the same code a
resume uses (`AcpRuntime.can_resume_session`, which reaches `AcpRuntime._listed`), whether it lists `session_id`
for `cwd`. A test that later resumes a session calls it after the first agent step it ran (the planner or build
step whose session the next step resumes; the session id is the one recorded in the run's agent record). When the
answer is no it fails there with a message that says:

> the agent does not list session <id> for <cwd> after its first step: it probably has no session store, because
> its test guard refuses its production store below a pytest process. Check that
> <redacted>, <redacted> and <redacted> are set in
> `verify.env`.

so the failure is at step 1, and not at the last step. The check is skipped nowhere: a test that resumes a
session and does not call it is a test that can pass by falling back to a fresh prompt, which the research note
names as hiding the problem.

## The clearer refusal (optional)

When `AcpRuntime._listed` returns False it logs, once per call and in the run log's notice channel, the number of
sessions the agent listed for that directory and whether a process in its ancestry has `pytest` in its argv
(`psutil`-free: read `/proc/<pid>/cmdline` up the parent chain, and say "unknown" where `/proc` is absent). The
return value and every resume decision stay as they are. A tier-1 test pins the line with a fake agent that lists
none and one that lists others.

## Operator note: the `abk.yaml` change

The installation that runs the acceptance tests adds three entries under `verify.env`, as it has for
`<redacted>`:

```yaml
verify:
  env:
    <redacted>:
      from: literal
      value: AGENT_HOME          # EXAMPLE ONLY: the name of the variable your agent reads for its home
    <redacted>:
      from: literal
      value: <home>/.agent            # EXAMPLE ONLY: the person's real home for that agent
    <redacted>:
      from: literal
      value: <redacted>   # EXAMPLE ONLY: the configuration and credential files it needs
```

`~` in the home value is expanded by the helper. This change does not edit any `abk.yaml`; the installation does,
when it adopts the change.

## Not fixed here

The `abk-web-ui/11` acceptance test fails one step after the resume, at its `claude_code` tab, with `RUN_ERROR a
test tried to spawn a real agent process — inject execute=`. That is a spawn guard in the serve app meeting a test
that does not inject `execute=`, a separate test-side problem. This change does not touch it; the resume step
before it is what this change makes pass.

## Decisions

- **Scratch home over bypass.** The person prefers isolation; the bypass writes into the real store. The scratch
  home was tried below a pytest ancestor: the agent answers, the session is persisted in the scratch store, and
  the real store gets nothing.
- **Links to files, never directories or the store.** Directories would carry state in; the store is the thing
  being isolated.
- **Agent-neutral.** The framework text names no agent product; the three variables are the whole interface.
- **Acceptance opt-out.** This is test support; the existing tier-2 tests it is wired into are what exercises it
  against a real agent, and they are the acceptance group of the changes they belong to. A tier-1 test proves the
  helper itself.

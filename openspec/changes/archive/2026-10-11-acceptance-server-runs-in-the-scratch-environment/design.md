# Design

## What was checked, and what was not

Read in the agent-build-kit checkout at `main` (556c728), and, read-only, the two unit worktrees
(`spec_abk_web_ui_11`, `spec_ui_chat_editing_5`) for what their tests need. Paths are under `src/agent_build_kit/`.

- `serve/server.py`: `start_server(installation, *, port=0)` returns `RunningServer(create_app(installation), port)`;
  `create_app` builds the app and calls `register_chat(app, installation, ...)`. `cli/serve_cmd.py` calls
  `start_server(inst, port=...)`. The fixtures of both unit worktrees call `start_server(scratch.installation)` and,
  for `abk-web-ui/11`, after `installation.activate()`; neither passes an environment.
- `serve/chat.py`: `Chat.request(...)` is the one place a turn's `AgentRequest` is built (`prompt`, `cwd`, `model`,
  `resume_session`, `fork_session`, `policy`, callbacks); it sets no `env`. Turns, new sessions and continued sessions
  call `runtimes.get(...).run(chat.request(...))`. `resumable(session)` asks
  `runtimes.get(ACP).can_resume_session(session, cwd)`.
- `runtimes/acp.py`: `_drive` starts the agent with `env={**os.environ, **request.env} if request.env else None`.
  `can_resume_session` -> `_declares_loading` starts the agent with no `env` argument at all, so it always takes the
  process environment. `_listed` answers no on a `RequestError`, which is the message the chat shows.
- `runtimes/claude_code.py`: `_run` passes `env=request.env` only when set to `execute` (default `spawn`), which merges it
  over `os.environ` and runs `claude_stream.stream_run`, which starts the process with `subprocess.Popen`.
- `tests/conftest.py`: the autouse guards. `no_real_agent` replaces `claude_code.spawn` with a refusal;
  `no_direct_claude` replaces `subprocess.Popen` with a subclass that refuses a program whose basename is `claude`;
  `no_real_login_refresh` and `no_real_usage_reading` replace the adapter's refresh and usage readers; `no_real_gh`,
  `no_real_github` and `no_real_forge_host` keep `gh` and the code host off the network. `local_stack` is registered in
  `pyproject.toml` and excluded by default.
- `pipeline/wiring.py` `Tier2Gate`: per project it runs each of the toolchain's tier 2 commands under `stack_lock`, parses
  the summary, appends `$ command\n<out>` to `outputs` for a failing command (and the last 1500 characters of a passing
  one), and builds `Tier2Result(output=output[-4000:])`; the repo's own dev stack path (`_run_on_dev_stack`) does the same
  with the script's output. `profiles/python_uv.py` `tier2_commands` is `uv run [...] pytest -m <marker> -v` per member.
  `pipeline/run_log.py` names a unit's file `<change>-<nn>-<stamp>-...`, keeps `RUNS_KEPT` per unit (`_prune`) and removes
  a change's files on archive (`remove_change_logs`).

UNVERIFIED, for the builder to confirm and correct here: the exact constructor of `Tier2Gate` (whether it knows its unit
and the state directory, which the file's name and place need); where `abk status` and the unit's run log mention a tier 2
result; whether `-vv` is what stops pytest cutting a short-summary line to the terminal width in the pinned pytest, and
whether the output of a command that is not a tty is cut at all; and that the Claude runtime's real path reaches
`subprocess.Popen` only through `stream_run` (the guard section depends on it).

## 1. The environment of the agents the server starts

### Recommendation

`start_server(installation, *, port=0, agent_environment=None)` and `create_app(installation, ..., agent_environment=None)`
take a mapping of text to text. It is stored on `Chat` and put on every `AgentRequest` the chat builds, in a new field,
`AgentRequest.environment: dict[str, str] | None = None`.

The semantics of the field are those of a whole environment: when it is given, the agent process is started with exactly
that mapping (plus `request.env`, which keeps meaning "added on top", as the gateway key needs); when it is `None`, the
runtimes behave as today, `os.environ` plus `request.env`. The alternative, an overlay on `os.environ`, was rejected
because the failure it is meant to fix is the agent inheriting the test process: pytest sets `PYTEST_CURRENT_TEST` in that
process, and an agent that refuses its own session store in a test context reads exactly such a variable. An overlay
cannot remove one. The scratch environment of the acceptance tests (`process_env(...)` plus the agent home and
`ABK_RUNTIME`) is already a complete copy, so replacing loses nothing there. A caller that wants an overlay passes
`{**os.environ, **extra}`. The cost is that a mapping without `PATH` starts nothing; the docstring says so.

### Where it takes effect

1. `AcpRuntime._drive` builds the child environment as `request.environment` when it is not `None`, else `os.environ`,
   then adds `request.env`. When neither is given it still passes `env=None`, as now.
2. `AcpRuntime.can_resume_session(session_id, cwd, *, environment=None)` and `_declares_loading` start the agent in that
   environment. The cache key of a yes (`(*command, session_id, cwd)`) gains it, since a yes in one environment says nothing
   of another. `serve/chat.py`'s `resumable` passes the server's.
3. `ClaudeCodeRuntime._run` passes `environment` to `execute` the way it passes `env`, only when set, so an injected
   `execute` written before it does not need the argument. `spawn(argv, *, cwd, on_event, env, environment)` merges as
   in 1.
4. `Chat.request` sets `environment=self.agent_environment`. Every chat path (a turn on a build session, a free session,
   a continued or forked one, the attach and commit flows) goes through it, so none is missed; a test asserts the request
   a turn builds carries it, and another that no `AgentRequest(` is built in `serve/` outside `Chat.request`.
5. `abk serve` (`cli/serve_cmd.py`) passes nothing, so a person's server is unchanged. The pipeline's own agent calls (the
   graph nodes) are untouched: they run in the `abk tick` process, whose environment the test already sets.

Reading the session lists (`/api/sessions`) does not start an agent for Claude sessions and is not changed.

### Why not set `os.environ` in the test

The acceptance tests could patch `os.environ` instead (the state-store change gives `AgentHome.apply(patch)` for exactly
that), and `abk-web-ui/11` already does for its module. It stays correct but leaks into everything else in the test
process (the fake host, the `abk` children built from `os.environ` copies, a second server in the same module) and
cannot remove a variable the process already has without also removing it from the test. An explicit argument is the
smaller blast radius and is visible in the call. Both remain available; this change adds the argument and does not
remove the helper.

## 2. A tier 2 test may start a real agent

The decision per guard, for a test marked `local_stack` (the marker on the test, its class or its module):

| Guard | For a `local_stack` test | Why |
|---|---|---|
| `no_real_agent` (`claude_code.spawn`) | not applied | The marker means the test uses a real agent. |
| `no_direct_claude` (`subprocess.Popen` refusing `claude`) | not applied | The real Claude runtime starts `claude` through `subprocess.Popen`, so lifting `no_real_agent` alone changes nothing: the next guard refuses the same process. The guard's job (finding a call site that bypasses the runtime) is done by every test that is not tier 2. |
| `no_real_login_refresh` | applied | Refreshing the login is a write to the person's own credentials, and no acceptance test has needed it; a run that does gets the guard's message naming it and a test may inject `refresh=`. |
| `no_real_usage_reading` | applied | It reads the person's live usage endpoint with their token; a tier 2 test injects readers or avoids the adapter's default, as it does for a limit. |
| `no_real_gh`, `no_real_github`, `no_real_forge_host` | applied | The scratch code host is the fake one; reaching GitHub is never what a test means. |

The two lifted guards keep their code. Each reads `request.node.get_closest_marker("local_stack")` through the `request`
fixture and returns without patching when it is set. Tier 1 (unmarked) tests are exactly as before. A marked test that
needs a refresh or a usage reading and finds the guard in the way fails with the guard's own message, which says what to
inject; it does not pass silently. UNVERIFIED: that no `local_stack` test of the two units reaches the refresh or the
usage readers on `main`'s code path; if one does, the table's decision for that guard is revisited in the rework of the
unit, not by lifting it here.

**A real agent call in a `local_stack` test is expected to be recorded and replayed.** Lifting the two guards lets a tier
2 test start the agent with whatever arguments it is given, including a set not seen before. That is accepted, on the
condition the change `tier2-replays-unchanged-calls` provides: a call with new arguments goes to the real endpoint and is
recorded, and the same call seen again is answered from the recording. That change's reverse proxy covers the Claude
runtime if the agent honours a base-URL override, which its design marks UNVERIFIED. Until it is built, such a call is a
real, unrecorded one. This change does not depend on it (no `Needs:` line) and does not build any recording.

The guard test uses `pytester` with a conftest that imports the real fixtures (`from tests.conftest import no_real_agent,
no_direct_claude`) and a registered `local_stack` marker, runs an unmarked and a marked test, and asserts the first is
refused with the guard's message and the second reaches a harmless argv (`sys.executable`) through the original
`spawn`, bound before the patch.

## 3. A failed tier 2 run keeps its first errors

### What is kept now, and the gap

For a failing command the gate keeps its whole output in `outputs`, then cuts the joined text to its last 4000 characters.
A run whose module fixture fails for several tests prints the first traceback early and four short ones after it, and
the tail holds only the end. The result and the feedback saved on the unit are made from that tail.

### The command

The profile hook builds the flags, so nothing outside `profiles/` names a pytest flag. The python profile adds
`-rfE --tb=short` to the tier 2 command (`-rfE`: a `FAILED`/`ERROR` line for each failed or errored test in the short
summary; `--tb=short`: one short traceback each). It adds nothing else, so the flag set `tier2-time-is-recorded-per-test`
adds (`--durations=0 --durations-min=1.0`) and this one sit beside each other in the same list; tests of both assert that
their own flags are present, not the whole argv, so whichever change merges second needs no edit to the first's tests. The
node profile gives no flags (its tier 2 hook is still a todo).

A second hook, `parse_test_failures(output) -> list[TestFailure]`, with `TestFailure(test: str, line: str)`, reads the
short summary: `FAILED <id> - <exception line>` and `ERROR <id> - <exception line>`. The default returns an empty list;
an output with no such lines gives an empty list, never an error. A line is capped at 500 characters with a visible
ellipsis, as a guard against one runaway message; the whole line is in the file. If the pinned pytest cuts the summary
line to the terminal width, the profile adds the flag that stops it (UNVERIFIED which, see above).

### The full output file

For each unit's tier 2 run the gate appends the full output of every command to
`<state_dir>/tier2-output/<change>-<nn>-<YYYYmmdd-HHMMSS>-<run>.log`, naming the unit and the time as run logs do, after
each command and not once at the end, so a run that is killed or hits the limit leaves what it had. Passing commands'
output is written whole too (the 1500-character tail rule is for the posted text, not the file). The name of the file
is kept on `Tier2Result.output_file` (default empty, so an older stored result loads) and:

- the result text, in its fixed part, says `Full output: <path>` (a path on the machine that ran the tier);
- the unit's run log gets one line with the path, and `abk status` shows it for a unit whose last result was a tier 2
  failure (UNVERIFIED where the unit's note is composed; the builder adds it beside it);
- the directory is pruned as run logs are: `RUNS_KEPT` files per unit and a change's files removed when it is archived.
  The code is `run_log`'s `_unit_logs`/`_prune`/`remove_change_logs`, parameterised by directory, not a second copy; the
  prefix match that stops a change whose name begins with another's from being pruned is the same.

The dev-stack path writes its script's output the same way.

### The failure listing, and truncation

`build_snapshot` writes, in the same fixed part above the `<details>` block as the other headline lines:

```
- **Failed:** 4 of 6 tests
  - `tests/integration/test_acp_build_unit.py::test_x` - FileNotFoundError: ...
  - ...
- **Full output:** `<path>`
```

every failed or errored test, in the order pytest printed them, never a "top N". It sits outside `output`, so
`pr_body._verification_section`'s shrinking (`_output_parts`, `_OUTPUT_CUT`), which cuts the output from the head, never
touches it; the existing 4000-character tail stays as the text of `<details>`. The saved `feedback` and the rework
prompt are made from the result text, so they carry the listing too: a rework agent sees the first line of every failure
even when the tail does not.

When a module-scoped fixture error fails many tests with the same line, each test is still one entry: the reader wants
to see the count, and the lines are short. (Grouping them would be an improvement the next change can make; not now.)

### Redaction

The file and the result text are text that leaves a run, so they pass through the redaction function that
`secrets-never-reach-stored-or-posted-output` specifies (`[redacted:<NAME>]` over the known values, applied before text is
cut). That change names the tier 2 result text and not a file the pipeline did not yet write; this change adds the file
to it and uses the same function, not a second one. The listing's lines are redacted before they are cut to 500
characters. If redaction fails, the file holds the one-line withheld notice that change defines, and the result says
the output is withheld. This is why groups 3 and 4 each carry a `Needs:` line for that change's group 1: there is no function to
call before it merges. The redaction is applied to each command's output as a whole before it is appended, so a secret
cannot be split across two writes.

### How this fits `tier2-time-is-recorded-per-test`

Neither change parses the other's output. The time change reads the `slowest durations` section through its hook,
`parse_test_durations`; this one reads the short summary through `parse_test_failures`. The result text then holds, in
this order, in the fixed part above `<details>`: the result line, the failure listing and the full-output path (this
change), the durations listing (the time change), then the cut output. Each change adds a block with its own heading
and its own test of survival under a small description, and neither reads the other's block; the builder of the one
that merges second puts its block next to the first's and runs both tests. No `Needs:` line joins them: each is correct
alone, and the only shared place is the order of two blocks in a text. A third value that the time change adds,
`Tier2Result.durations`, and `output_file` here are separate defaulted fields.

### Cause of the four full-run failures

Not decided here. The change's job is to make the next full run show the first error of each of
`test_the_unit_is_built_reviewed_and_pushed_through_the_runtime`,
`test_the_pipeline_alone_pushed_and_only_what_review_approved`,
`test_a_forbidden_command_is_refused_and_the_refusal_names_its_layer` and
`test_the_report_has_one_agent_record_per_call_in_the_run_log`. Acceptance for the units that depend on it, in their own
tier 2 runs, is that these four pass in a full run (run alone by hand, all six tests of the file pass in 8m52s, 528 s of
it the module fixture's build). If they fail again, the listing and the file say why, and the follow-up is a change
that knows the cause.

## Tests, and no tier 2

Every scenario is decided in tier 1: a fake agent command that writes its environment to a file (the state-store
change's tests already run one), `pytester` for the guards, recorded pytest output for the parser and a fake runner for
the gate. The proof that the server's agent now lists the build session is the two units' own tier 2 runs.

## Not included

A cause for the full-run failures; grouping equal failure lines; shipping the file anywhere beyond the machine; a setting
for the number of files kept (it is `RUNS_KEPT`); and changes to the units' test files and `tests/scratch_stack.py`.

# Design

## What was checked (origin/main, paths under `src/agent_build_kit/`)

- Every agent call goes through `AgentRuntime.run(AgentRequest)`; the only place a prompt becomes an argv element is
  `runtimes/claude_code.py` `build_argv` (`[*command(), "-p", request.prompt]`). Callers found: the planner (`pipeline/planner.py` `_ask`), restack
  (`pipeline/restack.py`), the wiring nodes (`pipeline/wiring.py`), tracks (`tracks/runner.py`), `init/propose.py`, `init/research.py` and the chat
  server (`serve/chat.py`). All reach `build_argv`. `runtimes/acp.py` sends `session/prompt` as a JSON-RPC message over the agent's stdin and is
  not bound by the argument limit. `refresh_login` and the doctor's check use fixed prompts of a few words.
- `spawn` runs `subprocess.run(argv, capture_output=True, text=True)` or, with a progress callback, `claude_stream.stream_run`, whose `Popen` gives the
  child no stdin of its own; both need an input for the prompt.
- `claude --help` lists `Usage: claude [options] [command] [prompt]`; run as `echo ... | claude -p --model haiku` it read the prompt from standard
  input and answered. A wrapper set as `runtimes.claude_code.command` therefore has to pass its standard input on to `claude`.
- Failure handling: `plan_all` in `cli/pipeline.py` catches every exception of a planning attempt, records `attempts + 1` and the first line of
  the error (at most 300 characters, the type name prefixed unless the error is a `PlannerError`), and prints `failing n/3: <reason>` in
  `abk replan`; at the maximum it gives up until `tasks.md` changes or `abk replan` is run. The oversize failure uses that path as it is.
- The planner uses its in-flight list in two ways: `_mark_built` reads the started units of the change being planned to mark groups
  `(built by <unit id>)`, and the prompt asks the model to place work after in-flight units and to join into unstarted ones. The code that
  checks a plan (`known`, joins, cycles) reads the store, not the prompt, and `Needs:` lines become edges in code. A merged unit of another
  change is therefore never read from the prompt.

## Decisions

- **Standard input, not a file.** It needs no temporary file to create, protect (a prompt can hold a diff of private code) or remove, and no
  agent-side read permission. A file would need `Read` allowed for a planner call that has no tools.
- **One place.** A `PromptTransport` string enum (`argument`, `stdin`, `protocol`) is declared on the runtime; one function in `runtimes/base.py`
  checks a request's prompt against the declared transport's safe size and returns the bytes to deliver. `build_argv` no longer contains the
  prompt; `spawn` gives the child that text as standard input.
- **Sizes in bytes of UTF-8**, which is what the kernel counts.
- **The planner's omission is by state and change**, not by age or count: merged and satisfied units of other changes only. Planned units of other
  changes stay, because the planner joins into them. They are about 33 KB today; if they alone ever pass the safe size, the named-parts failure
  says so and a later change can bound them.
- **A deterministic failure still counts attempts.** The prompt is rebuilt each attempt and the store changes, so the same size is not
  guaranteed; the usual `failing n/3` and `abk replan` apply and nothing new is written.
- UNVERIFIED, confirm in group 1: that the ACP runtime's write of the prompt has no limit below the safe size (its `LINE_LIMIT` bounds reading the
  agent's output).

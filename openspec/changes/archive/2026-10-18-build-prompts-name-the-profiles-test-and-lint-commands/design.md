# Design

## Verified on origin/main

- `wiring.allowed_tools(profile, forge, projects)` (~264-270) is the one composition of the tool list: base tools, forge read
  commands, then each distinct `allowed_tools` of the repo profile and of every project profile.
- The profile protocol (`profiles/base.py` ~82-157) has `allowed_tools` and `prompt_words` but nothing that names a runner for
  an agent. `prompt_words` is not read by `stack_runner.py`; the prompts hard-code "linting, formatting, types and the tests".
- Full prompts that tell an agent to run tests or lint, in `pipeline/stack_runner.py`: `TESTS_PROMPT` (~198), `REVIEW_FEEDBACK_PROMPT`
  (~274), `CHECKS_PROMPT` (~302), `REWORK_PROMPT` (~634), `IMPLEMENTATION_PROMPT` (~657), `ADAPT_PROMPT` (~753, a plain string,
  not a `PromptTemplate`). They are filled in `graph/nodes.py` at ~1045, ~1215, ~1239, ~1372, ~1529, ~1570-1579, the way
  `changelog_note(tree, r.repo_config)` already is. The continuations (`IMPLEMENTATION_CONTINUATION`, `CHECKS_CONTINUATION`,
  `REVIEW_FEEDBACK_CONTINUATION`, `REWORK_CONTINUATION`, `ADAPT_CONTINUATION`) go to a session that holds the full prompt, and
  `session-reuse` says a continuation drops context the session already holds; they stay as they are. `COMMIT_FIX_PROMPT`
  (`wiring.py` ~733) names no command to run and `RESOLVE_PROMPT` runs under a narrower tool list; both stay.
- The matcher the harness semantics need already exists: `runtimes/acp.py` `allows(tool_list, command)` (~393) built from
  `_tokens`, `_command_patterns`, `_matches` and `SHELL_OPERATORS` (~342-390): `*` stands for anything, the pattern covers
  the whole line, and a line that chains another command (`;`, `&`, `|`, a backtick, `$(`, `>`, `<`, a newline) is not
  allowed. That is why `ruff ... ; echo $?` and `python -m pytest` fail it. But `acp.py` imports the protocol library at the
  top and the library is an optional extra, so config load cannot import it.
- The pipeline's own checks are different commands (`lint_command`, `test_commands` run by the pipeline, not the agent), and
  stay untouched.

## The hint

`AgentCommand` (a `Frozen` model in `config.py`, since profiles import config and not the reverse):

- `purpose`: `StrEnum` `test | lint | format | check` (`check` is lint, format and types together).
- `command`: an argv list. In `abk.yaml` a string is also accepted and split with `shlex`. The word `{path}` stands for what
  the agent picks.
- `scope`: `StrEnum` `whole | file | node-id`, default `whole`. `{path}` appears exactly when the scope is not `whole`.

A profile provides `agent_commands: tuple[AgentCommand, ...]` through an **optional** protocol (`profiles.base.AgentCommands`,
`runtime_checkable`, like `CreatedFiles`); a profile without it, including one registered by a third party, gives none and
nothing changes. `python-uv`: test whole `uv run pytest -q`; test file `uv run pytest -q {path}`; check whole `uv run
pre-commit run --all-files`; check file `uv run pre-commit run --files {path}`. `node-npm`: test `npx vitest run` and
`npx vitest run {path}`; lint `npx oxlint .`; format `npx oxfmt --check .`; check `npx tsc --noEmit`. A workspace member that
needs `--package <name> --isolated` is what the repo override is for.

`repos.<name>.agent_commands: list[AgentCommand] | None = None`, beside `tests` and `checks`. `None` follows the profiles; a
list, an empty one included, replaces them. `abk config --show` prints it with the rest of the dump (`null` when it follows
the profile).

The effective list of a repo (`pipeline/agent_commands.py`) is the override, else the repo profile's commands followed by each
project profile's, each (purpose, command, scope) once, in that order, as `allowed_tools` composes.

## Language independence

Nothing outside `profiles/`, `init/` and `runtimes/` names an ecosystem or product: `pipeline/agent_commands.py`,
`stack_runner.py`, `graph/nodes.py`, `cli/doctor.py` and `config.py` only read the profile object and the repo
configuration. A test scans the new module for the registered profile names and the tool words and finds none.

## The allow-list consistency check

The matcher moves to `tool_patterns.py` (no protocol-library import); `runtimes/acp.py` imports it back, so `acp.allows` is
the same function and its tests keep passing. A command is judged as its line, argv joined with spaces and `{path}` replaced
by a sample word, against `wiring.allowed_tools(profile, forge, projects)`.

- **Config load** refuses an `agent_commands` list in `abk.yaml` with a command the list does not allow, naming the repo, the
  index, the line and the allow-list. The check imports `wiring` lazily; if that proves cyclic or heavy at load, the three
  composition functions (`BASE_TOOLS`, `forge_read_tools`, `allowed_tools`) move to a small module that `wiring` re-exports,
  so the composition stays defined once.
- **`abk doctor`** reports the effective list of each repo: ok (`N commands, all allowed`), info (none named), FAIL for a
  command outside the allow-list, which for a profile's own list is a defect of the profile and so is not a load error (a
  third-party profile must not stop the whole configuration), and warn when the prompt section would leave commands out.
- A unit test walks every registered profile and asserts its own commands match its own `allowed_tools`.

## The prompt section

`pipeline/agent_commands.commands_note(repo)` returns `""` for no commands, else a heading ("Commands you may run to test,
lint and format; any other command will be refused:") and one line per command, `- <purpose>, <scope words>: <line>`, with
`{path}` shown as `<path>` (`<test id>` for `node-id`). Whole lines are added in order until the next would pass 600
characters in total; a line that does not fit is left out whole, never cut. `PromptTemplate.format` defaults a `{commands}`
slot to `""` like `{guidance}`, the slot sits where an empty value adds no text, and `ADAPT_PROMPT` becomes a
`PromptTemplate`. The note is the same under every runtime. Under the `acp` runtime the profile's `allowed_tools` has no
effect (the agent's own configuration decides), so the sentence is a recommendation there; the kit does not vary it.

## The scratch app

`scratch_app` in `tests/factories.py` is a `python-uv` app with no instruction file. Once the prompts name `uv run pytest -q`
and `uv run pre-commit run --all-files`, the file a sibling edit in unit `tier2-tests-are-tagged-by-runtime/16` adds as a
stop-gap is redundant, and a test can drop it later. That is not a task here and carries no `Needs:`.

## Not decided here

`clean_command` skips the type hook at the tests commit because stubs fail it; the `check` line for `python-uv` runs every
hook. If the agent loops on that in practice, the profile's value changes (a `check` command with the hook skipped needs an
allow-list pattern for an environment prefix); this change does not widen the list.

## Priority

`Priority: 0`, the emergency lane. A build in a real repo can lose its tests-first order, and fail a billed unit, whenever the
agent picks a command the allow-list refuses; the only guard today is a repo's own instruction file. The groups are small and
independent of other unbuilt units, so the lane is cheap.

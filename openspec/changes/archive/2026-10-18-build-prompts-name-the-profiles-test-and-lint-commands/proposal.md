# Proposal

## Why

A build agent runs headless and cannot ask for approval. Its tool list is `allowed_tools()` in
`src/agent_build_kit/pipeline/wiring.py` (~257-271): `BASE_TOOLS` (`Read Edit Write Grep Glob Bash(git *)`), the forge's read
commands and the toolchain profile's `allowed_tools`, passed to the run at ~474. For the `python-uv` profile
(`profiles/python_uv.py` ~213-216) the profile adds only `Bash(uv run *) Bash(uv lock*) Bash(uv sync*) Bash(uv add *)
Bash(uv remove *) Bash(pre-commit *)`; `docs/toolchain-profiles.md` (~86) states that design. A command outside the list is
refused with "needs approval this session can't give".

The build prompts never name the runner. `TESTS_PROMPT` and `IMPLEMENTATION_PROMPT` (`pipeline/stack_runner.py` ~198-250,
~657-676) say "run linting and formatting" and "run the new tests". In a scratch app with no instruction file the agent chose
`python -m pytest tests -q`, bare `ruff check .`, `ruff format --check .` and a `ruff ... ; echo $? >> ...` chain. All were
refused, so it could not verify its work, put the implementation in the first commit, and the tests-first check failed (unit
`tier2-tests-are-tagged-by-runtime/16`). `uv run --active pytest -q`, which matches the list, worked. Real repos avoid this
only because their own instruction file says `uv run`; any consumer repo with a `python-uv` or `node-npm` profile and no such
file has the same exposure.

**Priority 0.** This is urgent: a build in a real repo can lose its tests-first order, and fail a billed unit, whenever the
agent picks a command the allow-list refuses. Nothing else in the pipeline tells it which commands are allowed.

## What Changes

- **A profile names the commands a build agent may run:** an optional, language-independent list of `{purpose, command,
  scope}` (purpose `test`, `lint`, `format` or `check`; scope `whole`, `file` or `node-id`). `python-uv` and `node-npm`
  provide values.
- **A repo can replace them:** `repos.<name>.agent_commands` in `abk.yaml` (strict schema, shown by `abk config --show`).
- **Every named command must match the build allow-list:** refused at config load for an `abk.yaml` list, reported by
  `abk doctor` for a profile's own list. The match reuses the matcher the ACP runtime applies to `Bash(...)` patterns, moved
  to a module that does not need the protocol library.
- **The build prompts carry a short section** "Commands you may run", filled from that list, under 600 characters, and absent
  when there is no list: `TESTS_PROMPT`, `IMPLEMENTATION_PROMPT`, `REVIEW_FEEDBACK_PROMPT`, `CHECKS_PROMPT`, `REWORK_PROMPT`
  and `ADAPT_PROMPT`.
- **Documents, skills and the changelog** describe it.

## Impact

- Capabilities: `toolchain-profiles` (new, added requirements), `build-prompts` (new, added requirements). No existing
  requirement is modified: neither area has a main spec.
- Code: `config.py`, `profiles/base.py`, `profiles/python_uv.py`, `profiles/node_npm.py`, a new `tool_patterns.py` and
  `pipeline/agent_commands.py`, `runtimes/acp.py` (imports the moved matcher), `pipeline/stack_runner.py`, `graph/nodes.py`,
  `cli/doctor.py`, documents, two skills, the changelog.
- Out of scope: widening the allow-list (rejected: it conflicts with the "uv run only" design), and the missing-test-file
  mystery of the same unit, which is diagnosed separately from the scratch-state dump.
- Overlap: unbuilt units that touch `stack_runner.py` prompts, `config.py` or `doctor.py` (for example
  `tests-are-stubbed-checked-and-committed-per-group/7`, `test-kinds-are-unit-test-and-e2e-test/23`) overlap by text only;
  nothing is a `Needs:`.

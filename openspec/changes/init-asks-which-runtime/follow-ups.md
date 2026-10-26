## From `init-asks-which-runtime/1`

- src/agent_build_kit/runtimes/known_agents.py:704 — The library check calls `importlib.util.find_spec(RUNTIME_NAME)`, so the runtime's name (`runtimes.acp`) also serves as the library's import name and the pip extra's name. The reason string hard-codes 'the acp extra' as well.
- tests/runtimes/test_acp_list_models.py:514 — The timeout test sets `LISTING_TIMEOUT` to 1 and waits one real second for `asyncio.wait_for` to give up.

## From `init-asks-which-runtime/2`

- merge_values recomputes _argv_paths() (every registered runtime's questions) for each list it meets; it is cheap today, but computing it once per top-level call, or passing it down, would keep it from growing with the number of runtimes.

## From `init-asks-which-runtime/3`

- Under interactive init, `_fallbacks` now passes can_go_back=True, so typing `back` at a fallback runtime's own question silently drops that fallback. The comment there only mentions declined needs. Consider a separate flag so only the declined-needs path leaves a fallback out.
- The models question is skipped only when the top-level `models` key was given. Giving per-runtime models (`--set runtimes.<name>.models.review=x`) still asks it.
- src/agent_build_kit/init/runtime_choice.py:443 — If `--agent-command` and a `--set`/`--runtime-config` value both write to the same place (e.g. `runtimes.acp.command`), `--agent-command` is used as the preset but the `--set` value is never removed from `rest`. `merge_values(values, rest)` then overwrites the parsed argv with the raw value.
- src/agent_build_kit/init/runtime_choice.py:517 — When an agent advertises a list, there is no single 'keep the agent's default for all roles' choice. The person presses Enter once per role (four prompts). The design lists that choice first, and the spec says 'keeping the agent's default first'.
- src/agent_build_kit/init/runtime_choice.py:519 — Claude Code's menu offers '1 = the default models' without saying what they are. The design says the framework's alias defaults are shown.
- src/agent_build_kit/cli/init.py:459 — On a kept abk.yaml, `--set models.review=x` (or a `--runtime-config` with models) is validated and then dropped. The message printed only says the runtime and command are left as they are.
- src/agent_build_kit/init/runtime_choice.py:402 — `--set` values are parsed as YAML. A value like `no`/`on` becomes a bool, `2.5` becomes a float, and an argv containing ': ' or ' #' is turned into a mapping or truncated.

## From `init-asks-which-runtime/4`

- Under --policy-only, a pass on an entry marked `policy: unchecked` only tells the person to remove the line by hand. A later unit could offer to remove it after a confirmation, or under --yes. That would need a deletion path in the abk.yaml writer, which the builder named as the reason for choosing the reworded hint.

## From `init-asks-which-runtime/5`

- tests/integration/test_init_runtime_live_stack.py:227 — `<redacted>` is bound to the first known agent that has an `apply` descriptor, not to <redacted> by name, so the constant's name says more than the code chooses.
- tests/integration/test_init_runtime_live_stack.py:155 — The nested `write` binds `body` and returns it on the next line, which adds nothing; `policy_home` also asserts `returncode in (0, 1)` without saying which one a leaky policy should produce.

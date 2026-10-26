## From `start-order-by-stack-age/1`

- Reword the _log_ready docstring (src/agent_build_kit/cli/pipeline.py:1313-1314). It currently says a unit 'that fits under' the limit is passed. It should say the comparison ignores the limit so that a ready unit left out because the started unit took the last free place is still named.
- src/agent_build_kit/cli/pipeline.py:1313 — The new docstring sentence 'a unit that fits under it is passed by one that took the place' says the opposite of what happens: the reason the limit is ignored is that the unit that was passed may not fit under the limit.

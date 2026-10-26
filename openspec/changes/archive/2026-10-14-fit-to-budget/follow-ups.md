## From `fit-to-budget/1`

- docs/architecture.md 'Cutting and fitting text' and the budget.py module docstring still say every cut closes what it leaves open. A tail cut now reopens what the dropped head left open (it prepends <details>/``` lines). Reword both to describe the head and tail behaviour separately.
- docs/architecture.md:702 — The architecture section and the module docstring of budget.py still say every cut 'closes any code fence or <details> block it leaves open'. A tail cut now reopens what the dropped head left open, so the text has its own closing lines to close.

## From `fit-to-budget/3`

- The remaining `[-4000:]` slices are what group 4 is meant to replace: wiring.py:1365 (storm), 1538, 2586 (tier 2 base output) and 2638 (dev-stack output). Put each of them through `fit`/`cut_tail` the way `Tier2Session.run` now does.
- tests/pipeline/test_tier2_output_fitted.py:163 — `failing_log` now takes `count`, but its docstring still says it is "a failed pytest run over seven tests".

## From `fit-to-budget/4`

- src/agent_build_kit/budget.py:106 — The `cut_head` and `cut_tail` docstrings, and docs/architecture.md:889, still say the cut falls back to the next finer boundary only 'when none [no whole piece with content] fits'. They do not mention the second trigger this round added: the first piece left out is longer than the size.

## From `policy-check-asks-the-agents-own-matcher/1`

- Group 2 must land before any release. Until then, `abk doctor` and `abk init` still call `policy_check.checked`. On a protocol-runtime installation, `checked` now gets a `cannot_check` report, and `describe` turns it into an empty 'not refused:' message, which `abk doctor` caches for 15 minutes. Group 2's doctor and init must show the `cannot_check` text.
- src/agent_build_kit/runtimes/policy_check.py:221 — In `checked`'s docstring, the second paragraph ('Answers are kept per runtime, ...') is now indented 8 spaces, deeper than the first paragraph's 4. The rework re-indented it by accident.
- src/agent_build_kit/pipeline/restack_lane.py:290 — The checks-round commit moves the restack record write onto `atomic_write_text`. That change belongs to no task in this unit. It is justified: `tests/test_atomic_write_guard.py` from origin/main fails on main's own `restack_lane.py` (the `os.replace(partial, ...)` at line 291), so without it the branch cannot pass its checks. The change is minimal and keeps behaviour.

## From `policy-check-asks-the-agents-own-matcher/2`

- doctor's failing runtime-policy line joins the unrefused classes and the count with ' | '. Prose (' — ') would read better next to the other detail lines.
- test_doctor_policy_unchecked.py does not assert that init reached the menu, for example that 'choice [1-2]' appears in operator.screens. Its 'no marker' assertion fails only while option 3 exists. A screen assertion would keep the test meaningful if the path to the menu changes later.

## From `policy-check-asks-the-agents-own-matcher/4`

- Nobody has run the real agent over the harness yet: docs/agent-runtimes.md says so, and design.md's UNVERIFIED items still stand. Someone with the agent installed should run the harness once and record two things in that section before group 6's acceptance test is trusted: how a refusal shows up, and whether the approval step refuses anything beyond the deny list.
- The main run path's `_Session` spawn in acp.py still has its own subprocess setup apart from `agent_connection`. Folding it in is a larger refactor, left for later.
- src/agent_build_kit/runtimes/acp.py:1672 — `AgentLink.killed` can be wrong. When the caller has already called `link.kill()` inside the block (as the harness now always does), `_ended` sees a process that has exited and reports `killed=False`, although the agent was killed.
- src/agent_build_kit/runtimes/acp.py:1721 — `agent_connection` now suppresses every exception from `conn.close()`. Before, `_bare_connection` let them propagate, so the product's model and resume probes now hide a close failure they used to surface.

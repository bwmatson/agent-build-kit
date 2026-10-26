# live-test-tags-cover-every-e2e-test

The drift test that forces every live e2e-test of agent-build-kit that starts an agent to carry exactly one runtime marker
(`runtime_claude_code` or `runtime_acp`; untagged means the test needs no agent) has six gaps, found by an audit on 2026-10-19. This change closes
them in the kit's own tests (`tests/live_tag_drift.py`, `tests/test_live_tests_are_tagged.py`, `tests/runtime_tags.py`) and documents the rule.
Tests and a documents-and-changelog group only; no product code changes. Other repos (<redacted>, <redacted>) have no equivalent test and no runtime
markers; that is a follow-up and not in this change.

Files: `proposal.md` (why, what, impact), `design.md` (what was checked at file:line, the decisions, the probe of item 6), `tasks.md` (7 groups, all
`Priority: 2`), `specs/live-test-tags/spec.md` (the requirements and scenarios).

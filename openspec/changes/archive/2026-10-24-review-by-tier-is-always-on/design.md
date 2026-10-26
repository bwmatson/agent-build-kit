# Design

## Context

The review reply (`REVIEW_PROMPT` in `pipeline/wiring.py`) carries `needs_human`, which the reviewer sets when every required change
left is one the builder reported `BLOCKED:`, and `escalate`, `class` or `disagreement`, with `reasoning`, to stop spending rounds.
`parse_verdict` reads both, and the review node holds the unit for either, with the cause `needs_human`, `review_escalated_class` or
`review_escalated_disagreement`, before anything is approved or pushed. The earlier phases added `classification` and `drivers` to
the same reply without touching these. The documents say a person merges every pull request in the README, `AGENTS.md`,
`docs/architecture.md`, `docs/code-forges.md`, `docs/unit-graph.md`, the three skills and the footer in `pipeline/pr_body.py`, and the
message in `pipeline/command_policy.py` says a human merges every PR.

## Decisions

- **Escalation to a person stays as it is.** `needs_human` and `escalate` are kept in the reply, the prompt and the review node,
  with the causes they already set. They are about the reviewer's own loop: a problem it cannot resolve in the rounds it has, which
  needs a person's decision before a pull request is worth opening. The classification is about the finished unit. A reviewer may
  do both, and the two never override each other: an escalated unit is held and has no final verdict, and a classification never
  clears or sets an escalation. This change touches neither field; it adds a test that pins both in the reply.
- **`review.enabled` is ignored with a notice.** The key is still accepted, so an old file loads, and is dropped from the model:
  `abk config`, `abk doctor` and the loader say once that it is no longer used. Each guard that read it becomes unconditional, and
  the tests that held the flag false to check the old behaviour are removed with it, since that behaviour no longer exists. The
  `abk init` template and the docs lose it.
- **`max_unit_lines` is a load error.** The one-release deprecation of the previous phases ends: a file that sets the key fails with
  a message that names `review.ceilings.full` and says `abk config --migrate` moves it (the command and the move are added by the
  sizing change). The remaining readers of the single ceiling
  (the planner's size check and prompt, the unit-size check, the oversize log in the pipeline wiring) read the ceiling for the
  unit's review tier. The floor rule `ceilings.auto >= light >= full > min_unit_lines` replaces the one between the two old keys.
- **Docs: one rule, said once.** The sentence is "a person merges every pull request that was not auto-landed, and the build agent
  never merges". The README, `AGENTS.md`, the documents and the three skills (the shipped copy and the mirror in the repo's own
  `.claude/skills`, which has drifted and is brought back in step) are edited; the pull request footer says the pipeline merges
  only a unit that review classified `auto` and policy allowed; the command policy's message says the agent never merges and does
  not claim who does. The philosophy and design documents get a `status: implemented` note at the top and are otherwise left as
  the record of the decision.
- **A document check.** A test reads every Markdown file, skill and source string that reaches a user and fails, naming file and
  line, on the phrases that state the old rule, with the two history documents and the changelog exempt by name.

## Risks

- **A config that sets `max_unit_lines`.** Failing is the point; the message and `--migrate` give the way out.
- **Docs drift.** The check fails the suite on a document that restates the old rule, and the skills' mirror is compared with the
  source in the same test.
- **Depends on every earlier phase.** The auto-land phase has to have shipped for the new wording to be true.

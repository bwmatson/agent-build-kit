# Tasks

Acceptance: none — this is a cleanup of two configuration keys and the words of documents, each proved by a unit-test over fake units, temporary configuration files and the repository's own Markdown; nothing a consumer drives is built beyond what those tests drive.

Priority: 1

## 1. [agent-build-kit] [unit-test] `review.enabled` is ignored

Done when a configuration that sets `review.enabled` loads with the key ignored and one notice, and every behaviour that the flag guarded is always on. Estimate: about 330 changed lines.

Needs: a-unit-over-its-tier-is-held-and-split group 14 — the flag is removed only after per-tier sizing is on by default
Needs: units-are-sized-by-review-tier group 4 — max_unit_lines is removed only after its deprecation and its migration are in place
Needs: low-risk-units-land-without-a-person group 18 — the documents describe auto-land and demotion as they are
Needs: open-changes-are-migrated-to-review-tiers group 11 — the documents describe migration as it is

- [x] 1.1 Test: in `tests/config/test_review_enabled_ignored.py`, a file with `review.enabled: false` loads, the key is not in the model or in what `abk config` prints, one notice names it from the loader, `abk config` and `abk doctor`, and a file without the key gives no notice; `abk init`'s template does not write it.
- [x] 1.2 Test: in `tests/pipeline/test_review_always_on.py`, with no `review.enabled` anywhere, the planner's prompt asks for a review tier, the review prompt asks for the classification, an approval records a verdict, and the same holds for a file that sets the key to false; the tests that held the flag false to check the old behaviour are removed.
- [x] 1.3 Test: in `tests/pipeline/test_review_escalation_kept.py`, the review prompt still names `needs_human` and `escalate` and what each is for, a reply that sets either still holds the unit with the cause it sets today before any pull request is opened, a classification of `auto` in the same reply does not clear the hold, and a held unit has no final verdict.
- [x] 1.4 Remove the flag from the model with the one-release notice, and make every guard that read it unconditional.
- [x] 1.5 Remove `review.enabled` from `docs/configuration.md`, the README's configuration block and table and the `abk-config` skill and its mirror, and add its changelog entry.

## 2. [agent-build-kit] [unit-test] `max_unit_lines` is refused and every size check uses the ceiling for the unit's tier

Done when a configuration that sets `max_unit_lines` fails naming `review.ceilings.full` and `abk config --migrate`, `min_unit_lines` stays, and every size check uses the ceiling for the unit's review tier. Estimate: about 270 changed lines.

- [x] 2.1 Test: in `tests/config/test_max_unit_lines_removed.py`, `global_limits.max_unit_lines` and the same key under the deprecated root `limits` each fail the load with a message naming `review.ceilings.full` and `abk config --migrate`; `min_unit_lines` loads as before; a ceiling at or below `min_unit_lines` and ceilings out of order each fail naming the keys.
- [x] 2.2 Test: in `tests/pipeline/test_planner_tier_ceilings.py`, a unit expected `light` of 1500 lines is accepted and one expected `full` of 1500 is refused naming the `full` ceiling; the oversize log and the prompt name the ceiling for the unit's tier; and no module reads a single unit ceiling.
- [x] 2.3 Remove `max_unit_lines` and its readers in the planner, the unit-size check and the pipeline wiring in favour of the tier ceilings, and move the floor rule to the ceilings.
- [x] 2.4 Remove `max_unit_lines` from the same documents and add its changelog entry.

## 3. [agent-build-kit] [unit-test] The footer, the command policy's message and the documents state who merges

Done when the pull request footer and the command policy's message state who merges correctly, the README, `AGENTS.md` and the five documents say a person merges what was not auto-landed and the build agent never merges, and a test fails on a document that states the old rule. Estimate: about 300 changed lines.

- [x] 3.1 Test: in `tests/pipeline/test_pr_body_footer.py`, the footer says the build agent never merges and that the pipeline merges only a unit review classified `auto` and policy allowed, and does not say a human merges every one.
- [x] 3.2 Test: in `tests/pipeline/test_command_policy_merge_message.py`, a refused merge command's message says the agent never merges and names no one who does.
- [x] 3.3 Test: in `tests/docs/test_no_human_merges_every_pr.py`, every Markdown file of the repository outside the shipped skills and their mirror, and the two strings above, are searched for statements that a human or a person merges every pull request, which fail naming file and line, with the changelog and the two history documents exempt by name; and the repository passes.
- [x] 3.4 Reword the footer and the message in the code, and edit the README line about what happens after a merge, `AGENTS.md`, `docs/architecture.md`, `docs/configuration.md`, `docs/cli.md`, `docs/code-forges.md` and `docs/unit-graph.md` to the one rule, saying where a person's merge is still needed and that an auto-landed unit is merged by the pipeline.

## 4. [agent-build-kit] [unit-test] The skills, their mirror and the history documents say who merges

Done when the three skills with their mirror say a person merges what was not auto-landed and the build agent never merges, the two history documents carry a status note, the changelog has its entries, and a test fails on a skill that states the old rule or differs from its mirror. Estimate: about 300 changed lines.

- [x] 4.1 Test: in `tests/docs/test_skills_say_who_merges.py`, each shipped skill is searched for the same statements and equals its mirror in `.claude/skills`, and the repository passes.
- [x] 4.2 Test: in `tests/docs/test_review_docs_status.py`, the philosophy and the design document each open with a note that their status is implemented, the documents other than the changelog contain neither `review.enabled` nor `max_unit_lines` outside the migration message, and the changelog's unreleased section has an entry for the two removed keys and the wording of who merges.
- [x] 4.3 Update the `abk-authoring`, `abk-config` and `abk-pipeline` skills and bring the mirror in `.claude/skills` back in step, add the status note to the two history documents, and add the changelog entries.

## 5. [agent-build-kit] [unit-test] The rename tool is deleted

Done when the test-kind rename tool and its tests are gone, nothing refers to them, and the guard's exemption for them is removed. A person runs the tool once over the planning repository's documents first, as the installation's runbook says; do not merge this group before that has been done. Estimate: about 140 changed lines.

- [x] 5.1 Test: in `tests/test_old_test_kind_names_guard.py`, the guard no longer exempts a rename tool, and a file naming the tool's module fails a source search for it.
- [x] 5.2 Delete the tool, its tests and the guard's exemption, and remove its mention from the documents.

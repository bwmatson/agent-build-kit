## From `dry-guidance/1`

- Move the `squeezed` test helper (now in four test files, two added by this change) and `carries` into one shared test-support module and import it everywhere.
- reuse-guidance.md says 'say in your summary', but only the rework and review-feedback prompts ask for a summary or account. Consider 'say so in your final message'.
- tests/graph/test_reuse_guidance_sessions.py:27 — The whitespace-squeezing helper `squeezed` is copied again in both new test files (tests/graph/test_reuse_guidance_sessions.py:27 and tests/pipeline/test_reuse_guidance_prompts.py:30). It already exists in tests/pipeline/test_output_convention_prompts.py:25 and tests/pipeline/test_changelog_prompts.py:34, and a close variant is `flat` in tests/graph/test_review_verdict_rounds.py:31.
- src/agent_build_kit/templates/reuse-guidance.md:5 — The part ends 'say in your summary when reuse needs a larger refactor'. The tests, implementation and checks prompts ask for no summary. Only the rework prompt's JSON `summary` field and the review-feedback 'account' have one.

## From `dry-guidance/2`

- CHANGELOG.md:12 — This unit adds a second Unreleased bullet for the dry-guidance change. Group 1 already has one at line 219 ('The agents that write tests, implement, fix checks and rework are now told to look for existing code before adding any...').
- tests/pipeline/test_review_prior_art_prompt.py:57 — test_the_rule_satisfies_the_required_finding_consequence_rule only checks that the word 'consequence' appears in the bullet and that the separate consequence rule exists elsewhere. It does not pin the sentence that links the two ('This states the consequence a required finding needs').

## From `dry-guidance/3`

- In tests/test_authoring_skill_describes_behaviour.py, `examples()` keeps only the first line of each Good/Bad bullet, so the syntax check never sees the bullet's wrapped continuation line (the Good example's second line). The section-wide test still catches file extensions and tool names. Joining each bullet with its indented continuation lines before checking would also cover syntax that falls on a wrapped line.

## From `dry-guidance/4`

- tests/claude_recorder.py:35 — The recorder reads standard input to EOF for any argv containing `-p`. `claude_code.refresh_login` (src/agent_build_kit/runtimes/claude_code.py:199) runs `claude -p "Reply with OK..."` through `subprocess.run` with no `stdin`, so under the wrapper that call would block on the inherited standard input until its 120 s timeout.
- tests/integration/test_dry_guidance_build.py:167 — `for _ in entry:` expresses 'only if the branch added `file_stem`' as a loop over a list of zero or one items.

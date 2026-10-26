## From `units-are-sized-by-review-tier/4`

- src/agent_build_kit/config_migrate.py:309 — When both keys agree, `_move_ceiling` calls `_place(lines, root, 0)` only for the refusals it raises and throws away the placement it returns. A reader will take it for a placement step.
- src/agent_build_kit/config_migrate.py:136 — The 'raise review.ceilings.light and review.ceilings.auto' hint is added to any load error containing 'must not be below'. That includes a `repos.<name>.review.ceilings` ordering error, where it names the workspace keys and not the repo's own keys.

## From `units-are-sized-by-review-tier/6`

- src/agent_build_kit/pipeline/planner.py:1157 — With review.enabled off, a repo that overrides `full` is held by the plan check to its own `full` (unit_ceiling -> review_ceiling(repo, ws, None)), but the prompt's one ceiling comes from review_ceiling(None, ...), so it states the workspace figure; the flag-off calibration line (_largest_raw_figures) does use the repo's figure, so the flag-off prompt is not consistent with itself either.
- src/agent_build_kit/pipeline/unit_size.py:59 — The status and PR-size comparison read the stored review_tier. For a unit whose reply named no tier, that is the floor (often `auto`), not `full`, so after planning the 'no tier is held to full' rule applies only in the plan check.

## From `units-are-sized-by-review-tier/10`

- The `abk replan` listing (src/agent_build_kit/cli/pipeline.py:5719) still calls `plan_is_stale(record)` without `current`, so it works out the sizing digest again for every change it lists. It could compute `sizing_digest()` once and pass it in, as `stale_plans_line` and `plan_all` now do.

## From `units-are-sized-by-review-tier/11`

- CHANGELOG.md:5 — The stale-plan bullet's list of causes ('a changed ceiling, `min_unit_lines` or `review.enabled`') is still narrower than what the digest hashes. The digest also covers protected paths, classes, auto_land, repo review blocks and `max_unit_lines`, and it applies only while `review.enabled` is on.
- docs/cli.md:581 — The new stale-plan sentences in docs/cli.md, docs/configuration.md and abk-pipeline/SKILL.md are each one very long unwrapped line with brackets nested inside brackets, which is hard to read.

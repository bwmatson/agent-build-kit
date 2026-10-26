# Proposal

## Why

`changelog-by-the-builder` made the build, rework, resolver and review prompts carry a
changelog convention and added a form check to tier 1. Both are tied to the one repo that
built them: the prompts read a `## Changelog` section from the built repo's `AGENTS.md`
and say nothing where there is none, and the check is a test under that repo's `tests/`
that reads that repo's file. Another repo in a workspace gets neither, and a repo that keeps
its conventions in `CLAUDE.md` is not read at all.

## What Changes

- **A per-repo `changelog` setting** in the workspace file: a path (default
  `CHANGELOG.md`) or off. Off switches the whole feature off for that repo: prompts,
  check and anything init would write.
- **A packaged convention text,** generic and naming no installation, used whenever the
  setting is on. A repo's own `## Changelog` section in `AGENTS.md` or `CLAUDE.md` still
  overrides it.
- **A packaged check: `abk changelog check [PATH]`,** the same rules as today (conflict
  markers, bullets run together, duplicated bullets, bullets outside a section, headings
  out of order), available to any repo the pipeline builds.
- **Tier 1 runs it** for any repo whose setting is on, through the toolchain profile, so
  the agent sees a form failure in its checks round before any review.
- **The prompts use it for every such repo:** the build, rework and test-writing prompts,
  the resolver's keep-both-and-fold rule, and the review paragraph apply whenever the
  setting is on, not only when the repo wrote its own section.
- **This repo uses the packaged pieces:** its own test becomes a thin test of the packaged
  check, and its own section is kept equal to the packaged text or marked as an override.

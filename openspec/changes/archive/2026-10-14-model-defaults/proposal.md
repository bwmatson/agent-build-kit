# Proposal

## Why

The defaults put the most capable model on every role, and a separate one, `fable`, on the review of a rework. Building and
reworking are the bulk of the calls and of the cost, and the review that follows is what keeps their quality. Installations
that care about usage already set the roles by hand, building and reworking on `sonnet` and both reviews on `opus`, so the
defaults describe something nobody runs.

The reason a rework had its own reviewer was that the model that made an edit is the worst judge of whether it landed.
That still holds: with `sonnet` building and reworking, both reviews on `opus` are made by a different model from the one
that wrote the work.

## What Changes

- **The Claude Code runtime's defaults become** `implement: sonnet`, `rework: sonnet`, `review: opus`,
  `rework_review: opus`. A role the configuration names keeps the name it gives; a role left out takes the new default.
- **Other runtimes are unchanged:** a runtime that declares no model names still runs every role on its agent's own default.
- **The documents are brought in line:** the configuration reference, the runtimes document, the configuration skill and
  the changelog state the new defaults and the reason the two reviews are not the author's model.

## Impact

- agent-build-kit: the default model block, the documents and tests that state or assert it. An installation that names its
  models is unaffected; one that relies on the defaults runs building and reworking on `sonnet` after this.

# Proposal

## Why

Code built by the pipeline's agents repeats itself in the same few ways: a call that is always paired with
another is written out at each of seven sites; a helper is written again where one already exists (three
wrappers around the same command, the same pattern defined in two modules, state read and written by hand in
ten places); the two hosts' versions of a feature carry the same logic twice; and test helpers are copied from
file to file. Reviewers have noticed most of these, but as optional notes that were never acted on.

The builders are told nothing about it. One prompt says not to re-implement what a predecessor provides, and
another says to keep the change to what the tests require, which pushes toward writing new code rather than
finding old. The reviewer has a single clause about duplicated logic inside a rule about interfaces, is never
asked to look for an existing equivalent of what the diff adds, and is told that a required finding needs a
consequence it can name, which a plain duplicate seems not to have.

## What Changes

- **Builders are told how to look and what to do:** a short, language-neutral part is added to the prompts
  for writing tests, implementing, fixing checks and reworking. It is part of the full prompt, so a session that is continued is not told it again. The prompt for adapting to a
  changed predecessor keeps its own narrower instruction not to re-implement what the predecessor provides. It says to read how the surrounding
  code does it, to search by behaviour as well as by name, to use or extend what exists, to write shared logic
  once, to give calls that must change together one function, to use the shared test support, to delete what the
  change makes dead, and to stay within the change.
- **The reviewer looks for prior art:** for what the diff adds, it searches for an existing equivalent and for a
  second copy within the diff. A duplicate the change introduces or makes worse is a required finding, with the
  consequence that two copies must change together.
- **Only the change's own duplication is raised:** a duplicate that was already there and is not added to is not
  reported. Cleaning those up is a separate specification.
- **Rework looks for the others of the kind** when feedback names one duplicate; the review-feedback and checks
  prompts already say so.
- **Tests first do not pin a duplicate:** where a task names code to add, the tests step searches first and decides
  whether to reuse what exists, generalize it, or create one shared helper for two places; the implementing step may
  repoint a test whose stub duplicates existing code; the authoring skill tells authors to describe behaviour and
  name only contracts.
- **A real agent proves it:** a tier-2 acceptance group builds small units with a real agent in a scratch app that
  tempts duplication and checks, by counting definitions and call sites in what it wrote, that an existing function
  is reused, extended, or shared as the prompts ask; that the prompts reached the agent; and that the reviewer
  blocks a seeded duplicate and not a clean change. No assertion is a model's judgement.

## Impact

- agent-build-kit: the builder prompts, the review prompt, a packaged prompt part and the authoring skill, with their tests and docs, and, for the acceptance group, a scratch
  fixture, a recording agent wrapper and a structural assertion helper in its tests.
  No change to configuration, to the target repositories' own files, or to the recommendation documents.

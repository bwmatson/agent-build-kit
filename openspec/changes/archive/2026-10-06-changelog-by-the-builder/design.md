# Design

## The convention

One section of the repository's conventions file (`AGENTS.md`) states it, and the
build, rework and resolver prompts include that section's text, so there is one
source. The statement covers: where a new bullet goes (under the unreleased heading,
beside the bullets for related work); when to edit an existing unreleased bullet
instead (the change is a follow-up or correction to something that has not been
released); the shape (one bullet, wrapped at the file's width with a two-space
continuation, a blank line between bullets); the content (what changed and why, for
someone using the tool); and what never appears (an installation's names, a
pull-request or issue number, a dated story).

## The check

`tests/test_changelog.py` parses `CHANGELOG.md` and asserts: no `<<<<<<<`, `=======`
or `>>>>>>>` line; every bullet separated from the next by one blank line; no two
bullets equal after whitespace normalisation; every bullet under a `##` heading; the
headings in the order the file defines (unreleased first, versions descending). The
no-installation-names rule is the existing structural test, extended to read the
changelog if it does not already. The test runs unmarked, so tier 1 and CI run it.

## The resolver

The restack resolver's prompt gets the conflict rule for this file: keep every bullet
from both sides, in either order, fold bullets that describe one change, and leave
blank lines between them. It is told the merge driver means a conflict here is rare and
means the same lines were edited, not just added.

## Review

The review prompt's list of things not to raise gains "changelog form and wording,
which tier 1 checks"; substance stays in scope.

## Existing file

Whatever the check flags in today's file is fixed in this change, so the check starts
green.

## Out of scope

Fragment files per entry (an option if collisions persist), and release tooling.

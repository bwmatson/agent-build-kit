# Proposal

## Why

A person who opens a pull request today gets a summary and a list of core changes, and still has to work out which of the hundreds of
changed lines matter and which are a rename. Builds arrive faster than a person can read them, and the few that need care look like
the rest. The philosophy this work follows says a person asked to review should see at once why the pull request needs them, what to
look at and what has already been checked. This change does that for every review that remains, whatever the review tiers end up
deciding. It also has to come before calibration: what a reviewer asks to have reworked depends on what the description tells them,
so a clean-merge rate measured on the old descriptions would be calibrated to a baseline that no longer exists.

## What Changes

- **The review reply gains a focus list.** Ranked, each entry a place and the reason it deserves a person's attention: a boundary
  another system depends on, a behaviour change, something hard to undo, or a path with thin test coverage. When the unit's
  classification recorded drivers, those lead it.
- **The review reply gains a skippable list.** Mechanical moves, renames, generated or formatting-only changes, each with the reason
  it is safe to skip.
- **The pipeline lists what it verified.** The red run, the unit-test and e2e-test results and the review rounds, written from the
  unit's recorded results and not from the reviewer's word, so a person does not redo them.
- **The pull request body opens with a "Start here" section** holding the three lists, then the unit's review tier and its reason
  when review is enabled, ahead of "Why". It is a fixed section of the body's size fitting, so a long description cannot push it
  out. A unit held for a person carries the same section.
- **Commit messages gain a body.** The `test:` and `feat:` commits say in a sentence or two why the change exists, not only what.
- **A `review.brief` setting** (default true) turns the section off and returns today's layout.
- **The verdict record's `brief` field becomes true** when the pull request carries the section, which is what calibration later
  counts from.

## Impact

Pull request text and commit messages change. The review reply gains two optional fields; a reply without them reads as before and
the body then shows the verified list alone. A new setting is added. No state, hold, label, notification or merge depends on any of it.

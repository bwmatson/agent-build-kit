# Proposal

## Why

A reviewer opening a pipeline pull request learns how it was built (a stack position, which unit of which
change, that tests came first, that lint passes) and nothing about why it exists or what it does. The title is
the task group's heading and is terse. The reason and the plan live in a change directory in another
repository, so a reviewer has to leave the pull request to find either. Review nits recorded for later are
the longest and most specific text on the page, and each appears twice.

## What Changes

- **The description opens with why and what:** a Why section taken from the change's proposal, then what this
  pull request does: the goal of the unit's task groups and a short list of core changes.
- **The reviewer writes the core changes:** an approving verdict carries a description of the whole branch, since
  the reviewer has just read all of it. It is stored with the approval, replaced by a later approval, and
  rendered with each push. When it is missing the goal alone is shown.
- **Process text moves down and shrinks:** the stack position, scope, assumptions and verification follow the
  new sections; the "how this was built" paragraph becomes one line.
- **Follow-ups appear once:** a finding recorded for later is listed one time, in its located form.
- **The new sections have the highest weight** when the description is fitted to the lowest limit any host allows, so
  they are the last to be reduced.

## Impact

- agent-build-kit: the pull request body builder, the task group parser, the reviewer's verdict and prompt, the
  unit record, and docs. No change to titles, to the stack position wording, or to what hosts receive beyond the
  body text.

# Proposal

## Why

`dry-guidance` stops agents adding duplication, but does not remove what is already there. A survey of the
framework's current tree and of the reviewers' notes found it in five places: metric calls made in pairs
with a local record at six sites; a few plain git calls beside the shared runner and the same patterns defined
more than once (the diff-hunk pattern in three modules, the host-address pattern in two); one atomic-write idiom
copied fourteen times; a listing and a validating tail repeated across the code hosts; and test helpers copied from
file to file. The reviewers noted most of these as optional follow-ups that no later change picked up.

## What Changes

- **Paired calls become one function:** the six sites that emit a metric and record it locally call one helper
  the metrics page can still see; a tier 1 failure is classified once; values derived twice come from one result.
- **One atomic write for state files:** the fourteen copies of the temporary-then-replace idiom become one function.
- **One way to run the command, find a change and match a pattern:** the plain git calls use the shared runner,
  the change layout comes from the one function, and the host-address and diff-hunk patterns are defined once.
- **The hosts share what is common:** GitHub's file listing is derived once and the hosts' parsing helpers share
  their validating tail.
- **Test support in one place:** the helpers copied identically (the restack commit helper, the change-tooling
  fake, the change writer, the tracks installation builder) move to the shared test modules and their copies are
  deleted.
- **Each cleanup ends with a guard** that fails if the same kind of duplicate is added again.

## Impact

- agent-build-kit: source and tests only. No behaviour changes; every existing test passes unchanged except where
  it imported a helper that moved.

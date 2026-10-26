# Proposal

## Why

`forge-retry-layer` repeats a create only after a declared read shows it did not land. That read
has to be trustworthy on each host, and today it is not: GitHub's pull request lookup returns
"none" on any transport error, so an outage looks like "no pull request" and a repeated create
could duplicate it; there is no read for "this reply or comment already exists"; and Azure's
follow-ups after a create (the stacked body, the commit status) raise and fail the unit after the
pull request exists, where GitHub's contain them.

## What Changes

- **`find_pr` tells "none" from "could not tell".** On GitHub a transport error raises instead of
  returning none, as Azure's already does; the callers that relied on none-on-error handle the raise.
- **A duplicate pull request is "found".** When GitHub refuses a create because a pull request
  for that head and base already exists, the forge returns that pull request.
- **A read for existing comments:** each forge answers whether a comment carrying the pipeline's
  marker and a given body exists on a pull request (a reply by its parent), by its own listing,
  without the pipeline reading host terms.
- **Stacks:** the stack lookup answers whether a pull request is already a member.
- **Follow-ups to a create are advisory on both hosts:** Azure's post-create body update and its
  commit-status post are contained as GitHub's are.

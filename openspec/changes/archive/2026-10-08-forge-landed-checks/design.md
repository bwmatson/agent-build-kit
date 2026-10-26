# Design

## find_pr

GitHub `find_pr`: remove the `except TransportError: return None`; the wrapper decides about
repeating. Callers that used the none (`open_pr`, `pr_based_on`, `fresh_base`) get the raise
through the wrapper and treat `HostUnavailable` as the step's outcome, not as "no pull request".

## Duplicate create

GitHub `create_pr`: a 422 whose error names an existing pull request for the head returns
`find_pr(head)`; the base-missing 422 is still `BaseMissing`. Azure answers a duplicate with its
own error code; the forge maps it the same way.

## comment_exists

A new protocol method `comment_exists(repo, pr, marker, body, *, reply_to=None) -> id | None`,
declared as the landed read for `post_comment` and `post_reply`. GitHub lists issue comments (or a
review comment's replies) and matches the marker and exact body; Azure lists the thread's comments
and matches the same. Ids found are returned so own-post recording stays correct.

## Stacks

`stack_of` answers membership for create and add; Azure keeps refusing as now.

## Advisory follow-ups

Azure `update_pr(stacked_body)` after a create and the commit-status post are declared `advisory`
in the operation table, like GitHub's, so a failure after the pull request exists is contained.

## Out of scope

The retry rules themselves, parking, and replies pending across passes.

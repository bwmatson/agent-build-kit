# Design

## Replies

`post_replies` returns the replies it did not post; the `open_pr` node (and the pass, for a unit in
review) stores exactly those back into `pending_replies` instead of clearing the list. Each attempt goes
through the retry layer, so a reply that landed on a lost answer is found by the existing-comment read
and counted as posted with its id recorded as the pipeline's own. The pass's round posts a unit's
pending replies when the host is reachable, with the unit's backoff.

## The close

The satisfied unit records `close_pending` (reason posted or not, pull request number). A round
retries: if the reason is not present (existing-comment read) post it, then close; both are safe to
repeat through the layer. On success the record is removed.

## Out of scope

The retry rules, parking.

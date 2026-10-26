# Proposal

## Why

A PR create answered 500 during a host incident and the unit ended `failed`. The cause is how
retry is decided today: two independent loops (the transport for Azure, the GitHub client's own
for GitHub), each deciding by HTTP method alone. A read, a PUT or a DELETE is retried; a POST
or PATCH never is on a 5xx or network error, so a PATCH to a fixed value, a commit status or a
label add is not retried either, and a create is not retried because nothing says whether it
landed. The rules are written twice, differ in detail, and cannot say "this write is safe to
repeat" or "check first, then repeat".

## What Changes

- **Every forge operation is declared once with a kind,** next to the forge protocol:
  read; idempotent write (a fixed target value, a status for a context, a label add, a close,
  a rerun); create (a pull request, a comment or reply, a stack, a stack member), which repeats
  only after a named read shows it did not land; advisory (labels, drafts, follow-ups to a
  create), retried and then contained.
- **A wrapper applies the kind,** for every host: a transient failure (a server error or a
  network failure on a call that can be repeated, a rate limit with its wait) is retried a
  bounded number of times with backoff and a total deadline; a permanent one (authentication,
  not found, any other client error) is never retried. Each retry is logged and counted.
- **Exhaustion raises one typed error** naming the operation and the cause, instead of the
  host's own error, so callers can tell "the host is unavailable" from "the call was wrong".
- **The old loops are removed.** The transport keeps its timeouts, credential handling and
  typed errors; the GitHub client's retry is switched off. Exactly one layer retries.

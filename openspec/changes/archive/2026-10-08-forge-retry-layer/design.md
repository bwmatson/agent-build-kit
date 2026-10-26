# Design

## The table

`forges/operations.py`: a frozen mapping from each protocol method to an `OperationSpec(kind,
lands=None)`. `kind` is `read`, `idempotent_write`, `create` or `advisory`. For a create, `lands`
names the read that shows whether it landed: `find_pr` for create PR, `comment_exists` for a reply
or comment, `stack_of` for the stack calls. A test asserts every protocol method has an entry, so
adding an operation forces a decision.

## The wrapper

`ResilientForge(inner, policy, clock, sleeper)` implements the protocol by delegation. For each
call it consults the table:

- read, idempotent write: attempt up to `policy.attempts`; on a transient error wait and repeat;
- create: on a transient error call the declared read; if it shows the write landed, return its
  result as the create's result; if it shows it did not, repeat the create; if the read itself
  fails transiently, count that as the attempt and wait;
- advisory: as an idempotent write, and on exhaustion log, count and return the operation's
  neutral value (none, empty) rather than raise.

Transient means the typed errors the forges already raise: `HostError` with a server status or a
network cause, and `RateLimited`; the wait is the larger of the backoff and the host's hint, and a
hint over the ceiling fails at once with the hint on the error. `AuthError`, `NotFound` and any
other client error are permanent. Backoff is exponential with jitter; there is a total deadline
(`ABK_FORGE_DEADLINE_SECONDS`) so a run of long waits cannot hold a step for ever.

## Visibility

Each retry logs `forge <operation>: attempt n of m failed (<cause>); waiting <s>s` and adds to
`abk.forge.retries` with `operation` and `outcome` (retried, landed, exhausted, contained).

## Exhaustion

`HostUnavailable(operation, cause, attempts)` subclasses the transport's error base, so existing
`except` clauses keep working; callers that need to tell the host being down from a bad call catch
it by name (the unit-level parking change does).

## Removing the old loops

`Transport.request` keeps timeout, credentials, the typed errors, the sign-in-page rule and
status mapping, and raises on the first failure. The GitHub client's `_Retry` and `auto_retry` are
removed. Before they go, their tests (503 then 200, a host that stays down, a timeout on a read,
rate limits with and without a hint over the ceiling, GraphQL repeated, creates not repeated) are
ported to the wrapper over a fake forge; the same cases must pass.

## Settings

`forge_retries` becomes the wrapper's attempts (default 3 repeats); `forge_timeout_seconds` is
unchanged; add `forge_deadline_seconds` (default 120).

## Out of scope

The landed-check implementations per host (`forge-landed-checks`), parking a unit (`park-on-host-outage`),
and the poller's own backoff.

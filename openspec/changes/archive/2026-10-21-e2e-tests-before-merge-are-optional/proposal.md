# Proposal

## Why

Every unit of the e2e-test kind runs its live-stack tests before its pull request opens, under a lock that serializes the whole
host, and runs them again when the base moves. That is the slowest and scarcest step in the build, and it holds a unit that has
passed everything else. For a repo whose live suite is slow, flaky or shared, an installation may prefer to merge on the strength of
the unit tests and the review and find a live failure afterwards, where `verify` already runs the live tests against the deployed
change before the change is archived. That has to be a choice an installation makes, per repo, and the review verdict has to know
that the e2e result it is reading was not obtained.

## What Changes

- **A setting `e2e_before_merge`, `required` or `deferred`.** Global in `global_limits`, with a per-repo override under the repo's
  `tests` block, resolved the way the e2e unit scope is. The default is `required`, which is today's behaviour.
- **With `deferred`,** a unit of the e2e-test kind skips the e2e node before its pull request opens, and skips the re-run when its
  base moves. It records its e2e result as `deferred`, and its pull request says "e2e-test deferred to verify". A scheduled run of the
  whole suite is unaffected.
- **`verify` is unchanged.** After the change's units have merged it deploys and runs the live tests and the acceptance run as it
  does today. When it fails and some of the change's units deferred their e2e, its report names them.
- **The e2e result is one of four states** on the unit (and is pending, which is met in an interim verdict, until the gate has run): `passed`, `deferred`, `failed` or `not-required` (a unit-test unit).
- **The verdict does not treat `deferred` as green.** A unit with a deferred e2e result does not reach `auto` unless
  `review.auto_land.allow_deferred_e2e` is true, which it is not by default. A deferred result never lowers a tier that another floor
  has set.

## Impact

None for an installation that does not set it. With `deferred`, a live-stack failure is found after the merge and not before it:
that is the trade the setting names, and the change's documentation says so. The verdict's e2e input changes from pass or fail to
the four states, and the review policy gains one key.

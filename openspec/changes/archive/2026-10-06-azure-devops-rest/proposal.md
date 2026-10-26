# Proposal

## Why

Each Azure DevOps operation is an `az` subprocess, and listing pull requests costs about
three to four of them per open pull request per poll (threads, policy evaluations, the
build behind a failing evaluation, statuses), run four at a time. The base retarget
already needs a direct REST call because the CLI cannot do it. There is no timeout and
no retry on any call.

Microsoft's Python SDK is not a base for this: its last release is 7.1.0b4 (2023-11),
it hard-pins an unmaintained `msrest`, it has no async client, and its repository has
had no functional commits since mid-2025 with 7.2 support and a continuation-token
bug still open. The `az devops` extension vendors its own copy of it rather than a
newer one. No generated Python client exists. The REST API itself is stable.

## What Changes

- **Typed REST over the framework transport** (`forge-http-transport`): api version
  pinned (`7.1`, `7.1-preview.1` where the endpoint is preview), PAT or Entra
  credentials from sources, timeouts, bounded retry, continuation-token and
  `$top/$skip` pagination.
- **Hand-written pydantic models** for exactly the fields the pipeline reads
  (`extra="ignore"`), drafted from the published REST specs and the `pyado` project
  as a reference only, not a dependency.
- **Pull-request listing in one process.** One list call, then a bounded-concurrency
  fan-out for each open pull request's threads, policy evaluations, builds and
  statuses; no subprocesses.
- **The domain mapping stays** as it is: `status == completed` is merged, the vote
  rule for changes requested, definite mergeability, newest status per genre and name,
  system comments filtered, compound note ids.
- **The base retarget uses the same client** instead of its private `urllib` path, with
  the no-op comparison kept.
- **The `az` CLI is a credential source only,** for a logged-in machine; the
  `permitted_commands` carve-out is removed if nothing else needs it.
- **Tests move to the transport:** the `az`-wire fakes are replaced by recorded-payload
  fixtures through a mock transport.

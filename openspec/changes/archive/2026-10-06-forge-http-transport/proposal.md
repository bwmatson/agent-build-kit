# Proposal

## Why

Every call to a code host is a `gh` or `az` subprocess. None has a timeout. Nothing
retries except the poller's coarse backoff after repeated failures. Credentials are
chosen by shelling out per call (`gh auth token --user <owner>`, an injected PAT) and
the host CLIs have to be installed and logged in. The result parsing is scattered:
each forge re-implements "treat a sign-in page as an error" and "a private repo that
answers not found may be the wrong account".

The pipeline is moving both forges onto typed HTTP clients (`azure-devops-rest`,
`github-typed-client`). Both need the same things around the call.

## What Changes

- **One transport module** builds the HTTP client for a host: base URL, headers,
  timeouts and bounded retry with backoff (network errors, 429 and 5xx, honouring
  `Retry-After`), never retrying a non-idempotent write unless the host marks it safe.
- **Credentials come from sources, by owner.** A settings token wins; otherwise the
  logged-in CLI's token is read once per owner or organisation and cached, as a source
  only. No token appears in an argument list and none is switched globally, because
  units run concurrently under different owners.
- **The silent-failure rules live here.** A response that is not the expected media
  type (a sign-in page with a 2xx) is an error, not an empty result. A not-found on a
  private repo names the account it was asked as, so a wrong account is diagnosable.
- **Tests inject the transport.** A mock transport replaces the network, and a
  recorded-payload fixture helper loads responses with fixture owners only.
- **`abk doctor` checks credentials,** not binaries: it resolves each repo's
  credential and calls a cheap authenticated endpoint.
- **The HTTP library is `httpx` for now,** behind this module alone, so
  `httpx-to-httpx2` is one change in one place.

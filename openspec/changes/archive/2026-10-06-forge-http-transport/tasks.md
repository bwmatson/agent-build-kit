# Tasks

Acceptance: none — a framework transport module; tier-1 tests over a mock transport
prove it. The forge changes that use it carry the live checks.

## 1. [agent-build-kit] [tier1] One transport for code hosts

Done when a forge can make a call with an owner's credential, a timeout, bounded retry
and the silent-failure rules, a test can replace the network, and doctor checks
credentials.

- [x] 1.1 Test: with a mock transport, 503 then 200 succeeds on retry honouring a
      `Retry-After`; persistent failure ends after the bound with a typed error; a
      timeout is applied to every call.
- [x] 1.2 Test: a create-style POST that times out is not retried; an idempotent
      write is.
- [x] 1.3 Test: credentials come from the repo setting, else a stubbed CLI source,
      once per owner and cached; two owners concurrently use their own; none gives an
      error naming the sources; no token appears in any argument list.
- [x] 1.4 Test: an HTML body with a 200 where JSON is expected raises an
      authentication error; a not-found names the account used.
- [x] 1.5 Test: doctor resolves a credential per repo and reports the account, or the
      failing source, with the transport faked.
- [x] 1.6 Add `forges/transport.py` with `Credentials`, `credential_for`, `Transport`
      and the typed errors, the two settings, a recorded-payload fixture helper under
      `tests/`, and the doctor change.
- [x] 1.7 Document it in `docs/code-forges.md`, `docs/configuration.md` and the
      `abk-config` skill, and add a changelog entry.

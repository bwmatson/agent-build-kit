# Tasks

Acceptance: none — a CLI option and a message; tier-1 tests with a fake Grafana API prove it.

## 1. [agent-build-kit] [tier1] The push works without a token

Done when the dashboard push runs with a URL alone, the token flow is unchanged, a refusal is
explained, and doctor says which path is used.

- [x] 1.1 Test: with a URL and no token, the folder create and the dashboard post carry no
      authorization header and a repeat leaves one dashboard; with a token the header is the
      bearer token as before.
- [x] 1.2 Test: a 401 or 403 with no token gives the message naming the token setting and exits
      non-zero; with a token the existing message is unchanged; no URL still names the URL setting.
- [x] 1.3 Test: doctor reports the token or anonymous path when a URL is set and nothing when it is
      not.
- [x] 1.4 Make the token optional, build the headers conditionally, add the message and the doctor
      line.
- [x] 1.5 Update `docs/configuration.md`, the `abk-config` skill, `docs/architecture.md` and the
      changelog, worded as the proposal says (naming no installation), and check the no-leaks test.

# Tasks

Acceptance: none — a test-only change to a browser-side parser; the unit tests prove each behaviour.

## 1. [agent-build-kit] [unit-test] The event stream reader is pinned by its own tests

Done when `readEvents` has direct tests for each chunking shape and they pass against the current code.

- [ ] 1.1 Test: in `web/src/agui.test.ts`, build `Response` objects from chunked streams and assert `readEvents` yields an event split across two chunks, two events in one chunk, a trailing event with no blank line, a multi-line `data:` field joined with newlines, and nothing for a response with no body.
- [ ] 1.2 Fix anything these tests show `readEvents` in `web/src/agui.ts` gets wrong; if all pass, change no production code.

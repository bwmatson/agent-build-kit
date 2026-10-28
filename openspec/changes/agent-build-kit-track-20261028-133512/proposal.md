## Why

`readEvents` in `web/src/agui.ts` is the only parser of the chat and agent event stream the web UI
reads. Its tests feed it one well-formed event per chunk. Nothing pins an event split across reads,
several events in one read, a final event with no blank line after it, a multi-line `data:` field,
or a response with no body. A regression there shows up as dropped or garbled chat output, not a
loud failure. Found by the 20261028-133512 recommend run (test-coverage section).

## What Changes

- Add `web/src/agui.test.ts` covering `readEvents` directly. No production change.

## Capabilities

### New Capabilities
- `web-event-stream-reader`: the behaviour of the browser's server-sent-events reader.

## Impact

`web/src/agui.test.ts` only.

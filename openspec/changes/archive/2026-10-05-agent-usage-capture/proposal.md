# Proposal

## Why

Nothing says where the pipeline's tokens go. The Claude runtime's closing result
event carries usage, cost, duration, turns and a session id, and the framework
reads none of it: the result model keeps only the outcome and text, the agent
result has no usage fields, and the wiring reduces the result to a string. The
ACP runtime ignores the usage its protocol can report. The one per-unit ledger in
the code records cost only and has no caller.

## What Changes

- **The result event is read for usage.** Input, output, cache-read and
  cache-write tokens, cost, turns, duration and session id, all optional and
  tolerant of extra or missing fields.
- **A call's result carries them.** The agent result gains optional usage
  fields; the Claude runtime fills them for successful and failed calls, the ACP
  runtime from the protocol's usage where the agent sends it.
- **Every figure says where it came from** (`usage_source`): reported by the
  agent, estimated, or none. Estimates are flagged and never mixed into measured
  figures. A missing figure is null, never zero.
- **A per-call record is appended to a ledger** at `runs/usage-ledger.jsonl`,
  gitignored, written best-effort: a write that fails is dropped and reported
  once and never affects a run.
- **Resumes do not double count.** A rerun or resumed session writes under the
  same node and round and the reader keeps the latest record per key.
- **The ACP drift guard.** The runtime records at initialize whether the agent
  offers usage, a contract test replays recorded payloads, and a payload that does
  not parse degrades to the next source with one log line.

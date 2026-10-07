# ACP tool call updates

Each `update_*.json` is the `session/update` payload an ACP agent sends over the
wire (camelCase keys) for one tool call update, as `agent-client-protocol`'s
`ToolCallProgress` reads it. Tool: ACP protocol version 1.

The shapes follow the protocol's schema, with a possible agent error in
`rawOutput.error` (`code`, `message`); they were written to the schema, not
recorded from a live agent, and no agent is shown to send `rawOutput.error`.
Only the codes in `DENIAL_CODES` short-circuit the phrase list. Re-record by running an agent through a denied, an
allowed and a failing tool call and keeping the `tool_call_update` messages.

- `update_denied`: failed, `rawOutput.error.code` is `permission_denied`.
- `update_allowed`: completed; its output merely mentions a denial.
- `update_errored`: failed, `rawOutput.error.code` is `command_failed`; its
  message is the command's own failure, which merely mentions a denial.
- `update_denied_unstructured`, `update_errored_unstructured`: failed with no
  `rawOutput`, only text, so only the phrase list can tell them apart.

## Recorded from a live agent (2026-10-07)

`update_denied_unstructured.json`, `update_allowed.json` and `update_errored_unstructured.json`
are recorded: the `tool_call_update` each of three calls produced when `Hermes Agent v0.21.5+3642.g8c9fe96 (2026.9.24) · upstream 8c9fe964` was driven over
`agent-client-protocol` through `hermes acp`, one prompt per call, in a scratch repository:

- denied: `gh pr merge 1`, which the agent's own `approvals.deny` rule `gh pr merge *`
  refuses. The update is `failed` with the text `terminal failed: BLOCKED: this command
  matches the user-defined deny rule ...`; it carries no `rawOutput` and no status or code
  beyond `failed`.
- allowed: `echo 'permission to run that was denied'`, which runs. The update is `completed`
  and its output merely repeats the words.
- errored: `ls /does-not-exist-abk`, which fails on its own. The update is `failed` with the
  command's output and `exit_code: 2`, with no `rawOutput`.

This agent sends no structured denial field, so for it only the phrase list tells a policy
denial from an ordinary failure. `update_denied.json` and `update_errored.json` (with
`rawOutput.error.code`) remain schema-written: no agent is shown to send that field.

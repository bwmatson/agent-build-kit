# ACP tool call updates

Each `update_*.json` is the `session/update` payload an ACP agent sends over the
wire (camelCase keys) for one tool call update, as `agent-client-protocol`'s
`ToolCallProgress` reads it. Tool: ACP protocol version 1.

The shapes follow the protocol's schema, with the agent's own error carried in
`rawOutput.error` (`code`, `message`); they were written to the schema, not
captured from a live agent. Re-record by running an agent through a denied, an
allowed and a failing tool call and keeping the `tool_call_update` messages.

- `update_denied`: failed, `rawOutput.error.code` is `permission_denied`.
- `update_allowed`: completed; its output merely mentions a denial.
- `update_errored`: failed, `rawOutput.error.code` is `command_failed`; its
  message reads like a denial but is the command's own failure.
- `update_denied_unstructured`, `update_errored_unstructured`: failed with no
  `rawOutput`, only text, so only the phrase list can tell them apart.

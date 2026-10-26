# Design

## Reconciliation

A notification is a statement about the present ("this unit is waiting for you"), so the pipeline derives it from
the present. After the round's poll (`run_round`, after `_refresh`, `plan_all` and the gating steps, so the store
is as current as the tick can make it), a `reconcile` step computes the desired cards from `store.all()`, reads the
stored set, and applies the difference:

| Card id | Desired when |
|---|---|
| `unit:review:<unit id>` | the unit is `in_review` and no rework is pending (`feedback` is empty and it has not been sent back) |
| `unit:failed:<unit id>` | the unit is `failed` |
| `unit:held:<unit id>` | the unit is `held` for a reason that needs a person (`HeldBy.REVIEW`, `HeldBy.TOOLCHAIN`, or a `Cause.NEEDS_HUMAN` stop); not for `DEPTH`, which clears itself, or `REVIEWER`, the person's own hold |

Ids are `StrEnum`-prefixed (`CardKind.REVIEW`, `CardKind.FAILED`, `CardKind.HELD`) so a kind is never a bare string.
Ids in the desired set and not stored are shown; ids stored and not desired are cleared. Auto-clear is therefore
exact: a failed card goes when the unit stops being failed (requeued, fixed, closed); a review card goes when the
pull request merges or closes, goes to rework or rebase, or is approved, and is shown again on its return to
review. The step reads the unit store only and makes no host call. Which exact fields express "no rework pending"
and "needs a person" is confirmed against `StoredUnit` and `Cause` by the first test task; the table is the
intent, not a transcription.

The step also runs, from the stored units and without a poll, when the round stops early at the usage pause, so a
pause does not freeze the cards.

## The stored set and timing

`notifications.json` in the state directory holds, per id, when it first became desired (`pending_since`), when it
was last sounded (`sounded_at`) and whether the provider accepted it. It is written the way `units.json` is
(atomic, under a lock), so two overlapping ticks cannot both show a card, and it survives a restart: a restart
neither repeats a card nor loses one.

- **Delay.** An id desired for less than `delay_minutes` (default 10) is not shown yet. If it stops being desired
  first, its entry is dropped and the provider is never called: a unit that fails and is requeued within the delay
  never shows.
- **Show once.** A shown id is not shown again on later ticks or passes.
- **Remind.** An id still desired `remind_after_minutes` (default 30) after it was last sounded is shown again
  through the same `show`; providers that replace by id turn that into a refresh.
- **Failed show.** When `show` fails, the id is not recorded as shown and is tried again next tick.
- **Failed clear.** The id stays stored and is cleared next tick.

`pr_replies.own_posts` is the pipeline's record of what it posted on a pull request. The reconciler uses it so that
an id the pipeline's own post would change is not mistaken for a person's activity. UNVERIFIED: whether a
person's comment can be told from the pipeline's using only what the store and the state directory already hold,
with no host call. If it cannot, the first round does not use person activity at all and says so in the docs.

## The provider interface

`notify/` holds a `Notifier` Protocol, `show(id: str, title: str, body: str, link: str) -> None` and
`clear(id: str) -> None`, the reconciler, the store, and the providers. The Protocol is the cross-platform layer;
each platform is one implementation behind it. `notifications.provider` is a `Provider` `StrEnum`
(`off`, `command`, `windows`); a provider is built from the config by one function, so adding a provider is one
member and one class. Off is the default and builds nothing. Any exception from a provider is caught in the
reconciler, logged with `log()` (the tick's own log line) and counted through `telemetry.count`
(`abk.notifications`, attributes `action` and `outcome`), and never reaches the tick's outcome. Telemetry is a
no-op when disabled, as everywhere.

## Settings

`notifications:` in `abk.yaml` is a `Frozen` pydantic model (`NotificationsConfig`) on `WorkspaceConfig`, because it
describes the workspace and is reviewed: `provider`, `remind_after_minutes` (30), `delay_minutes` (10), and for
`command` the templates `show` and `clear`. Nothing is read from `os.environ`. A value that is not a
number of minutes of zero or more, or a `command` provider with no `show` template, is a config error naming the
key. Machine-local facts (such as the path of `powershell.exe` if it is not on `PATH`) belong in `settings.py`
(`ABK_` prefix, pydantic-settings), not in `abk.yaml`.

## The command provider

The templates contain `{id}`, `{title}`, `{body}` and `{link}` for show and `{id}` for clear. The command is split
into arguments first and the values substituted into each argument after, never through a shell string, so a
title with quotes or a `;` cannot inject anything. An unknown placeholder is a config error. A non-zero exit or a
timeout is a provider failure. Anything that fits is a command: `curl` to ntfy or a webhook, `terminal-notifier`
or `osascript` on macOS. An empty `clear` template means the provider cannot clear, and its cards expire on their
own.

## The Windows provider

A toast has to come from a Windows process, so under WSL the provider calls `powershell.exe -NoProfile` with
BurntToast; on Windows it runs the same script locally. It is chosen over a hand-written WinRT script so that
there is one path to maintain: BurntToast handles the toast XML, the application identity Windows requires, and
replacement of a repeat card by identifier. The click opens `link` (the pull request, or the web UI's unit page
when `serve` is configured). The module version is pinned in the docs and in the provider's script.

UNVERIFIED, to be settled by the hand-run acceptance task on a real machine before the provider is relied on:

- the BurntToast cmdlet names and parameters (`New-BurntToastNotification`, `-UniqueIdentifier`, the cmdlet that
  removes a toast by identifier, how a click opens a link) as of the pinned version, which changed between versions;
- whether removal by identifier works from a `powershell.exe` process that is not the one that showed the toast,
  which `clear` after a restart depends on;
- how `powershell.exe` 5.1 under WSL treats the process's lifetime, quoting of arguments, and the time one call
  takes.

If clear-by-identifier does not work across processes, the provider documents that a card then expires on its own
and the doctor check says so; the reconciler is unchanged, because it only ever asks the provider to clear.

## `abk init` and `abk doctor`

`abk init` detects WSL (`WSL_DISTRO_NAME` in the environment, `microsoft` in `/proc/version`) or Windows in
`init/detect.py` as a `Host` `StrEnum` (`wsl`, `windows`, `other`), which is the only place the platform is read.
On `wsl` or `windows` it asks whether to enable notifications and, on a yes, whether to install the module. The
command, `powershell.exe -NoProfile -Command Install-Module BurntToast -Scope CurrentUser`, is printed before the
question and run only on a yes. A no to notifications writes the provider as `off`; a yes writes `windows`; `--yes`
asks nothing and writes `off`. On any other host nothing is asked.

`abk doctor` adds a check, by the same `Check` shape as its others, only when the provider is not `off`. For
`windows` it runs `powershell.exe -NoProfile -Command Get-Module -ListAvailable BurntToast`; a missing or unusable
module is a failure whose fix is the install command above. For `command` it checks the template's program is on
`PATH`. Both go through the injected `run` and `which` the other checks use.

## Evaluated and left as follow-ups

- **desktop-notifier** (Python; D-Bus on Linux, macOS, Windows WinRT) supports clicks and buttons, but its
  documentation shows no replace or clear by identifier, and its Linux path is D-Bus, which under WSL does not
  reach Windows. Not used.
- **ntfy** (HTTP): a message is updated by sequence id, `PUT /<topic>/<id>/clear` clears it, `DELETE /<topic>/<id>`
  removes it, and `X-Click` opens a link; popups come from its web app and phones from its apps. It would be the
  write-once option and can already be driven by the `command` provider with `curl`. A dedicated `ntfy` provider
  is a follow-up if macOS or phone delivery is wanted. UNVERIFIED: the server version that added clear and delete.

## Test harness

A fake `Notifier` that records calls, a fake clock (the pipeline's `spans.clock` is the existing seam), a store in
a temporary directory, and units built in memory; the command provider is tested with a fake `run`, and the
Windows provider with a fake `run` that records the `powershell.exe` command line. Nothing here needs
shared test utilities. No group crosses a service boundary, so no integration tier is needed; the real
toast is the hand-run acceptance task.

## Contracts

None widened: the `notifications` config section is new and optional, the unit store's shape is unchanged
(a separate `notifications.json`), and nothing outside this repo consumes any of it.

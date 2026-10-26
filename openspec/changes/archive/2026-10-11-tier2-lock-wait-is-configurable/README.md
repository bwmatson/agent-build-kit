# tier2-lock-wait-is-configurable

How long a unit waits for the tier 2 lock is now a setting, `limits.tier2_lock_wait_seconds`, instead of a fixed hour. It defaults to 5400 seconds
(ninety minutes), is checked when the config is loaded, is used by the tier 2 runner and by post-merge verification alike, and appears in
`abk config --show`. The "tier 2 is busy" message names the value and the setting. A small interim fix; `tier2-lock-wait-holds-the-unit` later removes
the deadline as the default.

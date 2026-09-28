# Category: Secrets scanning

Daily-cadence category (run via `health.md`) — a leaked credential is a
problem, not a "could be better," so it gets checked daily alongside the
runtime-health categories rather than weekly with `improve.md`. Every
project handles API keys and credentials of some kind (internal-auth
API keys between services, database passwords, LLM gateway or provider
keys, proxy/VPN credentials, the GitHub credentials the tracks
themselves run with). Scan this run's project repo for anything that
looks like a committed secret — API keys, tokens, private keys, database
passwords hard-coded rather than read from env/settings.

Use `gitleaks detect` if available; otherwise grep for common patterns
(high-entropy strings near words like `key`/`token`/`secret`/`password`,
known key-format prefixes) across tracked files, excluding
`*.lock`/`*-data/` directories.

Report concrete findings: file/line, what it looks like, and whether it
appears to be a real credential vs. a placeholder/example value. Treat any
finding here as higher priority than other categories — flag it clearly
even if it means skipping a category-fanout budget elsewhere this run. Do
not print the actual secret value in the run log or a PR description;
reference file/line only.

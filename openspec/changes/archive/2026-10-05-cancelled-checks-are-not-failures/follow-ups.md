## From `cancelled-checks-are-not-failures/1`

- design.md still says a cancelled re-run is surfaced on the status line, but only the log line was built. A person should either delete that sentence from design.md or add the status-line output in a follow-up unit. The builder cannot edit design.md.
- On a refusal, on_rerun_checks writes 're-run N of M' to the log before the 'host refused' line, so the log reads as if a re-run was attempted and then refused. Moving the 're-run N of M' line after the successful `rerun(pull)` call would leave only the refusal in the log when the host says no.

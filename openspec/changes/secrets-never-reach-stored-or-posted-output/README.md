# secrets-never-reach-stored-or-posted-output

A value the pipeline hands to a subprocess or runtime through configuration is replaced by `[redacted:<NAME>]` wherever text leaves a run into storage or onto the wire:
saved feedback, run logs, transcripts, the usage ledger, the tier-1 and tier-2 result text, anything posted to the code host, and a rework prompt. The framework's own acceptance
tests stop printing the child environment in a failure message.

## From `review-by-tier-is-always-on/4`

- docs/configuration.md:896 — This line says `abk doctor` warns 'when `split_rounds` is 0 with review enabled'. There is no review flag any more, and `doctor.py:268` warns whenever `split_rounds == 0`.
- docs/architecture.md:789 — '**The size hold and the split.** With review enabled, the verdict's size step...' still makes the size hold depend on the retired build-out flag.

## From `review-by-tier-is-always-on/5`

- Group 5's Done line says a person must finish the planning repository's vocabulary sweep before this merges, and the runbook (docs/runbooks/migrate-to-risk-tiered-review.md:127) says so too. Nothing on the branch can check that, so whoever merges needs to confirm the sweep is done first.

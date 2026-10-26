# Tasks

Acceptance: none — a config rename and one restacking rule, with no surface a consumer drives;
tier-1 tests over the renamed field, the default, and a merge event prove it.

## 1. [agent-build-kit] [tier1] Split the depth cap into a build cap and a rebase cap

Done when the config field is renamed with its behaviour unchanged, a separate rebase cap defaults to
the build cap's value, a merge restacks a dependent only within it, a dependent beyond it is held with
its branch kept, and a later merge reconsiders and can un-hold it.

- [x] 1.1 Test: `stack_depth_build_cap` gates starting a unit exactly as the single depth cap did,
      under its new name; an `abk.yaml` using the old name fails to load, naming the new one.
- [x] 1.2 Test: with no rebase cap set, its resolved value equals the build cap's, whatever that is
      set to; with both set to different values, each is read independently.
- [x] 1.3 Test: a dependent whose depth after a merge is within the rebase cap is restacked exactly
      as today; one beyond it is not restacked, is held with the depth and the cap on its record, and
      its branch is not deleted by that merge's cleanup.
- [x] 1.4 Test: a unit held for exceeding the rebase cap is restacked at a later merge in the same
      repository once its depth falls within the cap, without any action by a person; one still
      beyond it after that merge remains held.
- [x] 1.5 Rename the field in the configuration schema and every place that reads it; add the rebase
      cap, defaulting to the build cap's resolved value when unset.
- [x] 1.6 Compare each dependent's post-merge depth to the rebase cap where restacking is attempted;
      hold what exceeds it, and extend the branch-keeping list to include what was held for this
      reason.
- [x] 1.7 After restacking what a merge can reach, reconsider held-for-depth units in the same
      repository against the rebase cap, and restack whichever now qualify.
- [x] 1.8 Update `docs/configuration.md`, `docs/architecture.md` and the `abk-config` skill for the
      renamed and new fields, and say in `docs/architecture.md` where restacking is described that a
      merge only cascades within the rebase cap.

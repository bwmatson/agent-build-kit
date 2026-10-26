# policy-check-asks-the-agents-own-matcher

`abk doctor`'s runtime-policy check and `abk init`'s policy step stop spending model tokens, and stop running anything of
the agent's, to learn what a configuration says. For a known agent the check reads the agent's real configuration, read-only
(the file under the home its applier resolves, by the reader the applier already has), and judges every probe command with
the kit's own matcher and dialect. It starts nothing, imports nothing from the agent, and finishes in well under a second,
so its answer is no longer kept. Every result names the pattern that refused it; the classes the recommended policy
knowingly leaves to the person are reported "not covered by design" and no longer fail the check; an agent the kit has no
policy for is reported "cannot check: abk has no policy for this agent", never as a pass. The answer is labelled "what the
configuration says, in abk's dialect; not observed from the agent". The live probe, with its prompt, its token question and
its cache, is removed; one e2e-test acceptance test drives the real agent over the same commands and shows its behaviour agrees
with the verdict.

The directory keeps the name of the first design, which asked the agent's own matcher: units are stored under it, and a
rename would orphan them (design.md, "The change's name"). Priority 2. Specs only: nothing is built, ticked or started. It
builds on `the-recommended-policy-ships-with-the-kit` (merged). The design is `design.md`.

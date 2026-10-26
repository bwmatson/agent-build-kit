# planned-dependencies-never-close-a-cycle

A dependency can no longer close a cycle through units planned earlier. A planner edge that would close one is dropped and logged, an explicit
`Needs:` edge that would close one is refused and named, a cycle made of `Needs:` lines alone is an error before any planning, and a deadlock
that exists anyway is listed by `abk status` instead of looking like an idle queue. The cause was a graph check that only looked inside the plan
being parsed, while `Needs:` edges are added after planning with no check at all.

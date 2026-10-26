# direct-dependencies-only

A unit stores, and every view shows, only the dependencies it has directly. If C needs B and B needs A, C lists B and not A (73 of the 352 stored
edges today are such redundant ancestors). One function, `direct_dependencies`, is the transitive reduction of the stored graph, and the store
writes, the graph page, the web Dependencies list, `abk status`, the pull request body and the planner's in-flight lines all use it. What the extra
edges did that nothing else does is kept where it is needed: an `[acceptance]` or `[narrow]` unit still waits for every earlier unit of its
change, now as a rule computed from the change's units at run time; every other unit behaves as a plain chain does, a reworked grandparent
reaching the grandchild through the chain. A `Needs:` the chain already implies is no longer linked each tick and draws no edge, and a started
unit's base no longer depends on the order its dependencies are listed in.

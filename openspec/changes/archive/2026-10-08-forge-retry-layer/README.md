# forge-retry-layer

One retry layer, written once above both forges, that decides what to repeat when a call to
a code host fails for a transient reason. Each forge operation declares its kind (read,
idempotent write, create, advisory); the layer applies the matching rule. The per-library
retry loops in the transport and in the GitHub client go away.

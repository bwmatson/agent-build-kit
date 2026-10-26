# forge-http-transport

One framework-owned module through which the pipeline reaches code hosts over HTTP:
credentials resolved per owner or organisation, a client with timeouts and bounded
retry, the two silent-failure rules, and an injectable transport for tests. The
base the typed Azure DevOps and GitHub clients stand on.

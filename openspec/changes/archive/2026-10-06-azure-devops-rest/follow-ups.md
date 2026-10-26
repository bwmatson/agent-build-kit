## From `azure-devops-rest/1`

- CHANGELOG.md's Azure bullet and docs/code-forges.md line 264 were edited without re-wrapping. 'read again once the host rejects it (it expires), so' and '(read again, once, when the host rejects it as expired) is sent as a Bearer. Either' now run past the width of the lines around them. Re-wrap both paragraphs to match.
- AzureDevOpsForge._call retries on any AuthError from an az credential. That includes a 403, which is a missing permission, not an expired token, so a 403 costs one extra `az account get-access-token` run and a second request before it fails. The result is correct. Retrying only on 401 (and on the sign-in page) would match the docstring's 'most likely expired'.
- _failing_evaluations stops only on an empty page. If a host ever ignored `$skip`, the loop would never end. Optionally, also stop when a page repeats ids already read, or cap the number of pages.

# process-tests-fake-the-github-api

Puts the e2e-test tests that run `abk tick` as a process back on a faithful fake of GitHub. They
faked the `gh` command; the forge now speaks to GitHub's REST API, so they fail with a 401 from the
real host. This change gives the API address a setting and gives those tests a fake server to point
it at.

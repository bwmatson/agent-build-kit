## ADDED Requirements

### Requirement: The GitHub API address is a setting

The address GitHub calls are made to SHALL be read from the `ABK_GITHUB_API_URL` setting and default
to `https://api.github.com`. The forge's client and `abk doctor`'s credential check SHALL both use
it, and a trailing slash SHALL not change the address called.

#### Scenario: The default

- **GIVEN** no `ABK_GITHUB_API_URL`
- **WHEN** the forge makes a call
- **THEN** the request goes to `https://api.github.com`

#### Scenario: A different host

- **GIVEN** `ABK_GITHUB_API_URL` set to another address
- **WHEN** the forge creates a pull request, and when `abk doctor` checks the credential
- **THEN** both requests go to that address and none goes to `api.github.com`

#### Scenario: A trailing slash

- **GIVEN** `ABK_GITHUB_API_URL` ending in `/`
- **WHEN** the forge makes a call
- **THEN** the request path has no doubled slash

# ci-fetches-openspec-once

The integration job of the kit's own CI fetches the pinned OpenSpec CLI once, in a step of its own with a bounded retry, from the pin the kit already
defines, instead of letting the first test that needs it fetch it through `npx` under a 60-second limit. A test that needs the CLI and cannot run it
fails with one message, "the OpenSpec CLI is not installed", and not with an exit status 127 read as a failure of the thing under test.

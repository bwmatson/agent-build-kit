## ADDED Requirements

### Requirement: A prompt reaches the agent without being bound by the argument-size limit

A runtime SHALL declare how it carries a prompt: `stdin` (the process reads it on its standard input), `protocol` (a message of the agent protocol) or `argument` (one element of the command line). The Claude Code runtime SHALL declare `stdin` and SHALL NOT put the prompt in the argument list; an ACP runtime SHALL declare `protocol`. The transport SHALL be decided in one place and no caller SHALL build a command line holding a prompt. A prompt of any size up to the transport's safe size SHALL be delivered whole and unchanged, and the agent's reply parsed as for any prompt. A prompt that is short SHALL behave as it did, apart from the way it travels.

#### Scenario: A large prompt is delivered whole

- **GIVEN** a prompt of 300,000 bytes and the Claude Code runtime
- **WHEN** the runtime runs it
- **THEN** the process receives all 300,000 bytes on its standard input, none of its arguments holds the prompt, and the reply is parsed into the result

#### Scenario: A small prompt behaves as before

- **GIVEN** a prompt of five words
- **WHEN** the runtime runs it
- **THEN** the result is the same as before, and the other arguments are the same and in the same order

#### Scenario: A streamed run carries a large prompt

- **GIVEN** a prompt of 300,000 bytes and a progress callback
- **WHEN** the runtime runs it
- **THEN** the prompt is delivered whole, the events stream to the callback, and the run does not block on a full pipe

### Requirement: A prompt over a transport's safe size fails with a message that names it

Each transport SHALL state a safe size in bytes of UTF-8: 100,000 for `argument`, and 2,000,000 for `stdin` and `protocol`. A prompt over the safe size of its runtime's transport SHALL fail before any process is started, with an error whose first line names the call (its role, and the change when it names one), the size, the limit and the transport. The error SHALL NOT be the operating system's `Argument list too long`.

#### Scenario: An oversize prompt on a limited transport

- **GIVEN** a runtime that can carry a prompt only as an argument, and a prompt of 100,001 bytes
- **WHEN** it is run
- **THEN** it fails before any process starts with a message naming the role, 100,001 bytes, the limit of 100,000 and the `argument` transport

#### Scenario: A prompt at the limit

- **GIVEN** a prompt of exactly the transport's safe size
- **WHEN** it is run
- **THEN** it is delivered

#### Scenario: The size is counted in bytes

- **GIVEN** a prompt of 50,001 two-byte characters on an `argument` transport
- **WHEN** it is run
- **THEN** it is refused as 100,002 bytes

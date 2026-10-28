## ADDED Requirements

### Requirement: The event reader yields every event however the stream is chunked

`readEvents` SHALL yield each server-sent event of a response once, in order, whatever the chunk
boundaries of the body.

#### Scenario: An event split across two chunks
- **WHEN** one event's text arrives in two reads
- **THEN** it is yielded once, whole

#### Scenario: Two events in one chunk
- **WHEN** one read carries two events
- **THEN** both are yielded, in order

#### Scenario: A trailing event with no blank line
- **WHEN** the stream ends on an event with no blank line after it
- **THEN** that event is still yielded

#### Scenario: A multi-line data field
- **WHEN** an event has several `data:` lines
- **THEN** they are joined with newlines before the JSON is parsed

#### Scenario: A response with no body
- **WHEN** the response has no body
- **THEN** nothing is yielded and no error is raised

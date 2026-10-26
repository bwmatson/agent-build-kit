# abk-telemetry

Make the pipeline observable: OpenTelemetry traces and metrics from `abk tick`,
sent to the shared observability stack (Tempo for traces, Prometheus for
metrics) so a run's time, cost and outcomes can be seen instead of read out of
logs. Off unless configured; the framework carries its own small OTel setup and
shares no code with any installation.

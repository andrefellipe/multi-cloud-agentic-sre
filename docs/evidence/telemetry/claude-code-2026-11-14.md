# Claude Code telemetry, Phase 0 spike C (2026-11-14)

Question: does Claude Code export its OpenTelemetry metrics to a collector we run, so that Phase 1 can send them on to Managed Prometheus?

Setup:

- Collector: `otel/opentelemetry-collector-contrib:0.165.0@sha256:e40d61f10c9a617cca1ffd1be4d7e2b3a4b0f0001798ff07e58cabe82e618cea`, which Claude ran on your Mac with `tools/otel/collector-local.yaml` (OTLP in, the debug exporter out, metrics only) and its ports bound to `127.0.0.1`.
- Claude Code: one short session, which you ran from `/tmp`, outside the repository, so this project's AI-DLC hooks did not record it. Its environment: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_METRICS_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` and `OTEL_METRIC_EXPORT_INTERVAL=10000`. You typed one prompt and exited.

The collector received these between 13:31:52 and 13:32:09 UTC. Metric names and values only:

| Metric | Type | Unit | Data points | Total | `type` attribute |
|---|---|---|---|---|---|
| `claude_code.session.count` | Sum | count | 1 | 1 | none |
| `claude_code.cost.usage` | Sum | USD | 1 | 0.163543 | none |
| `claude_code.token.usage` | Sum | tokens | 4 | 47,642 | `input`, `output` |
| `claude_code.active_time.total` | Sum | s | 4 | 5.9 | `cli`, `user` |

Pass: `claude_code.session.count` arrived.

The data points also carry attributes whose values this record leaves out:

- personal and account identifiers: `user.email`, `user.account_id`, `user.account_uuid`, `user.id`, `organization.id` and `session.id`;
- descriptive ones: `terminal.type`, `model`, `effort`, `query_source`, `anthropic.plan`, `anthropic.provider` and `anthropic.custom_base_url`;
- resource attributes: `service.name`, `service.version`, `os.type`, `os.version` and `host.arch`.

Consequence for Phase 1: before these metrics reach Managed Prometheus, the collector must drop or hash `user.email`, `user.account_id`, `user.account_uuid`, `user.id` and `organization.id` (with an `attributes` or `transform` processor). It should also keep `session.id` out of metric labels: one new label value per session would multiply the series.

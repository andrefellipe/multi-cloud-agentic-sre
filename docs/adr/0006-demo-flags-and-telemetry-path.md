# ADR-0006: The demo's flags in Git, and the path of its telemetry and alerts

- Status: Accepted
- Date: 2026-11-12
- Requirements: REQ-022, REQ-023, REQ-024 (REQ-024.1), REQ-030 (REQ-030.1), REQ-112 (REQ-112.1), REQ-130 (REQ-130.2)

## Context

u1's second feature pull request, `feat/REQ-023-demo-telemetry-alerts`, deploys the OpenTelemetry Demo, its base flags and a Collector through Fleet, and builds the alert path up to the lab topic. The design left these choices open, and the pinned versions constrain them:

- **Flags.** The demo chart 0.42.6 (app 3.1.0) builds its flag file into the chart. flagd reads a copy, which the demo's flag UI edits. A flag merged to Git would reach the running demo only after flagd restarts, and a flag set in the UI is invisible to Fleet. BR8.5 asks that the running flags match Git after each sync, with a mismatch visible in Fleet. Later, u6 fixes a flag fault with a pull request that pins the flag off, and the Verifier then expects recovery, so a flag change in Git must reach the running demo by itself.
- **The workspace ID.** The Collector's remote-write address holds the Managed Prometheus workspace ID, which exists only after you apply `permanent` from the merged pull request.
- **Plan order.** `terraform-plan` is a required check. The lab root reads outputs that this pull request adds to `permanent`, and they exist only after your apply.
- **Contract C1.** The intake reads the alert manager's SNS message as JSON with RFC 3339 times. By default the alert manager sends plain text, with Go's own time format.
- **The demo.** It runs 25 components, including an AI agent that answers from recorded responses. Not every component is free of errors in normal running.

## Decision

1. **The base flags are a Fleet-managed ConfigMap that flagd reads directly.** `platform/base/flags/demo.flagd.json`, a copy of the chart's own defaults with every fault off, becomes the ConfigMap `flagd-base-flags` through the `cloud=aws` overlay and the root bundle. flagd mounts it whole and reloads it when it changes; flagd 0.16 follows Kubernetes ConfigMap updates. The flag UI is not deployed. A fault is set out of band by editing that ConfigMap in the cluster. Fleet then shows the flags bundle as `Modified` until the Git value is back.
2. **The platform Collector**, contrib 0.163.2, runs as one replica:
   - it turns server and consumer spans into request, error and duration metrics per service, and exports only those (an allow-list) to Managed Prometheus, through remote write;
   - it sends 10% of traces to the X-Ray OTLP endpoint, which stores them with Transaction Search, and logs at warning level and above to the CloudWatch Logs OTLP endpoint;
   - it signs all three with SigV4, with credentials from EKS Pod Identity;
   - it labels everything with `cluster` and `cloud`.

   The resource metrics the agents will read come with u5, which defines those reads.
3. **The workspace ID is set in Git once**, in `platform/otel-collector/values-aws.yaml`, with a one-line pull request after the first apply of `permanent`.
4. **The lab root plans before `permanent` is applied.** Without the permanent layer's new outputs, it plans the Collector's role without its metrics and logs permissions, and a check block warns.
5. **One alert rule, for the demo's fault:** payment charges failing above 5% for 1 minute, with `severity=critical` and `service=payment`, and `cluster` and `cloud` from the series. promtool unit tests check the exact labels (BR8.7).
6. **The SNS body** is AWS's documented JSON template for the alert manager, cut down to what C1 needs, with RFC 3339 times and labels in name order. Annotations are left out, because they are free text.

## Options considered

- **The demo's flag UI with its copied file.** A change in Git would need a flagd restart, and a change in the UI would never show as drift.
- **Flags inside the flagd pod spec,** for example as an init container's environment. A change would restart flagd, but an edit in the cluster would still be invisible to Fleet, and the flags would be JSON inside a values file.
- **The workspace ID from a Rancher cluster label,** through Fleet templating. It changes the Rancher configuration script of the first pull request, and the value would live outside Git.
- **An init container that finds the workspace by its alias.** One more image, one more permission and one more way to fail at start.
- **A Managed Prometheus managed scraper instead of remote write.** It costs by the hour and needs cluster access for the scraper.
- **One error-ratio rule for every service.** A component with errors in normal running would open incidents, and sessions, nobody asked for. u5 adds the rules the agents act on.
- **The `awsxray` and `awscloudwatchlogs` exporters.** They work too. The OTLP endpoints are what AWS documents with Transaction Search, and they let one exporter type with SigV4 carry all three signals.

## Consequences

- A fault is set with `kubectl` (`docs/runbooks/phase-1-skeleton.md`). That can be scripted for the evaluation runs, and it shows as drift. The demo's own flag page is gone, and the chart's own ConfigMap `flagd-config` is still created, unused.
- One more short pull request after the first apply of `permanent`. Until it merges, the Collector cannot write metrics.
- CI's plan of `lab` on this pull request shows a warning, by design.
- The Collector needs its Pod Identity credentials when it starts. A Collector pod started before the lab's association exists keeps failing until you restart it.
- The SNS template does not escape label values. That is safe for today's labels, which come from the rule file and the Collector's settings; revisit it if label values ever come from elsewhere.
- CI renders the bundles and checks the pins in Git, but it runs no `promtool` and checks no image pins in the rendered charts. Both were run by hand for this pull request; u2's CI checks should take them over.

## AI involvement

Claude, in the developer role of AI-DLC Code Generation for u1's second feature pull request, made these choices where the design left them open. It checked them against the pinned charts, flagd 0.16's source, Fleet 0.16.3's source (the version Rancher 2.15.3 ships) and AWS's documentation, and listed the options above. You accepted it unchanged before its pull request was opened: the flags live in Git and flagd reads them directly, the workspace ID is set with a one-line pull request, and running promtool, `terraform test` and an image-pin check of the rendered charts in CI is left to u2.

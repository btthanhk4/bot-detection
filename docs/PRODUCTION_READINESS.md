# Production readiness audit

This audit distinguishes verified code fixes from architectural work that still
needs evidence. Passing local tests is not a production-readiness certificate.

## Fixed in this audit

- Periodic collector sends now use the heartbeat path, so unchanged sessions do
  not generate a full telemetry request every interval.
- Collector retries honor server backoff and retain newer activity that arrives
  while an older request is in flight.
- A full fallback buffer returns a retryable 503 instead of evicting telemetry
  that was already acknowledged. Replay reserves capacity for its in-flight item.
- MongoDB-outage telemetry is committed to a SQLite spool on a named Docker
  volume before `recorded: true`; startup reloads it. A failed spool write returns
  503. Reopen/replay tests cover process-local state loss.
- Policy v8 gates release on 100 checkpoints per full held-out session, with no
  human-to-BOT or bot-to-HUMAN verdicts in the replayed validation/test splits.
- New events during the administrative delete pause return a retryable 503;
  replayed events from before the delete are not requeued.
- New training runs gate model publication on validation metrics and full
  validation/test replay. The test split has informed policy tuning, so it is
  no longer an untouched final holdout. CI also runs Ruff.

## Open production risks and acceptance criteria

1. **P0: Durable ingestion operations.** The local SQLite spool removes the
   acknowledged-RAM-only failure, but requires persistent volume backups,
   disk-capacity alerts, and a forced-kill/MongoDB-outage drill on staging.
   It is single-host; do not assume it works across replicas or a replaced host.
2. **P0: Real-world model validity.** The bundled model uses a limited labeled
   mouse dataset supplemented by synthetic training samples; the browser
   fingerprint columns are not validated by that dataset. Collect
   consented, labeled production-like sessions; measure per-device and per-site
   false-positive rates, calibration, and drift before enforcing bot decisions.
   Keep a truly independent final holdout and version the data/threshold policy.
3. **P1: Horizontal scaling.** Rate limits and fallback state are in-process;
   `BOT_API_WORKERS` is therefore restricted to one. Move these to shared
   infrastructure before adding replicas. Verify idempotent session upserts and
   delete behavior across replicas under concurrent traffic.
4. **P1: Capacity and overload.** The queue is bounded by event count but not
   total bytes; 1,000 near-limit payloads can consume substantial RAM. Add a
   byte budget, backpressure metrics, and load tests with MongoDB slow/down.
   Define and verify latency, error-rate, memory, and recovery SLOs.
5. **P1: Client and network edge cases.** Per-IP rate limiting can throttle
   many users behind one NAT; browser unload beacons cannot confirm server
   persistence. Evaluate per-tenant/session quotas, `429` behavior, and a
   deliberate at-least-once delivery contract with idempotency keys.
6. **P1: Deployment and observability.** Test on staging with the same proxy,
   MongoDB, and credentials as production. Publish immutable images, exercise
   rollback and database-outage drills, and alert on queue occupancy, rejected
   writes, model availability, and sustained inference latency.
7. **P2: Dashboard/browser coverage.** The dashboard depends on external CDN
   assets and has no browser regression suite. Vendor or pin assets with
   integrity controls; add browser tests for empty, large, stale, and failing
   API responses, plus responsive layout checks.

Security, privacy, and consent controls also require a separate production
review before exposing this telemetry service publicly.

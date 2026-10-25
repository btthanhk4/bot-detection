# Castle dashboard preparation

This change prepares the dashboard only. No Castle SDK, API call, credentials,
database persistence or automatic training/labeling is implemented here.
Existing backend responses remain supported and display an unconfigured state.

## Proposed internal response contract

This is DATACAT's optional normalized contract, NOT Castle's native API schema.
The future backend adapter must validate the actual provider API and map its
response to this contract. Return these fields on the existing authenticated
`GET /api/v1/research/traffic` endpoint:

```json
{
  "reference_integration": {
    "provider": "castle",
    "mode": "live",
    "status": "connected"
  },
  "sessions": [{
    "sessionId": "example-session",
    "reference": {
      "provider": "castle",
      "mode": "live",
      "status": "ready",
      "server_verified": true,
      "session_id": "example-session",
      "event_id": "provider-event-id",
      "observed_at": "2026-10-24T01:00:00Z",
      "bot_score": 95,
      "verdict": "UNKNOWN"
    }
  }]
}
```

- Integration statuses: `not_configured`, `disabled`, `pending`, `connected`,
  `error`, `quota_exceeded`. `connected` must reflect a verified provider
  connection, not merely the presence of credentials. `mode=mock` is visibly
  marked as test mode and never shown as a live connection.
- Session statuses: `pending`, `ready`, `error`, `unavailable`, `disabled`.
- A ready result is displayed only with `mode=live`, `server_verified=true`,
  matching `session_id`, nonempty `event_id`, and timezone-qualified timestamp.
  These are UI guards, not a security boundary. The server MUST own these values;
  never accept them from collector/client submissions.
- `bot_score`: finite JSON number in [0,100], or null. A score is not a calibrated
  probability; no percentage or threshold-derived label is shown. Zero is valid.
- `verdict`: `BOT`, `HUMAN`, `UNKNOWN`. The adapter must document the evidence
  supporting any normalized verdict. Allow, low risk, and not-detected do NOT
  automatically establish HUMAN. Unsupported classifications display UNKNOWN.
- Event IDs render as text, not external URLs or HTML. Do not send raw provider
  responses, secrets, tokens, or internal error traces to the browser.
- Coverage counts only authenticated reference results in the current page,
  not total traffic. Comparison is shown only for definitive DATACAT and provider
  verdicts; agreement is not an accuracy metric.
- Polling updates references independently from DATACAT's revision. The profile
  reference uses the selected traffic snapshot, not a possibly older detail fetch.
- Reference results do not modify `verdict`, `manual_label`, or training data.
  Provider output is external evidence, not verified ground truth.

## Next integration steps

1. Obtain account approval and confirm permission for the intended research use.
2. Configure secrets on the backend only; integrate the provider SDK and verified
   request-token flow appropriate to the actual website and provider API.
3. Add asynchronous server-side evaluation, bounded timeout/retry, quota tracking,
   idempotency, and reliable linkage to the session/capture being evaluated.
4. Persist source, timestamp, event/capture identifiers, adapter version, and raw
   evidence under appropriate access and retention controls.
5. Test the real adapter and failure paths before enabling live mode. No provider
   outage should block DATACAT inference. Review disagreements before dataset use.

## Local UI verification

Run `node pilot/reference-dashboard.test.cjs` with the pilot Playwright dependencies
installed. The test launches an isolated HTTP fixture and intercepts API reads;
no test result reaches MongoDB, Castle, or training data. It tests missing fields,
scores, verification/correlation, late updates, errors, injection safety, separate
verdict/label display, and desktop/mobile layout. Chart.js loads from the same CDN
as the existing dashboard.

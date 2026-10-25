# Per-Action Mouse Analysis

## Delivered

`core_ml/analyze_mouse_actions.py` adds an offline report for each retained
event instead of only a session average. It accepts a collector mouse object,
telemetry payload or a saved capture. It does not load weights, fit a model,
assign a bot label or participate in API inference.

| Level | Available measurements |
| --- | --- |
| Individual move | Original input index, time, coordinates, source, previous move reference, interval, displacement, velocity vector, speed, acceleration vector, tangential acceleration, jerk magnitude, signed turn and curvature |
| Continuous stroke | Constituent event IDs, duration, sampled path length, displacement, straightness, mean speed, speed variation and total absolute turn |
| Press/release | Endpoint event IDs, observed hold duration, moves while pressed, sampled path length and displacement; explicit incomplete/ambiguous status |
| Click | Time since the preceding retained move and click, when observed |
| Wheel | Per-notification deltas, timing and adjacent vertical reversal within a bounded interval |
| Coverage | Rejected inputs, uninspected and discarded counts, reordered input, retained time range, derivative availability and explicit incomplete-session status |

The input speed/acceleration summaries are ignored; measurements are recomputed
from coordinates and times. Undefined values stay `null`. The first velocity
requires two moves, acceleration requires three and jerk requires four.
Derivatives use backward differences at sample endpoints and seconds as the
time unit. They are discrete measurements, not estimates of physical hand
forces or certified neuromotor properties.

Motion segments end at click/press/release, source changes, malformed input,
backwards input order, duplicate timestamps or movement gaps greater than
250 ms. This threshold controls segmentation only; it is not a bot threshold.
Touch events remain visible but are excluded from mouse derivatives.
Overlapping presses without button identity cannot yield a reliable hold
duration; subsequent ambiguous presses in that continuity group remain unknown.
Press durations can span a long hold; the 250 ms move gap does not invalidate
an otherwise observed press/release pair.

## Important Limits Found in the Current Collector

The model currently consumes 8 sequential values per transition and 20
statistical features. The existing interaction measurements additionally
describe local motion and click/scroll timing. More report fields do not
automatically improve those trained classifiers.

`collector/src/mouse.js` keeps a bounded buffer and exports at most 100
records: up to 20 other events plus recent mouse moves. Those two histories
can cover different time ranges. An old click can survive after its preceding
moves have disappeared. A retained down/up pair also does not certify that
every intervening move was retained. `sampled_path_length` describes only the
observed samples, not the complete drag distance.

Coordinates are rounded normalized viewport axes, and handler times are
rounded to milliseconds. The exported mouse object does not include the
coordinate frame dimensions. Distances, speeds, turns and curvature are
reported in the supplied coordinate system, not pixels or physical units.
Unequal viewport width/height can distort geometry in normalized axes. A
stationary sample has no direction; duplicate timestamps cannot define a
velocity. Higher derivatives are particularly sensitive to quantization and
event timing and must be validated before use in a classifier.

Button identity, button state, pointer type/ID, target bounds, coalesced
samples and wheel `deltaMode` are not currently collected. A wheel delta must
not be described as pixels or actual page displacement. Missing source in
legacy records is reported as unspecified, not certified physical mouse input.
The report never claims it represents a full session and never concatenates
overlapping telemetry windows.

## Verification

38 new tests cover hand-calculated kinematics, turning, stationary motion,
duplicate timestamps, pauses, interrupted/overlapping/incomplete presses,
touch, malformed inputs, extreme finite timestamps, bounds, units, ignored
client derivatives, snapshot selection, CLI output and input preservation.
Full Python suite: **482 passed**, one Starlette TestClient deprecation warning.
Ruff passed. No browser or deployed-server test was run for this offline module.

Replayed the analyzer on **18 saved BOT runs, 90 sent windows** from
`captures-interactions-2026-10-02`. All reports serialized with strict JSON;
none rejected any mouse event in those captures. Across overlapping windows
there were 200 stroke reports, 324 paired-press reports, 324 click reports and
972 wheel reports. These are repeated-window measurements, not unique action
counts, independent users, or classifier accuracy statistics.

Three detailed examples were generated outside the product repository:

- `C:/Users/Admin/bot-detection-research/mouse-actions-2026-10-19/circular-detail.json`
- `C:/Users/Admin/bot-detection-research/mouse-actions-2026-10-19/heavy-wander-detail.json`
- `C:/Users/Admin/bot-detection-research/mouse-actions-2026-10-19/scrub-hover-detail.json`

Each selected example retained 100 events: 82 moves, 6 downs, 6 ups and
6 clicks, plus 18 wheel notifications. Each yielded 79 velocities,
76 accelerations and 74 jerks. Missing initial derivatives remain null.
The CLI selects the last actual send by default, excludes `test-probe` and
does not export session IDs, IP addresses or fingerprints. Reports still
contain movement coordinates and should remain with the research captures.

```powershell
python -m core_ml.analyze_mouse_actions `
  --input C:/Users/Admin/bot-detection-test/captures-interactions-2026-10-02/interaction-circular-fixed-0.json `
  --output C:/Users/Admin/bot-detection-research/mouse-actions-2026-10-19/circular-detail.json
```

Use `--snapshot-index 0` to select a particular sent snapshot. A probe index
or output path matching the input capture is rejected. Input work is limited
to the last 10,000 supplied events before retaining the latest 100 valid
records and 50 wheel notifications. The coverage section discloses these
limits; it cannot reconstruct history the collector never sent.

## Next Implementation Steps

1. Version a richer observation schema. Include page/frame identity, monotonic
   event IDs, coordinate frame dimensions, original event timestamps with a
   declared clock origin, button/buttons, pointerType, lifecycle boundaries
   and wheel deltaMode. Record availability instead of inventing defaults.
   Pointer IDs belong to the current page/input stream, not a persistent
   hardware identity.
2. Add optional Pointer Events collection with feature detection and a single
   mouse/touch fallback path. Account for compatibility events to avoid double
   counting. Coalesced samples can improve observed movement resolution;
   predicted events must not be treated as actual observed movement. Button,
   device type and coalesced-event semantics are defined by the
   [W3C Pointer Events specification](https://www.w3.org/TR/pointerevents3/).
3. Capture short batches of actual events before rolling buffers discard them.
   Use event IDs plus page identity to deduplicate retries and acknowledge
   durable writes. Bound batch size, local queues and server retention, and
   emit explicit gaps when an overflow or navigation loses data. Preserve a
   separate bounded inference window so a long visit does not create an
   unbounded request or model sequence.
4. Add task context without page text or form values: coarse target role and
   bounds, pointer entry/exit, click position relative to bounds and visibility
   changes. Then measure observed approach, corrections, press timing, movement
   while pressed and wheel bursts. Context is required to distinguish an
   intentional straight movement from an arbitrary synthetic trajectory.
5. Collect known human controls and controlled bot runs on the same website.
   Audit missingness and sampling differences. Split by person, page/session
   and bot generator before creating windows. Existing failed ablation folds
   remain development data; reserve fresh evaluation runs.
6. Compare new aggregate features in XGBoost first, then retrain a versioned
   BiLSTM input contract if per-step features help. Use validation data to
   select feature sets, sampling and fusion. Check bot-as-HUMAN,
   human-as-BOT, SUSPECT coverage and time to decision on fresh held-out data.

Attention weights can help inspect where a model attends, but do not by
themselves prove why an event is human or automated. This iteration delivers
the per-action measurement layer; richer collection, online dashboard
integration and classifier retraining are subsequent work.

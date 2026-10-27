const assert = require('assert');

const digestResolvers = [];
Object.defineProperty(global, 'crypto', {
  configurable: true,
  value: {
    randomUUID: () => '00000000-0000-4000-8000-000000000000',
    subtle: {
      digest: () => new Promise((resolve) => {
        digestResolvers.push(() => resolve(new Uint8Array(32).buffer));
      }),
    },
  },
});

let fetchCount = 0;
global.fetch = async () => {
  fetchCount++;
  return { ok: true, json: async () => ({}) };
};

const activeIntervals = new Map();
let nextInterval = 1;
global.setInterval = (callback) => {
  const id = nextInterval++;
  activeIntervals.set(id, callback);
  return id;
};
global.clearInterval = (id) => activeIntervals.delete(id);

const BotCollector = require('./dist/bot-collector.js');

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  throw new Error('Timed out waiting for asynchronous collector state');
}

async function testSessionContinuesAcrossPagesOfOneTab() {
  const previousWindow = global.window;
  const originalUUID = global.crypto.randomUUID;
  let counter = 0;
  global.crypto.randomUUID = () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
  const store = {};
  global.window = { sessionStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } } };
  try {
    const first = new BotCollector({ autoSendInterval: 0 });
    const reloaded = new BotCollector({ autoSendInterval: 0 });
    assert.strictEqual(reloaded.sessionId, first.sessionId, 'a reload or link in the same tab keeps the session');
    assert.notStrictEqual(reloaded.pageInstanceId, first.pageInstanceId, 'each page still has its own instance id');

    const saved = JSON.parse(store.datacat_session);
    store.datacat_session = JSON.stringify({ ...saved, seen: Date.now() - 31 * 60 * 1000 });
    const afterIdle = new BotCollector({ autoSendInterval: 0 });
    assert.notStrictEqual(afterIdle.sessionId, first.sessionId, '30 idle minutes start a new session');

    const explicit = new BotCollector({ autoSendInterval: 0, sessionId: 'sess_explicit-session-1' });
    assert.strictEqual(explicit.sessionId, 'sess_explicit-session-1');
    assert.strictEqual(JSON.parse(store.datacat_session).id, afterIdle.sessionId, 'an explicit id is not persisted');

    store.datacat_session = '{"id":"javascript:alert(1)","seen":' + Date.now() + '}';
    assert.ok(/^sess_0{8}-/.test(new BotCollector({ autoSendInterval: 0 }).sessionId), 'malformed stored ids are ignored');

    global.window = { sessionStorage: { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } } };
    const blockedA = new BotCollector({ autoSendInterval: 0 });
    const blockedB = new BotCollector({ autoSendInterval: 0 });
    assert.notStrictEqual(blockedA.sessionId, blockedB.sessionId, 'blocked storage falls back to one session per page');
  } finally {
    global.window = previousWindow;
    global.crypto.randomUUID = originalUUID;
  }
}

async function testTouchGesturesAreCaptured() {
  const collector = new BotCollector();
  const recorder = collector.mouseRecorder;
  const point = (x, y, extra = {}) => ({ clientX: x, clientY: y, radiusX: 11.04, radiusY: 9.5, force: 0.4321, ...extra });
  recorder.handleTouchStart({ isTrusted: true, touches: [point(100, 600)] });
  for (let i = 1; i <= 5; i++) recorder.handleTouchMove({ isTrusted: true, touches: [point(100 + i, 600 - i * 40)] });
  recorder.handleTouchEnd({ isTrusted: true, touches: [], changedTouches: [point(106, 380)] });

  // A pinch (two fingers) is not a single-finger stroke and is dropped.
  recorder.handleTouchStart({ isTrusted: true, touches: [point(50, 50)] });
  recorder.handleTouchStart({ isTrusted: true, touches: [point(50, 50), point(90, 90)] });
  recorder.handleTouchEnd({ isTrusted: true, touches: [point(90, 90)], changedTouches: [point(50, 50)] });
  // Script-dispatched touches are not trusted and never become gestures.
  recorder.handleTouchStart({ isTrusted: false, touches: [point(10, 10)] });
  recorder.handleTouchEnd({ isTrusted: false, touches: [], changedTouches: [point(10, 10)] });
  // A gesture the browser cancels (it started scrolling) is still kept.
  recorder.handleTouchStart({ isTrusted: true, touches: [point(200, 300)] });
  recorder.handleTouchCancel({ isTrusted: true, touches: [], changedTouches: [point(200, 250)] });

  const touch = recorder.exportData().touch;
  assert.strictEqual(touch.total, 2);
  assert.strictEqual(touch.gestures.length, 2);
  const swipe = touch.gestures[0].points;
  assert.strictEqual(swipe.length, 7, 'start, five moves and the release point');
  assert.deepStrictEqual(swipe[0].slice(1), [100, 600, 11, 9.5, 0.43], 'geometry rounded, force to 2 decimals');
  assert.ok(swipe.every((p) => p.length === 6 && p[0] >= 0));
  assert.ok(Number.isFinite(touch.gestures[0].t0));

  for (let i = 0; i < 40; i++) {
    recorder.handleTouchStart({ isTrusted: true, touches: [point(i, i)] });
    for (let j = 0; j < 80; j++) recorder.handleTouchMove({ isTrusted: true, touches: [point(i, j)] });
    recorder.handleTouchEnd({ isTrusted: true, touches: [], changedTouches: [point(i, 80)] });
  }
  const bounded = recorder.exportData().touch;
  assert.strictEqual(bounded.total, 42);
  assert.strictEqual(bounded.gestures.length, 20);
  assert.ok(bounded.gestures.every((g) => g.points.length <= 48));
  collector.destroy();
}

async function testKeyboardTimingAndPressPressure() {
  const collector = new BotCollector({ autoSendInterval: 0 });
  const recorder = collector.mouseRecorder;
  const key = (type, extra) => ({ isTrusted: true, repeat: false, target: { type: 'text' }, ...extra, type });
  recorder.handleKeyDown(key('keydown', { key: 'a', code: 'KeyA' }));
  recorder.handleKeyUp(key('keyup', { key: 'a', code: 'KeyA' }));
  recorder.handleKeyDown(key('keydown', { key: 'Shift', code: 'ShiftLeft' }));
  recorder.handleKeyDown(key('keydown', { key: 'Unidentified', code: '', keyCode: 229 }));
  recorder.handleKeyDown(key('keydown', { key: 'x', code: 'KeyX', repeat: true }));
  recorder.handleKeyDown(key('keydown', { key: 'p', code: 'KeyP', target: { type: 'password' } }));
  recorder.handleKeyDown({ isTrusted: false, key: 'b', code: 'KeyB', target: { type: 'text' } });
  recorder.handleKeyDown(key('keydown', { key: 'Backspace', code: 'Backspace' }));
  recorder.handleKeyDown(key('keydown', { key: 'ờ', code: '' }));
  const exported = recorder.exportData();
  const strokes = exported.keyboard.keystrokes;
  assert.deepStrictEqual(strokes.map((s) => s.k), ['c', 'o', 'u', 'b', 'n'],
    'kinds only (ASCII, other, virtual, Backspace, accented); repeats, password fields and untrusted events skipped');
  assert.ok(Number.isFinite(exported.pageAgeMs) && exported.pageAgeMs >= 0, 'page age is reported');
  assert.ok(strokes[0].h !== null && strokes[0].h >= 0, 'the released key has a hold time');
  assert.ok(strokes.every((s) => !('key' in s) && !('code' in s)), 'no key values leave the page');

  recorder.handleInput({ isTrusted: true, inputType: 'insertText', data: 'filled text', target: { type: 'text' } });
  assert.strictEqual(recorder.exportData().keyboard.bulkInserts, 0, 'text right after a keydown is ordinary typing');
  recorder.lastKeyDownAt = recorder.keyNow() - 5000;
  recorder.handleInput({ isTrusted: true, inputType: 'insertText', data: 'filled text', target: { type: 'text' } });
  assert.strictEqual(recorder.exportData().keyboard.bulkMaxLength, 11);

  recorder.handlePointerDown({ isTrusted: true, pointerType: 'mouse', buttons: 1, pressure: 0 });
  recorder.handlePointerDown({ isTrusted: true, pointerType: 'mouse', buttons: 1, pressure: 0.5 });
  recorder.handlePointerDown({ isTrusted: true, pointerType: 'pen', buttons: 1, pressure: 0 });
  const stats = recorder.exportData().pointerStats;
  assert.strictEqual(stats.mouseDowns, 2);
  assert.strictEqual(stats.zeroPressureDowns, 1);
}

async function testRestartDuringFingerprinting() {
  const collector = new BotCollector({ endpointUrl: '/telemetry', autoSendInterval: 1000 });
  const firstStart = collector.start();
  await waitFor(() => digestResolvers.length === 1);

  collector.destroy();
  const secondStart = collector.start();
  await waitFor(() => digestResolvers.length === 2);

  digestResolvers[0]();
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(fetchCount, 0, 'stale initialization must not send telemetry');
  assert.strictEqual(activeIntervals.size, 0, 'stale initialization must not create a timer');

  digestResolvers[1]();
  await secondStart;
  assert.strictEqual(fetchCount, 1, 'current initialization should send once');
  assert.strictEqual(activeIntervals.size, 1, 'only one heartbeat timer should exist');

  collector.destroy();
  await firstStart;
  assert.strictEqual(activeIntervals.size, 0, 'destroy should clear the current timer');
}

async function testDestroyAbortsStatusRequest() {
  const collector = new BotCollector({ detectUrl: '/detect' });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };
  global.fetch = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
  });

  const pending = collector.checkBotStatus();
  await waitFor(() => collector.abortControllers.size === 1);
  collector.destroy();
  const result = await pending;

  assert.strictEqual(result.fallback, true, 'aborted status request should use fallback');
  assert.strictEqual(result.error, 'aborted');
  assert.strictEqual(collector.abortControllers.size, 0);
}

async function testDestroyDuringProfileCollectionStopsWorkerAndInitialSend() {
  const previousWorker = global.Worker;
  let terminated = 0;
  let requests = 0;
  let workerStarted = false;
  global.Worker = class {
    constructor() { workerStarted = true; }
    terminate() { terminated++; }
  };
  global.fetch = async () => { requests++; return { ok: true }; };
  const collector = new BotCollector({ autoSendInterval: 0 });
  try {
    const resolverIndex = digestResolvers.length;
    const starting = collector.start();
    await waitFor(() => digestResolvers.length > resolverIndex);
    digestResolvers[resolverIndex]();
    await waitFor(() => workerStarted);
    collector.destroy();
    await starting;
    assert.strictEqual(requests, 0, 'destroyed profile initialization must not send telemetry');
    assert.strictEqual(terminated, 1, 'destroy must terminate the profile worker');
    assert.strictEqual(collector.abortControllers.size, 0);
  } finally {
    collector.destroy();
    if (previousWorker === undefined) delete global.Worker;
    else global.Worker = previousWorker;
  }
}

async function testPayloadPreservesPassiveProfileWithoutChangingBotdScore() {
  const collector = new BotCollector({ autoSendInterval: 0 });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = {
    heuristicScore: 0, isBot: false,
    profile: { schema: 'browser-profile-v1', main: { userAgent: 'Chrome' } },
  };
  const payload = await collector.getPayload();
  assert.strictEqual(payload.botd.profile.schema, 'browser-profile-v1');
  assert.strictEqual(payload.botd.heuristicScore, 0);
  assert.strictEqual(payload.botd.isBot, false);
  collector.destroy();
}

async function testLazyStatusProfileIsCancelledOnDestroy() {
  const previousWorker = global.Worker;
  let workerStarted = false;
  let terminated = 0;
  let requests = 0;
  global.Worker = class {
    constructor() { workerStarted = true; }
    terminate() { terminated++; }
  };
  global.fetch = async () => { requests++; return { ok: true }; };
  const collector = new BotCollector({ autoSendInterval: 0 });
  try {
    const resolverIndex = digestResolvers.length;
    const checking = collector.checkBotStatus();
    await waitFor(() => digestResolvers.length > resolverIndex);
    digestResolvers[resolverIndex]();
    await waitFor(() => workerStarted);
    assert.strictEqual(collector.abortControllers.size, 1, 'lazy profile must register cancellation');
    collector.destroy();
    assert.strictEqual((await checking).error, 'collector_inactive');
    assert.strictEqual(terminated, 1);
    assert.strictEqual(requests, 0);
  } finally {
    collector.destroy();
    if (previousWorker === undefined) delete global.Worker;
    else global.Worker = previousWorker;
  }
}

async function testColdPagehideDoesNotStartOptionalProfileProbe() {
  const previousWorker = global.Worker;
  let workers = 0;
  global.Worker = class {
    constructor() { workers++; }
    terminate() {}
  };
  const collector = new BotCollector({ autoSendInterval: 0 });
  try {
    const resolverIndex = digestResolvers.length;
    const payloadPromise = collector.getPayload('pagehide');
    await waitFor(() => digestResolvers.length > resolverIndex);
    digestResolvers[resolverIndex]();
    const payload = await payloadPromise;
    assert.strictEqual(payload.action, 'pagehide');
    assert.strictEqual(workers, 0, 'pagehide must not wait for an optional worker probe');
  } finally {
    collector.destroy();
    if (previousWorker === undefined) delete global.Worker;
    else global.Worker = previousWorker;
  }
}

async function testFailedDetectionDoesNotPromoteClientFlag() {
  const collector = new BotCollector({ detectUrl: '/detect' });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: true, heuristicScore: 0.99 };
  global.fetch = async () => ({ ok: false, status: 503 });

  const unavailable = await collector.checkBotStatus();
  assert.strictEqual(unavailable.is_bot, false);
  assert.strictEqual(unavailable.verdict, 'UNKNOWN');
  assert.strictEqual(unavailable.decision_state, 'UNAVAILABLE');
  assert.strictEqual(unavailable.bot_probability, null);

  global.fetch = async () => { throw new Error('network unavailable'); };
  const offline = await collector.checkBotStatus();
  assert.strictEqual(offline.is_bot, false);
  assert.strictEqual(offline.decision_state, 'UNAVAILABLE');
  collector.destroy();
}

async function testTouchIsTaggedAndExcludedFromMouseChunks() {
  const collector = new BotCollector();
  const recorder = collector.mouseRecorder;
  for (let i = 0; i < 30; i++) {
    recorder.handleTouchMove({ touches: [{ clientX: i * 10, clientY: 20 }] });
  }

  assert.ok(recorder.records.every((record) => record.source === 'touch'));
  assert.strictEqual(recorder.getChunks().length, 0);
  assert.strictEqual(recorder.getStats().movePointCount, 0);

  // A mouse used well after the finger (touch laptop) is recorded as a mouse.
  recorder.handleMouseMove({ clientX: 10, clientY: 20, timeStamp: performance.now() + 2000 });
  assert.strictEqual(recorder.records[30].source, 'mouse');
  assert.strictEqual(recorder.records[30].speed, 0);
  collector.destroy();
}

async function testTapCompatibilityMouseEventsAreNotMouseInput() {
  const collector = new BotCollector();
  const recorder = collector.mouseRecorder;
  const tapAt = performance.now();
  const point = { clientX: 180, clientY: 324 };
  recorder.handleTouchStart({ isTrusted: true, timeStamp: tapAt, touches: [point] });
  recorder.handleTouchEnd({ isTrusted: true, timeStamp: tapAt + 90, touches: [], changedTouches: [point] });
  // What the browser fires after the tap, at the tap position.
  const compat = { isTrusted: true, timeStamp: tapAt + 95, detail: 1, ...point };
  recorder.handleMouseMove(compat);
  recorder.handleMouseDown(compat);
  recorder.handleMouseUp(compat);
  recorder.handleClick(compat);
  // Chrome also marks them through sourceCapabilities, whatever the timing.
  recorder.handleMouseMove({ ...compat, timeStamp: tapAt + 5000, sourceCapabilities: { firesTouchEvents: true } });

  assert.ok(recorder.records.every((record) => record.source === 'touch'), 'no mouse records from a tap');
  assert.strictEqual(recorder.getStats().movePointCount, 0);
  assert.strictEqual(recorder.counters.mousemove, 0);
  assert.strictEqual(recorder.counters.mousedown, 0);
  assert.strictEqual(recorder.counters.click, 1, 'the tap still counts as activity');
  assert.strictEqual(recorder.clickEvents.length, 0, 'tap timing never feeds the synthetic-click rule');
  assert.ok(recorder.records.some((record) => record.type === 'click' && record.source === 'touch'));
  collector.destroy();
}

async function testDispatchedMouseEventsCannotSupplyBehavioralEvidence() {
  const collector = new BotCollector();
  const recorder = collector.mouseRecorder;
  const fake = { clientX: 10, clientY: 20, deltaX: 0, deltaY: 5, isTrusted: false };
  recorder.handleMouseMove(fake);
  recorder.handleMouseDown(fake);
  recorder.handleMouseUp(fake);
  recorder.handleClick(fake);
  recorder.handleWheel(fake);
  assert.strictEqual(recorder.records.length, 0);
  assert.strictEqual(recorder.scrollEvents.length, 0);

  recorder.handleMouseMove({ ...fake, isTrusted: true });
  assert.strictEqual(recorder.records.length, 1);
  assert.strictEqual(recorder.records[0].type, 'move');
  collector.destroy();
}

async function testClickGeometryAndPressTimingAreRecorded() {
  const collector = new BotCollector();
  const recorder = collector.mouseRecorder;
  const button = {
    getBoundingClientRect: () => ({ left: 100, top: 50, width: 80, height: 20 }),
    closest: () => null,
  };
  // Hardware-like click: held 96 ms, 7 px left of centre.
  recorder.handleMouseDown({ clientX: 133, clientY: 61, timeStamp: 1000, isTrusted: true });
  recorder.handleMouseUp({ clientX: 133, clientY: 61, timeStamp: 1096.4, isTrusted: true });
  recorder.handleClick({ clientX: 133, clientY: 61, detail: 1, target: button, isTrusted: true });
  // Automation-like click: zero hold, exact centre.
  recorder.handleMouseDown({ clientX: 140, clientY: 60, timeStamp: 2000, isTrusted: true });
  recorder.handleMouseUp({ clientX: 140, clientY: 60, timeStamp: 2000.2, isTrusted: true });
  recorder.handleClick({ clientX: 140, clientY: 60, detail: 1, target: button, isTrusted: true });
  // Keyboard activation (detail 0) and dispatched clicks carry no pointer geometry.
  recorder.handleClick({ clientX: 0, clientY: 0, detail: 0, target: button, isTrusted: true });
  recorder.handleClick({ clientX: 140, clientY: 60, detail: 1, target: button, isTrusted: false });
  // A click without a preceding press has no hold time.
  recorder.handleClick({ clientX: 150, clientY: 55, detail: 1, target: button, isTrusted: true });

  const data = recorder.exportData();
  assert.deepStrictEqual(data.clickEvents.map(({ hold, ox, oy, w, h }) => ({ hold, ox, oy, w, h })), [
    { hold: 96.4, ox: -7, oy: 1, w: 80, h: 20 },
    { hold: 0.2, ox: 0, oy: 0, w: 80, h: 20 },
    { hold: null, ox: 10, oy: -5, w: 80, h: 20 },
  ]);
  assert.strictEqual(data.counters.click, 4);
  assert.strictEqual(data.counters.mousedown, 2);

  const element = { getBoundingClientRect: () => { throw new Error('detached'); }, closest: () => null };
  recorder.handleClick({ clientX: 1, clientY: 1, detail: 1, target: element, isTrusted: true });
  assert.strictEqual(recorder.exportData().clickEvents.length, 3, 'geometry errors must not break the page');
  collector.destroy();
}

async function testPointerStatsCountCoalescedMouseSamples() {
  const collector = new BotCollector();
  const recorder = collector.mouseRecorder;
  recorder.handlePointerMove({ pointerType: 'mouse', isTrusted: true, getCoalescedEvents: () => [1, 2, 3] });
  recorder.handlePointerMove({ pointerType: 'mouse', isTrusted: true, getCoalescedEvents: () => [1] });
  recorder.handlePointerMove({ pointerType: 'touch', isTrusted: true, getCoalescedEvents: () => [1, 2] });
  recorder.handlePointerMove({ pointerType: 'mouse', isTrusted: false, getCoalescedEvents: () => [1, 2] });
  recorder.handlePointerRawUpdate({ pointerType: 'mouse', isTrusted: true });
  const stats = recorder.exportData().pointerStats;
  assert.strictEqual(stats.pointermove, 2);
  assert.strictEqual(stats.coalescedTotal, 4);
  assert.strictEqual(stats.coalescedMax, 3);
  assert.strictEqual(stats.coalescedMulti, 1);
  assert.strictEqual(stats.rawUpdates, 1);
  collector.destroy();
}

async function testFrameIntervalIsMeasuredOnce() {
  const frames = [];
  global.requestAnimationFrame = (callback) => { frames.push(callback); return frames.length; };
  global.cancelAnimationFrame = () => {};
  const previousWindow = global.window;
  global.window = { addEventListener: () => {}, removeEventListener: () => {}, isSecureContext: true };
  try {
    const collector = new BotCollector({ autoSendInterval: 0 });
    const recorder = collector.mouseRecorder;
    recorder.start();
    let now = 1000;
    // 60 Hz frames with one 2 s pause (hidden tab) and some jank.
    for (let i = 0; i < 70; i++) {
      now += i === 20 ? 2000 : i % 9 === 0 ? 33.4 : 16.7;
      frames.shift()(now);
      if (!frames.length) break;
    }
    const stats = recorder.exportData().pointerStats;
    assert.strictEqual(stats.frameMs, 16.7);
    assert.strictEqual(stats.frames, 60);
    assert.strictEqual(frames.length, 0, 'the probe stops once measured');
    recorder.stop();
    recorder.start();
    assert.strictEqual(frames.length, 0, 'a restart does not measure again');
    collector.destroy();
  } finally {
    global.window = previousWindow;
    delete global.requestAnimationFrame;
    delete global.cancelAnimationFrame;
  }
}

async function testResizeDoesNotCreateMouseMovement() {
  const previousWindow = global.window;
  global.window = {
    innerWidth: 1000,
    innerHeight: 1000,
    removeEventListener: () => {},
  };
  const collector = new BotCollector();
  const recorder = collector.mouseRecorder;
  try {
    recorder.recordPoint('move', 500, 500);
    global.window.innerWidth = 500;
    recorder.recordPoint('move', 500, 500);
    assert.strictEqual(recorder.records[1].x, 0.5);
    assert.strictEqual(recorder.records[1].dx, 0);
    global.window.innerWidth = 1015;
    recorder.recordPoint('move', 500, 500);
    assert.strictEqual(recorder.records.length, 3, 'scrollbar-sized changes should retain history');
    recorder.clear();
    global.window.innerWidth = 500;
    recorder.recordPoint('move', 250, 500);
    assert.strictEqual(recorder.records[0].x, 0.5, 'clear should adopt the new viewport');
    global.window.innerWidth = 1200;
    recorder.recordPoint('move', 250, 500);
    assert.strictEqual(recorder.records.length, 1, 'expansion should start a fresh coordinate frame');
    assert.strictEqual(recorder.records[0].x, Number((250 / 1200).toFixed(5)));
    assert.strictEqual(recorder.records[0].speed, 0);
  } finally {
    collector.destroy();
    global.window = previousWindow;
  }
}

async function testPagehideBeaconUsesCorsSafelistedContentType() {
  const collector = new BotCollector({ endpointUrl: 'https://api.example/telemetry' });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };
  let beaconBlob = null;
  const originalNavigator = Object.getOwnPropertyDescriptor(global, 'navigator');
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      sendBeacon: (_url, blob) => {
        beaconBlob = blob;
        return true;
      },
    },
  });

  try {
    const sent = await collector.sendTelemetry('pagehide');
    assert.strictEqual(sent, true);
    assert.ok(beaconBlob, 'pagehide should use sendBeacon when available');
    assert.strictEqual(beaconBlob.type, 'text/plain;charset=utf-8');
  } finally {
    if (originalNavigator) {
      Object.defineProperty(global, 'navigator', originalNavigator);
    } else {
      delete global.navigator;
    }
  }
}

async function testPagehideUsesUtf8ByteLengthAndSequenceWraps() {
  const collector = new BotCollector({ endpointUrl: '/telemetry' });
  collector.cachedFingerprint = {
    visitorId: 'visitor',
    components: { userAgent: 'đ'.repeat(40000) },
  };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };
  collector.sequence = 999999;
  collector.mouseRecorder.records = Array.from({ length: 100 }, (_, i) => ({
    time: i * 16, x: i / 100, y: 0.2, type: 'move',
  }));
  let body = null;
  const originalNavigator = Object.getOwnPropertyDescriptor(global, 'navigator');
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      sendBeacon: (_url, blob) => {
        body = blob;
        return true;
      },
    },
  });

  try {
    assert.strictEqual(await collector.sendTelemetry('pagehide'), true);
    assert.ok(body.size < 65536, 'UTF-8 payload should be trimmed below beacon limit');
    assert.strictEqual(collector.sequence, 0, 'sequence should wrap at the API limit');
  } finally {
    if (originalNavigator) {
      Object.defineProperty(global, 'navigator', originalNavigator);
    } else {
      delete global.navigator;
    }
  }
}

async function testOversizedPagehideRetainsMouseAndMobileDomain() {
  const collector = new BotCollector({ endpointUrl: '/telemetry' });
  collector.cachedFingerprint = {
    visitorId: 'visitor',
    components: { userAgent: 'Mozilla Mobile ' + 'x'.repeat(70000), maxTouchPoints: 5 },
  };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };
  collector.mouseRecorder.records = Array.from({ length: 100 }, (_, i) => ({
    time: i * 10, x: i / 100, y: 0.2, type: i % 3 === 0 ? 'click' : 'move', source: 'mouse',
  }));
  let body = null;
  const originalNavigator = Object.getOwnPropertyDescriptor(global, 'navigator');
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: { sendBeacon: (_url, blob) => { body = blob; return true; } },
  });
  try {
    assert.strictEqual(await collector.sendTelemetry('pagehide'), true);
    assert.ok(body.size < 60000);
    const payload = JSON.parse(await body.text());
    assert.match(payload.fingerprint.userAgent, /mobile/i);
    assert.strictEqual(payload.fingerprint.maxTouchPoints, 5);
    assert.ok(payload.mouse.records.filter((record) => record.type === 'move').length >= 25);
  } finally {
    collector.destroy();
    if (originalNavigator) Object.defineProperty(global, 'navigator', originalNavigator);
    else delete global.navigator;
  }
}

async function testPagehideFetchFallbackAvoidsCorsPreflight() {
  const collector = new BotCollector({ endpointUrl: 'https://api.example/telemetry' });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };
  let fetchOptions = null;
  global.fetch = async (_url, options) => {
    fetchOptions = options;
    return { ok: true };
  };
  const originalNavigator = Object.getOwnPropertyDescriptor(global, 'navigator');
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: { sendBeacon: () => false },
  });

  try {
    assert.strictEqual(await collector.sendTelemetry('pagehide'), true);
    assert.strictEqual(fetchOptions.keepalive, true);
    assert.strictEqual(fetchOptions.headers['Content-Type'], 'text/plain;charset=UTF-8');
  } finally {
    collector.destroy();
    if (originalNavigator) {
      Object.defineProperty(global, 'navigator', originalNavigator);
    } else {
      delete global.navigator;
    }
  }
}

async function testFailedHeartbeatRetriesLatestSnapshot() {
  let attempts = 0;
  global.fetch = async () => ({ ok: ++attempts >= 2 });
  const collector = new BotCollector({
    endpointUrl: '/telemetry',
    autoSendInterval: 0,
    retryBaseDelay: 1,
    maxRetryAttempts: 2,
  });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };

  assert.strictEqual(await collector.sendTelemetry('heartbeat'), false);
  await new Promise((resolve) => setTimeout(resolve, 150));
  assert.strictEqual(attempts, 2);
  assert.strictEqual(collector.pendingRetry, null);
  collector.destroy();
}

async function testHeartbeatRecoversAfterRetryBudgetIsExhausted() {
  let attempts = 0;
  global.fetch = async () => ({ ok: ++attempts >= 3 });
  const collector = new BotCollector({
    endpointUrl: '/telemetry', autoSendInterval: 0, retryBaseDelay: 100, maxRetryAttempts: 1,
  });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };

  assert.strictEqual(await collector.sendTelemetry('init'), false);
  await new Promise((resolve) => setTimeout(resolve, 130));
  await waitFor(() => attempts === 2 && collector.pendingRetry === null);
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), true);
  assert.strictEqual(attempts, 3);
  collector.destroy();
}

async function testClickBurstRetainsMouseEvidenceAndLongUrlIsBounded() {
  const collector = new BotCollector({ autoSendInterval: 0 });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };
  collector.mouseRecorder.records = [
    ...Array.from({ length: 25 }, (_, i) => ({ time: i * 20, x: i / 100, y: 0.2, type: 'move', source: 'mouse' })),
    ...Array.from({ length: 80 }, (_, i) => ({ time: 500 + i * 20, x: 0.3, y: 0.2, type: 'click', source: 'mouse' })),
  ];
  const records = collector.mouseRecorder.exportData().records;
  assert.strictEqual(records.filter((record) => record.type === 'move').length, 25);
  assert.ok(records.length <= 100);

  const previousWindow = global.window;
  const previousDocument = global.document;
  global.window = { location: { href: `https://example.com/?q=${'x'.repeat(3000)}` } };
  global.document = { referrer: `https://example.com/?r=${'y'.repeat(3000)}` };
  try {
    const payload = await collector.getPayload('heartbeat');
    assert.strictEqual(payload.pageUrl.length, 2048);
    assert.strictEqual(payload.referrer.length, 2048);
    assert.strictEqual(payload.mouse.records.filter((record) => record.type === 'move').length, 25);
  } finally {
    global.window = previousWindow;
    global.document = previousDocument;
    collector.destroy();
  }
}

async function testUnchangedHeartbeatIsCoalescedUntilIdleDeadline() {
  let attempts = 0;
  global.fetch = async () => {
    attempts++;
    return { ok: true };
  };
  const collector = new BotCollector({
    endpointUrl: '/telemetry',
    autoSendInterval: 0,
    idleHeartbeatInterval: 60000,
  });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };

  assert.strictEqual(await collector.sendTelemetry('init'), true);
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), true);
  assert.strictEqual(attempts, 1, 'an unchanged heartbeat should not issue another request');

  collector.mouseRecorder.records.push({ time: 16, x: 0.1, y: 0.2, type: 'move' });
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), true);
  assert.strictEqual(attempts, 2, 'new activity must be sent immediately');

  collector.lastSuccessfulSendAt -= 60001;
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), true);
  assert.strictEqual(attempts, 3, 'idle sessions should still send a bounded keepalive');
  collector.destroy();
}

function testActivitySignatureIncludesEarlierPoints() {
  const collector = new BotCollector({ autoSendInterval: 0 });
  const first = {
    pageUrl: '/shop',
    mouse: { records: [{ time: 1, x: 0.1 }, { time: 2, x: 0.5 }], scrollEvents: [] },
  };
  const second = {
    pageUrl: '/shop',
    mouse: { records: [{ time: 1, x: 0.9 }, { time: 2, x: 0.5 }], scrollEvents: [] },
  };
  assert.notStrictEqual(collector.getActivitySignature(first), collector.getActivitySignature(second));
  collector.destroy();
}

async function testIntervalSendsHeartbeatOnlyWhenNeeded() {
  let attempts = 0;
  global.fetch = async () => {
    attempts++;
    return { ok: true };
  };
  const collector = new BotCollector({ endpointUrl: '/telemetry', autoSendInterval: 1000 });
  const resolverIndex = digestResolvers.length;
  const start = collector.start();
  await waitFor(() => digestResolvers.length > resolverIndex);
  digestResolvers[resolverIndex]();
  await start;
  const tick = activeIntervals.get(collector.timer);
  assert.strictEqual(attempts, 1);

  tick();
  await waitFor(() => collector.sendPromise === null);
  assert.strictEqual(attempts, 1, 'idle interval should not send a redundant request');

  collector.mouseRecorder.records.push({ time: 16, x: 0.1, y: 0.2, type: 'move' });
  tick();
  await waitFor(() => attempts === 2 && collector.sendPromise === null);
  assert.strictEqual(attempts, 2, 'interval should send after activity');
  collector.destroy();
}

async function testHeartbeatUpdatesPendingRetryWithoutBypassingBackoff() {
  const requests = [];
  global.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return requests.length === 1
      ? { ok: false, headers: { get: () => '60' } }
      : { ok: true };
  };
  const collector = new BotCollector({ endpointUrl: '/telemetry', autoSendInterval: 0 });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };

  assert.strictEqual(await collector.sendTelemetry('heartbeat'), false);
  const firstBody = collector.pendingRetry.body;
  collector.mouseRecorder.records.push({ time: 16, x: 0.1, y: 0.2, type: 'move' });
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), false);
  assert.strictEqual(requests.length, 1, 'heartbeat must respect pending Retry-After');
  assert.notStrictEqual(collector.pendingRetry.body, firstBody);
  assert.strictEqual(JSON.parse(collector.pendingRetry.body).mouse.records.length, 1);
  collector.destroy();
}

async function testInFlightRetryPreservesNewHeartbeat() {
  const requests = [];
  let resolveOldRetry = null;
  global.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    if (requests.length === 1) return { ok: false };
    if (requests.length === 2) {
      return new Promise((resolve) => {
        resolveOldRetry = () => resolve({ ok: true });
      });
    }
    return { ok: true };
  };
  const collector = new BotCollector({ endpointUrl: '/telemetry', autoSendInterval: 0, retryBaseDelay: 100 });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };

  assert.strictEqual(await collector.sendTelemetry('heartbeat'), false);
  await new Promise((resolve) => setTimeout(resolve, 120));
  await waitFor(() => resolveOldRetry !== null);
  collector.mouseRecorder.records.push({ time: 16, x: 0.1, y: 0.2, type: 'move' });
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), false);
  assert.strictEqual(requests.length, 2, 'new heartbeat should wait for the retry result');

  resolveOldRetry();
  await waitFor(() => collector.pendingRetry && collector.pendingRetry.attempt === 1);
  await new Promise((resolve) => setTimeout(resolve, 120));
  await waitFor(() => requests.length === 3);
  assert.strictEqual(requests[2].mouse.records.length, 1);
  await waitFor(() => collector.pendingRetry === null);
  collector.destroy();
}

async function testRetryAfterIsRespectedAndBounded() {
  global.fetch = async () => ({
    ok: false,
    headers: { get: (name) => name === 'Retry-After' ? '600' : null },
  });
  const collector = new BotCollector({ endpointUrl: '/telemetry', autoSendInterval: 0 });

  assert.strictEqual(await collector.transmitTelemetry('{}', 'heartbeat'), false);
  assert.strictEqual(collector.retryAfterMs, 300000, 'server backoff should be capped at five minutes');
  assert.ok(collector.retryNotBefore > Date.now());
  collector.destroy();
}

async function testExhaustedRetryStillRespectsServerCooldown() {
  let attempts = 0;
  global.fetch = async () => {
    attempts++;
    return attempts === 1
      ? { ok: false, headers: { get: () => '60' } }
      : { ok: true };
  };
  const collector = new BotCollector({ maxRetryAttempts: 0, autoSendInterval: 0 });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };
  assert.strictEqual(await collector.sendTelemetry('init'), false);
  assert.strictEqual(collector.pendingRetry, null);
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), false);
  assert.strictEqual(attempts, 1);
  collector.retryNotBefore = 0;
  assert.strictEqual(await collector.sendTelemetry('heartbeat'), true);
  collector.destroy();
}

async function testOlderRetryCannotDiscardNewerFailedSnapshot() {
  let attempts = 0;
  let resolveOldRetry = null;
  global.fetch = async () => {
    attempts++;
    if (attempts === 1 || attempts === 3) return { ok: false };
    if (attempts === 2) {
      return new Promise((resolve) => {
        resolveOldRetry = () => resolve({ ok: true });
      });
    }
    return { ok: true };
  };
  const collector = new BotCollector({
    endpointUrl: '/telemetry',
    autoSendInterval: 0,
    retryBaseDelay: 100,
    maxRetryAttempts: 2,
  });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { isBot: false, heuristicScore: 0 };

  assert.strictEqual(await collector.sendTelemetry('older'), false);
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.ok(resolveOldRetry, 'the older retry should be in flight');

  assert.strictEqual(await collector.sendTelemetry('newer'), false);
  const newerPending = collector.pendingRetry;
  assert.strictEqual(JSON.parse(newerPending.body).action, 'newer');

  resolveOldRetry();
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(
    collector.pendingRetry,
    newerPending,
    'an older retry completion must preserve the newer failed snapshot',
  );

  await new Promise((resolve) => setTimeout(resolve, 150));
  assert.strictEqual(attempts, 4);
  assert.strictEqual(collector.pendingRetry, null);
  collector.destroy();
}

const testDeadline = setTimeout(() => {
  console.error('collector tests did not complete');
  process.exit(1);
}, 15000);

testRestartDuringFingerprinting()
  .then(testDestroyAbortsStatusRequest)
  .then(testDestroyDuringProfileCollectionStopsWorkerAndInitialSend)
  .then(testPayloadPreservesPassiveProfileWithoutChangingBotdScore)
  .then(testLazyStatusProfileIsCancelledOnDestroy)
  .then(testColdPagehideDoesNotStartOptionalProfileProbe)
  .then(testPagehideBeaconUsesCorsSafelistedContentType)
  .then(testPagehideUsesUtf8ByteLengthAndSequenceWraps)
  .then(testOversizedPagehideRetainsMouseAndMobileDomain)
  .then(testPagehideFetchFallbackAvoidsCorsPreflight)
  .then(testUnchangedHeartbeatIsCoalescedUntilIdleDeadline)
  .then(testActivitySignatureIncludesEarlierPoints)
  .then(testIntervalSendsHeartbeatOnlyWhenNeeded)
  .then(testHeartbeatUpdatesPendingRetryWithoutBypassingBackoff)
  .then(testInFlightRetryPreservesNewHeartbeat)
  .then(testRetryAfterIsRespectedAndBounded)
  .then(testExhaustedRetryStillRespectsServerCooldown)
  .then(testFailedDetectionDoesNotPromoteClientFlag)
  .then(testTouchIsTaggedAndExcludedFromMouseChunks)
  .then(testTapCompatibilityMouseEventsAreNotMouseInput)
  .then(testDispatchedMouseEventsCannotSupplyBehavioralEvidence)
  .then(testResizeDoesNotCreateMouseMovement)
  .then(testClickGeometryAndPressTimingAreRecorded)
  .then(testPointerStatsCountCoalescedMouseSamples)
  .then(testFrameIntervalIsMeasuredOnce)
  .then(testFailedHeartbeatRetriesLatestSnapshot)
  .then(testHeartbeatRecoversAfterRetryBudgetIsExhausted)
  .then(testClickBurstRetainsMouseEvidenceAndLongUrlIsBounded)
  .then(testOlderRetryCannotDiscardNewerFailedSnapshot)
  .then(testSessionContinuesAcrossPagesOfOneTab)
  .then(testKeyboardTimingAndPressPressure)
  .then(testTouchGesturesAreCaptured)
  .then(() => {
    clearTimeout(testDeadline);
    console.log('collector lifecycle tests: OK');
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });

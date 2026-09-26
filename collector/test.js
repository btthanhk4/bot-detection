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

  recorder.handleMouseMove({ clientX: 10, clientY: 20 });
  assert.strictEqual(recorder.records[30].source, 'mouse');
  assert.strictEqual(recorder.records[30].speed, 0);
  collector.destroy();
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
  const start = collector.start();
  await waitFor(() => digestResolvers.length === 3);
  digestResolvers[2]();
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

testRestartDuringFingerprinting()
  .then(testDestroyAbortsStatusRequest)
  .then(testPagehideBeaconUsesCorsSafelistedContentType)
  .then(testPagehideUsesUtf8ByteLengthAndSequenceWraps)
  .then(testPagehideFetchFallbackAvoidsCorsPreflight)
  .then(testUnchangedHeartbeatIsCoalescedUntilIdleDeadline)
  .then(testActivitySignatureIncludesEarlierPoints)
  .then(testIntervalSendsHeartbeatOnlyWhenNeeded)
  .then(testHeartbeatUpdatesPendingRetryWithoutBypassingBackoff)
  .then(testInFlightRetryPreservesNewHeartbeat)
  .then(testRetryAfterIsRespectedAndBounded)
  .then(testFailedDetectionDoesNotPromoteClientFlag)
  .then(testTouchIsTaggedAndExcludedFromMouseChunks)
  .then(testFailedHeartbeatRetriesLatestSnapshot)
  .then(testOlderRetryCannotDiscardNewerFailedSnapshot)
  .then(() => console.log('collector lifecycle tests: OK'))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });

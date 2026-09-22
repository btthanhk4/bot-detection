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

const activeIntervals = new Set();
let nextInterval = 1;
global.setInterval = () => {
  const id = nextInterval++;
  activeIntervals.add(id);
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
  .then(testFailedHeartbeatRetriesLatestSnapshot)
  .then(testOlderRetryCannotDiscardNewerFailedSnapshot)
  .then(() => console.log('collector lifecycle tests: OK'))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });

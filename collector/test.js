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

testRestartDuringFingerprinting()
  .then(testDestroyAbortsStatusRequest)
  .then(() => console.log('collector lifecycle tests: OK'))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });

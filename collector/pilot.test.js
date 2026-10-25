const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require('path').join(__dirname, 'src/pilot.js'), 'utf8')
  .replace(/^export /gm, '');

function bootstrap(attributes = {}, extra = {}) {
  const errors = [];
  const window = extra.window || { location: { protocol: 'https:' } };
  class Collector {
    constructor(options) { Object.assign(this, options); this.sessionId = 'session'; }
    async start() { this.starts = (this.starts || 0) + 1; return this; }
    destroy() { this.destroyed = true; }
  }
  const context = {
    URL, BotCollector: Collector, window,
    document: { currentScript: {
      src: 'https://api.example.org/prefix/bot-collector.js',
      hasAttribute: (name) => Object.prototype.hasOwnProperty.call(attributes, name),
      getAttribute: (name) => attributes[name] ?? null,
    } },
    console: { error: (...args) => errors.push(args.join(' ')) },
  };
  vm.runInNewContext(source, context);
  return { pilot: window.DatacatPilot, context, errors };
}

const attributes = { 'data-datacat': '', 'data-study-id': 'thesis_01', 'data-site-id': 'site_01' };

async function run() {
  assert.strictEqual(bootstrap().pilot, undefined, 'manual SDK loading must not auto-start');
  const manual = bootstrap(attributes, { window: { location: { protocol: 'https:' }, _bc: { sendTelemetry() {} } } });
  assert.strictEqual(manual.pilot, undefined, 'manual and auto integrations must not collect twice');
  assert.strictEqual(manual.errors.length, 1);
  const { pilot, context, errors } = bootstrap(attributes);
  await pilot.ready;
  assert.strictEqual(errors.length, 0);
  assert.strictEqual(pilot.collector.endpointUrl, 'https://api.example.org/prefix/api/v1/telemetry');
  assert.strictEqual(pilot.collector.detectUrl, 'https://api.example.org/prefix/api/v1/detect');
  vm.runInNewContext(source, context);
  assert.strictEqual(pilot.collector.starts, 1, 'duplicate tags must not duplicate collection');
  pilot.stop();
  assert.strictEqual(pilot.getStatus().stopped, true);
  assert.strictEqual(bootstrap({ ...attributes, 'data-study-id': '' }).pilot, undefined);
  assert.strictEqual(bootstrap({ ...attributes, 'data-site-id': '../wrong' }).pilot, undefined);
  assert.strictEqual(bootstrap({ ...attributes, 'data-interval-ms': '0' }).pilot, undefined);
  assert.strictEqual(bootstrap({ ...attributes, 'data-endpoint': 'http://api.example.org/telemetry' }).pilot, undefined);
  assert.strictEqual(bootstrap({ ...attributes, 'data-endpoint': 'javascript:alert(1)' }).pilot, undefined);
  const overridden = bootstrap({ ...attributes, 'data-endpoint': 'https://other.example.org/api/v1/telemetry' });
  assert.strictEqual(overridden.pilot.collector.endpointUrl, 'https://other.example.org/api/v1/telemetry');
  const conflicting = bootstrap({ ...attributes, 'data-study-id': 'other' }, { window: context.window });
  assert.strictEqual(conflicting.errors.length, 1);
  assert.strictEqual(conflicting.pilot, pilot);

  const SDK = require('./dist/bot-collector.js');
  const collector = new SDK({ studyId: 'study', siteId: 'site', autoSendInterval: 0 });
  collector.cachedFingerprint = { visitorId: 'visitor', components: {} };
  collector.cachedBotd = { heuristicScore: 0 };
  const payload = await collector.getPayload();
  assert.strictEqual(payload.collector.sdkVersion, require('./package.json').version);
  assert.strictEqual(payload.collector.studyId, 'study');
  assert.strictEqual(payload.collector.siteId, 'site');
  assert.strictEqual(payload.mouse.coordinateFrame.timestampResolutionMs, 1);
  const firstFrame = payload.mouse.coordinateFrame.id;
  collector.mouseRecorder.clear();
  assert.strictEqual(collector.mouseRecorder.exportData().coordinateFrame.id, firstFrame + 1);
  global.fetch = async () => ({ ok: true, status: 200, json: async () => ({
    recorded: true, capture_id: 'capture', persisted: true, buffered: false,
    capture_persisted: false, capture_buffered: true, analysis_available: true,
  }) });
  assert.strictEqual(await collector.sendTelemetry('init'), true);
  assert.strictEqual(collector.lastReceipt.captureId, 'capture');
  assert.strictEqual(collector.lastReceipt.persisted, false, 'summary persistence is not raw capture persistence');
  assert.strictEqual(collector.lastReceipt.buffered, true);
  assert.strictEqual(collector.lastDelivery.acknowledged, true);
  global.fetch = async () => ({ ok: true, status: 202, json: async () => ({
    recorded: true, capture_id: 'raw-only', persisted: true, buffered: false, analysis_available: false,
  }) });
  await collector.sendTelemetry('next');
  assert.strictEqual(collector.lastReceipt.analysisAvailable, false);
  assert.strictEqual(collector.lastReceipt.persisted, true);
  global.fetch = async () => ({ ok: true, status: 200, json: async () => { throw new Error('HTML response'); } });
  await collector.sendTelemetry('html');
  assert.strictEqual(collector.lastDelivery.acknowledged, false);
  assert.strictEqual(collector.lastReceipt.captureId, 'raw-only', 'bad responses must not create a new receipt');

  let resolveJson;
  global.fetch = async () => ({ ok: true, status: 200, json: () => new Promise((resolve) => { resolveJson = resolve; }) });
  const pending = collector.sendTelemetry('pending');
  while (!resolveJson) await new Promise((resolve) => setImmediate(resolve));
  const oldNavigator = Object.getOwnPropertyDescriptor(global, 'navigator');
  Object.defineProperty(global, 'navigator', { configurable: true, value: { sendBeacon: () => true } });
  try {
    await collector.sendTelemetry('pagehide');
    resolveJson({ recorded: true, capture_id: 'later-receipt', persisted: true });
    await pending;
    assert.strictEqual(collector.lastDelivery.transport, 'beacon');
    assert.strictEqual(collector.lastDelivery.acknowledged, false, 'fetch completion cannot acknowledge a beacon');
  } finally {
    if (oldNavigator) Object.defineProperty(global, 'navigator', oldNavigator);
    else delete global.navigator;
    collector.destroy();
  }
  const stalled = new SDK({ autoSendInterval: 0, maxRetryAttempts: 0 });
  stalled.cachedFingerprint = { visitorId: 'visitor', components: {} };
  stalled.cachedBotd = {};
  const timedFetch = stalled.fetchWithTimeout.bind(stalled);
  stalled.fetchWithTimeout = (url, options, _timeout, consume) => timedFetch(url, options, 30, consume);
  global.fetch = async (_url, options) => ({ ok: true, status: 200,
    json: () => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        const error = new Error('response body aborted'); error.name = 'AbortError'; reject(error);
      }, { once: true });
    }),
  });
  assert.strictEqual(await stalled.sendTelemetry('stalled-body'), false, 'body reads must remain within the request timeout');
  assert.strictEqual(stalled.sendPromise, null);
  assert.strictEqual(stalled.abortControllers.size, 0);
  assert.strictEqual(stalled.lastReceipt, null);
  const missingStatus = await stalled.checkBotStatus();
  assert.strictEqual(missingStatus.fallback, true);
  assert.strictEqual(missingStatus.bot_probability, null);
  global.fetch = async () => ({ ok: true, status: 202, json: async () => ({ recorded: true, capture_id: 'recovered' }) });
  assert.strictEqual(await stalled.sendTelemetry('recovered-body'), true);
  assert.strictEqual(stalled.lastReceipt.captureId, 'recovered');
  stalled.destroy();
  console.log('pilot integration and receipt tests: OK');
}

run().catch((error) => { console.error(error); process.exit(1); });

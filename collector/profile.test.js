const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(require.resolve('./src/profile.js'), 'utf8').replace(/^export /gm, '');
function load(overrides = {}) {
  return vm.runInNewContext(`${source}\n({ collectBrowserProfile, readProfileNavigator });`, {
    setTimeout, clearTimeout, Blob, AbortController, ...overrides,
  });
}

async function main() {
  const { readProfileNavigator } = load();
  const unsupported = await readProfileNavigator({ userAgent: 'Firefox', hardwareConcurrency: 8 });
  assert.strictEqual(unsupported.clientHintsStatus, 'unsupported');
  assert.strictEqual(unsupported.webdriver, null);

  const hints = {
    platform: 'Windows', mobile: false,
    brands: [{ brand: 'Chromium', version: '153' }],
    getHighEntropyValues: async () => ({ fullVersionList: [{ brand: 'HeadlessChrome', version: '153.0' }] }),
  };
  const measured = await readProfileNavigator({ userAgentData: hints });
  assert.strictEqual(measured.clientHintsStatus, 'ok');
  assert.strictEqual(measured.clientHints.fullVersionList[0].brand, 'HeadlessChrome');

  const timedOut = await readProfileNavigator({
    userAgentData: { ...hints, getHighEntropyValues: () => new Promise(() => {}) },
  }, 10);
  assert.strictEqual(timedOut.clientHintsStatus, 'timeout');
  assert.strictEqual(timedOut.clientHints.brands[0].brand, 'Chromium');
  const denied = await readProfileNavigator({
    userAgentData: { ...hints, getHighEntropyValues: () => { throw new Error('denied'); } },
  });
  assert.strictEqual(denied.clientHintsStatus, 'error');

  const protectedNavigator = {};
  Object.defineProperty(protectedNavigator, 'userAgentData', { get() { throw new Error('blocked'); } });
  assert.strictEqual((await readProfileNavigator(protectedNavigator)).clientHintsStatus, 'unsupported');

  const bounded = await readProfileNavigator({
    userAgent: 'x'.repeat(2000),
    userAgentData: { brands: Array.from({ length: 20 }, () => ({ brand: 'b'.repeat(100), version: 'v'.repeat(100) })) },
  });
  assert.strictEqual(bounded.userAgent.length, 1024);
  assert.strictEqual(bounded.clientHints.brands.length, 8);
  assert.strictEqual(bounded.clientHints.brands[0].brand.length, 64);

  let created = 0;
  let revoked = 0;
  let terminated = 0;
  const urls = { createObjectURL: () => { created++; return 'blob:probe'; }, revokeObjectURL: () => { revoked++; } };
  const blocked = await load({
    URL: urls, Worker: class { constructor() { throw new Error('CSP'); } },
  }).collectBrowserProfile();
  assert.strictEqual(blocked.workerStatus, 'error');
  assert.strictEqual(revoked, created);

  const successful = await load({
    URL: urls, window: { isSecureContext: true },
    Worker: class {
      constructor() { setTimeout(() => this.onmessage({ data: { userAgent: 'Worker UA' } }), 0); }
      terminate() { terminated++; }
    },
  }).collectBrowserProfile();
  assert.strictEqual(successful.workerStatus, 'ok');
  assert.strictEqual(successful.worker.userAgent, 'Worker UA');
  assert.strictEqual(successful.secureContext, true);
  assert.strictEqual(terminated, 1);

  const timedWorker = await load({
    URL: urls, Worker: class { terminate() { terminated++; } },
  }).collectBrowserProfile({ timeoutMs: 10 });
  assert.strictEqual(timedWorker.workerStatus, 'timeout');
  assert.strictEqual(terminated, 2);

  const controller = new AbortController();
  const cancelledPromise = load({
    URL: urls, Worker: class { terminate() { terminated++; } },
  }).collectBrowserProfile({ signal: controller.signal });
  controller.abort();
  assert.strictEqual((await cancelledPromise).workerStatus, 'cancelled');
  assert.strictEqual(terminated, 3);
  assert.strictEqual(revoked, created);
  const alreadyCancelled = await load({ URL: urls, Worker: class {} })
    .collectBrowserProfile({ signal: controller.signal });
  assert.strictEqual(alreadyCancelled.workerStatus, 'cancelled');
  assert.strictEqual(revoked, created);
  console.log('passive profile tests: OK');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });

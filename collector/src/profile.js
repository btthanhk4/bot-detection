/** Bounded, passive profile observations for offline/shadow evaluation. */

export async function readProfileNavigator(nav, timeoutMs = 1000) {
  const read = (key) => {
    try { return nav[key]; } catch (e) { return undefined; }
  };
  const text = (value) => typeof value === 'string' ? value.slice(0, 1024) : null;
  const brands = (value) => Array.isArray(value) ? value.slice(0, 8)
    .filter((entry) => entry && typeof entry.brand === 'string' && typeof entry.version === 'string')
    .map((entry) => ({ brand: entry.brand.slice(0, 64), version: entry.version.slice(0, 64) })) : [];
  const webdriver = read('webdriver');
  const cpu = read('hardwareConcurrency');
  const result = {
    userAgent: text(read('userAgent')),
    platform: text(read('platform')),
    hardwareConcurrency: typeof cpu === 'number' && Number.isFinite(cpu) ? cpu : null,
    webdriver: typeof webdriver === 'boolean' ? webdriver : null,
    clientHints: null,
    clientHintsStatus: 'unsupported',
  };
  const hints = read('userAgentData');
  if (!hints) return result;
  let timer;
  try {
    result.clientHints = {
      brands: brands(hints.brands),
      platform: text(hints.platform),
      mobile: typeof hints.mobile === 'boolean' ? hints.mobile : null,
      fullVersionList: [],
    };
    result.clientHintsStatus = 'partial';
    if (typeof hints.getHighEntropyValues !== 'function') return result;
    const extra = await Promise.race([
      Promise.resolve().then(() => hints.getHighEntropyValues(['fullVersionList'])),
      new Promise((resolve) => { timer = setTimeout(() => resolve(null), timeoutMs); }),
    ]);
    if (extra && typeof extra === 'object') {
      result.clientHints.fullVersionList = brands(extra.fullVersionList);
      result.clientHintsStatus = 'ok';
    } else {
      result.clientHintsStatus = extra === null ? 'timeout' : 'error';
    }
  } catch (e) {
    result.clientHintsStatus = 'error';
  } finally {
    if (timer) clearTimeout(timer);
  }
  return result;
}

export async function collectBrowserProfile({ timeoutMs = 1000, signal } = {}) {
  const limit = Math.max(10, Math.min(3000, Number(timeoutMs) || 1000));
  const nav = typeof navigator !== 'undefined' ? navigator : {};
  const mainPromise = readProfileNavigator(nav, limit);
  let worker = null;
  let workerUrl = null;
  let timer = null;
  let onAbort = null;
  let workerStatus = 'unsupported';
  const workerPromise = new Promise((resolve) => {
    if (signal?.aborted) { workerStatus = 'cancelled'; resolve(null); return; }
    if (typeof Worker === 'undefined' || typeof URL === 'undefined'
        || typeof URL.createObjectURL !== 'function' || typeof Blob === 'undefined') {
      resolve(null);
      return;
    }
    let settled = false;
    const finish = (status, value = null) => {
      if (settled) return;
      settled = true;
      workerStatus = status;
      resolve(value);
    };
    try {
      workerUrl = URL.createObjectURL(new Blob([
        `(${readProfileNavigator.toString()})(navigator, ${limit}).then(value => postMessage(value)).catch(() => postMessage(null));`,
      ], { type: 'text/javascript' }));
      worker = new Worker(workerUrl);
      timer = setTimeout(() => finish('timeout'), limit);
      worker.onmessage = (event) => finish(event.data ? 'ok' : 'error', event.data);
      worker.onerror = (event) => {
        if (typeof event.preventDefault === 'function') event.preventDefault();
        finish('error');
      };
      onAbort = () => finish('cancelled');
      if (signal) signal.addEventListener('abort', onAbort, { once: true });
    } catch (e) {
      finish('error');
    }
  });
  try {
    const [main, workerProfile] = await Promise.all([mainPromise, workerPromise]);
    return {
      schema: 'browser-profile-v1',
      secureContext: typeof window !== 'undefined' && window.isSecureContext === true,
      main,
      worker: workerProfile,
      workerStatus,
    };
  } finally {
    if (timer) clearTimeout(timer);
    if (signal && onAbort) signal.removeEventListener('abort', onAbort);
    try { if (worker) worker.terminate(); } catch (e) {}
    try { if (workerUrl) URL.revokeObjectURL(workerUrl); } catch (e) {}
  }
}

/**
 * Automation and tampering probes (BotD v2 layer).
 *
 * Sources: FingerprintJS BotD detectors (MIT), FPScanner (MIT), Castle and cside
 * write-ups on Playwright/CDP artefacts. Each probe is a boolean that is true only
 * when the evidence is present; a probe that cannot run returns false and is
 * listed in `unavailable`. Nothing here changes page state that the site can see.
 *
 * Collector 1.11: source checks and the DevTools probe use built-ins from a fresh
 * realm (see pristine.js), not the page's copies that monitoring libraries wrap.
 */
import { withPristineRealm } from './pristine.js';

function nativeSource(fn, toString = Function.prototype.toString) {
  try {
    return typeof fn === 'function' && /\{\s*\[native code\]\s*\}\s*$/.test(toString.call(fn));
  } catch (e) {
    return false;
  }
}

function getterOf(proto, name) {
  try {
    const descriptor = proto && Object.getOwnPropertyDescriptor(proto, name);
    return descriptor ? descriptor.get || null : undefined;
  } catch (e) {
    return undefined;
  }
}

export function collectAutomationSignals(nav, win, doc) {
  if (!doc || typeof doc.createElement !== 'function') return collectSignals(nav, win, doc, null);
  return withPristineRealm(doc, (realm) => collectSignals(nav, win, doc, realm));
}

function collectSignals(nav, win, doc, realm) {
  const out = {};
  const unavailable = [];
  // Function.prototype.toString of an untouched realm sees through a page that patched its own.
  const realmToString = realm && realm.Function && realm.Function.prototype.toString;
  const isNative = (fn) => nativeSource(fn, realmToString || Function.prototype.toString);
  out.pristineRealm = Boolean(realmToString);
  const ua = String((nav && nav.userAgent) || '');
  const chromium = /Chrome\//.test(ua) && !/Firefox\//.test(ua);
  const desktop = !/Android|iPhone|iPad|iPod|Mobile/i.test(ua);
  const navProto = (() => { try { return Object.getPrototypeOf(nav); } catch (e) { return null; } })();

  // Framework globals: injected only by Playwright / ChromeDriver / Selenium.
  out.playwrightGlobals = false;
  try {
    out.playwrightGlobals = '__pwInitScripts' in win || '__playwright__binding__' in win
      || '__playwright_evaluation_script__' in win;
    if (!out.playwrightGlobals) {
      for (const key of Object.keys(win).slice(0, 2000)) {
        const value = win[key];
        if (typeof value === 'function' && typeof value.__installed === 'boolean') {
          out.playwrightGlobals = true;
          break;
        }
      }
    }
  } catch (e) { unavailable.push('playwrightGlobals'); }

  // With a DevTools Protocol client attached (Runtime.enable) console previews read
  // Error#name a second time. Measured on Chrome/Edge 155-156: genuine 1 read per
  // call, Playwright/Puppeteer/Selenium 2, Patchright 1. Open DevTools also reads
  // twice, so developers look the same. The console comes from the fresh realm: a
  // page console wrapped by Sentry or LogRocket serialises its arguments and reads
  // the name itself (2 reads in a genuine browser, 2026-10-29).
  out.cdpRuntime = false;
  try {
    const probeConsole = (realm && realm.console) || win.console;
    if (chromium && probeConsole && typeof probeConsole.debug === 'function') {
      let reads = 0;
      class ProbeError extends Error {}
      Object.defineProperty(ProbeError.prototype, 'name', { configurable: true, get() { reads++; return 'Error'; } });
      probeConsole.debug(new ProbeError(''));
      out.cdpRuntime = reads >= 2;
    }
  } catch (e) { unavailable.push('cdpRuntime'); }

  out.seleniumGlobals = false;
  try {
    const props = ['__driver_evaluate', '__webdriver_evaluate', '__selenium_evaluate', '__fxdriver_evaluate',
      '__driver_unwrapped', '__webdriver_unwrapped', '__selenium_unwrapped', '__fxdriver_unwrapped',
      '_Selenium_IDE_Recorder', '_selenium', 'calledSelenium', '$chrome_asyncScriptInfo',
      '__$webdriverAsyncExecutor', '__webdriverFunc', '__lastWatirAlert', '__lastWatirConfirm',
      '__lastWatirPrompt', '__webdriver_script_fn', '_WEBDRIVER_ELEM_CACHE', 'domAutomation',
      'domAutomationController', 'callPhantom', '_phantom', '__nightmare'];
    out.seleniumGlobals = props.some((p) => p in win || (doc && p in doc));
  } catch (e) { unavailable.push('seleniumGlobals'); }

  // navigator.webdriver is a native getter on Navigator.prototype in Chromium,
  // Gecko and WebKit. Stealth kits delete it or replace it with a JS function.
  const webdriverGetter = getterOf(navProto, 'webdriver');
  out.webdriverDeleted = chromium && webdriverGetter === undefined;
  out.webdriverPatched = false;
  try {
    out.webdriverPatched = Object.prototype.hasOwnProperty.call(nav, 'webdriver')
      || (webdriverGetter !== undefined && webdriverGetter !== null && !isNative(webdriverGetter));
  } catch (e) { unavailable.push('webdriverPatched'); }

  // Non-native navigator getters reveal JS-level spoofing. Privacy extensions can
  // do the same, so this is tampering evidence, not proof of automation.
  out.navigatorGetterPatched = false;
  try {
    const names = ['userAgent', 'platform', 'languages', 'plugins', 'hardwareConcurrency', 'deviceMemory', 'vendor'];
    out.navigatorGetterPatched = names.some((name) => {
      const getter = getterOf(navProto, name);
      return getter !== undefined && getter !== null && !isNative(getter);
    }) || names.some((name) => Object.prototype.hasOwnProperty.call(nav, name));
  } catch (e) { unavailable.push('navigatorGetterPatched'); }

  // Research only since policy 25: Sentry and zone.js patch toString on ordinary sites.
  out.toStringPatched = false;
  try {
    out.toStringPatched = !isNative(Function.prototype.toString)
      || Function.prototype.toString.call(Function.prototype.toString).indexOf('toString') === -1;
  } catch (e) { out.toStringPatched = true; }

  // The coalesced-sample API the API reads pointer timing from (policy 23). Fingerprint
  // extensions and monitoring libraries leave it alone; a script evading the timing checks
  // does not. requestAnimationFrame is wrapped by Sentry and New Relic, so it is only
  // reported (rafWrapped); the frame probe calls the fresh realm's copy instead.
  out.inputApiPatched = false;
  out.rafWrapped = false;
  try {
    const coalesced = win.PointerEvent && win.PointerEvent.prototype.getCoalescedEvents;
    out.inputApiPatched = typeof coalesced === 'function' && !isNative(coalesced);
    out.rafWrapped = typeof win.requestAnimationFrame === 'function' && !isNative(win.requestAnimationFrame);
  } catch (e) { unavailable.push('inputApiPatched'); }

  out.missingChromeObject = chromium && desktop && typeof win.chrome === 'undefined';

  try {
    out.productSubMismatch = (chromium || /Safari\//.test(ua)) && nav.productSub !== undefined
      && nav.productSub !== '20030107';
  } catch (e) { out.productSubMismatch = false; unavailable.push('productSub'); }

  try {
    out.appVersionAutomation = /headless|electron|slimerjs/i.test(String(nav.appVersion || ''));
  } catch (e) { out.appVersionAutomation = false; }

  try {
    out.pluginsPrototypeMismatch = typeof PluginArray !== 'undefined' && nav.plugins !== undefined
      && !(nav.plugins instanceof PluginArray);
    out.mimeTypesPrototypeMismatch = typeof MimeTypeArray !== 'undefined' && nav.mimeTypes !== undefined
      && !(nav.mimeTypes instanceof MimeTypeArray);
  } catch (e) {
    out.pluginsPrototypeMismatch = false;
    out.mimeTypesPrototypeMismatch = false;
  }

  try {
    out.sequentum = !!(win.external && /Sequentum/i.test(String(win.external)));
  } catch (e) { out.sequentum = false; }

  try {
    const connection = nav.connection;
    out.rttZero = chromium && desktop && !!connection && connection.rtt === 0;
  } catch (e) { out.rttZero = false; }

  try {
    out.headlessScreen = (win.screen && win.screen.width === 800 && win.screen.height === 600) || false;
    out.noBrowserFrame = win.outerWidth > 0 && win.outerWidth === win.innerWidth
      && win.outerHeight === win.innerHeight;
  } catch (e) {
    out.headlessScreen = false;
    out.noBrowserFrame = false;
  }

  try {
    out.utcTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone === 'UTC';
  } catch (e) { out.utcTimezone = false; }

  try {
    const cpu = nav.hardwareConcurrency;
    const memory = nav.deviceMemory;
    out.impossibleHardware = (typeof cpu === 'number' && (cpu < 1 || cpu > 128))
      || (typeof memory === 'number' && (memory < 0.25 || memory > 64));
  } catch (e) { out.impossibleHardware = false; }

  // UA string versus User-Agent Client Hints: a UA override that forgets the hints.
  out.uaHintsMismatch = false;
  try {
    const hints = nav.userAgentData;
    if (chromium && hints && Array.isArray(hints.brands)) {
      const major = (ua.match(/Chrome\/(\d+)/) || [])[1];
      const brand = hints.brands.find((b) => /Chrom/.test(b.brand));
      if (major && brand && brand.version && String(brand.version) !== major) out.uaHintsMismatch = true;
      if (hints.brands.some((b) => /HeadlessChrome/i.test(b.brand)) && !/HeadlessChrome/.test(ua)) out.uaHintsMismatch = true;
    }
  } catch (e) { unavailable.push('uaHintsMismatch'); }

  // GPU string versus claimed OS: Windows Chromium renders through ANGLE/Direct3D,
  // macOS through Metal/OpenGL. Spoofing kits often paste a Mac renderer on Windows.
  out.gpuOsMismatch = false;
  try {
    const renderer = String(webglRenderer(doc) || '');
    if (renderer) {
      if (/Windows/.test(ua) && /OpenGL Engine|Apple (M\d|GPU)|Metal/.test(renderer)) out.gpuOsMismatch = true;
      if (/Mac OS X|Macintosh/.test(ua) && /Direct3D|D3D11|D3D9/.test(renderer)) out.gpuOsMismatch = true;
    }
  } catch (e) { unavailable.push('gpuOsMismatch'); }

  // Real Client Hints brand lists never contain an empty brand or duplicates.
  out.malformedBrands = false;
  try {
    const hints = nav.userAgentData;
    if (hints && Array.isArray(hints.brands)) {
      const names = hints.brands.map((b) => String((b && b.brand) || '').trim());
      out.malformedBrands = names.some((name) => name === '') || new Set(names).size !== names.length;
    }
  } catch (e) { unavailable.push('malformedBrands'); }

  out.unavailable = unavailable;
  return out;
}

function webglRenderer(doc) {
  const canvas = doc.createElement('canvas');
  const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
  if (!gl) return null;
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
}

const PERMISSION_STATE = { default: 'prompt', granted: 'granted', denied: 'denied' };

/**
 * Notification.permission and the Permissions API describe the same state. Legacy
 * headless Chrome and the stealth "permissions" patch make them disagree.
 * Returns true (mismatch), false (consistent) or null (not measurable).
 */
export async function probeNotificationPermission(nav, win, timeoutMs = 500) {
  try {
    if (!win.Notification || !nav.permissions || typeof nav.permissions.query !== 'function') return null;
    const query = nav.permissions.query({ name: 'notifications' });
    const status = await Promise.race([query, new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs))]);
    if (!status || !status.state) return null;
    const expected = PERMISSION_STATE[win.Notification.permission];
    return expected ? expected !== status.state : null;
  } catch (e) {
    return null;
  }
}

const WORKER_SOURCE = `(() => {
  const out = { ua: navigator.userAgent, platform: navigator.platform, cpu: navigator.hardwareConcurrency,
    webdriver: navigator.webdriver === true, renderer: null };
  try {
    if (typeof OffscreenCanvas !== 'undefined') {
      const gl = new OffscreenCanvas(1, 1).getContext('webgl');
      if (gl) {
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        out.renderer = String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
      }
    }
  } catch (e) {}
  postMessage(out);
})();`;

/**
 * JS-level spoofing usually patches the page but not a dedicated worker, which
 * runs a fresh navigator and WebGL. Compares CPU count, UA, platform, webdriver
 * and the WebGL renderer between the two contexts.
 */
// A site whose Content-Security-Policy forbids blob: workers (or requires Trusted Types)
// reports a violation every time the probe tries. After one refusal the collector skips the
// probe on that site for a day (collector 1.11), so the site's CSP reports are not flooded.
const WORKER_BLOCKED_KEY = 'datacat_worker_blocked';
const WORKER_BLOCKED_MS = 24 * 3600 * 1000;

function workerBlocked(win) {
  try {
    const since = Number(win.localStorage.getItem(WORKER_BLOCKED_KEY));
    return Number.isFinite(since) && since > 0 && Date.now() - since < WORKER_BLOCKED_MS;
  } catch (e) { return false; }
}

function rememberWorkerBlocked(win) {
  try { win.localStorage.setItem(WORKER_BLOCKED_KEY, String(Date.now())); } catch (e) { /* optional */ }
}

export function probeWorkerConsistency(nav, win, doc, timeoutMs = 800) {
  return new Promise((resolve) => {
    let worker = null;
    let url = null;
    let timer = null;
    let onViolation = null;
    const finish = (value) => {
      if (timer) clearTimeout(timer);
      try { if (onViolation) doc.removeEventListener('securitypolicyviolation', onViolation); } catch (e) {}
      try { if (worker) worker.terminate(); } catch (e) {}
      try { if (url) URL.revokeObjectURL(url); } catch (e) {}
      resolve(value);
    };
    try {
      if (typeof Worker === 'undefined' || typeof Blob === 'undefined' || typeof URL === 'undefined'
          || workerBlocked(win)) {
        finish(null);
        return;
      }
      url = URL.createObjectURL(new Blob([WORKER_SOURCE], { type: 'text/javascript' }));
      onViolation = (event) => {
        if (String((event && event.blockedURI) || '').indexOf('blob') === 0) {
          rememberWorkerBlocked(win);
          finish(null);
        }
      };
      try { doc.addEventListener('securitypolicyviolation', onViolation); } catch (e) {}
      try {
        worker = new Worker(url);
      } catch (e) {
        // Trusted Types or a CSP that throws synchronously.
        rememberWorkerBlocked(win);
        finish(null);
        return;
      }
      timer = setTimeout(() => finish(null), timeoutMs);
      worker.onerror = (event) => { if (event && event.preventDefault) event.preventDefault(); finish(null); };
      worker.onmessage = (event) => {
        const w = event.data || {};
        let mainRenderer = null;
        try { mainRenderer = webglRenderer(doc); } catch (e) {}
        const cpu = nav.hardwareConcurrency;
        finish({
          cpuMismatch: typeof w.cpu === 'number' && typeof cpu === 'number' && w.cpu !== cpu,
          uaMismatch: typeof w.ua === 'string' && w.ua !== nav.userAgent,
          platformMismatch: typeof w.platform === 'string' && w.platform !== nav.platform
            && !(/iPhone|iPad|iPod/.test(w.platform) && /Mac/.test(nav.platform)),
          webdriver: w.webdriver === true,
          rendererMismatch: !!(w.renderer && mainRenderer && String(mainRenderer) !== w.renderer),
        });
      };
    } catch (e) {
      finish(null);
    }
  });
}

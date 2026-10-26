(function (global, factory) {
  typeof exports === 'object' && typeof module !== 'undefined' ? module.exports = factory() :
  typeof define === 'function' && define.amd ? define(factory) :
  (global = typeof globalThis !== 'undefined' ? globalThis : global || self, global.BotCollector = factory());
})(this, (function () { 'use strict';

  // --- FingerprintJS Hardware Components ---
  /**
   * Lightweight Browser & Device Fingerprint Extractor
   * Inspired by FingerprintJS (https://github.com/fingerprintjs/fingerprintjs)
   * Collects 25 browser/hardware fields and generates a deterministic visitor ID hash.
   */

  // Simple 32-bit FNV-1a hash
  function fnv1a(str) {
    let hash = 2166136261;
    for (let i = 0; i < str.length; i++) {
      hash ^= str.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
  }

  async function hashVisitorId(value) {
    try {
      if (typeof crypto !== 'undefined' && crypto.subtle && typeof TextEncoder !== 'undefined') {
        const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
        return Array.from(new Uint8Array(digest).slice(0, 16))
          .map((byte) => byte.toString(16).padStart(2, '0'))
          .join('');
      }
    } catch (e) {}

    // Compatibility fallback: four independently salted 32-bit hashes (128 bits).
    return [0, 1, 2, 3].map((salt) => fnv1a(`${salt}:${value}`)).join('');
  }

  function supportsStorage(win, key) {
    try {
      return typeof win[key] !== 'undefined';
    } catch (e) {
      return false;
    }
  }

  // Canvas fingerprinting
  function getCanvasFingerprint() {
    try {
      if (typeof document === 'undefined') return 'unsupported';
      const canvas = document.createElement('canvas');
      canvas.width = 240;
      canvas.height = 60;
      const ctx = canvas.getContext('2d');
      if (!ctx) return 'unsupported';

      ctx.textBaseline = 'top';
      ctx.font = "14px 'Arial', sans-serif";
      ctx.textBaseline = 'alphabetic';
      ctx.fillStyle = '#f60';
      ctx.fillRect(125, 1, 62, 20);
      ctx.fillStyle = '#069';
      ctx.fillText('SilkmoonBotD, 😃 2026', 2, 15);
      ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
      ctx.fillText('SilkmoonBotD, 😃 2026', 4, 17);

      return fnv1a(canvas.toDataURL());
    } catch (e) {
      return 'error';
    }
  }

  // WebGL fingerprinting (Renderer & Vendor)
  function getWebGLFingerprint() {
    try {
      if (typeof document === 'undefined') return { vendor: 'unsupported', renderer: 'unsupported' };
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      if (!gl) return { vendor: 'unsupported', renderer: 'unsupported' };

      const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
      if (!debugInfo) return { vendor: 'no_debug_info', renderer: 'no_debug_info' };

      return {
        vendor: gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) || 'unknown',
        renderer: gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || 'unknown',
      };
    } catch (e) {
      return { vendor: 'error', renderer: 'error' };
    }
  }

  // Audio fingerprinting via OfflineAudioContext
  async function getAudioFingerprint() {
    try {
      const win = typeof window !== 'undefined' ? window : {};
      const AudioCtx = win.OfflineAudioContext || win.webkitOfflineAudioContext;
      if (!AudioCtx) return 'unsupported';

      const ctx = new AudioCtx(1, 44100, 44100);
      const osc = ctx.createOscillator();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(10000, ctx.currentTime);

      const comp = ctx.createDynamicsCompressor();
      comp.threshold.setValueAtTime(-50, ctx.currentTime);
      comp.knee.setValueAtTime(40, ctx.currentTime);
      comp.ratio.setValueAtTime(12, ctx.currentTime);
      comp.attack.setValueAtTime(0, ctx.currentTime);
      comp.release.setValueAtTime(0.25, ctx.currentTime);

      osc.connect(comp);
      comp.connect(ctx.destination);
      osc.start(0);

      // Timeout after 3 seconds to prevent hanging on some devices
      const renderedBuffer = await Promise.race([
        ctx.startRendering(),
        new Promise((_, reject) => setTimeout(() => reject(new Error('audio_timeout')), 3000)),
      ]);
      let sum = 0;
      const channelData = renderedBuffer.getChannelData(0);
      for (let i = 4500; i < 5000; i++) {
        sum += Math.abs(channelData[i]);
      }
      return sum.toString();
    } catch (e) {
      return e.message === 'audio_timeout' ? 'timeout' : 'error';
    }
  }

  // Installed font detection (heuristic probe). Measured inside an empty iframe:
  // its document has no access to the page's @font-face web fonts, which would
  // otherwise count as "installed" once cached (Roboto on SilkMoon: 11 fonts on a
  // first visit, 12 on the next, splitting one visitor into two visitorIds).
  function getFontList() {
    if (typeof document === 'undefined') return [];
    const host = document.body || document.documentElement;
    if (!host) return [];
    let frame = null;
    try {
      frame = document.createElement('iframe');
      frame.setAttribute('aria-hidden', 'true');
      frame.tabIndex = -1;
      frame.style.cssText = 'position:absolute;left:-9999px;top:0;width:10px;height:10px;border:0;visibility:hidden';
      host.appendChild(frame);
      const doc = frame.contentDocument;
      if (doc && doc.body) return measureFonts(doc, doc.body);
    } catch (e) {
      // Fall through to the page document.
    } finally {
      if (frame && frame.parentNode === host) host.removeChild(frame);
    }
    return measureFonts(document, host);
  }

  function measureFonts(doc, container) {
    const baseFonts = ['monospace', 'sans-serif', 'serif'];
    const testFonts = [
      'Arial', 'Verdana', 'Times New Roman', 'Courier New',
      'Georgia', 'Comic Sans MS', 'Trebuchet MS', 'Impact',
      'Segoe UI', 'Roboto', 'Helvetica', 'Ubuntu', 'Consolas'
    ];

    const span = doc.createElement('span');
    span.style.fontSize = '72px';
    span.textContent = 'mmmmmmmmmmlli';
    span.style.position = 'absolute';
    span.style.left = '-9999px';

    try {
      container.appendChild(span);

      const baseWidths = {};
      for (const base of baseFonts) {
        span.style.fontFamily = base;
        baseWidths[base] = span.offsetWidth;
      }

      const detected = [];
      for (const font of testFonts) {
        for (const base of baseFonts) {
          span.style.fontFamily = `'${font}', ${base}`;
          if (span.offsetWidth !== baseWidths[base]) {
            detected.push(font);
            break;
          }
        }
      }
      return detected;
    } catch (e) {
      return [];
    } finally {
      if (span.parentNode === container) {
        container.removeChild(span);
      }
    }
  }

  /**
   * Collect complete hardware & browser environment components
   */
  async function getFingerprintComponents() {
    const win = typeof window !== 'undefined' ? window : {};
    const nav = typeof navigator !== 'undefined' ? navigator : {};
    const scr = typeof screen !== 'undefined' ? screen : {};
    const webgl = getWebGLFingerprint();
    const audio = await getAudioFingerprint();
    const canvas = getCanvasFingerprint();
    const fonts = getFontList();

    const components = {
      userAgent: nav.userAgent || '',
      platform: nav.platform || '',
      language: nav.language || '',
      languages: Array.isArray(nav.languages) ? nav.languages : [],
      hardwareConcurrency: nav.hardwareConcurrency || 0,
      deviceMemory: nav.deviceMemory || 0,
      maxTouchPoints: nav.maxTouchPoints || 0,
      screenResolution: `${scr.width || 0}x${scr.height || 0}`,
      availableScreenResolution: `${scr.availWidth || 0}x${scr.availHeight || 0}`,
      colorDepth: scr.colorDepth || 0,
      pixelRatio: win.devicePixelRatio || 1,
      timezoneOffset: new Date().getTimezoneOffset(),
      timezone: (typeof Intl !== 'undefined' && Intl?.DateTimeFormat?.().resolvedOptions?.().timeZone) || '',
      sessionStorage: supportsStorage(win, 'sessionStorage'),
      localStorage: supportsStorage(win, 'localStorage'),
      indexedDb: typeof win.indexedDB !== 'undefined',
      openDatabase: typeof win.openDatabase !== 'undefined',
      pluginsLength: nav.plugins ? nav.plugins.length : 0,
      doNotTrack: nav.doNotTrack || 'unknown',
      webglVendor: webgl.vendor,
      webglRenderer: webgl.renderer,
      canvasHash: canvas,
      audioHash: audio,
      fontsCount: fonts.length,
      fontsList: fonts,
    };

    // Keep transient probe failures out of identity. Audio rendering can time out
    // depending on browser load even when the underlying device is unchanged.
    const rawId = [
      components.userAgent,
      components.platform,
      components.hardwareConcurrency,
      components.deviceMemory,
      components.screenResolution,
      components.colorDepth,
      components.timezone,
      components.canvasHash,
      components.webglVendor,
      components.webglRenderer,
      components.fontsCount,
      components.language,
      components.pluginsLength,
      components.maxTouchPoints,
      components.pixelRatio,
    ].join('###');

    const visitorId = await hashVisitorId(rawId);

    return { visitorId, components };
  }


  // --- BotD Client-Side Heuristics ---
  /**
   * BotD Client-Side Heuristic Detectors
   * Inspired by BotD (https://github.com/fingerprintjs/BotD)
   * Implements 13 heuristic tests for browser automation, headless environments, and spoofing.
   */

  function runBotDetectors(components = {}) {
    const nav = typeof navigator !== 'undefined' ? navigator : {};
    const win = typeof window !== 'undefined' ? window : {};
    const doc = typeof document !== 'undefined' ? document : {};

    const detectors = {};
    const reasons = [];

    // 1. WebDriver detector (Selenium, Puppeteer, Playwright default)
    detectors.webdriver = !!(nav.webdriver || doc.documentElement?.getAttribute?.('webdriver'));
    if (detectors.webdriver) reasons.push('navigator.webdriver is true');

    // 2. Distinctive automation properties
    const automationProps = [
      '_phantom', '__nightmare', '_selenium', 'callPhantom', 'callSelenium',
      '_Selenium_IDE_Recorder', '__webdriver_script_fn', '__driver_evaluate',
      '__webdriver_evaluate', '__selenium_evaluate', '__fxdriver_evaluate',
      '__driver_unwrapped', '__webdriver_unwrapped', '__selenium_unwrapped',
      '__fxdriver_unwrapped', 'domAutomation', 'domAutomationController',
    ];
    let foundDistinctive = false;
    for (const prop of automationProps) {
      if (prop in win || (doc && prop in doc)) {
        foundDistinctive = true;
        reasons.push(`Distinctive automation property found: ${prop}`);
        break;
      }
    }
    // 4. Automation-specific global variables (e.g., cdc_ from ChromeDriver)
    detectors.chromeDriverGlobal = false;
    try {
      for (const key of Object.keys(win)) {
        if (key.startsWith('cdc_') || key.startsWith('$cdc_')) {
          detectors.chromeDriverGlobal = true;
          reasons.push(`ChromeDriver global detected: ${key}`);
          break;
        }
      }
    } catch (e) {
      // Object.keys(window) may throw SecurityError in some environments
    }
    detectors.distinctiveProperties = foundDistinctive;

    // 3. WebGL Software Renderer / VM / Headless detection
    const renderer = (components.webglRenderer || '').toLowerCase();
    const vendor = (components.webglVendor || '').toLowerCase();
    const isVirtualGpu = /swiftshader|llvmpipe|virtualbox|vmware|mesa offscreen|softpipe/i.test(renderer);
    detectors.virtualGpu = isVirtualGpu;
    if (isVirtualGpu) reasons.push(`Software / Virtual GPU detected: ${renderer}`);

    // 4. Plugins Inconsistency (Desktop Chrome must have plugins, Headless Chrome has 0)
    const isChrome = /chrome/i.test(nav.userAgent || '') && !/edg|opr|brave/i.test(nav.userAgent || '');
    const isDesktop = !/android|iphone|ipad|ipod|mobile/i.test(nav.userAgent || '');
    const pluginsLength = nav.plugins ? nav.plugins.length : 0;
    detectors.pluginsInconsistency = isChrome && isDesktop && pluginsLength === 0;
    if (detectors.pluginsInconsistency) reasons.push('Chrome desktop with 0 plugins (indicates headless)');

    // 5. Languages Inconsistency
    const langs = nav.languages || [];
    const lang = nav.language || '';
    detectors.languagesInconsistency = !langs.length || (lang && langs.length > 0 && !langs.includes(lang));
    if (detectors.languagesInconsistency) reasons.push('Browser language inconsistency');

    // 6. Window Size Anomaly (Headless environments often start with 0x0 or fixed 800x600)
    const w = win.innerWidth || 0;
    const h = win.innerHeight || 0;
    const outerW = win.outerWidth || 0;
    const outerH = win.outerHeight || 0;
    detectors.windowSize = (w === 0 && h === 0) || (outerW === 0 && outerH === 0);
    if (detectors.windowSize) reasons.push('Zero inner/outer window dimensions');

    // 7. Error Stack Trace Inspection
    let errorTraceBot = false;
    try {
      throw new Error('trace');
    } catch (err) {
      const stack = err.stack || '';
      if (/puppeteer|playwright|selenium|phantomjs|webdriver/i.test(stack)) {
        errorTraceBot = true;
        reasons.push('Automation framework detected in stack trace');
      }
    }
    detectors.errorTrace = errorTraceBot;

    // 8. Process global in renderer (Electron / Node-Webkit / automation)
    detectors.hasProcess = typeof win.process === 'object' && win.process?.versions?.node !== undefined;
    if (detectors.hasProcess) reasons.push('Node.js process object exposed in browser');

    // 9. Eval / Function.bind length check (anti-tampering check)
    let evalLengthAnomaly = false;
    try {
      if (eval.toString().length !== 33 && eval.toString().length !== 37) {
        evalLengthAnomaly = true;
      }
      if (Function.prototype.bind.toString().length !== 33 && Function.prototype.bind.toString().length !== 37) {
        evalLengthAnomaly = true;
      }
    } catch (e) {
      evalLengthAnomaly = true;
    }
    detectors.evalLength = evalLengthAnomaly;

    // 10. Document Element Keys & Attributes check
    let hasDocAttr = false;
    try {
      if (doc.documentElement && typeof doc.documentElement.getAttributeNames === 'function') {
        const attrNames = doc.documentElement.getAttributeNames();
        hasDocAttr = attrNames.some((k) => /selenium|webdriver|driver/i.test(k));
      } else if (doc.documentElement && doc.documentElement.attributes) {
        for (let i = 0; i < doc.documentElement.attributes.length; i++) {
          if (/selenium|webdriver|driver/i.test(doc.documentElement.attributes[i].name)) {
            hasDocAttr = true;
            break;
          }
        }
      }
    } catch (e) {}
    const docKeys = Object.keys(doc.documentElement || {});
    detectors.documentKeys = hasDocAttr || docKeys.some((k) => /selenium|webdriver|driver/i.test(k));
    if (detectors.documentKeys) reasons.push('Automation attributes on documentElement');

    // 11. User-Agent vs Platform Inconsistency (FP-Inconsistent paper inspired)
    const ua = (nav.userAgent || '').toLowerCase();
    const plat = (nav.platform || '').toLowerCase();
    let platformMismatch = false;
    if (ua.includes('windows') && !plat.includes('win')) platformMismatch = true;
    if (ua.includes('macintosh') && !plat.includes('mac')) platformMismatch = true;
    if (ua.includes('linux') && !plat.includes('linux') && !plat.includes('arm')) platformMismatch = true;
    detectors.platformMismatch = platformMismatch;
    if (platformMismatch) reasons.push(`Platform mismatch: UserAgent (${nav.userAgent}) vs Platform (${nav.platform})`);

    // 12. Headless Chrome User-Agent flag
    detectors.headlessUa = /headlesschrome/i.test(nav.userAgent || '');
    if (detectors.headlessUa) reasons.push('User-Agent explicitly declares HeadlessChrome');

    // Calculate Weighted Heuristic Score
    // High-confidence detectors get higher weight than noisy ones
    const detectorWeights = {
      webdriver: 5.0,
      distinctiveProperties: 5.0,
      chromeDriverGlobal: 4.0,
      headlessUa: 4.0,
      virtualGpu: 3.0,
      windowSize: 2.5,
      hasProcess: 3.0,
      documentKeys: 3.0,
      platformMismatch: 2.0,
      pluginsInconsistency: 2.0,
      languagesInconsistency: 1.5,
      errorTrace: 1.5,
      evalLength: 1.0,  // noisy, low weight
    };

    const keys = Object.keys(detectors);
    const flagged = keys.filter((k) => detectors[k]);
    const totalWeight = keys.reduce((sum, k) => sum + (detectorWeights[k] || 1.0), 0);
    const flaggedWeight = flagged.reduce((sum, k) => sum + (detectorWeights[k] || 1.0), 0);
    const heuristicScore = totalWeight > 0 ? flaggedWeight / totalWeight : 0;
    const hasCriticalAutomationSignal = !!(
      detectors.webdriver ||
      detectors.distinctiveProperties ||
      detectors.chromeDriverGlobal ||
      detectors.headlessUa
    );
    const isBotHeuristic = hasCriticalAutomationSignal || heuristicScore >= 0.35;

    return {
      isBot: isBotHeuristic,
      heuristicScore: Number(heuristicScore.toFixed(4)),
      flaggedCount: flagged.length,
      detectors,
      reasons,
    };
  }


  // --- Passive Browser Profile Observations ---
  /** Bounded, passive profile observations for offline/shadow evaluation. */

  async function readProfileNavigator(nav, timeoutMs = 1000) {
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

  async function collectBrowserProfile({ timeoutMs = 1000, signal } = {}) {
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


  // --- Automation and Tampering Probes (BotD v2) ---
  /**
   * Automation and tampering probes (BotD v2 layer).
   *
   * Sources: FingerprintJS BotD detectors (MIT), FPScanner (MIT), Castle and cside
   * write-ups on Playwright/CDP artefacts. Each probe is a boolean that is true only
   * when the evidence is present; a probe that cannot run returns false and is
   * listed in `unavailable`. Nothing here changes page state that the site can see.
   */

  function nativeSource(fn) {
    try {
      return typeof fn === 'function' && /\{\s*\[native code\]\s*\}\s*$/.test(Function.prototype.toString.call(fn));
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

  function collectAutomationSignals(nav, win, doc) {
    const out = {};
    const unavailable = [];
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

    // Research only (not used by any rule): with a DevTools Protocol client attached
    // (Runtime.enable) console previews read Error#name a second time. Measured on
    // Chrome/Edge 155-156: genuine 1 read per call, Playwright/Puppeteer/Selenium 2,
    // Patchright 1. Open DevTools also reads twice, so developers look the same.
    out.cdpRuntime = false;
    try {
      if (chromium && win.console && typeof win.console.debug === 'function') {
        let reads = 0;
        class ProbeError extends Error {}
        Object.defineProperty(ProbeError.prototype, 'name', { configurable: true, get() { reads++; return 'Error'; } });
        win.console.debug(new ProbeError(''));
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
        || (webdriverGetter !== undefined && webdriverGetter !== null && !nativeSource(webdriverGetter));
    } catch (e) { unavailable.push('webdriverPatched'); }

    // Non-native navigator getters reveal JS-level spoofing. Privacy extensions can
    // do the same, so this is tampering evidence, not proof of automation.
    out.navigatorGetterPatched = false;
    try {
      const names = ['userAgent', 'platform', 'languages', 'plugins', 'hardwareConcurrency', 'deviceMemory', 'vendor'];
      out.navigatorGetterPatched = names.some((name) => {
        const getter = getterOf(navProto, name);
        return getter !== undefined && getter !== null && !nativeSource(getter);
      }) || names.some((name) => Object.prototype.hasOwnProperty.call(nav, name));
    } catch (e) { unavailable.push('navigatorGetterPatched'); }

    out.toStringPatched = false;
    try {
      out.toStringPatched = !nativeSource(Function.prototype.toString)
        || Function.prototype.toString.call(Function.prototype.toString).indexOf('toString') === -1;
    } catch (e) { out.toStringPatched = true; }

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
  async function probeNotificationPermission(nav, win, timeoutMs = 500) {
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
  function probeWorkerConsistency(nav, win, doc, timeoutMs = 800) {
    return new Promise((resolve) => {
      let worker = null;
      let url = null;
      let timer = null;
      const finish = (value) => {
        if (timer) clearTimeout(timer);
        try { if (worker) worker.terminate(); } catch (e) {}
        try { if (url) URL.revokeObjectURL(url); } catch (e) {}
        resolve(value);
      };
      try {
        if (typeof Worker === 'undefined' || typeof Blob === 'undefined' || typeof URL === 'undefined') {
          finish(null);
          return;
        }
        url = URL.createObjectURL(new Blob([WORKER_SOURCE], { type: 'text/javascript' }));
        worker = new Worker(url);
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


  // --- DELBOT Mouse Dynamics Recorder ---
  /**
   * Mouse Dynamics Tracker & Recorder
   * Inspired by DELBOT-Mouse (https://github.com/chrisgdt/DELBOT-Mouse)
   * Captures user mouse/touch trajectories, computes kinematic features (velocity, acceleration, jerk),
   * and prepares sequential chunks (24 points) for LSTM behavioral classification.
   */

  class MouseRecorder {
    constructor(options = {}) {
      this.maxRecords = options.maxRecords || 500;
      this.chunkSize = options.chunkSize || 24;
      this.records = [];
      this.chunks = [];
      this.lastMoveRecord = null;
      this.scrollEvents = [];  // separate scroll tracking
      this.coordinateWidth = null;
      this.coordinateHeight = null;
      this.recordingId = 0;
      this.recordingStartedAt = Date.now();
      this.startTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
      this.isListening = false;
      // Click geometry and press timing. Offsets are in CSS pixels relative to the
      // centre of the clicked control; no element text or identifiers are kept.
      this.clickEvents = [];
      this.lastPressStamp = null;
      this.lastReleaseStamp = null;
      this.counters = { mousemove: 0, mousedown: 0, click: 0, wheel: 0 };
      this.pointerStats = {
        pointermove: 0, coalescedTotal: 0, coalescedMax: 0, coalescedMulti: 0, rawUpdates: 0,
        mouseDowns: 0, zeroPressureDowns: 0,
      };
      // Keystroke timing only: no key values, field names or text; password fields are skipped.
      this.keystrokes = [];
      this.pendingKeys = {};
      this.lastKeyDownAt = null;
      this.bulkInserts = 0;
      this.bulkMaxLength = 0;
      this.handlePointerDown = this.handlePointerDown.bind(this);
      this.handleKeyDown = this.handleKeyDown.bind(this);
      this.handleKeyUp = this.handleKeyUp.bind(this);
      this.handleInput = this.handleInput.bind(this);
      this.handlePointerMove = this.handlePointerMove.bind(this);
      this.handlePointerRawUpdate = this.handlePointerRawUpdate.bind(this);
      this.handleMouseMove = this.handleMouseMove.bind(this);
      this.handleMouseDown = this.handleMouseDown.bind(this);
      this.handleMouseUp = this.handleMouseUp.bind(this);
      this.handleClick = this.handleClick.bind(this);
      this.handleWheel = this.handleWheel.bind(this);
      this.handleTouchStart = this.handleTouchStart.bind(this);
      this.handleTouchMove = this.handleTouchMove.bind(this);
      this.handleTouchEnd = this.handleTouchEnd.bind(this);
    }

    start() {
      if (this.isListening || typeof window === 'undefined') return;
      this.isListening = true;
      window.addEventListener('mousemove', this.handleMouseMove, { passive: true });
      window.addEventListener('mousedown', this.handleMouseDown, { passive: true });
      window.addEventListener('mouseup', this.handleMouseUp, { passive: true });
      window.addEventListener('click', this.handleClick, { passive: true });
      window.addEventListener('wheel', this.handleWheel, { passive: true });
      window.addEventListener('touchstart', this.handleTouchStart, { passive: true });
      window.addEventListener('touchmove', this.handleTouchMove, { passive: true });
      window.addEventListener('touchend', this.handleTouchEnd, { passive: true });
      // Coalesced samples and raw updates are only exposed in secure contexts.
      window.addEventListener('pointermove', this.handlePointerMove, { passive: true });
      if (window.isSecureContext && 'onpointerrawupdate' in window) {
        window.addEventListener('pointerrawupdate', this.handlePointerRawUpdate, { passive: true });
      }
      window.addEventListener('pointerdown', this.handlePointerDown, { passive: true });
      window.addEventListener('keydown', this.handleKeyDown, { capture: true, passive: true });
      window.addEventListener('keyup', this.handleKeyUp, { capture: true, passive: true });
      window.addEventListener('input', this.handleInput, { capture: true, passive: true });
    }

    stop() {
      if (!this.isListening || typeof window === 'undefined') return;
      this.isListening = false;
      window.removeEventListener('mousemove', this.handleMouseMove);
      window.removeEventListener('mousedown', this.handleMouseDown);
      window.removeEventListener('mouseup', this.handleMouseUp);
      window.removeEventListener('click', this.handleClick);
      window.removeEventListener('wheel', this.handleWheel);
      window.removeEventListener('touchstart', this.handleTouchStart);
      window.removeEventListener('touchmove', this.handleTouchMove);
      window.removeEventListener('touchend', this.handleTouchEnd);
      window.removeEventListener('pointermove', this.handlePointerMove);
      window.removeEventListener('pointerrawupdate', this.handlePointerRawUpdate);
      window.removeEventListener('pointerdown', this.handlePointerDown);
      window.removeEventListener('keydown', this.handleKeyDown, true);
      window.removeEventListener('keyup', this.handleKeyUp, true);
      window.removeEventListener('input', this.handleInput, true);
    }

    clear() {
      this.recordingId++;
      this.recordingStartedAt = Date.now();
      this.records = [];
      this.chunks = [];
      this.lastMoveRecord = null;
      this.scrollEvents = [];
      this.coordinateWidth = null;
      this.coordinateHeight = null;
      this.keystrokes = [];
      this.pendingKeys = {};
      this.lastKeyDownAt = null;
      this.startTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
    }

    recordPoint(type, clientX, clientY, source = 'mouse') {
      const viewportWidth = (typeof window !== 'undefined' && window.innerWidth > 0) ? window.innerWidth : 1920;
      const viewportHeight = (typeof window !== 'undefined' && window.innerHeight > 0) ? window.innerHeight : 1080;
      // Small viewport changes can come from scrollbars; larger growth needs a new frame.
      if (this.coordinateWidth !== null &&
          (viewportWidth > this.coordinateWidth + 32 || viewportHeight > this.coordinateHeight + 32)) {
        this.clear();
      }
      if (this.coordinateWidth === null) {
        this.coordinateWidth = viewportWidth;
        this.coordinateHeight = viewportHeight;
      }
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      const time = Math.round(now - this.startTime);
      const w = this.coordinateWidth;
      const h = this.coordinateHeight;
      const safeX = (typeof clientX === 'number' && Number.isFinite(clientX)) ? clientX : 0;
      const safeY = (typeof clientY === 'number' && Number.isFinite(clientY)) ? clientY : 0;
      const normX = Math.max(0, Math.min(1, Number((safeX / w).toFixed(5))));
      const normY = Math.max(0, Math.min(1, Number((safeY / h).toFixed(5))));

      const previousRecord = this.records.length > 0 ? this.records[this.records.length - 1] : null;
      const candidate = type === 'move' ? this.lastMoveRecord : previousRecord;
      const prev = candidate && candidate.source === source ? candidate : null;

      let timeDiff = 0;
      let dx = 0;
      let dy = 0;
      let distance = 0;
      let speedX = 0;
      let speedY = 0;
      let speed = 0;
      let accelX = 0;
      let accelY = 0;
      let accel = 0;

      if (prev) {
        timeDiff = Math.max(1, time - prev.time); // milliseconds
        dx = normX - prev.x;
        dy = normY - prev.y;
        distance = Math.sqrt(dx * dx + dy * dy);
        speedX = dx / (timeDiff / 1000); // normalized unit per second
        speedY = dy / (timeDiff / 1000);
        speed = distance / (timeDiff / 1000);

        accelX = (speedX - (prev.speedX || 0)) / (timeDiff / 1000);
        accelY = (speedY - (prev.speedY || 0)) / (timeDiff / 1000);
        accel = Math.sqrt(accelX * accelX + accelY * accelY);

        accelX = Number.isFinite(accelX) ? accelX : 0;
        accelY = Number.isFinite(accelY) ? accelY : 0;
        accel = Number.isFinite(accel) ? accel : 0;
      }

      const record = {
        time,
        type,
        source,
        x: normX,
        y: normY,
        dx: Number(dx.toFixed(5)),
        dy: Number(dy.toFixed(5)),
        timeDiff,
        distance: Number(distance.toFixed(5)),
        speedX: Number(speedX.toFixed(3)),
        speedY: Number(speedY.toFixed(3)),
        speed: Number(speed.toFixed(3)),
        accelX: Number(accelX.toFixed(3)),
        accelY: Number(accelY.toFixed(3)),
        accel: Number(accel.toFixed(3)),
      };

      this.records.push(record);
      if (type === 'move') this.lastMoveRecord = record;
      // Efficient truncation: splice from front in batch instead of shift() one-by-one
      if (this.records.length > this.maxRecords + 50) {
        this.records = this.records.slice(-this.maxRecords);
      }
    }

    handleMouseMove(e) {
      if (e.isTrusted === false) return;
      this.counters.mousemove++;
      this.recordPoint('move', e.clientX, e.clientY);
    }

    eventStamp(e) {
      if (e && typeof e.timeStamp === 'number' && Number.isFinite(e.timeStamp) && e.timeStamp > 0) return e.timeStamp;
      return typeof performance !== 'undefined' ? performance.now() : Date.now();
    }

    handleMouseDown(e) {
      if (e.isTrusted === false) return;
      this.counters.mousedown++;
      this.lastPressStamp = this.eventStamp(e);
      this.lastReleaseStamp = null;
      this.recordPoint('down', e.clientX, e.clientY);
    }

    handleMouseUp(e) {
      if (e.isTrusted === false) return;
      this.lastReleaseStamp = this.eventStamp(e);
      this.recordPoint('up', e.clientX, e.clientY);
    }

    handleClick(e) {
      if (e.isTrusted === false) return;
      this.counters.click++;
      this.recordPoint('click', e.clientX, e.clientY);
      this.recordClickGeometry(e);
    }

    recordClickGeometry(e) {
      // detail === 0 marks keyboard or assistive activation, which has no pointer position.
      if (!e || e.detail === 0 || typeof e.clientX !== 'number' || typeof e.clientY !== 'number') return;
      let target = e.target;
      try {
        if (target && typeof target.closest === 'function') {
          target = target.closest('a,button,input,select,textarea,label,summary,[role="button"],[role="link"]') || target;
        }
        if (!target || typeof target.getBoundingClientRect !== 'function') return;
        const rect = target.getBoundingClientRect();
        if (!(rect.width > 0 && rect.height > 0)) return;
        const round2 = (value) => Math.round(value * 100) / 100;
        const press = this.lastPressStamp;
        const release = this.lastReleaseStamp;
        const hold = press !== null && release !== null && release >= press && release - press < 10000
          ? round2(release - press) : null;
        const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
        this.clickEvents.push({
          time: Math.round(now - this.startTime),
          hold,
          ox: round2(e.clientX - (rect.left + rect.width / 2)),
          oy: round2(e.clientY - (rect.top + rect.height / 2)),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
        });
        if (this.clickEvents.length > 40) this.clickEvents = this.clickEvents.slice(-30);
      } catch (err) {
        // Geometry is optional evidence; never break the host page.
      } finally {
        this.lastPressStamp = null;
        this.lastReleaseStamp = null;
      }
    }

    handlePointerMove(e) {
      if (!e || e.isTrusted === false || e.pointerType !== 'mouse') return;
      const stats = this.pointerStats;
      stats.pointermove++;
      if (typeof e.getCoalescedEvents === 'function') {
        let count = 0;
        try { count = e.getCoalescedEvents().length; } catch (err) { count = 0; }
        stats.coalescedTotal += count;
        if (count > stats.coalescedMax) stats.coalescedMax = count;
        if (count > 1) stats.coalescedMulti++;
      }
    }

    handlePointerRawUpdate(e) {
      if (e && e.isTrusted !== false && e.pointerType === 'mouse') this.pointerStats.rawUpdates++;
    }

    handlePointerDown(e) {
      if (!e || e.isTrusted === false || e.pointerType !== 'mouse') return;
      // Pointer Events: a mouse with a button down MUST report pressure 0.5.
      this.pointerStats.mouseDowns++;
      if (e.buttons > 0 && e.pressure === 0) this.pointerStats.zeroPressureDowns++;
    }

    static isSecretField(target) {
      return !!target && typeof target.type === 'string' && target.type.toLowerCase() === 'password';
    }

    keyNow() {
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      return now - this.startTime;
    }

    handleKeyDown(e) {
      if (!e || e.isTrusted === false || e.repeat || MouseRecorder.isSecretField(e.target)) return;
      const at = this.keyNow();
      this.lastKeyDownAt = at;
      // 'u': virtual keyboards report Unidentified/229 and have no real press duration.
      const kind = e.key === 'Unidentified' || e.keyCode === 229
        ? 'u' : (typeof e.key === 'string' && e.key.length === 1 ? 'c' : 'o');
      const stroke = { t: Math.round(at * 10) / 10, h: null, k: kind };
      this.keystrokes.push(stroke);
      if (this.keystrokes.length > 80) this.keystrokes = this.keystrokes.slice(-60);
      this.pendingKeys[e.code || e.key || '?'] = { stroke, at };
    }

    handleKeyUp(e) {
      if (!e || e.isTrusted === false) return;
      const id = e.code || e.key || '?';
      const pending = this.pendingKeys[id];
      if (!pending) return;
      delete this.pendingKeys[id];
      const hold = this.keyNow() - pending.at;
      if (hold >= 0 && hold < 5000) pending.stroke.h = Math.round(hold * 10) / 10;
    }

    handleInput(e) {
      if (!e || e.isTrusted === false || e.inputType !== 'insertText' || MouseRecorder.isSecretField(e.target)) return;
      const length = typeof e.data === 'string' ? e.data.length : 0;
      // Text that arrives in one piece with no key pressed (research signal only:
      // browser autofill and dictation can look the same).
      if (length >= 2 && (this.lastKeyDownAt === null || this.keyNow() - this.lastKeyDownAt > 1000)) {
        this.bulkInserts++;
        if (length > this.bulkMaxLength) this.bulkMaxLength = length;
      }
    }

    handleWheel(e) {
      if (e.isTrusted === false) return;
      this.counters.wheel++;
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      const time = Math.round(now - this.startTime);
      this.scrollEvents.push({
        time,
        deltaY: e.deltaY,
        deltaX: e.deltaX,
      });
      // Keep last 200 scroll events
      if (this.scrollEvents.length > 200) {
        this.scrollEvents = this.scrollEvents.slice(-200);
      }
    }

    handleTouchStart(e) {
      if (e.touches && e.touches[0]) {
        this.recordPoint('down', e.touches[0].clientX, e.touches[0].clientY, 'touch');
      }
    }

    handleTouchMove(e) {
      if (e.touches && e.touches[0]) {
        this.recordPoint('move', e.touches[0].clientX, e.touches[0].clientY, 'touch');
      }
    }

    handleTouchEnd(e) {
      const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0]);
      if (touch) {
        this.recordPoint('up', touch.clientX, touch.clientY, 'touch');
      } else {
        const last = this.records.length > 0 ? this.records[this.records.length - 1] : null;
        const w = this.coordinateWidth || ((typeof window !== 'undefined' && window.innerWidth > 0) ? window.innerWidth : 1920);
        const h = this.coordinateHeight || ((typeof window !== 'undefined' && window.innerHeight > 0) ? window.innerHeight : 1080);
        const x = last ? last.x * w : 0;
        const y = last ? last.y * h : 0;
        this.recordPoint('up', x, y, 'touch');
      }
    }

    /**
     * Split records into consecutive chunks of 24 points for LSTM input
     */
    getChunks(chunkSize = 24) {
      const moveRecords = this.records.filter((r) => r.type === 'move' && r.source !== 'touch');
      const featureRows = [];
      let prevSpeedX = 0;
      let prevSpeedY = 0;

      for (let i = 1; i < moveRecords.length; i++) {
        const prev = moveRecords[i - 1];
        const point = moveRecords[i];
        const dt = Math.max(0.001, (point.time - prev.time) / 1000);
        const dx = point.x - prev.x;
        const dy = point.y - prev.y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        const speedX = dx / dt;
        const speedY = dy / dt;
        const speed = distance / dt;
        const accel = Math.sqrt(
          Math.pow(speedX - prevSpeedX, 2) + Math.pow(speedY - prevSpeedY, 2)
        ) / dt;
        featureRows.push([dx, dy, speedX, speedY, speed, accel, distance, dt]);
        prevSpeedX = speedX;
        prevSpeedY = speedY;
      }

      const chunks = [];
      const stride = Math.max(1, Math.floor(chunkSize / 2));
      for (let i = 0; i + chunkSize <= featureRows.length; i += stride) {
        chunks.push(featureRows.slice(i, i + chunkSize));
      }
      return chunks;
    }

    /**
     * Aggregated statistical summary of mouse dynamics
     */
    getStats() {
      const mouseRecords = this.records.filter((r) => r.source !== 'touch');
      if (mouseRecords.length < 2) {
        return {
          pointCount: mouseRecords.length,
          movePointCount: mouseRecords.filter((r) => r.type === 'move').length,
          hasEnoughData: false,
          avgSpeed: 0,
          maxSpeed: 0,
          avgAccel: 0,
          straightness: 1.0,
        };
      }

      const moveRecords = mouseRecords.filter((r) => r.type === 'move');
      const speeds = moveRecords.map((r) => r.speed).filter((s) => s > 0);
      const accels = moveRecords.map((r) => r.accel).filter((a) => a > 0);

      const avgSpeed = speeds.length ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0;
      const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
      const avgAccel = accels.length ? accels.reduce((a, b) => a + b, 0) / accels.length : 0;

      // Straightness = net displacement / total path length
      const first = moveRecords[0] || mouseRecords[0];
      const last = moveRecords[moveRecords.length - 1] || mouseRecords[mouseRecords.length - 1];
      const netDist = Math.sqrt(Math.pow(last.x - first.x, 2) + Math.pow(last.y - first.y, 2));
      const totalDist = moveRecords.reduce((sum, r) => sum + (r.distance || 0), 0);
      const straightness = totalDist > 0 ? Number((netDist / totalDist).toFixed(4)) : 1.0;

      return {
        pointCount: mouseRecords.length,
        movePointCount: moveRecords.length,
        hasEnoughData: moveRecords.length >= this.chunkSize + 1,
        avgSpeed: Number(avgSpeed.toFixed(4)),
        maxSpeed: Number(maxSpeed.toFixed(4)),
        avgAccel: Number(avgAccel.toFixed(4)),
        straightness,
      };
    }

    exportData() {
      const recentOtherEvents = this.records.filter((record) =>
        record.type !== 'move' || record.source === 'touch',
      ).slice(-20);
      const recentMouseMoves = this.records.filter((record) =>
        record.type === 'move' && record.source !== 'touch',
      ).slice(-(100 - recentOtherEvents.length));
      return {
        records: [...recentMouseMoves, ...recentOtherEvents]
          .sort((a, b) => a.time - b.time),
        stats: this.getStats(),
        scrollEvents: this.scrollEvents.slice(-50), // last 50 scroll events
        clickEvents: this.clickEvents.slice(-30),
        counters: { ...this.counters },
        pointerStats: {
          ...this.pointerStats,
          secureContext: typeof window !== 'undefined' && window.isSecureContext === true,
        },
        keyboard: {
          keystrokes: this.keystrokes.slice(-60).map(({ t, h, k }) => ({ t, h, k })),
          bulkInserts: this.bulkInserts,
          bulkMaxLength: this.bulkMaxLength,
          coarsePointer: typeof window !== 'undefined' && typeof window.matchMedia === 'function'
            && window.matchMedia('(pointer: coarse)').matches,
        },
        coordinateFrame: {
          id: this.recordingId,
          width: this.coordinateWidth,
          height: this.coordinateHeight,
          normalizedAxes: true,
          startedAtEpochMs: this.recordingStartedAt,
          timestampResolutionMs: 1,
          coordinateDecimals: 5,
        },
      };
    }
  }


  // --- Unified BotCollector SDK ---
  /**
   * Unified Bot & Fraud Telemetry Collector SDK
   * Combines FingerprintJS + BotD Heuristics + DELBOT Mouse Dynamics
   */







  const COLLECTOR_VERSION = '1.5.0';

  const SESSION_STORAGE_KEY = 'datacat_session';

  function boundedUrl(value) {
    return String(value || '').slice(0, 2048);
  }

  class BotCollector {
    constructor(options = {}) {
      this.endpointUrl = options.endpointUrl || options.endpoint || '/api/v1/telemetry';
      this.detectUrl = options.detectUrl || '/api/v1/detect';
      // One session per browser tab, renewed by activity and ended after 30 idle
      // minutes (the usual web-analytics definition), so a reload or a link to
      // another page of the site continues the same session.
      this.persistSession = !options.sessionId && options.persistSession !== false;
      this.sessionIdleMs = Math.max(60000, Number(options.sessionIdleMs ?? 1800000) || 1800000);
      this.sessionId = options.sessionId || this.restoreSessionId() || this.generateSessionId();
      this.touchSession();
      this.pageInstanceId = this.generateSessionId();
      this.studyId = String(options.studyId || '').slice(0, 64);
      this.siteId = String(options.siteId || '').slice(0, 64);
      this.lastReceipt = null;
      this.lastDelivery = null;
      this.autoSendInterval = options.autoSendInterval !== undefined ? options.autoSendInterval : 15000;
      this.idleHeartbeatInterval = Math.max(
        this.autoSendInterval,
        Number(options.idleHeartbeatInterval ?? 60000) || 60000,
      );
      this.mouseRecorder = new MouseRecorder();
      this.cachedFingerprint = null;
      this.cachedBotd = null;
      this.timer = null;
      this.initPromise = null;
      this.destroyed = false;
      this.lifecycleVersion = 0;
      this.sequence = 0;
      this.sendPromise = null;
      this.abortControllers = new Set();
      this.retryTimer = null;
      this.pendingRetry = null;
      this.lastSentActivitySignature = null;
      this.lastSuccessfulSendAt = 0;
      this.retryAfterMs = 0;
      this.retryNotBefore = 0;
      this.maxRetryAttempts = Math.max(0, Number(options.maxRetryAttempts ?? 3) || 0);
      this.retryBaseDelay = Math.max(100, Number(options.retryBaseDelay ?? 500) || 500);
      this.handlePageHide = () => { this.sendTelemetry('pagehide'); };
    }

    restoreSessionId() {
      if (!this.persistSession) return null;
      try {
        const saved = JSON.parse(window.sessionStorage.getItem(SESSION_STORAGE_KEY) || 'null');
        if (saved && typeof saved.id === 'string' && /^sess_[A-Za-z0-9-]{8,64}$/.test(saved.id)
            && Number.isFinite(saved.seen) && Date.now() - saved.seen < this.sessionIdleMs) {
          return saved.id;
        }
      } catch (e) { /* storage blocked: fall back to one session per page */ }
      return null;
    }

    touchSession() {
      if (!this.persistSession) return;
      try {
        window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ id: this.sessionId, seen: Date.now() }));
      } catch (e) { /* optional */ }
    }

    generateSessionId() {
      if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return 'sess_' + crypto.randomUUID();
      }
      return 'sess_' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
    }

    start() {
      return this.init();
    }

    init() {
      if (this.initPromise) return this.initPromise;
      this.destroyed = false;
      const lifecycleVersion = ++this.lifecycleVersion;
      this.initPromise = this.initialize(lifecycleVersion);
      return this.initPromise;
    }

    async initialize(lifecycleVersion) {
      this.mouseRecorder.start();
      if (typeof window !== 'undefined') {
        window.addEventListener('pagehide', this.handlePageHide, { capture: true });
      }
      // Pre-warm fingerprint and heuristics
      let visitorId;
      let components;
      try {
        ({ visitorId, components } = await getFingerprintComponents());
      } catch (e) {
        visitorId = this.generateSessionId().replace('sess_', 'fp_');
        components = {};
      }
      if (this.destroyed || lifecycleVersion !== this.lifecycleVersion) return this;
      this.cachedFingerprint = { visitorId, components };
      this.cachedBotd = runBotDetectors(components);
      const profile = await this.collectProfile();
      if (this.destroyed || lifecycleVersion !== this.lifecycleVersion) return this;
      this.cachedBotd.profile = profile;
      const automation = await this.collectAutomation();
      if (this.destroyed || lifecycleVersion !== this.lifecycleVersion) return this;
      this.cachedBotd.automation = automation;

      await this.sendTelemetry('init');

      if (!this.destroyed && lifecycleVersion === this.lifecycleVersion && this.autoSendInterval > 0) {
        this.timer = setInterval(() => {
          this.sendTelemetry('heartbeat').catch(() => false);
        }, this.autoSendInterval);
      }

      return this;
    }

    destroy() {
      this.destroyed = true;
      this.lifecycleVersion++;
      this.mouseRecorder.stop();
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
      this.initPromise = null;
      this.sendPromise = null;
      this.clearPendingRetry();
      this.retryAfterMs = 0;
      this.retryNotBefore = 0;
      for (const controller of this.abortControllers) controller.abort();
      this.abortControllers.clear();
      if (typeof window !== 'undefined') {
        window.removeEventListener('pagehide', this.handlePageHide, { capture: true });
      }
    }

    async collectProfile() {
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      if (controller) this.abortControllers.add(controller);
      try {
        return await collectBrowserProfile({ signal: controller?.signal });
      } finally {
        if (controller) this.abortControllers.delete(controller);
      }
    }

    async collectAutomation() {
      const nav = typeof navigator !== 'undefined' ? navigator : {};
      const win = typeof window !== 'undefined' ? window : {};
      const doc = typeof document !== 'undefined' ? document : null;
      let signals = {};
      try { signals = collectAutomationSignals(nav, win, doc); } catch (e) { signals = { unavailable: ['all'] }; }
      let notificationPermissionMismatch = null;
      let worker = null;
      try {
        [notificationPermissionMismatch, worker] = await Promise.all([
          probeNotificationPermission(nav, win),
          doc ? probeWorkerConsistency(nav, win, doc) : Promise.resolve(null),
        ]);
      } catch (e) { /* optional evidence */ }
      return { schema: 'automation-v1', signals, notificationPermissionMismatch, worker };
    }

    async getPayload(action = 'heartbeat') {
      if (!this.cachedFingerprint) {
        const { visitorId, components } = await getFingerprintComponents();
        this.cachedFingerprint = { visitorId, components };
        this.cachedBotd = runBotDetectors(components);
        if (action !== 'pagehide' && !this.destroyed) {
          this.cachedBotd.profile = await this.collectProfile();
        }
      }

      const mouseData = this.mouseRecorder.exportData();
      // The API rebuilds canonical chunks from raw records. Sending overlapping
      // windows can push a mature session beyond the request-size limit.
      delete mouseData.chunks;
      const sequence = this.sequence;
      this.sequence = (this.sequence + 1) % 1000000;

      return {
        sessionId: this.sessionId,
        action,
        timestamp: Date.now(),
        sequence,
        collector: {
          schemaVersion: 1,
          sdkVersion: COLLECTOR_VERSION,
          pageInstanceId: this.pageInstanceId,
          ...(this.studyId ? { studyId: this.studyId } : {}),
          ...(this.siteId ? { siteId: this.siteId } : {}),
        },
        pageUrl: typeof window !== 'undefined' ? boundedUrl(window.location.href) : '',
        referrer: typeof document !== 'undefined' ? boundedUrl(document.referrer) : '',
        visitorId: this.cachedFingerprint.visitorId,
        fingerprint: this.cachedFingerprint.components,
        botd: this.cachedBotd,
        mouse: mouseData,
      };
    }

    getActivitySignature(payload) {
      const mouse = payload && payload.mouse ? payload.mouse : {};
      const records = Array.isArray(mouse.records) ? mouse.records : [];
      const scrollEvents = Array.isArray(mouse.scrollEvents) ? mouse.scrollEvents : [];
      // Typing and clicks are activity too, even when the pointer does not move.
      const keystrokes = mouse.keyboard && Array.isArray(mouse.keyboard.keystrokes) ? mouse.keyboard.keystrokes.length : 0;
      const clicks = Array.isArray(mouse.clickEvents) ? mouse.clickEvents.length : 0;
      return JSON.stringify([payload.pageUrl || '', records, scrollEvents, keystrokes, clicks]);
    }

    /**
     * Send telemetry asynchronously via sendBeacon or fetch
     */
    async sendTelemetry(action = 'telemetry') {
      if (this.sendPromise && action !== 'pagehide') return this.sendPromise;

      const operation = this._sendTelemetry(action, this.lifecycleVersion);
      if (action === 'pagehide') return operation;
      const tracked = operation.finally(() => {
        if (this.sendPromise === tracked) this.sendPromise = null;
      });
      this.sendPromise = tracked;
      return tracked;
    }

    async fetchWithTimeout(url, options, timeoutMs = 10000, consumeResponse = null) {
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const timeoutId = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
      if (controller) this.abortControllers.add(controller);
      try {
        const response = await fetch(url, {
          ...options,
          ...(controller ? { signal: controller.signal } : {}),
        });
        return consumeResponse ? await consumeResponse(response) : response;
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
        if (controller) this.abortControllers.delete(controller);
      }
    }

    clearPendingRetry() {
      if (this.retryTimer) clearTimeout(this.retryTimer);
      this.retryTimer = null;
      this.pendingRetry = null;
    }

    scheduleRetry(body, lifecycleVersion, attempt = 1, activitySignature = null) {
      if (this.destroyed || lifecycleVersion !== this.lifecycleVersion) return;
      if (attempt > this.maxRetryAttempts) {
        this.clearPendingRetry();
        return;
      }

      if (this.retryTimer) clearTimeout(this.retryTimer);
      this.pendingRetry = { body, lifecycleVersion, attempt, activitySignature };
      const delay = Math.max(
        this.retryBaseDelay * Math.pow(2, attempt - 1),
        this.retryAfterMs,
        this.retryNotBefore - Date.now(),
      );
      this.retryAfterMs = 0;
      this.retryTimer = setTimeout(async () => {
        this.retryTimer = null;
        const pending = this.pendingRetry;
        if (!pending || this.destroyed || pending.lifecycleVersion !== this.lifecycleVersion) return;

        const sentBody = pending.body;
        const sentSignature = pending.activitySignature;
        const sent = await this.transmitTelemetry(sentBody, 'retry');
        // A heartbeat may have installed a newer snapshot while this request was
        // in flight. The older completion must not clear or replace that retry.
        if (this.pendingRetry !== pending) return;
        if (sent) {
          this.lastSentActivitySignature = sentSignature;
          this.lastSuccessfulSendAt = Date.now();
          if (pending.body === sentBody) {
            this.pendingRetry = null;
          } else {
            this.scheduleRetry(pending.body, pending.lifecycleVersion, 1, pending.activitySignature);
          }
        } else {
          this.scheduleRetry(pending.body, pending.lifecycleVersion, pending.attempt + 1, pending.activitySignature);
        }
      }, delay);
    }

    async transmitTelemetry(body, action) {
      let delivery = null;
      try {
        if (action === 'pagehide' && typeof navigator !== 'undefined' && navigator.sendBeacon) {
          // text/plain is CORS-safelisted, so a cross-origin unload beacon does
          // not depend on an asynchronous preflight that the browser may cancel.
          const blob = new Blob([body], { type: 'text/plain;charset=UTF-8' });
          const success = navigator.sendBeacon(this.endpointUrl, blob);
          if (success) {
            this.lastDelivery = { transport: 'beacon', queued: true, acknowledged: false };
            return true;
          }
        }

        delivery = { transport: 'fetch', status: null, acknowledged: false };
        this.lastDelivery = delivery;
        const res = await this.fetchWithTimeout(this.endpointUrl, {
          method: 'POST',
          headers: {
            // Keep the unload fallback CORS-safelisted. A JSON content type can
            // trigger a preflight that the browser cancels while leaving a page.
            'Content-Type': action === 'pagehide'
              ? 'text/plain;charset=UTF-8'
              : 'application/json',
          },
          body,
          keepalive: action === 'pagehide',
        }, 10000, async (response) => {
          delivery.status = response.status ?? null;
          if (response.ok && typeof response.json === 'function') {
            try {
              const receipt = await response.json();
              if (receipt && receipt.recorded === true) {
                const captureFlags = Object.prototype.hasOwnProperty.call(receipt, 'capture_persisted');
                this.lastReceipt = {
                  receivedAt: Date.now(),
                  captureId: typeof receipt.capture_id === 'string' ? receipt.capture_id : null,
                  persisted: captureFlags ? receipt.capture_persisted === true : receipt.persisted === true,
                  buffered: captureFlags ? receipt.capture_buffered === true : receipt.buffered === true,
                  analysisAvailable: receipt.analysis_available === true,
                };
                delivery.acknowledged = true;
              }
            } catch (error) {
              if (error.name === 'AbortError') throw error;
              // A transport success alone does not confirm a recorded snapshot.
            }
          }
          return response;
        });
        if (!res.ok && res.headers && typeof res.headers.get === 'function') {
          const retryAfterSeconds = Number(res.headers.get('Retry-After'));
          if (Number.isFinite(retryAfterSeconds) && retryAfterSeconds > 0) {
            this.retryAfterMs = Math.min(300000, Math.ceil(retryAfterSeconds * 1000));
            this.retryNotBefore = Date.now() + this.retryAfterMs;
          }
        } else if (res.ok) {
          this.retryAfterMs = 0;
          this.retryNotBefore = 0;
        }
        return res.ok;
      } catch (e) {
        if (delivery) delivery.error = String(e.message || e).slice(0, 256);
        return false;
      }
    }

    async _sendTelemetry(action, lifecycleVersion) {
      try {
        const payload = await this.getPayload(action);
        if (action !== 'pagehide' && (this.destroyed || lifecycleVersion !== this.lifecycleVersion)) {
          return false;
        }
        const activitySignature = this.getActivitySignature(payload);
        const unchangedHeartbeat = action === 'heartbeat'
          && !this.pendingRetry
          && activitySignature === this.lastSentActivitySignature
          && Date.now() - this.lastSuccessfulSendAt < this.idleHeartbeatInterval;
        if (unchangedHeartbeat) return true;
        if (action === 'heartbeat' && !this.pendingRetry && Date.now() < this.retryNotBefore) return false;
        let body = JSON.stringify(payload);

        // Browsers commonly cap beacon/keepalive request bodies around 64 KiB.
        if (action === 'pagehide' && new Blob([body]).size > 60000 && payload.mouse) {
          const records = Array.isArray(payload.mouse.records) ? payload.mouse.records : [];
          const retained = records.map((record, index) => ({ record, index }));
          const moves = retained.filter(({ record }) => record && record.type === 'move' && record.source !== 'touch').slice(-40);
          const other = retained.filter(({ record }) => !record || record.type !== 'move' || record.source === 'touch').slice(-10);
          payload.mouse.records = [...moves, ...other]
            .sort((left, right) => left.index - right.index)
            .map(({ record }) => record);
          delete payload.mouse.chunks;
          payload.mouse.scrollEvents = (payload.mouse.scrollEvents || []).slice(-20);
          body = JSON.stringify(payload);
        }
        // Preserve model input-domain signals even when optional fingerprint data is oversized.
        if (action === 'pagehide' && new Blob([body]).size > 60000) {
          const fingerprint = payload.fingerprint || {};
          const userAgent = String(fingerprint.userAgent || '');
          const touchPoints = Number(fingerprint.maxTouchPoints);
          payload.fingerprint = {
            userAgent: /mobile|android|iphone|ipad|ipod/i.test(userAgent) ? 'mobile' : userAgent.slice(0, 512),
            maxTouchPoints: Number.isFinite(touchPoints) ? touchPoints : 0,
          };
          if (payload.botd && Array.isArray(payload.botd.reasons)) {
            payload.botd.reasons = payload.botd.reasons.slice(0, 10).map((reason) => String(reason).slice(0, 256));
          }
          body = JSON.stringify(payload);
        }

        if (action === 'heartbeat' && this.pendingRetry) {
          if (activitySignature !== this.pendingRetry.activitySignature) {
            this.pendingRetry.body = body;
            this.pendingRetry.activitySignature = activitySignature;
          }
          return false;
        }

        this.touchSession();
        const sent = await this.transmitTelemetry(body, action);
        if (sent && action !== 'pagehide') {
          this.lastSentActivitySignature = activitySignature;
          this.lastSuccessfulSendAt = Date.now();
          this.clearPendingRetry();
        } else if (!sent && action !== 'pagehide') {
          // Heartbeats are cumulative snapshots. Keeping only the latest failed
          // body bounds memory while allowing transient network failures to heal.
          this.scheduleRetry(body, lifecycleVersion, 1, activitySignature);
        }
        return sent;
      } catch (e) {
        return false;
      }
    }

    /**
     * Query backend real-time ML inference for bot verdict
     */
    async checkBotStatus(action = 'verify') {
      const lifecycleVersion = this.lifecycleVersion;
      try {
        const payload = await this.getPayload(action);
        if (this.destroyed || lifecycleVersion !== this.lifecycleVersion) {
          return { is_bot: false, verdict: 'UNKNOWN', decision_state: 'UNAVAILABLE', bot_probability: null, fallback: true, error: 'collector_inactive' };
        }
        return await this.fetchWithTimeout(this.detectUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }, 10000, async (res) => {
          if (!res.ok) {
            return {
              is_bot: false,
              verdict: 'UNKNOWN',
              decision_state: 'UNAVAILABLE',
              bot_probability: null,
              fallback: true,
              status: res.status,
              error: `HTTP ${res.status}`,
            };
          }
          return await res.json();
        });
      } catch (e) {
        return {
          is_bot: false,
          verdict: 'UNKNOWN',
          decision_state: 'UNAVAILABLE',
          bot_probability: null,
          fallback: true,
          error: e.message,
        };
      }
    }
  }

  // Auto-instantiate singleton on window if running in browser
  if (typeof window !== 'undefined') {
    window.BotCollector = BotCollector;
  }




  // --- Opt-in research pilot integration ---
  /** Opt-in single-tag integration; legacy manual BotCollector usage is unchanged. */
  function bootstrapPilot(Collector) {
    if (typeof window === 'undefined' || typeof document === 'undefined') return null;
    const script = document.currentScript;
    if (!script || !script.hasAttribute('data-datacat')) return null;
    try {
      const studyId = script.getAttribute('data-study-id') || '';
      const siteId = script.getAttribute('data-site-id') || '';
      if (![studyId, siteId].every((value) => /^[A-Za-z0-9_-]{1,64}$/.test(value))) {
        throw new Error('data-study-id and data-site-id must contain 1-64 letters, digits, _ or -');
      }
      const endpointUrl = new URL(script.getAttribute('data-endpoint') || 'api/v1/telemetry', script.src);
      if (!['http:', 'https:'].includes(endpointUrl.protocol)
          || (window.location.protocol === 'https:' && endpointUrl.protocol !== 'https:')) {
        throw new Error('Use an HTTPS API endpoint when embedding on an HTTPS website');
      }
      const interval = Number(script.getAttribute('data-interval-ms') || 15000);
      if (!Number.isInteger(interval) || interval < 1000 || interval > 60000) {
        throw new Error('data-interval-ms must be an integer between 1000 and 60000');
      }
      if (window.DatacatPilot) {
        const current = window.DatacatPilot.collector;
        if (!current || current.endpointUrl !== endpointUrl.href
            || current.studyId !== studyId || current.siteId !== siteId) {
          throw new Error('A different DATACAT pilot is already configured on this page');
        }
        return window.DatacatPilot;
      }
      if (window._bc && typeof window._bc.sendTelemetry === 'function') {
        throw new Error('An existing manual collector (_bc) is active; use one integration method');
      }
      const collector = new Collector({
        endpointUrl: endpointUrl.href,
        detectUrl: new URL('detect', endpointUrl).href,
        studyId, siteId, autoSendInterval: interval,
      });
      const pilot = {
        collector,
        stop: () => collector.destroy(),
        getStatus: () => ({
          sessionId: collector.sessionId, studyId, siteId,
          stopped: collector.destroyed,
          lastReceipt: collector.lastReceipt,
          lastDelivery: collector.lastDelivery,
        }),
      };
      window.DatacatPilot = pilot;
      pilot.ready = collector.start().catch((error) => {
        console.error('[DATACAT] Collector initialization failed:', error);
        return false;
      });
      return pilot;
    } catch (error) {
      console.error('[DATACAT] Pilot configuration:', error.message);
      return null;
    }
  }

  bootstrapPilot(BotCollector);


  return BotCollector;
}));

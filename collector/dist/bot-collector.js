(function (global, factory) {
  typeof exports === 'object' && typeof module !== 'undefined' ? module.exports = factory() :
  typeof define === 'function' && define.amd ? define(factory) :
  (global = typeof globalThis !== 'undefined' ? globalThis : global || self, global.BotCollector = factory());
})(this, (function () { 'use strict';

  // --- FingerprintJS Hardware Components ---
  /**
   * Lightweight Browser & Device Fingerprint Extractor
   * Inspired by FingerprintJS (https://github.com/fingerprintjs/fingerprintjs)
   * Collects ~40 browser/hardware signals and generates a deterministic visitor ID hash.
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

  // Installed font detection (heuristic probe)
  function getFontList() {
    if (typeof document === 'undefined') return [];
    const container = document.body || document.documentElement;
    if (!container) return [];

    const baseFonts = ['monospace', 'sans-serif', 'serif'];
    const testFonts = [
      'Arial', 'Verdana', 'Times New Roman', 'Courier New',
      'Georgia', 'Comic Sans MS', 'Trebuchet MS', 'Impact',
      'Segoe UI', 'Roboto', 'Helvetica', 'Ubuntu', 'Consolas'
    ];

    const span = document.createElement('span');
    span.style.fontSize = '72px';
    span.innerHTML = 'mmmmmmmmmmlli';
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

    // Generate deterministic visitorId hash (high-entropy: 16 components)
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
      components.audioHash,
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
   * Implements 18 heuristic tests for browser automation, headless environments, and spoofing.
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
      this.startTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
      this.isListening = false;
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
    }

    clear() {
      this.records = [];
      this.chunks = [];
      this.lastMoveRecord = null;
      this.scrollEvents = [];
      this.startTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
    }

    recordPoint(type, clientX, clientY) {
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      const time = Math.round(now - this.startTime);

      const w = (typeof window !== 'undefined' && window.innerWidth > 0) ? window.innerWidth : 1920;
      const h = (typeof window !== 'undefined' && window.innerHeight > 0) ? window.innerHeight : 1080;
      const safeX = (typeof clientX === 'number' && Number.isFinite(clientX)) ? clientX : 0;
      const safeY = (typeof clientY === 'number' && Number.isFinite(clientY)) ? clientY : 0;
      const normX = Math.max(0, Math.min(1, Number((safeX / w).toFixed(5))));
      const normY = Math.max(0, Math.min(1, Number((safeY / h).toFixed(5))));

      const previousRecord = this.records.length > 0 ? this.records[this.records.length - 1] : null;
      const prev = type === 'move' ? this.lastMoveRecord : previousRecord;

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
      this.recordPoint('move', e.clientX, e.clientY);
    }

    handleMouseDown(e) {
      this.recordPoint('down', e.clientX, e.clientY);
    }

    handleMouseUp(e) {
      this.recordPoint('up', e.clientX, e.clientY);
    }

    handleClick(e) {
      this.recordPoint('click', e.clientX, e.clientY);
    }

    handleWheel(e) {
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
        this.recordPoint('down', e.touches[0].clientX, e.touches[0].clientY);
      }
    }

    handleTouchMove(e) {
      if (e.touches && e.touches[0]) {
        this.recordPoint('move', e.touches[0].clientX, e.touches[0].clientY);
      }
    }

    handleTouchEnd(e) {
      const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0]);
      if (touch) {
        this.recordPoint('up', touch.clientX, touch.clientY);
      } else {
        const last = this.records.length > 0 ? this.records[this.records.length - 1] : null;
        const w = (typeof window !== 'undefined' && window.innerWidth > 0) ? window.innerWidth : 1920;
        const h = (typeof window !== 'undefined' && window.innerHeight > 0) ? window.innerHeight : 1080;
        const x = last ? last.x * w : 0;
        const y = last ? last.y * h : 0;
        this.recordPoint('up', x, y);
      }
    }

    /**
     * Split records into consecutive chunks of 24 points for LSTM input
     */
    getChunks(chunkSize = 24) {
      const moveRecords = this.records.filter((r) => r.type === 'move');
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
      if (this.records.length < 2) {
        return {
          pointCount: this.records.length,
          hasEnoughData: false,
          avgSpeed: 0,
          maxSpeed: 0,
          avgAccel: 0,
          straightness: 1.0,
        };
      }

      const moveRecords = this.records.filter((r) => r.type === 'move');
      const speeds = moveRecords.map((r) => r.speed).filter((s) => s > 0);
      const accels = moveRecords.map((r) => r.accel).filter((a) => a > 0);

      const avgSpeed = speeds.length ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0;
      const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
      const avgAccel = accels.length ? accels.reduce((a, b) => a + b, 0) / accels.length : 0;

      // Straightness = net displacement / total path length
      const first = moveRecords[0] || this.records[0];
      const last = moveRecords[moveRecords.length - 1] || this.records[this.records.length - 1];
      const netDist = Math.sqrt(Math.pow(last.x - first.x, 2) + Math.pow(last.y - first.y, 2));
      const totalDist = moveRecords.reduce((sum, r) => sum + (r.distance || 0), 0);
      const straightness = totalDist > 0 ? Number((netDist / totalDist).toFixed(4)) : 1.0;

      return {
        pointCount: this.records.length,
        movePointCount: moveRecords.length,
        hasEnoughData: moveRecords.length >= this.chunkSize + 1,
        avgSpeed: Number(avgSpeed.toFixed(4)),
        maxSpeed: Number(maxSpeed.toFixed(4)),
        avgAccel: Number(avgAccel.toFixed(4)),
        straightness,
      };
    }

    exportData() {
      return {
        records: this.records.slice(-100), // last 100 points
        chunks: this.getChunks(this.chunkSize),
        stats: this.getStats(),
        scrollEvents: this.scrollEvents.slice(-50), // last 50 scroll events
      };
    }
  }


  // --- Unified BotCollector SDK ---
  /**
   * Unified Bot & Fraud Telemetry Collector SDK
   * Combines FingerprintJS + BotD Heuristics + DELBOT Mouse Dynamics
   */





  class BotCollector {
    constructor(options = {}) {
      this.endpointUrl = options.endpointUrl || options.endpoint || '/api/v1/telemetry';
      this.detectUrl = options.detectUrl || '/api/v1/detect';
      this.sessionId = options.sessionId || this.generateSessionId();
      this.autoSendInterval = options.autoSendInterval !== undefined ? options.autoSendInterval : 5000;
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
      this.maxRetryAttempts = Math.max(0, Number(options.maxRetryAttempts ?? 3) || 0);
      this.retryBaseDelay = Math.max(100, Number(options.retryBaseDelay ?? 500) || 500);
      this.handlePageHide = () => { this.sendTelemetry('pagehide'); };
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

      await this.sendTelemetry('init');

      if (!this.destroyed && lifecycleVersion === this.lifecycleVersion && this.autoSendInterval > 0) {
        this.timer = setInterval(() => {
          this.sendTelemetry().catch(() => false);
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
      for (const controller of this.abortControllers) controller.abort();
      this.abortControllers.clear();
      if (typeof window !== 'undefined') {
        window.removeEventListener('pagehide', this.handlePageHide, { capture: true });
      }
    }

    async getPayload(action = 'heartbeat') {
      if (!this.cachedFingerprint) {
        const { visitorId, components } = await getFingerprintComponents();
        this.cachedFingerprint = { visitorId, components };
        this.cachedBotd = runBotDetectors(components);
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
        pageUrl: typeof window !== 'undefined' ? window.location.href : '',
        referrer: typeof document !== 'undefined' ? document.referrer : '',
        visitorId: this.cachedFingerprint.visitorId,
        fingerprint: this.cachedFingerprint.components,
        botd: this.cachedBotd,
        mouse: mouseData,
      };
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

    async fetchWithTimeout(url, options, timeoutMs = 10000) {
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const timeoutId = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
      if (controller) this.abortControllers.add(controller);
      try {
        return await fetch(url, {
          ...options,
          ...(controller ? { signal: controller.signal } : {}),
        });
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

    scheduleRetry(body, lifecycleVersion, attempt = 1) {
      if (
        this.destroyed ||
        lifecycleVersion !== this.lifecycleVersion ||
        attempt > this.maxRetryAttempts
      ) return;

      if (this.retryTimer) clearTimeout(this.retryTimer);
      this.pendingRetry = { body, lifecycleVersion, attempt };
      const delay = this.retryBaseDelay * Math.pow(2, attempt - 1);
      this.retryTimer = setTimeout(async () => {
        this.retryTimer = null;
        const pending = this.pendingRetry;
        if (!pending || this.destroyed || pending.lifecycleVersion !== this.lifecycleVersion) return;

        const sent = await this.transmitTelemetry(pending.body, 'retry');
        if (sent) {
          this.pendingRetry = null;
        } else {
          this.scheduleRetry(pending.body, pending.lifecycleVersion, pending.attempt + 1);
        }
      }, delay);
    }

    async transmitTelemetry(body, action) {
      try {
        if (action === 'pagehide' && typeof navigator !== 'undefined' && navigator.sendBeacon) {
          // text/plain is CORS-safelisted, so a cross-origin unload beacon does
          // not depend on an asynchronous preflight that the browser may cancel.
          const blob = new Blob([body], { type: 'text/plain;charset=UTF-8' });
          const success = navigator.sendBeacon(this.endpointUrl, blob);
          if (success) return true;
        }

        const res = await this.fetchWithTimeout(this.endpointUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
          keepalive: action === 'pagehide',
        });
        return res.ok;
      } catch (e) {
        return false;
      }
    }

    async _sendTelemetry(action, lifecycleVersion) {
      try {
        const payload = await this.getPayload(action);
        if (action !== 'pagehide' && (this.destroyed || lifecycleVersion !== this.lifecycleVersion)) {
          return false;
        }
        let body = JSON.stringify(payload);

        // Browsers commonly cap beacon/keepalive request bodies around 64 KiB.
        if (action === 'pagehide' && new Blob([body]).size > 60000 && payload.mouse) {
          payload.mouse.records = (payload.mouse.records || []).slice(-40);
          payload.mouse.chunks = (payload.mouse.chunks || []).slice(-2);
          payload.mouse.scrollEvents = (payload.mouse.scrollEvents || []).slice(-20);
          body = JSON.stringify(payload);
        }
        // Fingerprint fields such as user-agent or font lists can also dominate
        // an unload payload. The init/heartbeat requests already sent this data.
        if (action === 'pagehide' && new Blob([body]).size > 60000) {
          payload.fingerprint = {};
          if (payload.botd && Array.isArray(payload.botd.reasons)) {
            payload.botd.reasons = payload.botd.reasons.slice(0, 10);
          }
          body = JSON.stringify(payload);
        }

        const sent = await this.transmitTelemetry(body, action);
        if (sent && action !== 'pagehide') {
          this.clearPendingRetry();
        } else if (!sent && action !== 'pagehide') {
          // Heartbeats are cumulative snapshots. Keeping only the latest failed
          // body bounds memory while allowing transient network failures to heal.
          this.scheduleRetry(body, lifecycleVersion);
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
          return { is_bot: false, bot_probability: 0, fallback: true, error: 'collector_inactive' };
        }
        const res = await this.fetchWithTimeout(this.detectUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          return {
            is_bot: this.cachedBotd?.isBot || false,
            bot_probability: this.cachedBotd?.heuristicScore || 0,
            fallback: true,
            status: res.status,
            error: `HTTP ${res.status}`,
          };
        }
        return await res.json();
      } catch (e) {
        return {
          is_bot: this.cachedBotd?.isBot || false,
          bot_probability: this.cachedBotd?.heuristicScore || 0,
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




  return BotCollector;
}));

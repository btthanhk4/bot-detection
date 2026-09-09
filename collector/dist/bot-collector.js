(function (global, factory) {
  typeof exports === 'object' && typeof module !== 'undefined' ? module.exports = factory() :
  typeof define === 'function' && define.amd ? define(factory) :
  (global = typeof globalThis !== 'undefined' ? globalThis : global || self, global.BotCollector = factory());
})(this, (function () { 'use strict';

  function fnv1a(str) {
    let hash = 2166136261;
    for (let i = 0; i < str.length; i++) {
      hash ^= str.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
  }

  function getCanvasFingerprint() {
    try {
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

  function getWebGLFingerprint() {
    try {
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

  async function getAudioFingerprint() {
    try {
      const AudioCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
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
      const renderedBuffer = await ctx.startRendering();
      let sum = 0;
      const channelData = renderedBuffer.getChannelData(0);
      for (let i = 4500; i < 5000; i++) sum += Math.abs(channelData[i]);
      return sum.toString();
    } catch (e) {
      return 'error';
    }
  }

  function getFontList() {
    const baseFonts = ['monospace', 'sans-serif', 'serif'];
    const testFonts = ['Arial', 'Verdana', 'Times New Roman', 'Courier New', 'Georgia', 'Comic Sans MS', 'Trebuchet MS', 'Impact', 'Segoe UI', 'Roboto', 'Helvetica', 'Ubuntu', 'Consolas'];
    try {
      const span = document.createElement('span');
      span.style.fontSize = '72px';
      span.innerHTML = 'mmmmmmmmmmlli';
      span.style.position = 'absolute';
      span.style.left = '-9999px';
      document.body.appendChild(span);
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
      document.body.removeChild(span);
      return detected;
    } catch (e) {
      return [];
    }
  }

  async function getFingerprintComponents() {
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
      pixelRatio: window.devicePixelRatio || 1,
      timezoneOffset: new Date().getTimezoneOffset(),
      timezone: Intl?.DateTimeFormat?.().resolvedOptions?.().timeZone || '',
      sessionStorage: typeof window.sessionStorage !== 'undefined',
      localStorage: typeof window.localStorage !== 'undefined',
      indexedDb: typeof window.indexedDB !== 'undefined',
      openDatabase: typeof window.openDatabase !== 'undefined',
      pluginsLength: nav.plugins ? nav.plugins.length : 0,
      doNotTrack: nav.doNotTrack || 'unknown',
      webglVendor: webgl.vendor,
      webglRenderer: webgl.renderer,
      canvasHash: canvas,
      audioHash: audio,
      fontsCount: fonts.length,
      fontsList: fonts,
    };

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
    ].join('###');

    return { visitorId: fnv1a(rawId), components };
  }

  function runBotDetectors(components = {}) {
    const nav = typeof navigator !== 'undefined' ? navigator : {};
    const win = typeof window !== 'undefined' ? window : {};
    const doc = typeof document !== 'undefined' ? document : {};

    const detectors = {};
    const reasons = [];

    detectors.webdriver = !!(nav.webdriver || doc.documentElement?.getAttribute('webdriver'));
    if (detectors.webdriver) reasons.push('navigator.webdriver is true');

    const automationProps = ['_phantom', '__nightmare', '_selenium', 'callPhantom', 'callSelenium', 'domAutomation'];
    let foundDistinctive = false;
    for (const prop of automationProps) {
      if (prop in win || (doc && prop in doc)) {
        foundDistinctive = true;
        reasons.push(`Distinctive automation property found: ${prop}`);
        break;
      }
    }
    for (const key of Object.keys(win)) {
      if (key.startsWith('cdc_') || key.startsWith('$cdc_')) {
        foundDistinctive = true;
        reasons.push(`Chromedriver artifact found: ${key}`);
        break;
      }
    }
    detectors.distinctiveProperties = foundDistinctive;

    const renderer = (components.webglRenderer || '').toLowerCase();
    const isVirtualGpu = /swiftshader|llvmpipe|virtualbox|vmware|mesa offscreen|softpipe/i.test(renderer);
    detectors.virtualGpu = isVirtualGpu;
    if (isVirtualGpu) reasons.push(`Software / Virtual GPU detected: ${renderer}`);

    const isChrome = /chrome/i.test(nav.userAgent || '') && !/edg|opr|brave/i.test(nav.userAgent || '');
    const isDesktop = !/android|iphone|ipad|ipod|mobile/i.test(nav.userAgent || '');
    const pluginsLength = nav.plugins ? nav.plugins.length : 0;
    detectors.pluginsInconsistency = isChrome && isDesktop && pluginsLength === 0;
    if (detectors.pluginsInconsistency) reasons.push('Chrome desktop with 0 plugins (indicates headless)');

    const langs = nav.languages || [];
    const lang = nav.language || '';
    detectors.languagesInconsistency = !langs.length || (lang && langs.length > 0 && !langs.includes(lang));

    const w = win.innerWidth || 0;
    const h = win.innerHeight || 0;
    detectors.windowSize = (w === 0 && h === 0);

    let errorTraceBot = false;
    try {
      throw new Error('trace');
    } catch (err) {
      if (/puppeteer|playwright|selenium|phantomjs|webdriver/i.test(err.stack || '')) {
        errorTraceBot = true;
        reasons.push('Automation framework detected in stack trace');
      }
    }
    detectors.errorTrace = errorTraceBot;
    detectors.hasProcess = typeof win.process === 'object' && win.process?.versions?.node !== undefined;

    const ua = (nav.userAgent || '').toLowerCase();
    const plat = (nav.platform || '').toLowerCase();
    let platformMismatch = false;
    if (ua.includes('windows') && !plat.includes('win')) platformMismatch = true;
    if (ua.includes('macintosh') && !plat.includes('mac')) platformMismatch = true;
    if (ua.includes('linux') && !plat.includes('linux') && !plat.includes('arm')) platformMismatch = true;
    detectors.platformMismatch = platformMismatch;

    detectors.headlessUa = /headlesschrome/i.test(nav.userAgent || '');

    const keys = Object.keys(detectors);
    const flagged = keys.filter((k) => detectors[k]);
    const heuristicScore = keys.length ? flagged.length / keys.length : 0;

    return {
      isBot: flagged.length > 0,
      heuristicScore: Number(heuristicScore.toFixed(4)),
      flaggedCount: flagged.length,
      detectors,
      reasons,
    };
  }

  class MouseRecorder {
    constructor(options = {}) {
      this.maxRecords = options.maxRecords || 500;
      this.chunkSize = options.chunkSize || 24;
      this.records = [];
      this.startTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
      this.isListening = false;
      this.handleMouseMove = this.handleMouseMove.bind(this);
      this.handleMouseDown = this.handleMouseDown.bind(this);
      this.handleMouseUp = this.handleMouseUp.bind(this);
      this.handleClick = this.handleClick.bind(this);
    }

    start() {
      if (this.isListening || typeof window === 'undefined') return;
      this.isListening = true;
      window.addEventListener('mousemove', this.handleMouseMove, { passive: true });
      window.addEventListener('mousedown', this.handleMouseDown, { passive: true });
      window.addEventListener('mouseup', this.handleMouseUp, { passive: true });
      window.addEventListener('click', this.handleClick, { passive: true });
    }

    stop() {
      if (!this.isListening || typeof window === 'undefined') return;
      this.isListening = false;
      window.removeEventListener('mousemove', this.handleMouseMove);
      window.removeEventListener('mousedown', this.handleMouseDown);
      window.removeEventListener('mouseup', this.handleMouseUp);
      window.removeEventListener('click', this.handleClick);
    }

    recordPoint(type, clientX, clientY) {
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      const time = Math.round(now - this.startTime);
      const w = window.innerWidth || 1920;
      const h = window.innerHeight || 1080;
      const normX = Number((clientX / w).toFixed(5));
      const normY = Number((clientY / h).toFixed(5));
      const prev = this.records.length > 0 ? this.records[this.records.length - 1] : null;

      let timeDiff = 0, dx = 0, dy = 0, distance = 0, speedX = 0, speedY = 0, speed = 0, accelX = 0, accelY = 0, accel = 0;
      if (prev) {
        timeDiff = Math.max(1, time - prev.time);
        dx = normX - prev.x;
        dy = normY - prev.y;
        distance = Math.sqrt(dx * dx + dy * dy);
        speedX = dx / (timeDiff / 1000);
        speedY = dy / (timeDiff / 1000);
        speed = distance / (timeDiff / 1000);
        accelX = (speedX - prev.speedX) / (timeDiff / 1000);
        accelY = (speedY - prev.speedY) / (timeDiff / 1000);
        accel = Math.sqrt(accelX * accelX + accelY * accelY);
      }

      this.records.push({
        time, type, x: normX, y: normY, dx: Number(dx.toFixed(5)), dy: Number(dy.toFixed(5)),
        timeDiff, distance: Number(distance.toFixed(5)), speedX: Number(speedX.toFixed(3)),
        speedY: Number(speedY.toFixed(3)), speed: Number(speed.toFixed(3)),
        accelX: Number(accelX.toFixed(3)), accelY: Number(accelY.toFixed(3)), accel: Number(accel.toFixed(3)),
      });
      if (this.records.length > this.maxRecords) this.records.shift();
    }

    handleMouseMove(e) { this.recordPoint('move', e.clientX, e.clientY); }
    handleMouseDown(e) { this.recordPoint('down', e.clientX, e.clientY); }
    handleMouseUp(e) { this.recordPoint('up', e.clientX, e.clientY); }
    handleClick(e) { this.recordPoint('click', e.clientX, e.clientY); }

    getChunks(chunkSize = 24) {
      const moveRecords = this.records.filter((r) => r.type === 'move' && r.timeDiff > 0);
      const chunks = [];
      for (let i = 0; i + chunkSize <= moveRecords.length; i += Math.floor(chunkSize / 2)) {
        chunks.push(moveRecords.slice(i, i + chunkSize).map((p) => [
          p.dx, p.dy, p.speedX, p.speedY, p.speed, p.accel, p.distance, p.timeDiff / 1000,
        ]));
      }
      return chunks;
    }

    getStats() {
      if (this.records.length < 2) return { pointCount: this.records.length, hasEnoughData: false, avgSpeed: 0, maxSpeed: 0, avgAccel: 0, straightness: 1.0 };
      const speeds = this.records.map((r) => r.speed).filter((s) => s > 0);
      const accels = this.records.map((r) => r.accel).filter((a) => a > 0);
      const avgSpeed = speeds.length ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0;
      const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
      const avgAccel = accels.length ? accels.reduce((a, b) => a + b, 0) / accels.length : 0;
      const first = this.records[0];
      const last = this.records[this.records.length - 1];
      const netDist = Math.sqrt(Math.pow(last.x - first.x, 2) + Math.pow(last.y - first.y, 2));
      const totalDist = this.records.reduce((sum, r) => sum + (r.distance || 0), 0);
      const straightness = totalDist > 0 ? Number((netDist / totalDist).toFixed(4)) : 1.0;
      return {
        pointCount: this.records.length, hasEnoughData: this.records.length >= this.chunkSize,
        avgSpeed: Number(avgSpeed.toFixed(4)), maxSpeed: Number(maxSpeed.toFixed(4)),
        avgAccel: Number(avgAccel.toFixed(4)), straightness,
      };
    }

    exportData() {
      return { records: this.records.slice(-100), chunks: this.getChunks(this.chunkSize), stats: this.getStats() };
    }
  }

  class BotCollector {
    constructor(options = {}) {
      this.endpointUrl = options.endpointUrl || '/api/v1/telemetry';
      this.detectUrl = options.detectUrl || '/api/v1/detect';
      this.sessionId = options.sessionId || ('sess_' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36));
      this.autoSendInterval = options.autoSendInterval || 5000;
      this.mouseRecorder = new MouseRecorder();
      this.cachedFingerprint = null;
      this.cachedBotd = null;
      this.timer = null;
    }

    async init() {
      this.mouseRecorder.start();
      const { visitorId, components } = await getFingerprintComponents();
      this.cachedFingerprint = { visitorId, components };
      this.cachedBotd = runBotDetectors(components);
      if (this.autoSendInterval > 0) {
        this.timer = setInterval(() => { this.sendTelemetry(); }, this.autoSendInterval);
      }
      return this;
    }

    destroy() {
      this.mouseRecorder.stop();
      if (this.timer) clearInterval(this.timer);
    }

    async getPayload(action = 'heartbeat') {
      if (!this.cachedFingerprint) {
        const { visitorId, components } = await getFingerprintComponents();
        this.cachedFingerprint = { visitorId, components };
        this.cachedBotd = runBotDetectors(components);
      }
      return {
        sessionId: this.sessionId,
        action,
        timestamp: Date.now(),
        pageUrl: typeof window !== 'undefined' ? window.location.href : '',
        referrer: typeof document !== 'undefined' ? document.referrer : '',
        visitorId: this.cachedFingerprint.visitorId,
        fingerprint: this.cachedFingerprint.components,
        botd: this.cachedBotd,
        mouse: this.mouseRecorder.exportData(),
      };
    }

    async sendTelemetry(action = 'telemetry') {
      const payload = await this.getPayload(action);
      const body = JSON.stringify(payload);
      if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
        if (navigator.sendBeacon(this.endpointUrl, body)) return true;
      }
      try {
        await fetch(this.endpointUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true });
        return true;
      } catch (e) {
        return false;
      }
    }

    async checkBotStatus(action = 'verify') {
      const payload = await this.getPayload(action);
      try {
        const res = await fetch(this.detectUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        return await res.json();
      } catch (e) {
        return { is_bot: this.cachedBotd?.isBot || false, bot_probability: this.cachedBotd?.heuristicScore || 0, fallback: true, error: e.message };
      }
    }
  }

  return BotCollector;
}));

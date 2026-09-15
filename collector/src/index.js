/**
 * Unified Bot & Fraud Telemetry Collector SDK
 * Combines FingerprintJS + BotD Heuristics + DELBOT Mouse Dynamics
 */

import { getFingerprintComponents } from './fingerprint.js';
import { runBotDetectors } from './botd.js';
import { MouseRecorder } from './mouse.js';

export class BotCollector {
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
    this.sequence = 0;
    this.sendPromise = null;
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
    this.initPromise = this.initialize();
    return this.initPromise;
  }

  async initialize() {
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
    this.cachedFingerprint = { visitorId, components };
    this.cachedBotd = runBotDetectors(components);

    if (this.destroyed) return this;

    await this.sendTelemetry('init');

    if (!this.destroyed && this.autoSendInterval > 0) {
      this.timer = setInterval(() => {
        this.sendTelemetry().catch(() => false);
      }, this.autoSendInterval);
    }

    return this;
  }

  destroy() {
    this.destroyed = true;
    this.mouseRecorder.stop();
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.initPromise = null;
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

    return {
      sessionId: this.sessionId,
      action,
      timestamp: Date.now(),
      sequence: this.sequence++,
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

    const operation = this._sendTelemetry(action);
    if (action === 'pagehide') return operation;
    const tracked = operation.finally(() => {
      if (this.sendPromise === tracked) this.sendPromise = null;
    });
    this.sendPromise = tracked;
    return tracked;
  }

  async _sendTelemetry(action) {
    let timeoutId = null;
    try {
      const payload = await this.getPayload(action);
      let body = JSON.stringify(payload);

      // Browsers commonly cap beacon/keepalive request bodies around 64 KiB.
      if (action === 'pagehide' && body.length > 60000 && payload.mouse) {
        payload.mouse.records = (payload.mouse.records || []).slice(-40);
        payload.mouse.chunks = (payload.mouse.chunks || []).slice(-2);
        payload.mouse.scrollEvents = (payload.mouse.scrollEvents || []).slice(-20);
        body = JSON.stringify(payload);
      }

      if (action === 'pagehide' && typeof navigator !== 'undefined' && navigator.sendBeacon) {
        const blob = new Blob([body], { type: 'application/json' });
        const success = navigator.sendBeacon(this.endpointUrl, blob);
        if (success) return true;
      }

      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      timeoutId = controller ? setTimeout(() => controller.abort(), 10000) : null;
      const res = await fetch(this.endpointUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: action === 'pagehide',
        ...(controller ? { signal: controller.signal } : {}),
      });
      return res.ok;
    } catch (e) {
      return false;
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
    }
  }

  /**
   * Query backend real-time ML inference for bot verdict
   */
  async checkBotStatus(action = 'verify') {
    const payload = await this.getPayload(action);
    try {
      const res = await fetch(this.detectUrl, {
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

export default BotCollector;

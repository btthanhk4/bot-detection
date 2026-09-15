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
    // Pre-warm fingerprint and heuristics
    const { visitorId, components } = await getFingerprintComponents();
    this.cachedFingerprint = { visitorId, components };
    this.cachedBotd = runBotDetectors(components);

    if (this.destroyed) return this;

    if (typeof window !== 'undefined') {
      window.addEventListener('pagehide', this.handlePageHide, { capture: true });
    }

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

    return {
      sessionId: this.sessionId,
      action,
      timestamp: Date.now(),
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
    const payload = await this.getPayload(action);
    const body = JSON.stringify(payload);

    if (action === 'pagehide' && typeof navigator !== 'undefined' && navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' });
      const success = navigator.sendBeacon(this.endpointUrl, blob);
      if (success) return true;
    }

    try {
      const res = await fetch(this.endpointUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true,
      });
      return res.ok;
    } catch (e) {
      return false;
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

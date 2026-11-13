/**
 * Unified Bot & Fraud Telemetry Collector SDK
 * Combines FingerprintJS + BotD Heuristics + DELBOT Mouse Dynamics
 */

import { getFingerprintComponents } from './fingerprint.js';
import { runBotDetectors } from './botd.js';
import { collectBrowserProfile } from './profile.js';
import { collectAutomationSignals, probeNotificationPermission, probeWorkerConsistency } from './automation.js';
import { MouseRecorder } from './mouse.js';
import { PagePresence } from './presence.js';

export const COLLECTOR_VERSION = '1.16.1';

const SESSION_STORAGE_KEY = 'datacat_session';
// A random id kept in this site's localStorage (collector 1.11). The API counts how many
// browsers, not tabs, one device fingerprint starts sessions from on one address: a person's
// thirty product tabs share it; a farm that wipes storage between runs does not.
const DEVICE_STORAGE_KEY = 'datacat_device';
// Set when the API refuses this website (not registered, or paused): the collector stays
// silent on it until then, instead of retrying every few seconds on every page.
const REFUSAL_STORAGE_KEY = 'datacat_refused';
const MAX_REFUSAL_MS = 7 * 24 * 3600 * 1000;
// Collector 1.14: the API writes into the script it serves when a page last became monitored
// (Unix seconds). A refusal recorded before then is void, so a page registered or resumed again
// collects at once instead of after the silence. 0 when the script is not served by the API.
const REGISTRY_EPOCH = Number('__DATACAT_REGISTRY_EPOCH__') || 0;
// Collector 1.15: reference labels from Fingerprint bot detection (api_service.reference). The API
// writes its public key and the sampled share of sessions into the script; no key or 0 turns it off.
const REFERENCE_KEY = '__DATACAT_FP_KEY__';
const REFERENCE_RATE = Number('__DATACAT_FP_RATE__') || 0;
const REFERENCE_STORAGE_KEY = 'datacat_reference';

function refusalStores() {
  const stores = [];
  try { if (window.localStorage) stores.push(window.localStorage); } catch (e) { /* blocked */ }
  try { if (window.sessionStorage) stores.push(window.sessionStorage); } catch (e) { /* blocked */ }
  return stores;
}

function currentPath() {
  try { return String(window.location.pathname || '/'); } catch (e) { return '/'; }
}

// X-Datacat-Stop of a refused request: [seconds, scope], or null when the API did not refuse.
function stopSignal(response) {
  if (!response || response.status !== 403 || !response.headers || typeof response.headers.get !== 'function') {
    return null;
  }
  const seconds = Number(response.headers.get('X-Datacat-Stop'));
  if (!(seconds > 0)) return null;
  return [seconds, response.headers.get('X-Datacat-Stop-Scope') === 'page' ? 'page' : 'origin'];
}

function boundedUrl(value) {
  return String(value || '').slice(0, 2048);
}

export class BotCollector {
  constructor(options = {}) {
    this.endpointUrl = options.endpointUrl || options.endpoint || '/api/v1/telemetry';
    this.detectUrl = options.detectUrl || '/api/v1/detect';
    // Collector 1.13: a page-view token from the API for each session (api_service.page_tokens),
    // asked for beside the telemetry endpoint of a third-party integration. A gateway endpoint
    // (first-party path) proves its page loads with the gateway's cookie instead.
    const endpointPath = String(this.endpointUrl).split('?')[0];
    this.visitUrl = options.visitUrl !== undefined ? options.visitUrl
      : (/^https?:\/\//.test(endpointPath) && /\/api\/v1\/telemetry$/.test(endpointPath)
        ? endpointPath.replace(/\/api\/v1\/telemetry$/, '/api/v1/visit') : null);
    this.pageToken = null;
    this.tokenSessionId = null;
    this.referenceEventId = null;
    this.referenceSessionId = null;
    this.tokenPromise = null;
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
    this.presence = new PagePresence();
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
    // Gateway embeds (policy 24) greet the API before fingerprinting; see sendHello().
    this.helloEnabled = options.hello === true;
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

  deviceToken() {
    if (this.cachedDeviceToken !== undefined) return this.cachedDeviceToken;
    this.cachedDeviceToken = null;
    try {
      let token = window.localStorage.getItem(DEVICE_STORAGE_KEY);
      if (!token || !/^[a-f0-9]{32}$/.test(token)) {
        const bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);
        token = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
        window.localStorage.setItem(DEVICE_STORAGE_KEY, token);
      }
      this.cachedDeviceToken = token;
    } catch (e) { /* storage blocked: every session counts on its own */ }
    return this.cachedDeviceToken;
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

  // When the API last refused this website (or this page of it), until when the collector stays
  // silent. A refusal from before the registry epoch, or for another page, does not count.
  refusedUntil() {
    for (const store of refusalStores()) {
      try {
        const saved = JSON.parse(store.getItem(REFUSAL_STORAGE_KEY) || 'null');
        if (!saved || !Number.isFinite(saved.until)) continue;
        if (REGISTRY_EPOCH > 0 && !(Number(saved.epoch) >= REGISTRY_EPOCH)) {
          store.removeItem(REFUSAL_STORAGE_KEY);
          continue;
        }
        if (typeof saved.path === 'string' && saved.path !== currentPath()) continue;
        return Math.min(saved.until, Date.now() + MAX_REFUSAL_MS);
      } catch (e) { /* unreadable: ignore */ }
    }
    return 0;
  }

  refuse(seconds, scope = 'origin') {
    this.refused = true;
    const record = { until: Date.now() + Math.min(seconds * 1000, MAX_REFUSAL_MS), epoch: REGISTRY_EPOCH };
    if (scope === 'page') record.path = currentPath();
    // localStorage first; sessionStorage where it is blocked; else silent for this page only.
    for (const store of refusalStores()) {
      try {
        store.setItem(REFUSAL_STORAGE_KEY, JSON.stringify(record));
        break;
      } catch (e) { /* try the next one */ }
    }
    this.destroy();
  }

  init() {
    if (this.initPromise) return this.initPromise;
    if (this.refused || this.refusedUntil() > Date.now()) {
      this.refused = true;
      this.initPromise = Promise.resolve(this);
      return this.initPromise;
    }
    this.destroyed = false;
    const lifecycleVersion = ++this.lifecycleVersion;
    this.tokenPromise = this.fetchPageToken();
    this.helloPromise = this.sendHello();
    this.referencePromise = this.fetchReference();
    this.initPromise = this.initialize(lifecycleVersion);
    return this.initPromise;
  }

  // The page-view token of the current session; telemetry goes without it if this fails.
  async fetchPageToken() {
    if (!this.visitUrl || typeof fetch !== 'function' || this.refused) return null;
    const sessionId = this.sessionId;
    try {
      const page = typeof window !== 'undefined' && window.location ? boundedUrl(window.location.href) : '';
      const url = this.visitUrl + (this.visitUrl.includes('?') ? '&' : '?') + 'sid=' + encodeURIComponent(sessionId)
        + (page ? '&page=' + encodeURIComponent(page) : '');
      const res = await this.fetchWithTimeout(url, { method: 'GET', credentials: 'omit' }, 5000);
      const stop = stopSignal(res);
      if (stop) {
        this.refuse(...stop);
        return null;
      }
      if (res && res.ok && res.status !== 204 && typeof res.json === 'function') {
        const body = await res.json();
        if (body && typeof body.token === 'string' && body.token.length <= 512 && sessionId === this.sessionId) {
          this.pageToken = body.token;
          this.tokenSessionId = sessionId;
        }
      }
    } catch (e) { /* judged as an unverified page load, never blocks telemetry */ }
    return this.pageToken;
  }

  // A sampled session also asks the Fingerprint agent for its own bot verdict, which the API
  // fetches server-side as a reference label (one identification per session). It never blocks
  // or changes DATACAT's telemetry, and a refused page loads nothing from a third party.
  async fetchReference() {
    if (!/^[A-Za-z0-9]{8,64}$/.test(REFERENCE_KEY) || !(REFERENCE_RATE > 0) || typeof window === 'undefined') {
      return null;
    }
    const sessionId = this.sessionId;
    let saved = null;
    try { saved = JSON.parse(window.sessionStorage.getItem(REFERENCE_STORAGE_KEY) || 'null'); } catch (e) { /* blocked */ }
    if (saved && saved.sid === sessionId) {
      if (typeof saved.eventId === 'string') {
        this.referenceEventId = saved.eventId;
        this.referenceSessionId = sessionId;
      }
      if (saved.done) return this.referenceEventId;
    }
    const picked = Math.random() < REFERENCE_RATE;
    const remember = (extra) => {
      try {
        window.sessionStorage.setItem(REFERENCE_STORAGE_KEY, JSON.stringify({ sid: sessionId, picked, done: true, ...extra }));
      } catch (e) { /* optional */ }
    };
    remember({});
    if (!picked) return null;
    if (this.tokenPromise) await this.tokenPromise;
    if (this.refused || this.destroyed || sessionId !== this.sessionId) return null;
    try {
      const agent = await import('https://fpjscdn.net/v4/' + REFERENCE_KEY);
      const fp = agent.start({ region: 'us' });
      const result = await fp.get({ linkedId: sessionId, timeout: 8000 });
      const eventId = result && typeof result.event_id === 'string' ? result.event_id : '';
      if (/^[A-Za-z0-9._-]{1,128}$/.test(eventId) && sessionId === this.sessionId && !this.destroyed) {
        this.referenceEventId = eventId;
        this.referenceSessionId = sessionId;
        remember({ eventId });
        this.sendTelemetry('heartbeat').catch(() => false);
      }
    } catch (e) { /* ad blocker or CSP: this session simply has no reference label */ }
    return this.referenceEventId;
  }

  // Greets the API before fingerprinting (which takes a second or more), so a gateway that
  // gates shop requests on this page can tell that the collector runs. No device data.
  // A third-party page waits for the token answer first (at most 1.5 s): on a refused website
  // that answer already silences the collector, so the visitor costs the API one request.
  async sendHello() {
    if (!this.helloEnabled || this.helloSent || typeof fetch !== 'function') return;
    this.helloSent = true;
    if (this.tokenPromise) {
      await Promise.race([this.tokenPromise, new Promise((resolve) => setTimeout(resolve, 1500))]);
      if (this.refused || this.destroyed) return;
    }
    try {
      const res = await fetch(this.endpointUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId: this.sessionId,
          action: 'hello',
          timestamp: Date.now(),
          collector: { schemaVersion: 1, sdkVersion: COLLECTOR_VERSION, pageInstanceId: this.pageInstanceId },
        }),
        keepalive: true,
        credentials: 'same-origin',
      });
      const stop = stopSignal(res);
      if (stop) this.refuse(...stop);
    } catch (e) { /* never break the host page */ }
  }

  async initialize(lifecycleVersion) {
    this.mouseRecorder.start();
    try { this.presence.start(); } catch (e) { /* optional evidence */ }
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
    try { this.presence.stop(); } catch (e) { /* optional evidence */ }
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
    try { mouseData.presence = this.presence.exportData(); } catch (e) { /* optional evidence */ }
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
        ...(this.pageToken && this.tokenSessionId === this.sessionId ? { pageToken: this.pageToken } : {}),
        ...(this.referenceEventId && this.referenceSessionId === this.sessionId
          ? { referenceEventId: this.referenceEventId } : {}),
        ...(this.studyId ? { studyId: this.studyId } : {}),
        ...(this.siteId ? { siteId: this.siteId } : {}),
      },
      pageUrl: typeof window !== 'undefined' ? boundedUrl(window.location.href) : '',
      referrer: typeof document !== 'undefined' ? boundedUrl(document.referrer) : '',
      visitorId: this.cachedFingerprint.visitorId,
      deviceToken: this.deviceToken(),
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
    const gestures = mouse.touch && Number.isFinite(mouse.touch.total) ? mouse.touch.total : 0;
    const scrolls = mouse.presence && Number.isFinite(mouse.presence.scrolls) ? mouse.presence.scrolls : 0;
    // A reference event id that arrives later is news worth one heartbeat even without activity.
    const reference = payload.collector && payload.collector.referenceEventId ? payload.collector.referenceEventId : '';
    return JSON.stringify([payload.pageUrl || '', records, scrollEvents, keystrokes, clicks, gestures, scrolls, reference]);
  }

  /**
   * Send telemetry asynchronously via sendBeacon or fetch
   */
  async sendTelemetry(action = 'telemetry') {
    if (this.refused) return false;
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
        const stop = stopSignal(response);
        if (stop) {
          // This page is not monitored (or paused): no retries, no heartbeats.
          this.refuse(...stop);
          return response;
        }
        if (response.ok && typeof response.json === 'function') {
          try {
            const receipt = await response.json();
            if (receipt && receipt.session_closed === true && this.persistSession) {
              // The session was deleted on the server; continue under a fresh id (and token).
              this.sessionId = this.generateSessionId();
              this.touchSession();
              this.pageToken = null;
              this.tokenPromise = this.fetchPageToken();
            }
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
      if (this.tokenPromise && action !== 'pagehide') {
        // Usually ready long before fingerprinting ends; never hold telemetry back for long.
        await Promise.race([this.tokenPromise, new Promise((resolve) => setTimeout(resolve, 2000))]);
        if (this.refused) return false;
      }
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
        if (payload.mouse.touch && Array.isArray(payload.mouse.touch.gestures)) {
          payload.mouse.touch.gestures = payload.mouse.touch.gestures.slice(-6);
        }
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
        const stop = stopSignal(res);
        if (stop) this.refuse(...stop);
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

export default BotCollector;

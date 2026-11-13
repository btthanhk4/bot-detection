/**
 * Page presence and device motion (1.16.0): was the page ever seen, how long after it
 * appeared did the first finger land, how far was it scrolled, and was the phone held.
 *
 * - A prerendered or preloaded page (speculation rules, in-app browser prefetch) runs
 *   scripts before anyone looks at it; such a session is not a visit.
 * - Reaction time: a person needs a few hundred milliseconds to see a page and touch it.
 * - Motion (zkSENSE, BeCAPTCHA): a phone in a hand trembles; an emulator reports no
 *   motion or a constant vector, a phone in a rack lies perfectly still. Only summary
 *   statistics leave the page; no motion stream is kept. iOS asks for permission before
 *   any motion event, so nothing is requested and nothing arrives there.
 */

const MOTION_MAX_EVENTS = 400;
const MOTION_MAX_MS = 12000;

function presenceNow() {
  return typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now();
}

function presenceRound(value, digits = 3) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

// Welford running mean and variance.
function motionStat() {
  return { n: 0, mean: 0, m2: 0 };
}

function motionPush(s, x) {
  if (typeof x !== 'number' || !Number.isFinite(x)) return;
  s.n++;
  const d = x - s.mean;
  s.mean += d / s.n;
  s.m2 += d * (x - s.mean);
}

function motionSd(s) {
  return s.n > 1 ? Math.sqrt(s.m2 / (s.n - 1)) : null;
}

export class PagePresence {
  constructor() {
    this.listening = false;
    this.startedAt = presenceNow();
    this.prerendered = false;
    this.initialVisibility = null;
    this.visibleSince = null;
    this.visibleMs = 0;
    this.firstVisibleMs = null;
    this.hiddenCount = 0;
    this.firstTouchMs = null;
    this.scrolls = 0;
    this.maxScrollRatio = 0;
    this.motion = {
      supported: false, permissionGated: false, events: 0, nullEvents: 0, intervals: motionStat(),
      ax: motionStat(), ay: motionStat(), az: motionStat(), gx: motionStat(), gy: motionStat(), gz: motionStat(), rotation: motionStat(),
      lastAt: null, done: false,
    };
    this.handleVisibility = this.handleVisibility.bind(this);
    this.handleActivation = this.handleActivation.bind(this);
    this.handleScroll = this.handleScroll.bind(this);
    this.handleTouch = this.handleTouch.bind(this);
    this.handleMotion = this.handleMotion.bind(this);
  }

  start() {
    if (this.listening || typeof window === 'undefined' || typeof document === 'undefined') return;
    this.listening = true;
    // Times are on the page's clock (ms since navigation start), like event.timeStamp.
    let activation = 0;
    try {
      const nav = typeof performance !== 'undefined' && performance.getEntriesByType
        ? performance.getEntriesByType('navigation')[0] : null;
      activation = nav && nav.activationStart > 0 ? nav.activationStart : 0;
      this.prerendered = document.prerendering === true || activation > 0;
    } catch (e) { /* unsupported */ }
    this.initialVisibility = document.prerendering === true ? 'prerender' : String(document.visibilityState || '');
    // Visible since navigation (or since a prerendered page was activated).
    if (document.visibilityState === 'visible' && document.prerendering !== true) this.markVisible(activation);
    document.addEventListener('visibilitychange', this.handleVisibility, { capture: true, passive: true });
    document.addEventListener('prerenderingchange', this.handleActivation, { capture: true, passive: true });
    window.addEventListener('scroll', this.handleScroll, { capture: true, passive: true });
    window.addEventListener('touchstart', this.handleTouch, { capture: true, passive: true });
    const Motion = typeof DeviceMotionEvent !== 'undefined' ? DeviceMotionEvent : null;
    this.motion.supported = Boolean(Motion) && window.isSecureContext === true;
    this.motion.permissionGated = Boolean(Motion && typeof Motion.requestPermission === 'function');
    // Listening never prompts. iOS delivers nothing until a page asks; Chrome on Android also
    // exposes requestPermission (1.16.0 skipped it there by mistake) yet delivers events.
    if (this.motion.supported) {
      window.addEventListener('devicemotion', this.handleMotion, { passive: true });
    }
  }

  stop() {
    if (!this.listening) return;
    this.listening = false;
    this.closeVisible();
    document.removeEventListener('visibilitychange', this.handleVisibility, true);
    document.removeEventListener('prerenderingchange', this.handleActivation, true);
    window.removeEventListener('scroll', this.handleScroll, true);
    window.removeEventListener('touchstart', this.handleTouch, true);
    window.removeEventListener('devicemotion', this.handleMotion);
  }

  markVisible(at = presenceNow()) {
    if (this.visibleSince !== null) return;
    this.visibleSince = at;
    if (this.firstVisibleMs === null) this.firstVisibleMs = Math.round(at);
  }

  closeVisible() {
    if (this.visibleSince === null) return;
    this.visibleMs += presenceNow() - this.visibleSince;
    this.visibleSince = null;
  }

  handleVisibility() {
    if (document.prerendering === true) return;
    if (document.visibilityState === 'visible') this.markVisible();
    else {
      this.closeVisible();
      this.hiddenCount++;
    }
  }

  handleActivation() {
    if (document.visibilityState === 'visible') this.markVisible();
  }

  handleScroll(e) {
    if (e && e.isTrusted === false) return;
    this.scrolls++;
    try {
      const root = document.scrollingElement || document.documentElement;
      const height = root ? root.scrollHeight : 0;
      if (height > 0) {
        const ratio = Math.min(1, ((window.scrollY || 0) + (window.innerHeight || 0)) / height);
        if (ratio > this.maxScrollRatio) this.maxScrollRatio = ratio;
      }
    } catch (err) { /* layout unavailable */ }
  }

  handleTouch(e) {
    if (!e || e.isTrusted === false || this.firstTouchMs !== null || this.firstVisibleMs === null) return;
    // Old WebKit stamps events in epoch ms; the page clock is used then.
    const at = typeof e.timeStamp === 'number' && e.timeStamp > 0 && e.timeStamp < 1e11 ? e.timeStamp : presenceNow();
    this.firstTouchMs = Math.max(0, Math.round(at - this.firstVisibleMs));
  }

  handleMotion(e) {
    const m = this.motion;
    if (m.done || !e || e.isTrusted === false) return;
    const t = presenceNow();
    if (m.lastAt !== null) motionPush(m.intervals, t - m.lastAt);
    m.lastAt = t;
    m.events++;
    const a = e.acceleration || {};
    const g = e.accelerationIncludingGravity || {};
    const r = e.rotationRate || {};
    if (g.x === null || g.x === undefined) m.nullEvents++;
    motionPush(m.ax, a.x); motionPush(m.ay, a.y); motionPush(m.az, a.z);
    motionPush(m.gx, g.x); motionPush(m.gy, g.y); motionPush(m.gz, g.z);
    if ([r.alpha, r.beta, r.gamma].every((v) => typeof v === 'number' && Number.isFinite(v))) {
      motionPush(m.rotation, Math.sqrt(r.alpha * r.alpha + r.beta * r.beta + r.gamma * r.gamma));
    }
    if (m.events >= MOTION_MAX_EVENTS || t - this.startedAt > MOTION_MAX_MS) {
      m.done = true;
      try { window.removeEventListener('devicemotion', this.handleMotion); } catch (err) { /* ignore */ }
    }
  }

  motionSummary() {
    const m = this.motion;
    if (!m.supported) return { status: 'unsupported' };
    if (!m.events) return { status: m.permissionGated ? 'permission_gated' : 'no_events' };
    const gravity = Math.sqrt(m.gx.mean ** 2 + m.gy.mean ** 2 + m.gz.mean ** 2);
    // Tilt from lying flat: 0 degrees on a table, typically 20-70 in a hand.
    const tilt = gravity > 0 ? Math.acos(Math.min(1, Math.abs(m.gz.mean) / gravity)) * 180 / Math.PI : null;
    const linear = [motionSd(m.ax), motionSd(m.ay), motionSd(m.az)].filter((v) => v !== null);
    const gravitySd = [motionSd(m.gx), motionSd(m.gy), motionSd(m.gz)].filter((v) => v !== null);
    return {
      status: 'ok',
      events: m.events,
      nullEvents: m.nullEvents,
      intervalMs: presenceRound(m.intervals.n ? m.intervals.mean : null, 1),
      gravity: presenceRound(gravity, 2),
      tiltDeg: presenceRound(tilt, 1),
      linearSd: linear.length ? presenceRound(Math.max(...linear), 4) : null,
      gravitySd: gravitySd.length ? presenceRound(Math.max(...gravitySd), 4) : null,
      rotationMean: presenceRound(m.rotation.n ? m.rotation.mean : null, 3),
      rotationSd: presenceRound(motionSd(m.rotation), 3),
    };
  }

  exportData() {
    const visible = this.visibleMs + (this.visibleSince !== null ? presenceNow() - this.visibleSince : 0);
    return {
      prerendered: this.prerendered,
      initialVisibility: this.initialVisibility,
      firstVisibleMs: this.firstVisibleMs,
      visibleMs: Math.round(visible),
      hiddenCount: this.hiddenCount,
      firstTouchMs: this.firstTouchMs,
      scrolls: this.scrolls,
      maxScrollRatio: presenceRound(this.maxScrollRatio, 3),
      motion: this.motionSummary(),
    };
  }
}

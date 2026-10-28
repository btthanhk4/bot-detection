/**
 * Mouse Dynamics Tracker & Recorder
 * Inspired by DELBOT-Mouse (https://github.com/chrisgdt/DELBOT-Mouse)
 * Captures user mouse/touch trajectories, computes kinematic features (velocity, acceleration, jerk),
 * and prepares sequential chunks (24 points) for LSTM behavioral classification.
 */

// Compatibility mouse events follow a touchend within one frame to ~350 ms
// (legacy tap delay); a real mouse used after the finger arrives later.
const TOUCH_COMPAT_WINDOW_MS = 800;
// Real input reaches the page aligned to display frames; the API compares the
// spacing of pointermoves with the frame interval measured over this many frames.
// The 25th percentile is reported: page-load jank only lengthens frames.
const FRAME_PROBE_FRAMES = 60;

export class MouseRecorder {
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
    this.lastTouchStamp = null;
    this.counters = { mousemove: 0, mousedown: 0, click: 0, wheel: 0 };
    this.pointerStats = {
      pointermove: 0, coalescedTotal: 0, coalescedMax: 0, coalescedMulti: 0, rawUpdates: 0,
      mouseDowns: 0, zeroPressureDowns: 0, frameMs: null, frames: 0, coalescedSelf: 0, coalescedStale: 0,
    };
    this.lastSampleStamp = -1;
    this.lastRawStamp = -1;
    this.frameProbe = null;
    // Keystroke timing only: no key values, field names or text; password fields are skipped.
    this.keystrokes = [];
    this.pendingKeys = {};
    this.lastKeyDownAt = null;
    this.bulkInserts = 0;
    this.bulkMaxLength = 0;
    // Touch gestures (phones/tablets): per point [ms since touch start, x, y, radiusX,
    // radiusY, force] in CSS px. Geometry and timing only; multi-finger gestures dropped.
    this.touchGestures = [];
    this.activeGesture = null;
    this.touchGestureTotal = 0;
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
    this.handleTouchCancel = this.handleTouchCancel.bind(this);
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
    window.addEventListener('touchcancel', this.handleTouchCancel, { passive: true });
    // Coalesced samples and raw updates are only exposed in secure contexts.
    window.addEventListener('pointermove', this.handlePointerMove, { passive: true });
    if (window.isSecureContext && 'onpointerrawupdate' in window) {
      window.addEventListener('pointerrawupdate', this.handlePointerRawUpdate, { passive: true });
    }
    window.addEventListener('pointerdown', this.handlePointerDown, { passive: true });
    window.addEventListener('keydown', this.handleKeyDown, { capture: true, passive: true });
    window.addEventListener('keyup', this.handleKeyUp, { capture: true, passive: true });
    window.addEventListener('input', this.handleInput, { capture: true, passive: true });
    this.startFrameProbe();
  }

  startFrameProbe() {
    if (this.frameProbe !== null || this.pointerStats.frames || typeof requestAnimationFrame !== 'function') return;
    const deltas = [];
    let last = null;
    const step = (now) => {
      this.frameProbe = null;
      if (!this.isListening) return;
      // Frames stop while the tab is hidden; the gap after it is not a frame interval.
      if (last !== null && now - last > 0 && now - last < 100) deltas.push(now - last);
      last = now;
      if (deltas.length < FRAME_PROBE_FRAMES) {
        this.frameProbe = requestAnimationFrame(step);
        return;
      }
      const sorted = deltas.sort((a, b) => a - b);
      this.pointerStats.frameMs = Math.round(sorted[sorted.length >> 2] * 10) / 10;
      this.pointerStats.frames = sorted.length;
    };
    this.frameProbe = requestAnimationFrame(step);
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
    window.removeEventListener('touchcancel', this.handleTouchCancel);
    window.removeEventListener('pointermove', this.handlePointerMove);
    window.removeEventListener('pointerrawupdate', this.handlePointerRawUpdate);
    window.removeEventListener('pointerdown', this.handlePointerDown);
    window.removeEventListener('keydown', this.handleKeyDown, true);
    window.removeEventListener('keyup', this.handleKeyUp, true);
    window.removeEventListener('input', this.handleInput, true);
    if (this.frameProbe !== null && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(this.frameProbe);
    this.frameProbe = null;
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

  // After a tap, phones fire compatibility mouse events (mousemove, mousedown,
  // mouseup, click) at the tap position, back to back. They are the finger, not a
  // mouse: counting them gave phone sessions a few "mouse points" whenever the user
  // tapped and none when they only swiped.
  isTouchCompatibility(e) {
    if (e && e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents === true) return true;
    return this.lastTouchStamp !== null && Math.abs(this.eventStamp(e) - this.lastTouchStamp) < TOUCH_COMPAT_WINDOW_MS;
  }

  noteTouch(e) {
    this.lastTouchStamp = this.eventStamp(e);
  }

  handleMouseMove(e) {
    if (e.isTrusted === false || this.isTouchCompatibility(e)) return;
    this.counters.mousemove++;
    this.recordPoint('move', e.clientX, e.clientY);
  }

  eventStamp(e) {
    if (e && typeof e.timeStamp === 'number' && Number.isFinite(e.timeStamp) && e.timeStamp > 0) return e.timeStamp;
    return typeof performance !== 'undefined' ? performance.now() : Date.now();
  }

  handleMouseDown(e) {
    if (e.isTrusted === false || this.isTouchCompatibility(e)) return;
    this.counters.mousedown++;
    this.lastPressStamp = this.eventStamp(e);
    this.lastReleaseStamp = null;
    this.recordPoint('down', e.clientX, e.clientY);
  }

  handleMouseUp(e) {
    if (e.isTrusted === false || this.isTouchCompatibility(e)) return;
    this.lastReleaseStamp = this.eventStamp(e);
    this.recordPoint('up', e.clientX, e.clientY);
  }

  handleClick(e) {
    if (e.isTrusted === false) return;
    this.counters.click++;
    if (this.isTouchCompatibility(e)) {
      // A tap: keep it as touch activity; its press timing is not a mouse button's.
      this.recordPoint('click', e.clientX, e.clientY, 'touch');
      return;
    }
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
      // Browsers return trusted copies, each newer than the last. A patched method can
      // repeat the event itself or older events, but cannot create new trusted ones.
      let count = 0;
      try {
        for (const sample of e.getCoalescedEvents()) {
          if (sample === e) stats.coalescedSelf++;
          else if (!sample || sample.isTrusted !== true || !(sample.timeStamp > this.lastSampleStamp)) stats.coalescedStale++;
          else { count++; this.lastSampleStamp = sample.timeStamp; }
        }
      } catch (err) { count = 0; }
      stats.coalescedTotal += count;
      if (count > stats.coalescedMax) stats.coalescedMax = count;
      if (count > 1) stats.coalescedMulti++;
    }
  }

  handlePointerRawUpdate(e) {
    // One count per event: a wrapped listener called twice with the same event adds nothing.
    if (!e || e.isTrusted === false || e.pointerType !== 'mouse' || !(e.timeStamp > this.lastRawStamp)) return;
    this.lastRawStamp = e.timeStamp;
    this.pointerStats.rawUpdates++;
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
    // u: virtual keyboards/IME composition (Unidentified, 229), no real press duration.
    // c: ASCII character, n: accented/other character, b: Backspace/Delete (Vietnamese
    // input methods inject these with ~0 ms holds), o: any other key. No key values.
    let kind = 'o';
    if (e.key === 'Unidentified' || e.keyCode === 229) kind = 'u';
    else if (e.key === 'Backspace' || e.key === 'Delete') kind = 'b';
    else if (typeof e.key === 'string' && e.key.length === 1) kind = e.key.charCodeAt(0) < 128 ? 'c' : 'n';
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
    this.noteTouch(e);
    if (e.touches && e.touches[0]) {
      this.recordPoint('down', e.touches[0].clientX, e.touches[0].clientY, 'touch');
    }
    if (!e || e.isTrusted === false) return;
    if (e.touches && e.touches.length === 1) {
      const touch = e.touches[0];
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      this.activeGesture = { start: now, t0: Math.round(now), points: [], multi: false };
      this.addGesturePoint(touch, now);
    } else if (this.activeGesture) {
      this.activeGesture.multi = true;
    }
  }

  handleTouchMove(e) {
    this.noteTouch(e);
    if (e.touches && e.touches[0]) {
      this.recordPoint('move', e.touches[0].clientX, e.touches[0].clientY, 'touch');
    }
    if (!e || e.isTrusted === false || !this.activeGesture) return;
    if (e.touches && e.touches.length > 1) { this.activeGesture.multi = true; return; }
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    if (e.touches && e.touches[0]) this.addGesturePoint(e.touches[0], now);
  }

  addGesturePoint(touch, now) {
    const gesture = this.activeGesture;
    if (!gesture || gesture.points.length >= 48) return;
    const r1 = (value) => (typeof value === 'number' && Number.isFinite(value) ? Math.round(value * 10) / 10 : null);
    gesture.points.push([
      r1(now - gesture.start), r1(touch.clientX), r1(touch.clientY),
      r1(touch.radiusX), r1(touch.radiusY),
      typeof touch.force === 'number' && Number.isFinite(touch.force) ? Math.round(touch.force * 100) / 100 : null,
    ]);
  }

  finishGesture(e) {
    const gesture = this.activeGesture;
    if (!gesture) return;
    const touch = e && e.changedTouches && e.changedTouches[0];
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    if (touch) this.addGesturePoint(touch, now);
    this.activeGesture = null;
    if (gesture.multi || !gesture.points.length) return;
    this.touchGestureTotal++;
    this.touchGestures.push({ t0: gesture.t0, points: gesture.points });
    if (this.touchGestures.length > 30) this.touchGestures = this.touchGestures.slice(-20);
  }

  handleTouchCancel(e) {
    // The browser took the gesture over (scroll, zoom); what was seen is still a real stroke.
    if (e && e.isTrusted !== false) this.finishGesture(e);
  }

  handleTouchEnd(e) {
    this.noteTouch(e);
    if (e && e.isTrusted !== false) this.finishGesture(e);
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
      // Time since navigation start: lets the API tell a page left idle for a while
      // from one that was only just opened.
      pageAgeMs: typeof performance !== 'undefined' ? Math.round(performance.now()) : null,
      pointerStats: {
        ...this.pointerStats,
        secureContext: typeof window !== 'undefined' && window.isSecureContext === true,
      },
      touch: {
        gestures: this.touchGestures.slice(-20),
        total: this.touchGestureTotal,
        viewport: typeof window !== 'undefined' ? [window.innerWidth || 0, window.innerHeight || 0] : null,
        dpr: typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1,
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

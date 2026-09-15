/**
 * Mouse Dynamics Tracker & Recorder
 * Inspired by DELBOT-Mouse (https://github.com/chrisgdt/DELBOT-Mouse)
 * Captures user mouse/touch trajectories, computes kinematic features (velocity, acceleration, jerk),
 * and prepares sequential chunks (24 points) for LSTM behavioral classification.
 */

export class MouseRecorder {
  constructor(options = {}) {
    this.maxRecords = options.maxRecords || 500;
    this.chunkSize = options.chunkSize || 24;
    this.records = [];
    this.chunks = [];
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
    const prev = type === 'move'
      ? [...this.records].reverse().find((record) => record.type === 'move') || null
      : previousRecord;

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

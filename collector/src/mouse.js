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

  clear() {
    this.records = [];
    this.chunks = [];
  }

  recordPoint(type, clientX, clientY) {
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const time = Math.round(now - this.startTime);

    const w = window.innerWidth || 1920;
    const h = window.innerHeight || 1080;
    const normX = Number((clientX / w).toFixed(5));
    const normY = Number((clientY / h).toFixed(5));

    const prev = this.records.length > 0 ? this.records[this.records.length - 1] : null;

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

      const dtPrev = prev.timeDiff || 1;
      accelX = (speedX - prev.speedX) / (timeDiff / 1000);
      accelY = (speedY - prev.speedY) / (timeDiff / 1000);
      accel = Math.sqrt(accelX * accelX + accelY * accelY);
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
    if (this.records.length > this.maxRecords) {
      this.records.shift();
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

  /**
   * Split records into consecutive chunks of 24 points for LSTM input
   */
  getChunks(chunkSize = 24) {
    const moveRecords = this.records.filter((r) => r.type === 'move' && r.timeDiff > 0);
    const chunks = [];
    for (let i = 0; i + chunkSize <= moveRecords.length; i += Math.floor(chunkSize / 2)) {
      const slice = moveRecords.slice(i, i + chunkSize);
      // Format 8 features per point: [dx, dy, speedX, speedY, speed, accel, distance, timeDiff]
      const matrix = slice.map((p) => [
        p.dx,
        p.dy,
        p.speedX,
        p.speedY,
        p.speed,
        p.accel,
        p.distance,
        p.timeDiff / 1000,
      ]);
      chunks.push(matrix);
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

    const speeds = this.records.map((r) => r.speed).filter((s) => s > 0);
    const accels = this.records.map((r) => r.accel).filter((a) => a > 0);

    const avgSpeed = speeds.length ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0;
    const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
    const avgAccel = accels.length ? accels.reduce((a, b) => a + b, 0) / accels.length : 0;

    // Straightness = net displacement / total path length
    const first = this.records[0];
    const last = this.records[this.records.length - 1];
    const netDist = Math.sqrt(Math.pow(last.x - first.x, 2) + Math.pow(last.y - first.y, 2));
    const totalDist = this.records.reduce((sum, r) => sum + (r.distance || 0), 0);
    const straightness = totalDist > 0 ? Number((netDist / totalDist).toFixed(4)) : 1.0;

    return {
      pointCount: this.records.length,
      hasEnoughData: this.records.length >= this.chunkSize,
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
    };
  }
}

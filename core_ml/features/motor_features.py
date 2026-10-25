"""Candidate mouse-motion feature families from the bot-detection literature.

Offline research module: nothing here is used by the released policy. Each
family is computed from move events in pixel coordinates with millisecond
timestamps, and returns a flat ``{name: float}`` dict. Missing values are NaN
(XGBoost handles them natively); they are never invented as zeros.

Families
--------
kinematic   Distribution statistics of speed, acceleration, jerk, curvature and
            angular velocity (Ahmed & Traore 2007; Shen et al.; Chu et al. 2013).
neuromotor  Stroke/submovement structure and smoothness: velocity-peak counts,
            peak-time asymmetry, single-lognormal fit per stroke (sigma-lognormal,
            Plamondon; BeCAPTCHA-Mouse), log dimensionless jerk (LDLJ) and
            spectral arc length (SPARC) (Balasubramanian et al. 2012/2015).
timing      How events were produced: event rate, inter-event interval
            regularity/entropy, repeated positions, teleports and micro-jitter
            (Castle 2025; Choudhary et al. arXiv:2607.26935).
"""

import math

import numpy as np

NAN = float("nan")
RESAMPLE_HZ = 100.0


def _finite(value):
    return float(value) if value is not None and np.isfinite(value) else NAN


def _pct(values, q):
    return _finite(np.percentile(values, q)) if len(values) else NAN


def clean_moves(records):
    """Return (t_ms, x_px, y_px) arrays for chronological, finite move events."""
    rows = []
    for record in records:
        if record.get("type", "move") != "move":
            continue
        try:
            t, x, y = float(record["time"]), float(record["x"]), float(record["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(v) for v in (t, x, y)):
            rows.append((t, x, y))
    rows.sort(key=lambda row: row[0])
    if not rows:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    arr = np.asarray(rows, dtype=np.float64)
    return arr[:, 0], arr[:, 1], arr[:, 2]


def _derivatives(t, x, y):
    dt = np.diff(t) / 1000.0
    ok = dt > 0
    dx, dy, dt = np.diff(x)[ok], np.diff(y)[ok], dt[ok]
    step = np.hypot(dx, dy)
    speed = step / dt
    if len(speed) < 2:
        return dx, dy, dt, step, speed, np.zeros(0), np.zeros(0)
    accel = np.diff(speed) / dt[1:]
    jerk = np.diff(accel) / dt[2:] if len(accel) > 1 else np.zeros(0)
    return dx, dy, dt, step, speed, accel, jerk


def kinematic_features(t, x, y):
    out = {}
    dx, dy, dt, step, speed, accel, jerk = _derivatives(t, x, y)
    moving = step > 0
    angles = np.arctan2(dy[moving], dx[moving])
    turn = np.angle(np.exp(1j * np.diff(angles))) if len(angles) > 1 else np.zeros(0)
    seg = step[moving][1:] if len(angles) > 1 else np.zeros(0)
    curvature = np.abs(turn) / np.maximum(seg, 1e-6) if len(turn) else np.zeros(0)
    dt_moving = dt[moving][1:] if len(angles) > 1 else np.zeros(0)
    ang_vel = np.abs(turn) / np.maximum(dt_moving, 1e-3) if len(turn) else np.zeros(0)
    for name, values in (("speed", speed), ("accel", np.abs(accel)), ("jerk", np.abs(jerk)),
                         ("curv", curvature), ("angvel", ang_vel)):
        out[f"kin_{name}_p10"] = _pct(values, 10)
        out[f"kin_{name}_p50"] = _pct(values, 50)
        out[f"kin_{name}_p90"] = _pct(values, 90)
    path = float(step.sum())
    out["kin_path_px"] = path
    out["kin_straightness"] = _finite(math.hypot(x[-1] - x[0], y[-1] - y[0]) / path) if path > 0 else NAN
    out["kin_duration_s"] = _finite((t[-1] - t[0]) / 1000.0) if len(t) > 1 else NAN
    out["kin_turn_abs_mean"] = _finite(np.mean(np.abs(turn))) if len(turn) else NAN
    return out


def _resample(t, x, y, hz=RESAMPLE_HZ):
    """Uniform-time resampling so smoothness metrics do not depend on event timing."""
    if len(t) < 4 or t[-1] - t[0] < 30:
        return None
    grid = np.arange(t[0], t[-1], 1000.0 / hz)
    if len(grid) < 6:
        return None
    return grid, np.interp(grid, t, x), np.interp(grid, t, y)


def _smooth(values, width=3):
    if len(values) < width:
        return values
    kernel = np.ones(width) / width
    return np.convolve(values, kernel, mode="same")


def _strokes(speed, threshold_ratio=0.15, min_len=4):
    """Split a resampled speed profile at minima below a fraction of its peak."""
    if len(speed) == 0 or speed.max() <= 0:
        return []
    low = speed < threshold_ratio * speed.max()
    strokes, start = [], None
    for i, is_low in enumerate(low):
        if not is_low and start is None:
            start = i
        elif is_low and start is not None:
            if i - start >= min_len:
                strokes.append((start, i))
            start = None
    if start is not None and len(speed) - start >= min_len:
        strokes.append((start, len(speed)))
    return strokes


def _lognormal_fit(tt, v):
    """Fit v(t) = D/(sqrt(2pi) s (t-t0)) exp(-(ln(t-t0)-mu)^2/(2 s^2)); return (r2, sigma, mu)."""
    try:
        from scipy.optimize import curve_fit
    except ImportError:  # pragma: no cover - scipy is a declared dependency
        return NAN, NAN, NAN
    tt = tt - tt[0] + 1e-3

    def model(time, d, t0, mu, sigma):
        shifted = np.maximum(time - t0, 1e-6)
        return d / (np.sqrt(2 * np.pi) * sigma * shifted) * np.exp(
            -((np.log(shifted) - mu) ** 2) / (2 * sigma ** 2))

    duration = tt[-1]
    area = float(np.trapz(v, tt))
    peak_t = tt[int(np.argmax(v))]
    p0 = [max(area, 1e-3), -0.05 * duration, math.log(max(peak_t + 0.05 * duration, 1e-3)), 0.4]
    bounds = ([0, -duration, -10, 0.05], [np.inf, peak_t, 5, 3.0])
    try:
        params, _ = curve_fit(model, tt, v, p0=p0, bounds=bounds, maxfev=2000)
    except (RuntimeError, ValueError):
        return NAN, NAN, NAN
    resid = v - model(tt, *params)
    total = float(np.sum((v - v.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / total if total > 0 else NAN
    return _finite(r2), _finite(params[3]), _finite(params[2])


def _ldlj(tt, vx, vy):
    """Log dimensionless jerk on a velocity profile (more negative = less smooth)."""
    duration = tt[-1] - tt[0]
    speed = np.hypot(vx, vy)
    if duration <= 0 or speed.max() <= 0 or len(tt) < 5:
        return NAN
    dt = np.diff(tt).mean()
    jx = np.gradient(np.gradient(vx, dt), dt)
    jy = np.gradient(np.gradient(vy, dt), dt)
    integral = np.trapz(jx ** 2 + jy ** 2, tt)
    value = (duration ** 3 / speed.max() ** 2) * integral
    return _finite(-math.log(value)) if value > 0 else NAN


def _sparc(speed, fs, fc=10.0, amp_th=0.05, padlevel=4):
    """Spectral arc length of a speed profile (closer to 0 = smoother)."""
    if len(speed) < 6 or speed.max() <= 0:
        return NAN
    nfft = int(2 ** (math.ceil(math.log2(len(speed))) + padlevel))
    freqs = np.arange(0, fs, fs / nfft)
    mag = np.abs(np.fft.fft(speed, nfft))
    mag = mag / mag.max()
    keep = freqs <= fc
    freqs, mag = freqs[keep], mag[keep]
    above = np.nonzero(mag >= amp_th)[0]
    if len(above) == 0:
        return NAN
    freqs, mag = freqs[:above[-1] + 1], mag[:above[-1] + 1]
    dfreq = np.diff(freqs) / (freqs[-1] - freqs[0]) if freqs[-1] > freqs[0] else np.zeros(1)
    return _finite(-np.sum(np.sqrt(dfreq ** 2 + np.diff(mag) ** 2)))


def neuromotor_features(t, x, y):
    out = {name: NAN for name in (
        "neu_peaks", "neu_peaks_per_s", "neu_strokes", "neu_peak_time_ratio_mean",
        "neu_peak_time_ratio_std", "neu_lognorm_r2_mean", "neu_lognorm_r2_min", "neu_lognorm_sigma_mean",
        "neu_ldlj", "neu_sparc", "neu_near_zero_accel_frac", "neu_speed_cv", "neu_primary_dist_ratio")}
    sampled = _resample(t, x, y)
    if sampled is None:
        return out
    grid, gx, gy = sampled
    tt = (grid - grid[0]) / 1000.0
    fs = RESAMPLE_HZ
    vx, vy = np.gradient(gx, tt), np.gradient(gy, tt)
    speed = _smooth(np.hypot(vx, vy))
    if speed.max() <= 0:
        return out
    inner = speed[1:-1]
    peaks = np.nonzero((inner > speed[:-2]) & (inner >= speed[2:]) & (inner > 0.2 * speed.max()))[0]
    duration = max(tt[-1], 1e-3)
    out["neu_peaks"] = float(len(peaks))
    out["neu_peaks_per_s"] = len(peaks) / duration
    strokes = _strokes(speed)
    out["neu_strokes"] = float(len(strokes))
    ratios, r2s, sigmas, dists = [], [], [], []
    for start, end in strokes[:20]:
        seg_t, seg_v = tt[start:end], speed[start:end]
        span = seg_t[-1] - seg_t[0]
        if span <= 0:
            continue
        ratios.append((seg_t[int(np.argmax(seg_v))] - seg_t[0]) / span)
        dists.append(float(np.trapz(seg_v, seg_t)))
        r2, sigma, _mu = _lognormal_fit(seg_t, seg_v)
        if np.isfinite(r2):
            r2s.append(r2)
            sigmas.append(sigma)
    if ratios:
        out["neu_peak_time_ratio_mean"] = float(np.mean(ratios))
        out["neu_peak_time_ratio_std"] = float(np.std(ratios))
    if r2s:
        out["neu_lognorm_r2_mean"] = float(np.mean(r2s))
        out["neu_lognorm_r2_min"] = float(np.min(r2s))
        out["neu_lognorm_sigma_mean"] = float(np.mean(sigmas))
    if dists and sum(dists) > 0:
        out["neu_primary_dist_ratio"] = max(dists) / sum(dists)
    out["neu_ldlj"] = _ldlj(tt, vx, vy)
    out["neu_sparc"] = _sparc(speed, fs)
    # Dimensionless: |a| * 0.1 s below 5% of the mean speed counts as "flat".
    accel = np.gradient(speed, tt)[2:-2]
    mean_speed = speed.mean()
    out["neu_near_zero_accel_frac"] = (
        _finite(np.mean(np.abs(accel) * 0.1 < 0.05 * mean_speed)) if mean_speed > 0 and len(accel) else NAN)
    out["neu_speed_cv"] = _finite(speed.std() / speed.mean()) if speed.mean() > 0 else NAN
    return out


def timing_features(t, x, y, clicks=()):
    out = {}
    dt_ms = np.diff(t)
    duration_s = (t[-1] - t[0]) / 1000.0 if len(t) > 1 else 0.0
    out["tim_event_rate"] = _finite(len(t) / duration_s) if duration_s > 0 else NAN
    positive = dt_ms[dt_ms > 0]
    out["tim_dt_p50"] = _pct(positive, 50)
    out["tim_dt_cv"] = _finite(positive.std() / positive.mean()) if len(positive) > 1 and positive.mean() > 0 else NAN
    if len(positive) > 2:
        hist, _ = np.histogram(np.clip(positive, 0, 200), bins=100, range=(0, 200))
        prob = hist[hist > 0] / hist.sum()
        out["tim_dt_entropy"] = float(-(prob * np.log2(prob)).sum())
        rounded = np.round(positive)
        _values, counts = np.unique(rounded, return_counts=True)
        out["tim_dt_mode_share"] = float(counts.max() / len(rounded))
    else:
        out["tim_dt_entropy"] = NAN
        out["tim_dt_mode_share"] = NAN
    step = np.hypot(np.diff(x), np.diff(y))
    out["tim_zero_step_frac"] = _finite(np.mean(step == 0)) if len(step) else NAN
    out["tim_teleport_frac"] = _finite(np.mean((step > 100) & (dt_ms < 50))) if len(step) else NAN
    med = np.median(step[step > 0]) if np.any(step > 0) else 0
    out["tim_max_step_ratio"] = _finite(step.max() / med) if med > 0 else NAN
    sx, sy = np.sign(np.diff(x)), np.sign(np.diff(y))
    small = (np.abs(np.diff(x)) <= 1) & (np.abs(np.diff(y)) <= 1) & (step > 0)
    flips = np.zeros(len(step), dtype=bool)
    if len(step) > 1:
        flips[1:] = ((sx[1:] * sx[:-1]) < 0) | ((sy[1:] * sy[:-1]) < 0)
    out["tim_micro_jitter_frac"] = _finite(np.mean(small & flips)) if len(step) else NAN
    if clicks and len(t):
        approach = []
        for click_t, click_x, click_y in clicks:
            before = np.nonzero(t <= click_t)[0]
            if len(before):
                i = before[-1]
                approach.append(math.hypot(click_x - x[i], click_y - y[i]))
        out["tim_click_gap_px"] = _finite(np.mean(approach)) if approach else NAN
    else:
        out["tim_click_gap_px"] = NAN
    return out


FAMILIES = {
    "kinematic": kinematic_features,
    "neuromotor": neuromotor_features,
    "timing": timing_features,
}


def extract_motor_features(records, clicks=(), families=("kinematic", "neuromotor", "timing")):
    t, x, y = clean_moves(records)
    out = {}
    for family in families:
        if len(t) < 5:
            continue
        func = FAMILIES[family]
        out.update(func(t, x, y, clicks) if family == "timing" else func(t, x, y))
    return out

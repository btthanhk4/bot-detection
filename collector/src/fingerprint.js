/**
 * Lightweight Browser & Device Fingerprint Extractor
 * Inspired by FingerprintJS (https://github.com/fingerprintjs/fingerprintjs)
 * Collects ~40 browser/hardware signals and generates a deterministic visitor ID hash.
 */

// Simple 32-bit FNV-1a hash
export function fnv1a(str) {
  let hash = 2166136261;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

// Canvas fingerprinting
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

// WebGL fingerprinting (Renderer & Vendor)
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

// Audio fingerprinting via OfflineAudioContext
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
  const baseFonts = ['monospace', 'sans-serif', 'serif'];
  const testFonts = [
    'Arial', 'Verdana', 'Times New Roman', 'Courier New',
    'Georgia', 'Comic Sans MS', 'Trebuchet MS', 'Impact',
    'Segoe UI', 'Roboto', 'Helvetica', 'Ubuntu', 'Consolas'
  ];

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

/**
 * Collect complete hardware & browser environment components
 */
export async function getFingerprintComponents() {
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

  const visitorId = fnv1a(rawId);

  return { visitorId, components };
}

/**
 * BotD Client-Side Heuristic Detectors
 * Inspired by BotD (https://github.com/fingerprintjs/BotD)
 * Implements 13 heuristic tests for browser automation, headless environments, and spoofing.
 */

export function runBotDetectors(components = {}) {
  const nav = typeof navigator !== 'undefined' ? navigator : {};
  const win = typeof window !== 'undefined' ? window : {};
  const doc = typeof document !== 'undefined' ? document : {};

  const detectors = {};
  const reasons = [];

  // 1. WebDriver detector (Selenium, Puppeteer, Playwright default)
  detectors.webdriver = !!(nav.webdriver || doc.documentElement?.getAttribute?.('webdriver'));
  if (detectors.webdriver) reasons.push('navigator.webdriver is true');

  // 2. Distinctive automation properties
  const automationProps = [
    '_phantom', '__nightmare', '_selenium', 'callPhantom', 'callSelenium',
    '_Selenium_IDE_Recorder', '__webdriver_script_fn', '__driver_evaluate',
    '__webdriver_evaluate', '__selenium_evaluate', '__fxdriver_evaluate',
    '__driver_unwrapped', '__webdriver_unwrapped', '__selenium_unwrapped',
    '__fxdriver_unwrapped', 'domAutomation', 'domAutomationController',
  ];
  let foundDistinctive = false;
  for (const prop of automationProps) {
    if (prop in win || (doc && prop in doc)) {
      foundDistinctive = true;
      reasons.push(`Distinctive automation property found: ${prop}`);
      break;
    }
  }
  // 4. Automation-specific global variables (e.g., cdc_ from ChromeDriver)
  detectors.chromeDriverGlobal = false;
  try {
    for (const key of Object.keys(win)) {
      if (key.startsWith('cdc_') || key.startsWith('$cdc_')) {
        detectors.chromeDriverGlobal = true;
        reasons.push(`ChromeDriver global detected: ${key}`);
        break;
      }
    }
  } catch (e) {
    // Object.keys(window) may throw SecurityError in some environments
  }
  detectors.distinctiveProperties = foundDistinctive;

  // 3. WebGL Software Renderer / VM / Headless detection
  const renderer = (components.webglRenderer || '').toLowerCase();
  const vendor = (components.webglVendor || '').toLowerCase();
  const isVirtualGpu = /swiftshader|llvmpipe|virtualbox|vmware|mesa offscreen|softpipe/i.test(renderer);
  detectors.virtualGpu = isVirtualGpu;
  if (isVirtualGpu) reasons.push(`Software / Virtual GPU detected: ${renderer}`);

  // 4. Plugins Inconsistency (Desktop Chrome must have plugins, Headless Chrome has 0)
  const isChrome = /chrome/i.test(nav.userAgent || '') && !/edg|opr|brave/i.test(nav.userAgent || '');
  const isDesktop = !/android|iphone|ipad|ipod|mobile/i.test(nav.userAgent || '');
  const pluginsLength = nav.plugins ? nav.plugins.length : 0;
  detectors.pluginsInconsistency = isChrome && isDesktop && pluginsLength === 0;
  if (detectors.pluginsInconsistency) reasons.push('Chrome desktop with 0 plugins (indicates headless)');

  // 5. Languages Inconsistency
  const langs = nav.languages || [];
  const lang = nav.language || '';
  detectors.languagesInconsistency = !langs.length || (lang && langs.length > 0 && !langs.includes(lang));
  if (detectors.languagesInconsistency) reasons.push('Browser language inconsistency');

  // 6. Window Size Anomaly (Headless environments often start with 0x0 or fixed 800x600)
  const w = win.innerWidth || 0;
  const h = win.innerHeight || 0;
  const outerW = win.outerWidth || 0;
  const outerH = win.outerHeight || 0;
  detectors.windowSize = (w === 0 && h === 0) || (outerW === 0 && outerH === 0);
  if (detectors.windowSize) reasons.push('Zero inner/outer window dimensions');

  // 7. Error Stack Trace Inspection
  let errorTraceBot = false;
  try {
    throw new Error('trace');
  } catch (err) {
    const stack = err.stack || '';
    if (/puppeteer|playwright|selenium|phantomjs|webdriver/i.test(stack)) {
      errorTraceBot = true;
      reasons.push('Automation framework detected in stack trace');
    }
  }
  detectors.errorTrace = errorTraceBot;

  // 8. Process global in renderer (Electron / Node-Webkit / automation)
  detectors.hasProcess = typeof win.process === 'object' && win.process?.versions?.node !== undefined;
  if (detectors.hasProcess) reasons.push('Node.js process object exposed in browser');

  // 9. Eval / Function.bind length check (anti-tampering check)
  let evalLengthAnomaly = false;
  try {
    if (eval.toString().length !== 33 && eval.toString().length !== 37) {
      evalLengthAnomaly = true;
    }
    if (Function.prototype.bind.toString().length !== 33 && Function.prototype.bind.toString().length !== 37) {
      evalLengthAnomaly = true;
    }
  } catch (e) {
    evalLengthAnomaly = true;
  }
  detectors.evalLength = evalLengthAnomaly;

  // 10. Document Element Keys & Attributes check
  let hasDocAttr = false;
  try {
    if (doc.documentElement && typeof doc.documentElement.getAttributeNames === 'function') {
      const attrNames = doc.documentElement.getAttributeNames();
      hasDocAttr = attrNames.some((k) => /selenium|webdriver|driver/i.test(k));
    } else if (doc.documentElement && doc.documentElement.attributes) {
      for (let i = 0; i < doc.documentElement.attributes.length; i++) {
        if (/selenium|webdriver|driver/i.test(doc.documentElement.attributes[i].name)) {
          hasDocAttr = true;
          break;
        }
      }
    }
  } catch (e) {}
  const docKeys = Object.keys(doc.documentElement || {});
  detectors.documentKeys = hasDocAttr || docKeys.some((k) => /selenium|webdriver|driver/i.test(k));
  if (detectors.documentKeys) reasons.push('Automation attributes on documentElement');

  // 11. User-Agent vs Platform Inconsistency (FP-Inconsistent paper inspired)
  const ua = (nav.userAgent || '').toLowerCase();
  const plat = (nav.platform || '').toLowerCase();
  let platformMismatch = false;
  if (ua.includes('windows') && !plat.includes('win')) platformMismatch = true;
  if (ua.includes('macintosh') && !plat.includes('mac')) platformMismatch = true;
  if (ua.includes('linux') && !plat.includes('linux') && !plat.includes('arm')) platformMismatch = true;
  detectors.platformMismatch = platformMismatch;
  if (platformMismatch) reasons.push(`Platform mismatch: UserAgent (${nav.userAgent}) vs Platform (${nav.platform})`);

  // 12. Headless Chrome User-Agent flag
  detectors.headlessUa = /headlesschrome/i.test(nav.userAgent || '');
  if (detectors.headlessUa) reasons.push('User-Agent explicitly declares HeadlessChrome');

  // Calculate Weighted Heuristic Score
  // High-confidence detectors get higher weight than noisy ones
  const detectorWeights = {
    webdriver: 5.0,
    distinctiveProperties: 5.0,
    chromeDriverGlobal: 4.0,
    headlessUa: 4.0,
    virtualGpu: 3.0,
    windowSize: 2.5,
    hasProcess: 3.0,
    documentKeys: 3.0,
    platformMismatch: 2.0,
    pluginsInconsistency: 2.0,
    languagesInconsistency: 1.5,
    errorTrace: 1.5,
    evalLength: 1.0,  // noisy, low weight
  };

  const keys = Object.keys(detectors);
  const flagged = keys.filter((k) => detectors[k]);
  const totalWeight = keys.reduce((sum, k) => sum + (detectorWeights[k] || 1.0), 0);
  const flaggedWeight = flagged.reduce((sum, k) => sum + (detectorWeights[k] || 1.0), 0);
  const heuristicScore = totalWeight > 0 ? flaggedWeight / totalWeight : 0;
  const hasCriticalAutomationSignal = !!(
    detectors.webdriver ||
    detectors.distinctiveProperties ||
    detectors.chromeDriverGlobal ||
    detectors.headlessUa
  );
  const isBotHeuristic = hasCriticalAutomationSignal || heuristicScore >= 0.35;

  return {
    isBot: isBotHeuristic,
    heuristicScore: Number(heuristicScore.toFixed(4)),
    flaggedCount: flagged.length,
    detectors,
    reasons,
  };
}

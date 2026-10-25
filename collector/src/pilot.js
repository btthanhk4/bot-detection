/** Opt-in single-tag integration; legacy manual BotCollector usage is unchanged. */
export function bootstrapPilot(Collector) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  const script = document.currentScript;
  if (!script || !script.hasAttribute('data-datacat')) return null;
  try {
    const studyId = script.getAttribute('data-study-id') || '';
    const siteId = script.getAttribute('data-site-id') || '';
    if (![studyId, siteId].every((value) => /^[A-Za-z0-9_-]{1,64}$/.test(value))) {
      throw new Error('data-study-id and data-site-id must contain 1-64 letters, digits, _ or -');
    }
    const endpointUrl = new URL(script.getAttribute('data-endpoint') || 'api/v1/telemetry', script.src);
    if (!['http:', 'https:'].includes(endpointUrl.protocol)
        || (window.location.protocol === 'https:' && endpointUrl.protocol !== 'https:')) {
      throw new Error('Use an HTTPS API endpoint when embedding on an HTTPS website');
    }
    const interval = Number(script.getAttribute('data-interval-ms') || 15000);
    if (!Number.isInteger(interval) || interval < 1000 || interval > 60000) {
      throw new Error('data-interval-ms must be an integer between 1000 and 60000');
    }
    if (window.DatacatPilot) {
      const current = window.DatacatPilot.collector;
      if (!current || current.endpointUrl !== endpointUrl.href
          || current.studyId !== studyId || current.siteId !== siteId) {
        throw new Error('A different DATACAT pilot is already configured on this page');
      }
      return window.DatacatPilot;
    }
    if (window._bc && typeof window._bc.sendTelemetry === 'function') {
      throw new Error('An existing manual collector (_bc) is active; use one integration method');
    }
    const collector = new Collector({
      endpointUrl: endpointUrl.href,
      detectUrl: new URL('detect', endpointUrl).href,
      studyId, siteId, autoSendInterval: interval,
    });
    const pilot = {
      collector,
      stop: () => collector.destroy(),
      getStatus: () => ({
        sessionId: collector.sessionId, studyId, siteId,
        stopped: collector.destroyed,
        lastReceipt: collector.lastReceipt,
        lastDelivery: collector.lastDelivery,
      }),
    };
    window.DatacatPilot = pilot;
    pilot.ready = collector.start().catch((error) => {
      console.error('[DATACAT] Collector initialization failed:', error);
      return false;
    });
    return pilot;
  } catch (error) {
    console.error('[DATACAT] Pilot configuration:', error.message);
    return null;
  }
}

bootstrapPilot(BotCollector);

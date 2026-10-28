/**
 * Untouched built-ins from a blank same-origin iframe (collector 1.11).
 *
 * Monitoring libraries on ordinary sites wrap the page's copies: Sentry wraps every
 * console method, requestAnimationFrame and Function.prototype.toString; LogRocket,
 * Bugsnag and in-app browser scripts wrap console too. Probes that used those copies
 * read a person on such a site as a DevTools client and as a tampered page (measured
 * 2026-10-29: real Chrome, OS input, Sentry 8 on the page -> SUSPECT). A frame created
 * here has its own realm, which page scripts have not touched.
 *
 * The frame lives only while `use` runs. Plain JavaScript built-ins keep working after
 * it is removed; `use` gets null when the page cannot create one (sandboxed document).
 */
export function withPristineRealm(doc, use) {
  let frame = null;
  let realm = null;
  try {
    frame = doc.createElement('iframe');
    frame.setAttribute('aria-hidden', 'true');
    frame.tabIndex = -1;
    frame.style.cssText = 'position:absolute;width:0;height:0;border:0;visibility:hidden;pointer-events:none';
    (doc.body || doc.documentElement).appendChild(frame);
    const candidate = frame.contentWindow;
    if (candidate && candidate.Function && candidate.console) realm = candidate;
  } catch (e) {
    realm = null;
  }
  try {
    return use(realm);
  } finally {
    try { if (frame && frame.parentNode) frame.parentNode.removeChild(frame); } catch (e) { /* already gone */ }
  }
}

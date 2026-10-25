/* Browser-only contract tests. Fixtures never reach the API or dataset. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const { chromium } = require('playwright');

async function main() {
  const html = fs.readFileSync(path.join(__dirname, '../api_service/dashboard.html'));
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(html);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors = [], writes = [];
    const session = { sessionId: 'fixture-session', traffic_number: 1, revision: 0,
      verdict: 'HUMAN', bot_probability: 0.1, pageUrl: 'https://example.test/', client_ip: '127.0.0.1',
      received_at: new Date().toISOString(), breakdown: { mouse_points: 0, has_enough_mouse_data: false } };
    let payload = { sessions: [session], total: 1, next_before: null };
    let failed = false;
    page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(() => sessionStorage.setItem('bot_read_token', 'fixture-only'));
    await page.route('**/api/v1/**', async route => {
      if (route.request().method() !== 'GET') writes.push(route.request().url());
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/v1/research/traffic') {
        await route.fulfill({ status: failed ? 503 : 200, json: failed ? {} : payload });
      } else if (pathname.endsWith('/detail')) {
        await route.fulfill({ json: session });
      } else {
        await route.fulfill({ json: {} });
      }
    });
    await page.route('**/health', route => route.fulfill({ json: { status: 'healthy' } }));
    await page.goto(`http://127.0.0.1:${server.address().port}/dashboard`);
    await page.waitForSelector('#trafficBody tr[data-idx]');
    // Stop the interval only after initial rendering; exercise real fetch/render functions below.
    await page.evaluate(() => { for (let id = 1; id < 100; id++) clearInterval(id); });
    const refresh = () => page.evaluate(() => fetchRecentTelemetry());
    assert.match(await page.locator('#referenceConnection').innerText(), /Chưa cấu hình/);
    assert.match(await page.locator('#trafficBody td').nth(10).innerText(), /Chưa có kết quả/);
    assert.equal(await page.locator('#trafficBody td').count(), 12);
    await page.locator('#trafficBody td').first().click();
    assert.equal(await page.locator('#sessionDrawer').evaluate(el => el.classList.contains('open')), false);
    await page.locator('.view-btn').first().click();
    await page.waitForSelector('#sessionDrawer.open');
    assert.equal(await page.locator('#dReferenceScore').innerText(), '--');

    const ready = { provider: 'castle', mode: 'live', status: 'ready', server_verified: true,
      session_id: session.sessionId, verdict: 'BOT', bot_score: 0,
      event_id: '<img src=x onerror="window.referenceXss=true">', observed_at: '2026-10-24T01:00:00Z' };
    session.reference = ready;
    payload.reference_integration = { provider: 'castle', mode: 'live', status: 'connected' };
    await refresh();
    assert.equal(await page.locator('#dReferenceScore').innerText(), '0.0 / 100');
    assert.equal(await page.locator('#dReferenceVerdict').innerText(), 'BOT');
    assert.match(await page.locator('#dReferenceComparison').innerText(), /Bất đồng/);
    assert.match(await page.locator('#referenceCoverage').innerText(), /^1 \/ 1/);
    assert.equal(await page.locator('#dReferenceEvent').innerText(), ready.event_id);
    assert.equal(await page.locator('#dReferenceEvent img').count(), 0);
    assert.equal(await page.evaluate(() => window.referenceXss), undefined);
    assert.equal(await page.locator('#trafficBody td').nth(4).innerText(), 'HUMAN');
    assert.equal(await page.locator('#trafficBody td').nth(9).innerText(), '--');
    for (const value of [null, '', '95', -1, 101]) {
      session.reference = { ...ready, bot_score: value };
      await refresh();
      assert.equal(await page.locator('#dReferenceScore').innerText(), '--');
    }
    for (const change of [{ server_verified: false }, { session_id: 'other-session' },
      { observed_at: 'bad-date' }, { observed_at: '2026-10-24T01:00:00' }, { event_id: '' }]) {
      session.reference = { ...ready, ...change };
      await refresh();
      assert.equal(await page.locator('#dReferenceStatus').innerText(), 'Chưa xác thực');
      assert.equal(await page.locator('#dReferenceVerdict').innerText(), '--');
    }
    session.reference = { ...ready, verdict: 'NOT_DETECTED' };
    await refresh();
    assert.equal(await page.locator('#dReferenceVerdict').innerText(), 'UNKNOWN');
    assert.equal(await page.locator('#dReferenceComparison').innerText(), 'Chưa thể đối chiếu');
    for (const [change, expected] of [[{ mode: 'mock' }, 'Dữ liệu thử'],
      [{ status: 'pending' }, 'Đang chờ'], [{ status: 'error' }, 'Lỗi tham chiếu']]) {
      session.reference = { ...ready, ...change };
      await refresh();
      assert.equal(await page.locator('#dReferenceStatus').innerText(), expected);
      assert.equal(await page.locator('#dReferenceScore').innerText(), '--');
      assert.match(await page.locator('#referenceCoverage').innerText(), /^0 \/ 1/);
    }
    payload.reference_integration.status = 'quota_exceeded';
    await refresh();
    assert.equal(await page.locator('#referenceConnection').innerText(), 'Hết hạn mức');
    failed = true;
    await refresh();
    assert.equal(await page.locator('#referenceConnection').innerText(), 'Không tải được trạng thái');
    failed = false;
    delete session.reference;
    delete payload.reference_integration;
    await refresh();
    assert.equal(await page.locator('#dReferenceStatus').innerText(), 'Chưa có kết quả');
    await page.evaluate(() => closeDrawer());
    const screenshots = fs.mkdtempSync(path.join(os.tmpdir(), 'datacat-reference-'));
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${name}: no document overflow`);
      await page.screenshot({ path: path.join(screenshots, name + '.png'), fullPage: true, animations: 'disabled' });
    }
    await page.locator('.view-btn').first().click();
    await page.waitForSelector('#sessionDrawer.open');
    await page.locator('#dReferenceStatus').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(screenshots, 'mobile-profile.png'), animations: 'disabled' });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, [], 'no uncaught browser errors');
    assert.deepEqual(writes, [], 'reference display must not write labels or training data');
    console.log('PASS: legacy payload, independent verdict/labels, reference refresh, validation, mock/pending/error, XSS, outage, desktop/mobile, profile interaction.');
    console.log('Screenshots: ' + screenshots);
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });

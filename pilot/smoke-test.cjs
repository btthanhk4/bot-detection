/* Real browser + real MongoDB verification in a fresh, task-owned sandbox. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { createHash } = require('node:crypto');
const http = require('node:http');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.DATACAT_TEST_PYTHON || 'python';
const mongod = process.env.DATACAT_TEST_MONGOD;
if (!mongod || !fs.existsSync(mongod)) throw new Error('Set DATACAT_TEST_MONGOD to a local mongod executable');
const work = process.env.DATACAT_SMOKE_DIR || path.join(os.tmpdir(), `datacat-pilot-${Date.now()}`);
fs.mkdirSync(work, { recursive: false });
fs.mkdirSync(path.join(work, 'mongo'));
let api, mongo, browser, site;
let apiLogs = '';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(check, message, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try { const result = await check(); if (result) return result; } catch (_error) { /* startup/reconnect */ }
    await sleep(250);
  }
  throw new Error(`Timed out: ${message}\n${apiLogs.slice(-5000)}`);
}
async function port() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const value = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return value;
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  const done = new Promise((resolve) => child.once('exit', resolve));
  child.kill();
  await Promise.race([done, sleep(5000)]);
}
function command(args, env) {
  const result = spawnSync(python, args, { cwd: root, env, encoding: 'utf8', timeout: 30000 });
  if (result.status !== 0) throw new Error(result.stderr || result.error || `Command exited ${result.status}`);
  return result.stdout.trim();
}

async function main() {
  const mongoPort = await port();
  const apiPort = await port();
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const database = `datacat_pilot_smoke_${Date.now()}`;
  const since = new Date(Date.now() - 1000).toISOString();
  const env = { ...process.env,
    MONGO_URI: `mongodb://127.0.0.1:${mongoPort}`, MONGO_DB: database,
    BOT_CAPTURE_ENABLED: 'true', BOT_ADMIN_TOKEN: 'isolated-smoke-admin', BOT_READ_TOKEN: 'isolated-smoke-read',
    BOT_TELEMETRY_SPOOL_PATH: path.join(work, 'spool.sqlite'),
    BOT_MAINTENANCE_INTERVAL_SECONDS: '1', BOT_HEALTH_CACHE_SECONDS: '0', BOT_RATE_LIMIT_PER_MINUTE: '1000',
  };
  function databaseQuery(code) {
    return JSON.parse(command(['-c', `import os,json\nfrom pymongo import MongoClient\nclient=MongoClient(os.environ['MONGO_URI'],serverSelectionTimeoutMS=2000)\nassert os.environ['MONGO_DB'].startswith('datacat_pilot_smoke_')\ndb=client[os.environ['MONGO_DB']]\n${code}`], env));
  }
  function startMongo() {
    mongo = spawn(mongod, ['--bind_ip', '127.0.0.1', '--port', String(mongoPort),
      '--dbpath', path.join(work, 'mongo'), '--wiredTigerCacheSizeGB', '0.25',
      '--setParameter', 'ttlMonitorSleepSecs=1', '--logpath', path.join(work, 'mongo.log'), '--logappend'],
    { stdio: 'ignore', windowsHide: true });
    mongo.on('error', (error) => { apiLogs += String(error); });
  }
  function startApi() {
    api = spawn(python, ['-m', 'uvicorn', 'api_service.main:app', '--host', '127.0.0.1', '--port', String(apiPort)],
      { cwd: root, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    for (const stream of [api.stdout, api.stderr]) stream.on('data', (data) => { apiLogs = (apiLogs + data).slice(-20000); });
    api.on('error', (error) => { apiLogs += String(error); });
  }
  async function ready() {
    return until(async () => {
      const response = await fetch(`${apiBase}/health`);
      const health = await response.json();
      return response.ok && health.database && health.research_capture?.enabled && health;
    }, 'API + database ready', 45000);
  }

  site = http.createServer((_request, response) => {
    response.setHeader('Content-Type', 'text/html; charset=utf-8');
    response.end(`<!doctype html><html><head><title>DATACAT integration fixture</title>
      <script defer src="${apiBase}/bot-collector.js" data-datacat data-study-id="smoke" data-site-id="fixture" data-interval-ms="60000"></script>
      </head><body><main style="height:2400px;padding:32px"><h1>Integration fixture</h1>
      <button style="margin-top:60px">Target</button><p>Scroll target</p></main></body></html>`);
  });
  await new Promise((resolve) => site.listen(0, '127.0.0.1', resolve));
  const siteBase = `http://127.0.0.1:${site.address().port}`;
  env.BOT_CORS_ORIGINS = siteBase;
  startMongo();
  await until(() => databaseQuery("print(json.dumps(bool(client.admin.command('ping')['ok'])))"), 'MongoDB startup');
  startApi();
  const health = await ready();
  console.log('Real MongoDB and API ready');
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const payloads = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url() === `${apiBase}/api/v1/telemetry`) {
      try { payloads.push(request.postDataJSON()); } catch (_error) { /* not a JSON send */ }
    }
  });
  await page.goto(siteBase);
  await page.waitForFunction(() => window.DatacatPilot?.getStatus().lastReceipt?.captureId, undefined, { timeout: 20000 });
  assert.equal(payloads[0].mouse.records.length, 0, 'no-mouse visits must still be captured');
  const firstSession = await page.evaluate(() => window.DatacatPilot.collector.sessionId);
  assert.equal(databaseQuery(`print(json.dumps(db.research_sessions.find_one({'_id': ${JSON.stringify(firstSession)}})['traffic_number']))`), 1);
  for (let i = 0; i < 40; i++) await page.mouse.move(50 + i * 8, 80 + (i % 7) * 10);
  await page.locator('button').click();
  await page.mouse.wheel(0, 100);
  await page.waitForFunction(() => window.DatacatPilot.collector.mouseRecorder.scrollEvents.length > 0);
  await page.evaluate(() => window.DatacatPilot.collector.sendTelemetry('smoke-mouse'));
  assert(payloads.some((p) => p.action === 'smoke-mouse' && p.mouse.records.length >= 25));
  assert(payloads.some((p) => p.mouse.scrollEvents.length > 0));
  await page.evaluate((sdk) => new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = sdk;
    script.setAttribute('data-datacat', '');
    script.setAttribute('data-study-id', 'smoke'); script.setAttribute('data-site-id', 'fixture');
    script.onload = resolve; script.onerror = reject; document.head.append(script);
  }), `${apiBase}/bot-collector.js`);
  assert.equal(await page.evaluate(() => window.DatacatPilot.collector.sessionId), firstSession);
  assert.equal(payloads.filter((p) => p.action === 'init').length, 1);
  console.log('Cross-origin embed, no-mouse/mouse/wheel and duplicate tag verified');

  let lostReceipt = null;
  let retryAttempts = 0;
  await page.route('**/api/v1/telemetry', async (route) => {
    const body = route.request().postDataJSON();
    if (body.action === 'smoke-retry') {
      retryAttempts++;
      if (!lostReceipt) {
        const response = await route.fetch();
        lostReceipt = await response.json();
        return route.abort('internetdisconnected');
      }
    }
    return route.continue();
  });
  await page.evaluate(() => window.DatacatPilot.collector.sendTelemetry('smoke-retry'));
  await until(async () => {
    const receipt = await page.evaluate(() => window.DatacatPilot.getStatus().lastReceipt);
    return lostReceipt && receipt?.captureId === lostReceipt.capture_id;
  }, 'retry of lost response');
  assert(retryAttempts >= 2);
  const retryCount = databaseQuery(`print(json.dumps(db.telemetry_captures.count_documents({'event_id': ${JSON.stringify(lostReceipt.capture_id)}})))`);
  assert.equal(retryCount, 1);
  console.log('Lost-response retry stored exactly one raw capture');

  await page.goto(`${siteBase}/next-page`);
  await page.waitForFunction(() => window.DatacatPilot?.getStatus().lastReceipt?.captureId);
  assert.notEqual(await page.evaluate(() => window.DatacatPilot.collector.sessionId), firstSession);
  await until(() => databaseQuery("print(json.dumps(any(json.loads(d['payload_json']).get('action')=='pagehide' for d in db.telemetry_captures.find({}))))"), 'cross-origin pagehide beacon');
  console.log('Navigation and cross-origin pagehide verified');

  await stop(mongo);
  await page.evaluate(() => window.DatacatPilot.collector.sendTelemetry('smoke-outage'));
  const buffered = await page.evaluate(() => window.DatacatPilot.getStatus().lastReceipt);
  assert.equal(buffered.buffered, true);
  assert.equal(buffered.persisted, false);
  await stop(api);
  startMongo();
  await until(() => databaseQuery("print(json.dumps(bool(client.admin.command('ping')['ok'])))"), 'MongoDB restart');
  startApi();
  await ready();
  await until(() => databaseQuery(`print(json.dumps(db.telemetry_captures.count_documents({'event_id': ${JSON.stringify(buffered.captureId)}})==1))`), 'durable capture recovery after API restart');
  console.log('MongoDB outage and process restart recovered acknowledged capture');

  const dashboard = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const uiErrors = [];
  dashboard.on('pageerror', (error) => uiErrors.push(error.message));
  await dashboard.addInitScript(() => {
    sessionStorage.setItem('bot_read_token', 'isolated-smoke-read');
    sessionStorage.setItem('bot_admin_token', 'isolated-smoke-admin');
  });
  await dashboard.goto(`${apiBase}/dashboard`);
  await dashboard.waitForFunction(() => document.querySelectorAll('#trafficBody tr[data-idx]').length === 2);
  assert.equal(await dashboard.locator('#trafficBody tr[data-idx]').first().locator('td').first().innerText(), '2');
  assert.equal(await dashboard.locator('#trafficBody tr[data-idx]').nth(1).locator('td').first().innerText(), '1');
  await dashboard.locator('#trafficBody tr[data-idx]').first().click();
  assert.equal(await dashboard.locator('#sessionDrawer').evaluate((element) => element.classList.contains('open')), false);
  await dashboard.locator('#trafficBody tr[data-idx]').first().locator('.view-btn').click();
  await dashboard.waitForFunction(() => document.getElementById('sessionDrawer').classList.contains('open'));
  await dashboard.keyboard.press('Escape');
  const originalVerdict = databaseQuery(`print(json.dumps(db.detection_results.find_one({'sessionId': ${JSON.stringify(firstSession)}})['verdict']))`);
  await dashboard.locator('#trafficBody tr[data-idx]').nth(1).locator('.label-btn').click();
  await dashboard.locator('#labelValue').selectOption('BOT');
  await dashboard.locator('#labelSource').selectOption('controlled_bot');
  await dashboard.locator('#labelGroup').fill('fixture_runner_01');
  await dashboard.locator('#labelReviewer').fill('local-smoke');
  await dashboard.locator('#labelNotes').fill('Controlled Playwright runner; independent of model verdict');
  await dashboard.locator('#labelConfirmed').check();
  await dashboard.locator('#labelSave').click();
  await dashboard.waitForFunction(() => !document.getElementById('labelDialog').open);
  const labelDoc = databaseQuery(`print(json.dumps(db.research_sessions.find_one({'_id': ${JSON.stringify(firstSession)}})['manual_label']))`);
  assert.equal(labelDoc.label, 'BOT');
  assert.equal(labelDoc.revision, 1);
  assert.equal(databaseQuery(`print(json.dumps(db.detection_results.find_one({'sessionId': ${JSON.stringify(firstSession)}})['verdict']))`), originalVerdict);
  const conflict = await fetch(`${apiBase}/api/v1/sessions/${encodeURIComponent(firstSession)}/label`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-Admin-Token': 'isolated-smoke-admin' },
    body: JSON.stringify({ ...labelDoc, updated_at: undefined, revision: undefined, expected_revision: 0 }),
  });
  assert.equal(conflict.status, 409);
  await dashboard.reload();
  await dashboard.waitForFunction(() => document.querySelectorAll('#trafficBody tr[data-idx]').length === 2);
  assert.equal(await dashboard.locator('#trafficBody tr[data-idx]').nth(1).locator('td').nth(9).innerText(), 'BOT');
  await dashboard.locator('#trafficBody tr[data-idx]').nth(1).click();
  await dashboard.waitForFunction(() => parseInt(document.getElementById('trajPoints').textContent, 10) >= 25);
  await dashboard.screenshot({ path: path.join(work, 'dashboard-desktop.png'), fullPage: true });
  await dashboard.setViewportSize({ width: 390, height: 844 });
  await dashboard.locator('#trafficBody tr[data-idx]').nth(1).locator('.label-btn').click();
  const dialogBounds = await dashboard.locator('#labelDialog').boundingBox();
  assert(dialogBounds.x >= 0 && dialogBounds.x + dialogBounds.width <= 390);
  await dashboard.screenshot({ path: path.join(work, 'dashboard-mobile-label.png'), fullPage: true });
  await dashboard.keyboard.press('Escape');
  assert.deepEqual(uiErrors, []);
  await dashboard.close();
  console.log('Dashboard numbering, profile selection, manual label persistence/conflict and mobile dialog verified');

  const output = path.join(work, 'export');
  command(['-m', 'core_ml.dataset.export_captures', '--study-id', 'smoke', '--site-id', 'fixture',
    '--since', since, '--until', new Date(Date.now() + 1000).toISOString(), '--output', output,
    '--include-manual-labels'], env);
  command(['-m', 'core_ml.dataset.export_captures', '--verify', output], env);
  const manifest = JSON.parse(fs.readFileSync(path.join(output, 'manifest.json'), 'utf8'));
  assert(manifest.snapshots >= 5);
  assert.equal(manifest.runs, 2);
  const datasetOutput = path.join(work, 'labeled-export');
  command(['-m', 'core_ml.dataset.export_captures', '--study-id', 'smoke', '--site-id', 'fixture',
    '--since', since, '--until', new Date(Date.now() + 1000).toISOString(), '--output', datasetOutput,
    '--labeled-only'], env);
  const trainingCount = Number(command(['-c',
    `from core_ml.dataset.manual_labels import manual_training_samples\nprint(len(manual_training_samples(${JSON.stringify(datasetOutput)}, ['fixture_runner_01'])))`], env));
  assert.equal(trainingCount, 1);
  databaseQuery("from datetime import datetime,timedelta,timezone\ndb.telemetry_captures.insert_one({'_id':'ttl-check','expires_at':datetime.now(timezone.utc)-timedelta(seconds=10)})\nprint('true')");
  await until(() => databaseQuery("print(json.dumps(db.telemetry_captures.find_one({'_id':'ttl-check'}) is None))"), 'real TTL deletion', 30000);
  const cleanupDashboard = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await cleanupDashboard.addInitScript(() => {
    sessionStorage.setItem('bot_read_token', 'isolated-smoke-read');
    sessionStorage.setItem('bot_admin_token', 'isolated-smoke-admin');
  });
  cleanupDashboard.on('dialog', (dialog) => dialog.accept());
  await cleanupDashboard.goto(`${apiBase}/dashboard`);
  await cleanupDashboard.waitForFunction(() => document.querySelectorAll('#trafficBody tr[data-idx]').length === 2);
  await cleanupDashboard.locator('.delete-all-btn').first().click();
  await cleanupDashboard.waitForFunction(() => document.getElementById('kpiTotalSessions').textContent === '0'
    && document.querySelectorAll('#trafficBody tr[data-idx]').length === 0);
  assert.equal(databaseQuery("print(json.dumps(db.labeled_captures.count_documents({})))"), 0);
  assert.equal(databaseQuery("print(json.dumps(db.research_sessions.count_documents({'manual_label.label':'BOT'})))"), 0);
  assert.equal(databaseQuery("print(json.dumps(db.research_counters.find_one({'_id':'traffic'})['value']))"), 2);
  await cleanupDashboard.close();
  const evidence = {
    verified: true, api_health: health.status, bundle_id: health.model_bundle_id,
    collector_sha256: createHash('sha256').update(fs.readFileSync(path.join(root, 'collector/dist/bot-collector.js'))).digest('hex'),
    browser: browser.version(), tests: ['cross-origin embed', 'no mouse', 'movement/click/wheel',
      'duplicate embed', 'lost-response retry idempotency', 'navigation/pagehide',
      'MongoDB outage', 'process restart + durable recovery', 'export/verify', 'TTL deletion'],
    research_tests: ['persistent traffic numbers', 'row versus profile click', 'manual label UI',
      'optimistic label conflict', 'desktop/mobile dashboard', 'retained labeled export + training import',
      'explicit dataset deletion + counter preservation'],
    exported_snapshots: manifest.snapshots, exported_runs: manifest.runs,
    scope: 'local browser/database integration, not human labels or detection accuracy',
  };
  fs.writeFileSync(path.join(work, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ work, ...evidence }, null, 2));
}

main().catch((error) => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stop(api); await stop(mongo);
  if (site) await new Promise((resolve) => site.close(resolve));
});

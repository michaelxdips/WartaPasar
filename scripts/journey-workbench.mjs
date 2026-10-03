// Slice 4 browser acceptance: login -> inspect -> map -> origin-review -> hold -> approve ->
// export -> inspect public result -> advance (new revision) -> stale approval refused ->
// review the new revision -> inspect history -> logout. Desktop 1280x900 and mobile 390x844.
// The workbench server and its synthetic demo store are started by this script; nothing
// touches a real archive and live publishing stays off.
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

const ROOT = process.cwd();
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PYTHON = process.env.PYTHON || 'python';
const CDP_PORT = 9231;
const WORKBENCH_PORT = 8788;
const OUT = process.env.OUT_DIR || path.resolve(ROOT, '.internal/phase7/browser-workbench');
const PROFILE = path.resolve(ROOT, '.internal/phase7/chrome-workbench-profile');
const DEMO = path.resolve(ROOT, '.internal/phase7/workbench-demo');
const SECRET = process.env.WORKBENCH_DEMO_SECRET || 'rahasia-demo-lokal-uji';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(fn, timeoutMs = 25000, label = 'kondisi') {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { const value = await fn(); if (value) return value; } catch { /* retry */ }
    await sleep(250);
  }
  throw new Error(`${label} tidak siap dalam ${timeoutMs} ms`);
}

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.listeners = new Map(); }
  static async attach(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', reject, { once: true });
    });
    const cdp = new Cdp(ws);
    ws.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id && cdp.pending.has(message.id)) {
        const { resolve, reject } = cdp.pending.get(message.id);
        cdp.pending.delete(message.id);
        message.error ? reject(new Error(message.error.message)) : resolve(message.result);
      } else if (message.method) {
        for (const listener of cdp.listeners.get(message.method) ?? []) listener(message.params);
      }
    });
    return cdp;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  on(method, listener) { this.listeners.set(method, [...(this.listeners.get(method) ?? []), listener]); }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error('evaluate: ' + (result.exceptionDetails.text || 'error'));
    return result.result.value;
  }
}

async function main() {
  await rm(DEMO, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });
  await mkdir(DEMO, { recursive: true });
  const report = { checks: [], console: [], screenshots: [], httpErrors: [] };
  globalThis.__report = report;
  const check = (name, ok, detail) => report.checks.push({ name, ok: Boolean(ok), detail });

  // 1. Synthetic store + workbench server.
  const built = spawnSync(PYTHON, ['scripts/build_workbench_demo.py', DEMO], { cwd: ROOT, encoding: 'utf8' });
  if (built.status !== 0) throw new Error('demo store gagal: ' + built.stderr);
  const demo = JSON.parse(built.stdout.trim().split('\n').pop());
  const hashResult = spawnSync(PYTHON, ['workbench.py', '--print-hash', SECRET], { cwd: ROOT, encoding: 'utf8' });
  if (hashResult.status !== 0) throw new Error('hash gagal: ' + hashResult.stderr);
  const server = spawn(PYTHON, ['workbench.py', '--port', String(WORKBENCH_PORT)], {
    cwd: ROOT,
    env: { ...process.env, RONCE_WORKBENCH_OPERATOR: 'Editor Demo',
           RONCE_WORKBENCH_SECRET_HASH: hashResult.stdout.trim(),
           RONCE_WORKBENCH_DB: demo.demo_db, RONCE_WORKBENCH_EXPORT_DIR: demo.demo_export_dir },
    stdio: 'ignore',
  });
  const BASE = `http://127.0.0.1:${WORKBENCH_PORT}`;
  await waitFor(async () => (await fetch(`${BASE}/api/session`)).ok, 20000, 'workbench');

  const chrome = spawn(CHROME, [`--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${PROFILE}`,
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  try {
    await waitFor(async () => (await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`)).ok, 20000, 'chrome');
    const target = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${encodeURIComponent(BASE + '/')}`,
      { method: 'PUT' })).json();
    const cdp = await Cdp.attach(target.webSocketDebuggerUrl);
    cdp.on('Runtime.consoleAPICalled', (params) => {
      if (params.type === 'error' || params.type === 'warning') {
        report.console.push({ type: params.type, text: (params.args ?? []).map((a) => a.value ?? a.description).join(' ') });
      }
    });
    cdp.on('Runtime.exceptionThrown', (params) =>
      report.console.push({ type: 'exception', text: params.exceptionDetails?.text ?? 'unknown' }));
    cdp.on('Network.responseReceived', (params) => {
      if (params.response.status >= 400) {
        report.httpErrors.push({ url: params.response.url.replace(BASE, ''), status: params.response.status });
      }
    });
    await cdp.send('Runtime.enable');
    await cdp.send('Page.enable');
    await cdp.send('Network.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    const shot = async (name, fullPage = false) => {
      const image = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: fullPage });
      await writeFile(path.join(OUT, name), Buffer.from(image.data, 'base64'));
      report.screenshots.push(name);
    };
    const text = () => cdp.evaluate('document.body.innerText');
    const reload = async () => { await cdp.send('Page.reload'); await sleep(1100); };

    // 2. Unauthenticated: the workbench shows only the login form.
    await cdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(1000);
    let body = await text();
    check('login form visible before authentication', /Masuk sebagai operator lokal/.test(body), 'login');
    check('public boundary stated', /127\.0\.0\.1|loopback/.test(body), 'batas');
    await shot('01-login-desktop.png');

    // 3. Login.
    await cdp.evaluate(`(() => { const input = document.querySelector('#secret');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(SECRET)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('#login-form button[type=submit]').click(); })()`);
    await waitFor(async () => (await text()).includes('Batas lokal'), 8000, 'masuk');
    body = await text();
    check('login reaches the workbench', /operator: Editor Demo/.test(body), 'principal');
    check('no external-release action is offered', !/publikasi eksternal/i.test(body) || /tidak ada tindakan publikasi eksternal/i.test(body), 'batas');
    await waitFor(async () => (await cdp.evaluate(`document.querySelectorAll('#runs button[data-run]').length`)) > 0, 8000, 'daftar run');
    check('runs list loads with the synthetic run', /2026-09-25T11:00:00\+07:00/.test(await text()), 'runs');

    // 4. Inspect: pick the run, then open the first candidate detail.
    await waitFor(async () => (await cdp.evaluate(`document.querySelectorAll('#runs button[data-run]').length`)) > 0, 8000, 'daftar run');
    await cdp.evaluate(`document.querySelector('#runs button[data-run]').click()`);
    await waitFor(async () => (await cdp.evaluate(`document.querySelectorAll('#candidates button[data-key]').length`)) > 0, 8000, 'kandidat');
    await cdp.evaluate(`document.querySelector('#candidates button[data-key]').click()`);
    await waitFor(async () => (await text()).includes('Keputusan asal'), 8000, 'detail');
    body = await text();
    check('candidate detail shows decision context', /BBCA/.test(body) && /review/.test(body), 'konteks');
    check('evidence interpretation limits stay visible', /bukan pemahaman semantik/i.test(body), 'batas tafsir');
    check('origin decisions required per candidate source', /Keputusan asal \(sumber kandidat\)/.test(body), 'asal');
    await shot('02-detail-desktop.png');

    // 5. Origin review for both candidate sources (before mapping, as the engine allows).
    const sourceCount = await cdp.evaluate(`document.querySelectorAll('.origin-source-form').length`);
    check('two candidate sources need origin decisions', sourceCount === 2, sourceCount);
    await cdp.evaluate(`(() => {
      const forms = [...document.querySelectorAll('.origin-source-form')];
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      for (const form of forms) {
        setter.call(form.querySelector('[name=rationale]'), 'contoh sintetis: sumber uji berdiri sendiri');
        form.querySelector('button[type=submit]').click();
      } })()`);
    await waitFor(async () => /Keputusan asal tercatat/.test(await text()), 10000, 'origin tersimpan');
    check('origin decisions persisted with principal', /Keputusan asal tercatat/.test(await text()), 'asal');

    // 6. Map a claim (typed mapping) and save the review.
    await cdp.evaluate(`(() => {
      const form = document.querySelector('#review-form');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      const set = (name, value) => { const input = form.querySelector('[name=' + name + ']');
        setter.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); };
      set('text', 'BBCA uji sintetis umumkan dividen tunai 100 juta rupiah.');
      set('entity', 'BBCA'); set('action', 'umumkan'); set('event_time', '2026-09-25');
      set('value', '100'); set('unit', 'rupiah'); set('scale', 'juta'); set('metric', 'dividen'); set('period', '2026');
      const rows = [...document.querySelectorAll('.evidence-row')];
      const values = [
        ['https://kanal-a.test/uji/a1', 'BBCA uji sintetis umumkan dividen tunai 100 juta rupiah', 'contoh sintetis 1'],
        ['https://kanal-b.test/uji/a2', 'Dividen tunai uji sintetis BBCA diumumkan 100 juta rupiah', 'contoh sintetis 2']];
      values.forEach(([source, quote, origin], index) => {
        if (!rows[index]) document.querySelector('#add-evidence').click();
        const row = [...document.querySelectorAll('.evidence-row')][index];
        row.querySelector('[name=source]').value = source;
        row.querySelector('[name=quote]').value = quote;
        row.querySelector('[name=origin]').value = origin;
        row.querySelector('[name=origin_note]').value = 'contoh sintetis: dua judul uji terpisah';
      });
      form.querySelector('button[type=submit]').click(); })()`);
    await waitFor(async () => /Review klaim tersimpan/.test(await text()), 10000, 'review tersimpan');
    check('typed mapping accepted by the engine', /Review klaim tersimpan/.test(await text()), 'pemetaan');
    await waitFor(async () => (await cdp.evaluate(`document.querySelector('.tag') && document.body.innerText.includes('revisi saat ini')`)), 8000, 'revisi');
    const revisionOne = await cdp.evaluate(`(async () => (await (await fetch('/api/candidate/' + ${JSON.stringify(demo.story_key)}, { credentials: 'same-origin' })).json()).current_revision_id)()`);
    check('review registered an immutable revision', typeof revisionOne === 'string' && revisionOne.length === 16, revisionOne);

    // 7. Hold, approve, export.
    await cdp.evaluate(`document.querySelector('#btn-hold').click()`);
    await waitFor(async () => /Keputusan hold tercatat/.test(await text()), 8000, 'hold');
    check('hold records on the seen revision', /Keputusan hold tercatat/.test(await text()), 'hold');
    await cdp.evaluate(`document.querySelector('#btn-approve').click()`);
    await waitFor(async () => /disetujui pada revisi/.test(await text()), 8000, 'approve');
    check('approval bound to the seen revision', /disetujui pada revisi/.test(await text()), 'approve');
    await cdp.evaluate(`document.querySelector('#btn-export').click()`);
    await waitFor(async () => /Ekspor privat ditulis atomik/.test(await text()), 8000, 'export');
    check('approved edition exported atomically', /Ekspor privat ditulis atomik/.test(await text()), 'ekspor');
    const manifest = JSON.parse(await readFile(path.join(DEMO, 'export', 'edisi-uji', 'threads', 'manifest.json'), 'utf8'));
    check('export manifest carries posts and no live publishing',
      manifest.counts.posts === 1 && manifest.policy.live_publishing === false, manifest.counts);
    const stories = JSON.parse(await readFile(path.join(DEMO, 'export', 'edisi-uji', 'threads', 'stories.json'), 'utf8'));
    check('public result shows the approved revision', stories.stories[0].revision !== null
      && /uji sintetis/.test(JSON.stringify(stories)), 'hasil publik');
    await shot('03-approved-desktop.png');

    // 8. A new revision arrives (second synthetic run) -> the page refreshes to it.
    const advanced = spawnSync(PYTHON, ['scripts/build_workbench_demo.py', 'advance', demo.demo_db], { cwd: ROOT, encoding: 'utf8' });
    if (advanced.status !== 0) throw new Error('advance gagal: ' + advanced.stderr);
    await reload();
    await waitFor(async () => (await cdp.evaluate(`document.querySelectorAll('#runs button[data-run]').length`)) > 0, 8000, 'daftar run');
    await cdp.evaluate(`document.querySelectorAll('#runs button[data-run]')[0].click()`);
    await waitFor(async () => (await cdp.evaluate(`document.querySelectorAll('#candidates button[data-key]').length`)) > 0, 8000, 'kandidat baru');
    await cdp.evaluate(`document.querySelector('#candidates button[data-key]').click()`);
    await waitFor(async () => {
      const value = await cdp.evaluate(`(async () => (await (await fetch('/api/candidate/' + ${JSON.stringify(demo.story_key)}, { credentials: 'same-origin' })).json()).current_revision_id)()`);
      return typeof value === 'string' && value.length === 16 && value !== revisionOne;
    }, 8000, 'revisi baru');
    const revisionTwo = await cdp.evaluate(`(async () => (await (await fetch('/api/candidate/' + ${JSON.stringify(demo.story_key)}, { credentials: 'same-origin' })).json()).current_revision_id)()`);
    check('new revision replaces the current one', revisionTwo !== revisionOne && revisionTwo.length === 16, revisionTwo);
    check('revision history shows typed comparison', /Riwayat revisi \(imutabel\)/.test(await text())
      && /claim_corrected|new_evidence|text_only/.test(await text()), 'riwayat');
    await shot('04-history-desktop.png');

    // 9. Stale approval: a second tab that still holds revision one must be refused with conflict.
    const staleTarget = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${encodeURIComponent(BASE + '/')}`,
      { method: 'PUT' })).json();
    const staleCdp = await Cdp.attach(staleTarget.webSocketDebuggerUrl);
    await staleCdp.send('Runtime.enable');
    await staleCdp.send('Page.enable');
    await staleCdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(900);
    await waitFor(async () => {
      const value = await staleCdp.evaluate('document.body.innerText');
      return value.includes('Kandidat') || value.includes('Masuk sebagai');
    }, 8000, 'tab dua');
    if ((await staleCdp.evaluate('document.body.innerText')).includes('Masuk sebagai')) {
      await staleCdp.evaluate(`(() => { const input = document.querySelector('#secret');
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(input, ${JSON.stringify(SECRET)});
        document.querySelector('#login-form button[type=submit]').click(); })()`);
    }
    await waitFor(async () => (await staleCdp.evaluate('document.body.innerText')).includes('Kandidat'), 8000, 'tab dua masuk');
    // Tab two acts on the revision-one view it captured before the new run arrived.
    const staleResult = await staleCdp.evaluate(`(async () => {
      const session = await (await fetch('/api/session', { credentials: 'same-origin' })).json();
      const response = await fetch('/api/decision', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Ronce-CSRF': session.csrf },
        body: JSON.stringify({ action: 'hold', story_key: ${JSON.stringify(demo.story_key)},
          note: 'tab dua dari tampilan lama',
          expected_revisions: { [${JSON.stringify(demo.story_key)}]: ${JSON.stringify(revisionOne)} } }) });
      return { status: response.status, body: await response.json() }; })()`);
    check('stale revision refused with 409 conflict', staleResult.status === 409, staleResult);
    check('conflict message is clear', /revisi|berubah|usang/i.test(staleResult.body.error || ''), staleResult.body.error);
    // The same stale tab also cannot re-export the old edition: its bound revision is superseded.
    const staleExport = await staleCdp.evaluate(`(async () => {
      const session = await (await fetch('/api/session', { credentials: 'same-origin' })).json();
      const response = await fetch('/api/export', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Ronce-CSRF': session.csrf },
        body: JSON.stringify({ run_id: ${JSON.stringify(demo.run_a)}, edition_id: 'edisi-uji',
          platform: 'threads', dataset: 'fixture', story_key: ${JSON.stringify(demo.story_key)},
          expected_revisions: { [${JSON.stringify(demo.story_key)}]: ${JSON.stringify(revisionOne)} } }) });
      return { status: response.status, body: await response.json() }; })()`);
    check('stale export of the old edition refused with conflict', staleExport.status === 409, staleExport);

    // 10. Review the new revision on the primary tab, then approve and export a new edition.
    await cdp.evaluate(`(() => {
      const form = document.querySelector('#review-form');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      const set = (name, value) => { const input = form.querySelector('[name=' + name + ']');
        setter.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); };
      set('text', 'BBCA uji sintetis umumkan dividen tunai 120 juta rupiah.');
      set('entity', 'BBCA'); set('action', 'umumkan'); set('event_time', '2026-09-25');
      set('value', '120'); set('unit', 'rupiah'); set('scale', 'juta'); set('metric', 'dividen'); set('period', '2026');
      const rows = [...document.querySelectorAll('.evidence-row')];
      const values = [
        ['https://kanal-a.test/uji/b1', 'BBCA uji sintetis umumkan dividen tunai 120 juta rupiah', 'contoh sintetis 1'],
        ['https://kanal-b.test/uji/b2', 'Dividen tunai uji sintetis BBCA diumumkan 120 juta rupiah', 'contoh sintetis 2']];
      values.forEach(([source, quote, origin], index) => {
        if (!rows[index]) document.querySelector('#add-evidence').click();
        const row = [...document.querySelectorAll('.evidence-row')][index];
        row.querySelector('[name=source]').value = source;
        row.querySelector('[name=quote]').value = quote;
        row.querySelector('[name=origin]').value = origin;
        row.querySelector('[name=origin_note]').value = 'contoh sintetis: dua judul uji terpisah';
      });
      form.querySelector('button[type=submit]').click(); })()`);
    await waitFor(async () => /Review klaim tersimpan/.test(await text()), 10000, 'review baru');
    check('new revision reviewed on its own run', /Review klaim tersimpan/.test(await text()), 'review baru');

    // Approve + export the new revision with a new edition id.
    await cdp.evaluate(`(() => { const input = document.querySelector('#edition-id');
      input.value = 'edisi-uji-b'; input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    await cdp.evaluate(`document.querySelector('#btn-approve').click()`);
    await waitFor(async () => /disetujui pada revisi/.test(await text()), 8000, 'approve baru');
    check('new revision approved', /disetujui pada revisi/.test(await text()), 'approve baru');
    await cdp.evaluate(`document.querySelector('#btn-export').click()`);
    await waitFor(async () => /Ekspor privat ditulis atomik/.test(await text()), 8000, 'ekspor baru');
    check('new revision exported', /Ekspor privat ditulis atomik/.test(await text()), 'ekspor baru');
    const manifestB = JSON.parse(await readFile(path.join(DEMO, 'export', 'edisi-uji-b', 'threads', 'manifest.json'), 'utf8'));
    check('second export carries its own edition', manifestB.edition_id === 'edisi-uji-b', manifestB.edition_id);

    // 11. Mobile 390x844: no horizontal overflow, main actions reachable, screenshots.
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await sleep(600);
    const overflow = await cdp.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth');
    check('no horizontal overflow at 390x844', overflow <= 0, overflow);
    const actionsVisible = await cdp.evaluate(`(() => { const button = document.querySelector('#btn-approve');
      if (!button) return false; button.scrollIntoView({ block: 'center' });
      const rect = button.getBoundingClientRect();
      return rect.width > 0 && rect.left >= 0 && rect.right <= window.innerWidth + 1; })()`);
    check('approve action reachable on mobile width', actionsVisible, actionsVisible);
    await shot('05-mobile-390.png');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(400);

    // 12. Keyboard: skip link focuses content, and the audit trail shows the principal + conflicts.
    await cdp.evaluate(`document.querySelector('.skip').focus()`);
    const skipFocus = await cdp.evaluate(`({ tag: document.activeElement.tagName,
      text: document.activeElement.textContent })`);
    check('skip link is focusable', skipFocus.tag === 'A' && /Lewati ke konten/.test(skipFocus.text || ''), skipFocus);
    // Real keyboard navigation: Tab until a BUTTON holds focus, then read its outline.
    await cdp.evaluate(`document.activeElement.blur()`);
    let focusedButton = null;
    for (let press = 0; press < 25 && !focusedButton; press += 1) {
      await cdp.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
      focusedButton = await cdp.evaluate(`(() => { const el = document.activeElement;
        if (!el || el.tagName !== 'BUTTON') return null;
        const style = getComputedStyle(el);
        return { id: el.id, text: (el.textContent || '').trim().slice(0, 24),
                 outline: style.outlineWidth + ' ' + style.outlineStyle }; })()`);
    }
    check('keyboard focus shows a visible outline on a button',
      focusedButton && /^[2-9]/.test(focusedButton.outline) && !focusedButton.outline.includes('none'),
      focusedButton || 'tidak ada tombol menerima fokus');
    const audit = await cdp.evaluate('document.querySelector("#audit")?.innerText ?? ""');
    check('audit trail shows principal and outcomes', /Editor Demo/.test(audit) && /conflict/.test(audit), 'audit');

    // 13. Logout invalidates the session.
    await cdp.evaluate(`document.querySelector('#logout').click()`);
    await waitFor(async () => /Masuk kembali|Masuk sebagai/.test(await text()), 8000, 'keluar');
    const afterLogout = await cdp.evaluate(`(async () => (await fetch('/api/runs', { credentials: 'same-origin' })).status)()`);
    check('logout invalidates the session', afterLogout === 401, afterLogout);
    await shot('06-logout-desktop.png');

    report.consoleErrors = report.console;
  } finally {
    chrome.kill();
    server.kill();
  }
  await writeFile(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  const failed = report.checks.filter((row) => !row.ok);
  console.log(JSON.stringify({
    checks: report.checks, console: report.console, httpErrors: report.httpErrors,
    screenshots: report.screenshots,
    verdict: failed.length === 0 && report.console.length === 0 ? 'PASS' : 'FAIL',
  }, null, 2));
  process.exit(failed.length === 0 && report.console.length === 0 ? 0 : 1);
}

main().catch(async (error) => {
  // Write whatever was observed before the failure, so debugging has evidence.
  try {
    const report = globalThis.__report;
    if (report) {
      await writeFile(path.resolve(process.env.OUT_DIR || '.internal/phase7/browser-workbench', 'report-failure.json'),
        JSON.stringify({ ...report, failure: String(error) }, null, 2));
    }
  } catch { /* best effort */ }
  console.error(error);
  process.exit(1);
});

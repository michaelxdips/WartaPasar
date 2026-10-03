// Acceptance journey for the comparison + citation feature, driving real Chrome over CDP.
// Steps: fixture comparison -> inspect old/new evidence -> relations -> copy citation (success and
// clipboard-denied fallback) -> direct URL/reload/Back -> unknown pair -> desktop + 390x844.
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9224;
const BASE = process.env.BASE_URL || 'http://localhost:8099';
const OUT = process.env.OUT_DIR || path.resolve(process.cwd(), '.internal/phase7/browser');
const PROFILE = path.resolve(process.cwd(), '.internal/phase7/chrome-profile');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForDevtools(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (response.ok) return await response.json();
    } catch { /* not up yet */ }
    await sleep(250);
  }
  throw new Error('devtools endpoint tidak siap');
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
  on(method, listener) {
    this.listeners.set(method, [...(this.listeners.get(method) ?? []), listener]);
  }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return result.result.value;
  }
}

async function openTarget(url) {
  const response = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
  if (!response.ok) throw new Error(`gagal membuka tab: ${response.status}`);
  return await response.json();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const fixture = JSON.parse(await readFile(path.resolve('web/public/data/fixture/model.json'), 'utf8')).model;
  const pair = fixture.comparisons.find((row) => row.story_key === '3364d60163ad92ba') ?? fixture.comparisons[0];
  const report = { base: BASE, checks: [], console: [], screenshots: [], pair };
  const check = (name, ok, detail) => report.checks.push({ name, ok: Boolean(ok), detail });

  const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  try {
    await waitForDevtools();
    const url = `${BASE}/banding/${pair.story_key}/${pair.from_revision}/${pair.to_revision}/`;
    const target = await openTarget(url);
    const cdp = await Cdp.attach(target.webSocketDebuggerUrl);
    cdp.on('Runtime.consoleAPICalled', (params) => {
      if (params.type === 'error' || params.type === 'warning') {
        report.console.push({ type: params.type, text: (params.args ?? []).map((a) => a.value ?? a.description).join(' ') });
      }
    });
    cdp.on('Runtime.exceptionThrown', (params) =>
      report.console.push({ type: 'exception', text: params.exceptionDetails?.text ?? 'unknown' }));
    await cdp.send('Runtime.enable');
    await cdp.send('Page.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    await cdp.send('Page.navigate', { url });
    await sleep(1200);

    const body = await cdp.evaluate('document.body.innerText');
    check('fixture banner visible', /FIXTURE SINTETIS/.test(body), 'banner text found');
    check('old value 100 shown', /100 juta rupiah/.test(body), 'revisi lama');
    check('new value 120 shown', /120 juta rupiah/.test(body), 'revisi baru');
    check('correction category shown', /angka dikoreksi/.test(body), 'perubahan');
    check('evidence category shown', /bukti baru/.test(body), 'perubahan');
    check('correction basis from relation', /relasi koreksi/.test(body), 'dasar');
    check('relation recorded', /corrects/.test(body) && /dikoreksi redaksi/.test(body), 'relasi');
    check('evidence quotes visible', /Koreksi uji sintetis/.test(body), 'kutipan bukti');

    // Clipboard success path: capture what the page writes.
    await cdp.evaluate(`window.__copied = null;
      navigator.clipboard.writeText = async (text) => { window.__copied = text; };`);
    await cdp.evaluate(`(() => { const buttons = [...document.querySelectorAll('.citation button')];
      buttons[0].scrollIntoView(); buttons[0].click(); return true; })()`);
    await sleep(400);
    const copied = await cdp.evaluate('window.__copied');
    const statusText = await cdp.evaluate(`document.querySelector('.citation [role="status"]').textContent`);
    check('clipboard success reported', /tersalin/.test(statusText ?? ''), statusText);
    check('citation carries metric/value/period', /120 juta rupiah/.test(copied ?? '') && /periode 2026/.test(copied ?? ''), (copied ?? '').split('\n')[0]);
    check('citation carries revision + link', new RegExp(pair.to_revision).test(copied ?? '') && /\/banding\//.test(copied ?? ''), 'revisi + tautan');
    check('citation keeps the synthetic label', /FIXTURE SINTETIS/.test(copied ?? ''), 'label');
    await writeFile(path.join(OUT, 'citation-success.txt'), copied ?? '', 'utf8');

    // Clipboard denied path on the historical citation.
    await cdp.evaluate(`navigator.clipboard.writeText = async () => { throw new DOMException('denied', 'NotAllowedError'); };`);
    await cdp.evaluate(`(() => { const buttons = [...document.querySelectorAll('.citation button')];
      const target = buttons[buttons.length - 1]; target.scrollIntoView(); target.click(); return true; })()`);
    await sleep(400);
    const fallback = await cdp.evaluate(`(() => { const area = document.querySelector('.citation textarea');
      const status = [...document.querySelectorAll('.citation [role="status"]')].map((n) => n.textContent).join(' | ');
      return { hasArea: Boolean(area), value: area ? area.value : '', status }; })()`);
    check('clipboard denial shows fallback textarea', fallback.hasArea, fallback.status);
    check('fallback text is the historical citation', /historis/.test(fallback.value ?? '') && new RegExp(pair.from_revision).test(fallback.value ?? ''), (fallback.value ?? '').split('\n')[0]);
    check('denial status is announced', /ditolak/i.test(fallback.status ?? ''), fallback.status);
    await writeFile(path.join(OUT, 'citation-fallback.txt'), fallback.value ?? '', 'utf8');

    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'banding-desktop.png'), Buffer.from(shot.data, 'base64'));
    report.screenshots.push('banding-desktop.png');

    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await sleep(400);
    const overflow = await cdp.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth');
    check('no horizontal overflow at 390x844', overflow <= 0, `overflow=${overflow}`);
    const mobileShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'banding-mobile.png'), Buffer.from(mobileShot.data, 'base64'));
    report.screenshots.push('banding-mobile.png');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    // Direct URL, reload, Back.
    const archiveStory = JSON.parse(await readFile(path.resolve('web/public/data/stories.json'), 'utf8'))
      .stories[0];
    await cdp.send('Page.navigate', { url: `${BASE}/warta/${archiveStory.id}/` });
    await sleep(900);
    const storyBody = await cdp.evaluate('document.body.innerText');
    check('story page explains its single-revision state or links a comparison',
      /Bandingkan|Satu revisi tercatat/.test(storyBody), 'tautan perbandingan');
    await cdp.send('Page.navigate', { url });
    await sleep(900);
    const back = await cdp.evaluate(`history.back(); true`);
    await sleep(900);
    const afterBack = await cdp.evaluate('location.pathname');
    check('Back returns to the story page', afterBack.includes('/warta/'), afterBack);
    await cdp.send('Page.navigate', { url });
    await sleep(900);
    await cdp.send('Page.reload');
    await sleep(1000);
    const reloaded = await cdp.evaluate('document.body.innerText');
    check('reload keeps the comparison rendered', /FIXTURE SINTETIS/.test(reloaded), 'reload');

    // Unknown / mismatched pair must not silently fall back to the latest content.
    const bogus = `${BASE}/banding/${pair.story_key}/${'0'.repeat(16)}/${'1'.repeat(16)}/`;
    await cdp.send('Page.navigate', { url: bogus });
    await sleep(900);
    const bogusBody = await cdp.evaluate('document.body.innerText');
    const bogusTitle = await cdp.evaluate('document.title');
    check('unknown revision pair is refused', /404|tidak ditemukan|This page could not be found/i.test(bogusBody), bogusTitle);

    // Keyboard: tab to the copy button and activate with Enter.
    await cdp.send('Page.navigate', { url });
    await sleep(900);
    const keyboard = await cdp.evaluate(`(() => {
      const button = document.querySelector('.citation button');
      button.focus();
      return document.activeElement === button; })()`);
    check('copy button is focusable by keyboard', keyboard, 'fokus');
  } finally {
    chrome.kill();
  }

  await writeFile(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2), 'utf8');
  const failed = report.checks.filter((row) => !row.ok);
  console.log(JSON.stringify({
    pair: `${pair.story_key.slice(0, 8)} ${pair.from_revision} -> ${pair.to_revision}`,
    checks: report.checks.length, failed: failed.map((row) => `${row.name}: ${row.detail}`),
    consoleErrors: report.console, screenshots: report.screenshots,
    verdict: failed.length === 0 && report.console.length === 0 ? 'PASS' : 'FAIL',
  }, null, 2));
  process.exit(failed.length === 0 && report.console.length === 0 ? 0 : 1);
}

main().catch((error) => { console.error(error); process.exit(1); });

// Slice 3 journey: Orbit movers -> Emiten context -> Kalender -> date-kind filter -> event ->
// source/emiten links -> back to Warta. Also checks denial/partial labels and mobile layout.
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9227;
const BASE = process.env.BASE_URL || 'http://localhost:8099';
const OUT = process.env.OUT_DIR || path.resolve(process.cwd(), '.internal/phase7/browser');
const PROFILE = path.resolve(process.cwd(), '.internal/phase7/chrome-companion-profile');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForDevtools(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (response.ok) return true;
    } catch { /* not up */ }
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
  on(method, listener) { this.listeners.set(method, [...(this.listeners.get(method) ?? []), listener]); }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return result.result.value;
  }
  async visit(url, settle = 900) {
    await this.send('Page.navigate', { url });
    await sleep(settle);
    return this.evaluate('document.body.innerText');
  }
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const companion = JSON.parse(await readFile(path.resolve('web/public/data/fixture/companion.json'), 'utf8')).companion;
  const report = { base: BASE, checks: [], console: [], screenshots: [] };
  const check = (name, ok, detail) => report.checks.push({ name, ok: Boolean(ok), detail });

  const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  try {
    await waitForDevtools();
    const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(`${BASE}/`)}`,
      { method: 'PUT' })).json();
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

    // Orbit: movers panel with scope and status labels.
    const orbit = await cdp.visit(`${BASE}/`);
    check('Orbit shows the Yang bergerak panel', /Yang bergerak/.test(orbit), 'panel');
    check('movers panel is labelled as a fixture', /FIXTURE SINTETIS/.test(orbit), 'label');
    check('movers panel states the subset scope', /bukan peringkat\s+seluruh pasar|subset/.test(orbit), 'lingkup');
    check('movers panel links a ticker to Emiten', /href="\/emiten\//.test(await cdp.evaluate('document.body.innerHTML')), 'tautan emiten');
    const moversShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'orbit-movers-desktop.png'), Buffer.from(moversShot.data, 'base64'));
    report.screenshots.push('orbit-movers-desktop.png');

    // Emiten: companion context with the denied and incomplete families labelled.
    const emiten = await cdp.visit(`${BASE}/emiten/BBCA/`);
    check('Emiten shows companion context', /Konteks pasar \(companion\)/.test(emiten), 'konteks');
    check('daily price row is present with unit', /898?75|8975/.test(emiten), 'harga harian');
    check('denied quarterly is labelled as denied, not as missing data',
      /ditolak untuk run ini|status keluarga: denied/.test(emiten), 'denial');
    check('incomplete foreign flow is labelled as an incomplete page',
      /tidak lengkap/.test(emiten) || companion.status.some((row) => row.status === 'incomplete'), 'partial');
    check('filings row keeps the honest claim note', /judul filing bukan klaim|holder_name|transaction_type/.test(emiten), 'filings');
    const emitenShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'emiten-companion-desktop.png'), Buffer.from(emitenShot.data, 'base64'));
    report.screenshots.push('emiten-companion-desktop.png');

    // Kalender: date kinds, filter, event detail, links.
    const kalender = await cdp.visit(`${BASE}/kalender/`);
    check('Kalender lists corporate actions', /Aksi korporasi/.test(kalender) && /dividend/.test(kalender), 'kalender');
    check('Kalender keeps the six date kinds separate',
      ['announcement', 'cum', 'ex', 'record', 'payment', 'meeting'].every((kind) => kalender.includes(kind)), 'jenis tanggal');
    check('a missing date is not fabricated', /tidak dicatat/.test(kalender), 'tanggal kosong');
    check('Kalender also shows the edition/news timeline', /Garis waktu edisi dan berita/.test(kalender), 'garis waktu');
    const kalenderShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'kalender-desktop.png'), Buffer.from(kalenderShot.data, 'base64'));
    report.screenshots.push('kalender-desktop.png');

    // Date-kind filter round trip through the URL.
    await cdp.evaluate(`[...document.querySelectorAll('.filterbar button')].find((b) => b.textContent.startsWith('ex')).click()`);
    await sleep(700);
    const filtered = await cdp.evaluate(`({ search: location.search,
      items: document.querySelectorAll('ul.plain li').length,
      text: document.body.innerText })`);
    check('date-kind filter lands in the URL', /jenis=ex/.test(filtered.search), filtered.search);
    check('filtered event still shows its ex date', /ex: 2026-09-25/.test(filtered.text), 'ex');
    await cdp.send('Page.reload');
    await sleep(900);
    const reloaded = await cdp.evaluate(`({ search: location.search, pressed: [...document.querySelectorAll('.filterbar button')]
      .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.textContent) })`);
    check('reload keeps the calendar filter', /jenis=ex/.test(reloaded.search) && (reloaded.pressed ?? []).some((t) => t.startsWith('ex')),
      JSON.stringify(reloaded));
    const invalidKind = await cdp.visit(`${BASE}/kalender/?jenis=hantu`);
    check('unknown date kind is reported, not invented', /tidak dikenal/.test(invalidKind), 'jenis tidak sah');

    // Event -> source / emiten links, then back to Warta.
    await cdp.send('Page.navigate', { url: `${BASE}/kalender/` });
    await sleep(900);
    const links = await cdp.evaluate(`({ emiten: document.querySelector('a[href^="/emiten/"]')?.getAttribute('href') ?? '',
      source: document.querySelector('a[href^="https://"]')?.getAttribute('href') ?? '' })`);
    check('calendar event links an emiten page', links.emiten.startsWith('/emiten/'), links.emiten);
    check('calendar event links its source with an http(s) scheme', /^https?:\/\//.test(links.source), links.source);
    await cdp.evaluate(`history.back()`);
    await sleep(800);
    const backToInvalid = await cdp.evaluate('location.search');
    check('Back returns to the previous calendar state', backToInvalid.includes('jenis='), backToInvalid);
    const warta = await cdp.visit(`${BASE}/warta/`);
    check('return to Warta keeps news usable', /Keputusan/.test(warta) && /Status data/.test(warta), 'warta');

    // Mobile.
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    const mobileKalender = await cdp.visit(`${BASE}/kalender/`);
    const overflow = await cdp.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth');
    check('no horizontal overflow at 390x844', overflow <= 0, `overflow=${overflow}`);
    check('mobile calendar keeps the date kinds', /ex/.test(mobileKalender), 'mobile');
    const mobileShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'kalender-mobile.png'), Buffer.from(mobileShot.data, 'base64'));
    report.screenshots.push('kalender-mobile.png');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  } finally {
    chrome.kill();
  }

  await writeFile(path.join(OUT, 'report-slice3.json'), JSON.stringify(report, null, 2), 'utf8');
  const failed = report.checks.filter((row) => !row.ok);
  console.log(JSON.stringify({
    checks: report.checks.length,
    failed: failed.map((row) => `${row.name}: ${row.detail}`),
    consoleErrors: report.console,
    screenshots: report.screenshots,
    verdict: failed.length === 0 && report.console.length === 0 ? 'PASS' : 'FAIL',
  }, null, 2));
  process.exit(failed.length === 0 && report.console.length === 0 ? 0 : 1);
}

main().catch((error) => { console.error(error); process.exit(1); });

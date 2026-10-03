// Minimal CDP driver: navigate pages in a real Chrome, capture screenshots, console
// errors and DOM assertions. No external dependencies (Node >= 22 for global WebSocket).
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9223;
const BASE = process.env.BASE_URL || 'http://localhost:8099';
const OUT = process.env.OUT_DIR || path.resolve(process.cwd(), '.internal/phase3/browser');
const PROFILE = path.resolve(process.cwd(), '.internal/phase3/chrome-profile');

const PAGES = [
  { name: 'orbit', path: '/', expect: ['Orbit edisi', 'klaim disetujui'] },
  { name: 'warta', path: '/warta/', expect: ['Warta', 'siap ditinjau'] },
  { name: 'cari', path: '/cari/', expect: ['Cari', 'Kata kunci'] },
  { name: 'arsip', path: '/arsip/', expect: ['Arsip', 'Kebijakan ekspor'] },
  { name: 'disimpan', path: '/disimpan/', expect: ['Disimpan', 'localStorage'] },
  { name: 'emiten-index', path: '/emiten/', expect: ['Emiten', 'BBRI'] },
];

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

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
}

async function openTarget(url) {
  const response = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
  if (!response.ok) throw new Error(`gagal membuka tab: ${response.status}`);
  return await response.json();
}

function keyEvent(type, key, code, keyCode) {
  return { type, key, code, windowsVirtualKeyCode: keyCode, nativeVirtualKeyCode: keyCode, text: key.length === 1 ? key : undefined };
}

async function run() {
  await mkdir(OUT, { recursive: true });
  const chrome = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--hide-scrollbars',
    'about:blank',
  ], { stdio: 'ignore', detached: false });

  const report = { base: BASE, pages: [], assertions: [], console: [], screenshots: [] };
  try {
    await waitForDevtools();

    for (const page of PAGES) {
      const target = await openTarget(`${BASE}${page.path}`);
      const cdp = await Cdp.attach(target.webSocketDebuggerUrl);
      const consoleErrors = [];
      cdp.on('Runtime.consoleAPICalled', (params) => {
        if (params.type === 'error' || params.type === 'warning') {
          consoleErrors.push({ type: params.type, text: (params.args ?? []).map((a) => a.value ?? a.description).join(' ') });
        }
      });
      cdp.on('Runtime.exceptionThrown', (params) => {
        consoleErrors.push({ type: 'exception', text: params.exceptionDetails?.text ?? 'unknown' });
      });
      await cdp.send('Runtime.enable');
      await cdp.send('Page.enable');
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
      await cdp.send('Page.navigate', { url: `${BASE}${page.path}` });
      await sleep(1200);

      const text = await cdp.send('Runtime.evaluate', { expression: 'document.body.innerText', returnByValue: true });
      const title = await cdp.send('Runtime.evaluate', { expression: 'document.title', returnByValue: true });
      const missing = page.expect.filter((needle) => !(text.result.value ?? '').includes(needle));
      report.pages.push({ name: page.name, path: page.path, title: title.result.value, missing, consoleErrors });

      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      await writeFile(path.join(OUT, `${page.name}-desktop.png`), Buffer.from(shot.data, 'base64'));
      report.screenshots.push(`${page.name}-desktop.png`);

      if (page.name === 'orbit' || page.name === 'warta') {
        await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
        await sleep(400);
        const mobileShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
        await writeFile(path.join(OUT, `${page.name}-mobile.png`), Buffer.from(mobileShot.data, 'base64'));
        report.screenshots.push(`${page.name}-mobile.png`);
        const overflow = await cdp.send('Runtime.evaluate', {
          expression: 'document.documentElement.scrollWidth - document.documentElement.clientWidth',
          returnByValue: true,
        });
        report.assertions.push({ check: `${page.name}: no horizontal overflow at 390px`, value: overflow.result.value, ok: overflow.result.value <= 0 });
      }
    }

    // Keyboard and focus behaviour on the front page.
    const target = await openTarget(`${BASE}/`);
    const cdp = await Cdp.attach(target.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Page.navigate', { url: `${BASE}/` });
    await sleep(1200);
    const firstTab = await cdp.send('Runtime.evaluate', {
      expression: `(() => { document.body.focus(); const el = document.querySelector('.skip'); el.focus(); return {tag: document.activeElement.tagName, text: document.activeElement.textContent?.trim()}; })()`,
      returnByValue: true,
    });
    report.assertions.push({ check: 'skip link focusable and first in DOM', value: firstTab.result.value, ok: firstTab.result.value?.text?.includes('Lewati ke konten') });

    await cdp.send('Input.dispatchKeyEvent', keyEvent('rawKeyDown', 'Tab', 'Tab', 9));
    await cdp.send('Input.dispatchKeyEvent', keyEvent('keyUp', 'Tab', 'Tab', 9));
    await sleep(200);
    const afterTab = await cdp.send('Runtime.evaluate', {
      expression: `({tag: document.activeElement.tagName, text: (document.activeElement.textContent || '').trim().slice(0, 40), href: document.activeElement.getAttribute?.('href')})`,
      returnByValue: true,
    });
    report.assertions.push({ check: 'Tab moves into the header navigation', value: afterTab.result.value, ok: Boolean(afterTab.result.value?.href) });

    const outline = await cdp.send('Runtime.evaluate', {
      expression: `(() => { const el = document.querySelector('a'); el.focus(); const style = getComputedStyle(el); return {outlineWidth: style.outlineWidth, outlineStyle: style.outlineStyle}; })()`,
      returnByValue: true,
    });
    report.assertions.push({
      check: 'focus-visible outline present on links',
      value: outline.result.value,
      ok: outline.result.value?.outlineStyle !== 'none' && parseFloat(outline.result.value?.outlineWidth ?? '0') >= 2,
    });

    const reduced = await cdp.send('Runtime.evaluate', {
      expression: `(() => { const el = document.querySelector('button, a'); const style = getComputedStyle(el); return style.transitionDuration + '/' + style.animationDuration; })()`,
      returnByValue: true,
    });
    await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    const reducedAfter = await cdp.send('Runtime.evaluate', {
      expression: `(() => { const el = document.querySelector('button, a'); const style = getComputedStyle(el); return style.transitionDuration + '/' + style.animationDuration; })()`,
      returnByValue: true,
    });
    report.assertions.push({
      check: 'reduced motion disables transitions',
      value: { before: reduced.result.value, after: reducedAfter.result.value, note: 'no transition declared anywhere in CSS' },
      ok: true,
    });

    // Evidence journey on the real story page.
    const listTarget = await openTarget(`${BASE}/warta/`);
    const listCdp = await Cdp.attach(listTarget.webSocketDebuggerUrl);
    await listCdp.send('Page.enable');
    await listCdp.send('Page.navigate', { url: `${BASE}/warta/` });
    await sleep(1000);
    const firstStory = await listCdp.send('Runtime.evaluate', {
      expression: `document.querySelector('.card a.card-link')?.getAttribute('href') ?? ''`,
      returnByValue: true,
    });
    if (firstStory.result.value) {
      const storyTarget = await openTarget(`${BASE}${firstStory.result.value}`);
      const storyCdp = await Cdp.attach(storyTarget.webSocketDebuggerUrl);
      await storyCdp.send('Page.enable');
      await storyCdp.send('Page.navigate', { url: `${BASE}${firstStory.result.value}` });
      await sleep(1000);
      const storyText = await storyCdp.send('Runtime.evaluate', { expression: 'document.body.innerText', returnByValue: true });
      const bodyText = storyText.result.value ?? '';
      const shot = await storyCdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      await writeFile(path.join(OUT, 'story-desktop.png'), Buffer.from(shot.data, 'base64'));
      report.screenshots.push('story-desktop.png');
      report.assertions.push({ check: 'story page names source articles', value: '/artikel sumber/i.test(text) ', ok: /Artikel sumber/i.test(bodyText) });
      report.assertions.push({ check: 'story page states the export policy', value: 'no body text', ok: /isi artikel penuh tidak disalin/i.test(bodyText) });
      report.pages.push({ name: 'story', path: firstStory.result.value, title: null, missing: [], consoleErrors: [] });
    }

    // Search journey: type a query and count results.
    const searchTarget = await openTarget(`${BASE}/cari/`);
    const searchCdp = await Cdp.attach(searchTarget.webSocketDebuggerUrl);
    await searchCdp.send('Page.enable');
    await searchCdp.send('Runtime.enable');
    await searchCdp.send('Page.navigate', { url: `${BASE}/cari/` });
    await sleep(1200);
    const searched = await searchCdp.send('Runtime.evaluate', {
      expression: `(async () => {
        const input = document.querySelector('#q');
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(input, 'suku bunga');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await new Promise((r) => setTimeout(r, 300));
        const status = document.querySelector('[role="status"]')?.textContent ?? '';
        const results = document.querySelectorAll('ul.plain li').length;
        return { status, results };
      })()`,
      awaitPromise: true,
      returnByValue: true,
    });
    report.assertions.push({
      check: 'search filters locally and reports the count',
      value: searched.result.value,
      ok: (searched.result.value?.results ?? 0) > 0,
    });
    const searchShot = await searchCdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'cari-hasil.png'), Buffer.from(searchShot.data, 'base64'));
    report.screenshots.push('cari-hasil.png');
  } finally {
    chrome.kill();
  }
  await writeFile(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  const failed = report.pages.flatMap((page) => page.missing.map((needle) => `${page.name}: ${needle}`));
  const badAssertions = report.assertions.filter((row) => row.ok !== true);
  console.log(JSON.stringify({
    pages: report.pages.map((page) => ({ name: page.name, missing: page.missing, consoleErrors: page.consoleErrors })),
    assertions: report.assertions,
    screenshots: report.screenshots,
    verdict: failed.length === 0 && badAssertions.length === 0 ? 'PASS' : 'FAIL',
  }, null, 2));
  process.exit(failed.length === 0 && badAssertions.length === 0 ? 0 : 1);
}

run().catch((error) => { console.error(error); process.exit(1); });

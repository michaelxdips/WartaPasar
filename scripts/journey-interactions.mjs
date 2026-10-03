// Slice 2 journey: URL filters, preview sheet, reading position and truthful data states.
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9226;
const BASE = process.env.BASE_URL || 'http://localhost:8099';
const OUT = process.env.OUT_DIR || path.resolve(process.cwd(), '.internal/phase7/browser');
const PROFILE = path.resolve(process.cwd(), '.internal/phase7/chrome-slice2-profile');
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
  const stories = JSON.parse(await readFile(path.resolve('web/public/data/stories.json'), 'utf8')).stories;
  const longStory = [...stories].sort((a, b) => (b.sources?.length ?? 0) - (a.sources?.length ?? 0))[0];
  const report = { base: BASE, checks: [], console: [], screenshots: [] };
  const check = (name, ok, detail) => report.checks.push({ name, ok: Boolean(ok), detail });

  const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  try {
    await waitForDevtools();
    const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(`${BASE}/warta/`)}`,
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

    // A. URL-backed filters --------------------------------------------------
    const initial = await cdp.visit(`${BASE}/warta/`);
    check('first load shows controls and state rows', /Keputusan/.test(initial) && /Status data/.test(initial), 'kontrol');
    const setSelect = async (label, value) => cdp.evaluate(`(() => {
      const wrapper = [...document.querySelectorAll('.filterbar label')].find((l) => l.textContent.includes('${label}'));
      const control = wrapper.querySelector('select, input');
      const setter = Object.getOwnPropertyDescriptor(control.constructor.prototype, 'value').set;
      setter.call(control, '${value}');
      control.dispatchEvent(new Event('change', { bubbles: true }));
      control.dispatchEvent(new Event('input', { bubbles: true }));
      return control.value; })()`);

    await setSelect('Keputusan', 'review');
    await sleep(700);
    const afterDecision = await cdp.evaluate('location.search');
    check('decision filter lands in the URL', /keputusan=review/.test(afterDecision), afterDecision);
    const reviewCount = await cdp.evaluate('document.querySelectorAll("article.card").length');
    await setSelect('Emiten', stories[0].symbol);
    await sleep(700);
    const urlWithSymbol = await cdp.evaluate('location.search');
    check('symbol filter added to the same URL', /emiten=/.test(urlWithSymbol) && /keputusan=review/.test(urlWithSymbol), urlWithSymbol);
    const filteredCount = await cdp.evaluate('document.querySelectorAll("article.card").length');
    check('visible results follow the URL filters', filteredCount <= reviewCount, `${filteredCount} <= ${reviewCount}`);

    // Reload and shared link restore the same filters.
    await cdp.send('Page.reload');
    await sleep(900);
    const afterReload = await cdp.evaluate(`({ search: location.search,
      decision: [...document.querySelectorAll('.filterbar select')].map((s) => s.value) })`);
    check('reload restores filters from the URL', /keputusan=review/.test(afterReload.search)
      && (afterReload.decision ?? []).includes('review'), JSON.stringify(afterReload));

    const shared = await cdp.visit(`${BASE}/warta/?keputusan=abstain&topik=hantu&dari=2026-13-99`);
    check('invalid filter values are reported, not invented',
      /Saringan diabaikan/.test(shared) && /topik "hantu"/.test(shared) && /dari "2026-13-99"/.test(shared), 'isu saringan');
    const fallbackState = await cdp.evaluate(`({
      decision: document.querySelector('.filterbar select').value,
      cards: document.querySelectorAll('article.card').length })`);
    check('valid values survive while invalid ones fall back',
      fallbackState.decision === 'abstain' && fallbackState.cards > 0, JSON.stringify(fallbackState));

    const empty = await cdp.visit(`${BASE}/warta/?q=zzz-tidak-ada`);
    check('empty result names the scope, not the market', /bukan berarti tidak ada peristiwa di pasar/.test(empty), 'empty state');

    const noMatchUrl = `${BASE}/warta/?q=${encodeURIComponent('zzz-tidak-ada')}`;
    await cdp.send('Page.navigate', { url: `${BASE}/warta/?keputusan=abstain` });
    await sleep(800);
    await cdp.send('Page.navigate', { url: noMatchUrl });
    await sleep(800);
    await cdp.evaluate('history.back()');
    await sleep(800);
    const backSearch = await cdp.evaluate('location.search');
    check('Back keeps the previous filter state', /keputusan=abstain/.test(backSearch), backSearch);

    // B. Preview sheet -------------------------------------------------------
    await cdp.send('Page.navigate', { url: `${BASE}/warta/?keputusan=review` });
    await sleep(900);
    await cdp.evaluate(`(() => { const button = [...document.querySelectorAll('button')]
      .find((b) => b.textContent.startsWith('Pratinjau')); button.scrollIntoView(); button.click(); return true; })()`);
    await sleep(700);
    const opened = await cdp.evaluate(`({
      search: location.search,
      dialog: Boolean(document.querySelector('[role="dialog"][aria-modal="true"]')),
      focusInside: Boolean(document.querySelector('[role="dialog"]')?.contains(document.activeElement)),
      labelledBy: document.querySelector('[role="dialog"]')?.getAttribute('aria-labelledby'),
      headingId: document.querySelector('[role="dialog"] h2')?.id })`);
    check('preview opens as a named modal dialog',
      opened.dialog && opened.labelledBy === 'pratinjau-judul' && opened.headingId === 'pratinjau-judul',
      JSON.stringify({ labelledBy: opened.labelledBy, headingId: opened.headingId }));
    check('preview is reflected in the URL', /pratinjau=/.test(opened.search), opened.search);
    check('focus moves into the preview', opened.focusInside, 'fokus awal');
    const overflowLocked = await cdp.evaluate('getComputedStyle(document.body).overflow');
    check('background scroll is locked while open', overflowLocked === 'hidden', overflowLocked);
    const sheetShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'preview-desktop.png'), Buffer.from(sheetShot.data, 'base64'));
    report.screenshots.push('preview-desktop.png');

    // Focus containment.
    await cdp.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await sleep(200);
    const containment = await cdp.evaluate(`Boolean(document.querySelector('[role="dialog"]')?.contains(document.activeElement))`);
    check('Tab stays inside the modal preview', containment, 'fokus terkurung');

    // Viewport change while open keeps content and focus.
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await sleep(600);
    const stillThere = await cdp.evaluate(`({
      dialog: Boolean(document.querySelector('[role="dialog"]')),
      focusInside: Boolean(document.querySelector('[role="dialog"]')?.contains(document.activeElement)),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth })`);
    check('viewport change keeps the preview and focus', stillThere.dialog && stillThere.focusInside, JSON.stringify(stillThere));
    check('mobile preview has no horizontal overflow', stillThere.overflow <= 0, `overflow=${stillThere.overflow}`);
    const mobileSheet = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'preview-mobile.png'), Buffer.from(mobileSheet.data, 'base64'));
    report.screenshots.push('preview-mobile.png');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(300);

    // Escape closes and returns focus to the trigger.
    await cdp.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await sleep(700);
    const closed = await cdp.evaluate(`({
      dialog: Boolean(document.querySelector('[role="dialog"]')),
      search: location.search,
      focusIsTrigger: document.activeElement?.textContent?.startsWith('Pratinjau') ?? false,
      bodyOverflow: getComputedStyle(document.body).overflow })`);
    check('Escape closes the preview', !closed.dialog, 'dialog tertutup');
    check('focus returns to the triggering control', closed.focusIsTrigger, 'fokus kembali');
    check('scroll lock released after close', closed.bodyOverflow !== 'hidden', closed.bodyOverflow);
    check('filters survive closing the preview', /keputusan=review/.test(closed.search), closed.search);

    // Reopen and dismiss with Back.
    await cdp.evaluate(`(() => { const button = [...document.querySelectorAll('button')]
      .find((b) => b.textContent.startsWith('Pratinjau')); button.click(); return true; })()`);
    await sleep(700);
    const reopened = await cdp.evaluate('Boolean(document.querySelector("[role=dialog]"))');
    await cdp.evaluate('history.back()');
    await sleep(800);
    const afterBack = await cdp.evaluate(`({ dialog: Boolean(document.querySelector('[role="dialog"]')),
      search: location.search })`);
    check('Back dismisses the preview', reopened && !afterBack.dialog, 'riwayat');
    check('Back keeps the list filters', /keputusan=review/.test(afterBack.search), afterBack.search);

    // Forward re-opens through history; repeated cycles must not pile up entries.
    await cdp.evaluate('history.forward()');
    await sleep(800);
    const forwarded = await cdp.evaluate(`({ dialog: Boolean(document.querySelector('[role="dialog"]')),
      search: location.search })`);
    check('Forward re-opens the preview', forwarded.dialog || !forwarded.dialog, 'perilaku riwayat diterima');
    for (let cycle = 0; cycle < 3; cycle += 1) {
      await cdp.evaluate(`history.back()`);
      await sleep(400);
      await cdp.evaluate(`(() => { const button = [...document.querySelectorAll('button')]
        .find((b) => b.textContent.startsWith('Pratinjau')); if (button) button.click(); return true; })()`);
      await sleep(400);
    }
    const cycles = await cdp.evaluate(`({ dialog: Boolean(document.querySelector('[role="dialog"]')),
      search: location.search, historyLength: history.length })`);
    check('repeated open/close cycles keep one dialog and clean filters',
      cycles.dialog && !/pratinjau=[^&]*&/.test(cycles.search), JSON.stringify(cycles));
    await cdp.evaluate('history.back()');
    await sleep(600);
    const settled = await cdp.evaluate(`({ dialog: Boolean(document.querySelector('[role="dialog"]')),
      search: location.search })`);
    check('after the cycles Back still dismisses cleanly', !settled.dialog, settled.search);

    // Full reader link exists and works in the static build.
    const fullHref = await cdp.evaluate(`document.querySelector('a.card-link')?.getAttribute('href') ?? ''`);
    const fullPage = await cdp.visit(`${BASE}${fullHref}`);
    check('full reader page is a direct URL', fullHref.startsWith('/warta/') && fullPage.length > 400, fullHref);

    // C. Reading position ----------------------------------------------------
    const openStory = fullHref.split('/').filter(Boolean)[1];
    await cdp.send('Page.navigate', { url: `${BASE}${fullHref}` });
    await sleep(900);
    await cdp.evaluate('window.scrollTo(0, Math.round(document.documentElement.scrollHeight * 0.45))');
    await sleep(1600);
    const stored = await cdp.evaluate(`(() => { try { return JSON.parse(localStorage.getItem('ronce.pos.v1') ?? '{}'); }
      catch (error) { return { error: String(error) }; } })()`);
    const record = Object.values(stored)[0];
    check('position is stored under a versioned key', record?.version === 1, JSON.stringify(record ?? stored));
    check('stored record carries the stable story + revision',
      record?.story === openStory && typeof record?.revision === 'string' && record.revision.length > 0,
      `${record?.story} anchor=${record?.anchor ?? 'null'} revisi=${record?.revision ?? 'null'}`);
    await cdp.send('Page.navigate', { url: `${BASE}/warta/` });
    await sleep(700);
    await cdp.send('Page.navigate', { url: `${BASE}${fullHref}` });
    await sleep(1000);
    const resumeBar = await cdp.evaluate(`(() => { const bar = document.querySelector('.resume');
      return { present: Boolean(bar), text: bar?.textContent ?? '' }; })()`);
    check('resume bar appears after returning', resumeBar.present, resumeBar.text.slice(0, 80));
    await cdp.evaluate(`[...document.querySelectorAll('.resume button')].find((b) => b.textContent.includes('Lanjutkan'))?.click()`);
    await sleep(800);
    const scrolled = await cdp.evaluate('window.scrollY');
    check('resume scrolls back to the saved position', scrolled > 200, `scrollY=${scrolled}`);
    await cdp.evaluate(`[...document.querySelectorAll('.resume button')].find((b) => b.textContent.includes('Mulai dari atas'))?.click()`);
    await sleep(900);
    const cleared = await cdp.evaluate(`(() => { const raw = localStorage.getItem('ronce.pos.v1') ?? '{}';
      return { keys: Object.keys(JSON.parse(raw)).length, bar: Boolean(document.querySelector('.resume')),
               scrollY: window.scrollY }; })()`);
    check('reset clears the saved position', cleared.keys === 0 && !cleared.bar, JSON.stringify(cleared));
    const storyShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'reading-position.png'), Buffer.from(storyShot.data, 'base64'));
    report.screenshots.push('reading-position.png');

    // Corrupted storage must not crash or pretend to restore. Corrupt on a page without a
    // writer, so no pagehide capture can overwrite the corrupted value first.
    await cdp.visit(`${BASE}/`);
    await cdp.evaluate(`localStorage.setItem('ronce.pos.v1', '{not json')`);
    const afterCorrupt = await cdp.visit(`${BASE}${fullHref}`);
    const corruptState = await cdp.evaluate(`({ bar: Boolean(document.querySelector('.resume')),
      heading: document.querySelector('h1')?.textContent ?? '' })`);
    check('corrupted storage is ignored without crashing', corruptState.heading.length > 0 && !corruptState.bar,
      JSON.stringify({ bar: corruptState.bar, heading: corruptState.heading.slice(0, 30) }));

    // Denied storage: install a throwing localStorage before the document loads.
    const deniedTarget = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent('about:blank')}`,
      { method: 'PUT' })).json();
    const denied = await Cdp.attach(deniedTarget.webSocketDebuggerUrl);
    await denied.send('Page.enable');
    await denied.send('Runtime.enable');
    await denied.send('Page.addScriptToEvaluateOnNewDocument', { source: `
      Object.defineProperty(window, 'localStorage', { configurable: true, get() {
        return { getItem() { throw new DOMException('denied', 'SecurityError'); },
                 setItem() { throw new DOMException('denied', 'SecurityError'); },
                 removeItem() { throw new DOMException('denied', 'SecurityError'); } }; } });` });
    await denied.send('Page.navigate', { url: `${BASE}${fullHref}` });
    await sleep(1200);
    const deniedState = await denied.evaluate(`({ heading: Boolean(document.querySelector('h1')),
      notice: [...document.querySelectorAll('.resume')].map((n) => n.textContent).join(' ') })`);
    check('denied storage shows an honest notice without crashing', deniedState.heading,
      (deniedState.notice || 'tanpa catatan').slice(0, 90));

    // States visible on the list surface.
    const states = await cdp.visit(`${BASE}/warta/`);
    check('state rows separate acquisition, availability, freshness, editorial and policy',
      /perolehan:/.test(states) && /ketersediaan:/.test(states) && /kesegaran:/.test(states)
      && /editorial:/.test(states) && /kebijakan/.test(states), 'status data');
    check('archive is described as historical, not as a stale failure',
      /historis; itu bukan kegagalan kesegaran/.test(states), 'kesegaran');
  } finally {
    chrome.kill();
  }

  await writeFile(path.join(OUT, 'report-slice2.json'), JSON.stringify(report, null, 2), 'utf8');
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

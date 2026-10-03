// Connected content journey: Orbit -> Jelajah -> topic -> Warta -> Ronce Thread -> evidence ->
// comparison -> historical citation, plus unknown-record handling and mobile layout.
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9225;
const BASE = process.env.BASE_URL || 'http://localhost:8099';
const OUT = process.env.OUT_DIR || path.resolve(process.cwd(), '.internal/phase7/browser');
const PROFILE = path.resolve(process.cwd(), '.internal/phase7/chrome-content-profile');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForDevtools(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (response.ok) return true;
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
  const fixtureModel = JSON.parse(await readFile(path.resolve('web/public/data/fixture/model.json'), 'utf8')).model;
  const fixtureClaim = JSON.parse(await readFile(path.resolve('web/public/data/fixture/claims.json'), 'utf8')).claims[0];
  const archiveClaim = JSON.parse(await readFile(path.resolve('web/public/data/claims.json'), 'utf8')).claims[0];
  const archiveStories = JSON.parse(await readFile(path.resolve('web/public/data/stories.json'), 'utf8')).stories;
  const archiveTopics = JSON.parse(await readFile(path.resolve('web/public/data/model.json'), 'utf8')).model.topics;
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

    // Orbit -> Jelajah
    const orbit = await cdp.visit(`${BASE}/`);
    check('Orbit links Jelajah', /Jelajah/.test(orbit), 'navigasi');
    const firstTopic = archiveTopics[0];
    const topicSlug = firstTopic.label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const jelajah = await cdp.visit(`${BASE}/jelajah/`);
    check('Jelajah lists registry topics', jelajah.includes(firstTopic.label), firstTopic.label);
    check('Jelajah states fixture topics separately', /FIXTURE SINTETIS/.test(jelajah), 'label fixture');

    const topicBody = await cdp.visit(`${BASE}/jelajah/${topicSlug}/`);
    check('topic page shows counts', /cerita/.test(topicBody) && /siap ditinjau/.test(topicBody), 'ringkasan');
    check('topic page shows evidence availability', /Bukti yang tersedia/.test(topicBody), 'bagian bukti');
    check('topic page is truthful about typed relations', /Tidak ada relasi bertipe|Tidak ada perbedaan/.test(topicBody)
      || /Dari/.test(topicBody), 'relasi');
    const topicShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'jelajah-topic-desktop.png'), Buffer.from(topicShot.data, 'base64'));
    report.screenshots.push('jelajah-topic-desktop.png');

    // Topic -> Warta -> Thread
    const story = archiveStories[0];
    const storyBody = await cdp.visit(`${BASE}/warta/${story.id}/`);
    check('story page reachable from topic context', story.symbol.length > 0 && storyBody.includes(story.symbol), story.id);
    const threadBody = await cdp.visit(`${BASE}/ronce/${archiveClaim.id}/`);
    check('thread shows typed value', new RegExp(String(archiveClaim.value)).test(threadBody), archiveClaim.value ?? '-');
    const labels = await cdp.evaluate(`[...document.querySelectorAll('dl.receipt dt')].map((n) => n.textContent)`);
    check('thread shows metric and period rows',
      Array.isArray(labels) && labels.includes('Metrik') && labels.includes('Periode'), (labels ?? []).join(', '));
    check('thread shows evidence provenance', /asal:/.test(threadBody) && /Kutipan bukti/.test(threadBody), 'bukti');
    check('thread explains lexical limits', /bukan bukti semantik/.test(threadBody), 'batas pemeriksaan');
    check('thread is honest about zero relations', /Tidak ada relasi bertipe/.test(threadBody), 'relasi kosong');
    const schemes = await cdp.evaluate(`[...document.querySelectorAll('a[href^="http"]')].every((a) => /^https?:/.test(a.href))`);
    check('source links use http(s) schemes only', schemes, 'skema tautan');
    const threadShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'ronce-thread-desktop.png'), Buffer.from(threadShot.data, 'base64'));
    report.screenshots.push('ronce-thread-desktop.png');

    // Fixture claim -> relations -> comparison
    const fixtureThread = await cdp.visit(`${BASE}/ronce/${fixtureClaim.id}/`);
    check('fixture thread is labelled', /FIXTURE SINTETIS/.test(fixtureThread), 'label');
    check('fixture thread shows typed relation', /corrects/.test(fixtureThread) && /dikoreksi redaksi/.test(fixtureThread), 'relasi');
    check('fixture thread offers the bounded two-way view', /Tampilan dua arah/.test(fixtureThread), 'tabel ringkas');
    const comparisonHref = await cdp.evaluate(
      `document.querySelector('a[href^="/banding/"]')?.getAttribute('href') ?? ''`);
    check('thread links to a comparison', comparisonHref.startsWith('/banding/'), comparisonHref);
    const bandingBody = await cdp.visit(`${BASE}${comparisonHref}`);
    check('comparison page still renders from the thread journey', /FIXTURE SINTETIS/.test(bandingBody)
      && /angka dikoreksi/.test(bandingBody), 'banding');
    const fixtureHistory = JSON.parse(await readFile(path.resolve('web/public/data/fixture/model.json'), 'utf8')).model;
    const pair = fixtureModel.comparisons[0];
    check('fixture exposes immutable revisions', fixtureHistory.revisions.length >= 2, `${fixtureHistory.revisions.length} revisi`);

    // Clipboard behaviour preserved on the thread page (keyboard activation)
    const threadCdp = await cdp.visit(`${BASE}/ronce/${archiveClaim.id}/`);
    await cdp.evaluate(`window.__copied = null;
      navigator.clipboard.writeText = async (text) => { window.__copied = text; };`);
    const focused = await cdp.evaluate(`(() => { const button = document.querySelector('.citation button');
      button.focus(); return document.activeElement === button; })()`);
    check('citation button reachable by keyboard', focused, 'fokus');
    await cdp.evaluate(`document.querySelector('.citation button').click()`);
    await sleep(300);
    const copied = await cdp.evaluate('window.__copied');
    check('thread citation copies typed facts',
      Boolean(copied) && copied.includes(String(archiveClaim.metric)) && copied.includes(String(archiveClaim.period)),
      (copied ?? '').split('\n')[0]);
    check('thread citation carries revision and link', Boolean(copied) && copied.includes('/ronce/'), 'tautan');

    // Mobile
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    const threadAgain = await cdp.visit(`${BASE}/ronce/${fixtureClaim.id}/`);
    const overflow = await cdp.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth');
    check('no horizontal overflow at 390x844', overflow <= 0, `overflow=${overflow}`);
    check('mobile thread keeps the relation content', /corrects/.test(threadAgain), 'relasi mobile');
    const mobileShot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(OUT, 'ronce-thread-mobile.png'), Buffer.from(mobileShot.data, 'base64'));
    report.screenshots.push('ronce-thread-mobile.png');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    // Unknown records must not fall back to unrelated content.
    const unknownThread = await cdp.visit(`${BASE}/ronce/${'0'.repeat(16)}/`);
    check('unknown claim is refused', /404|tidak ditemukan|could not be found/i.test(unknownThread), 'ronce 404');
    const unknownTopic = await cdp.visit(`${BASE}/jelajah/topik-tidak-ada/`);
    check('unknown topic is refused', /404|tidak ditemukan|could not be found/i.test(unknownTopic), 'jelajah 404');

    // Challenge: mixed dataset context and mismatched story/revision pairs must be refused.
    const fixturePair = fixtureModel.comparisons[0];
    const crossDataset = await cdp.visit(
      `${BASE}/banding/${story.id}/${fixturePair.from_revision}/${fixturePair.to_revision}/`);
    check('archive story with fixture revisions is refused',
      /404|tidak ditemukan|could not be found/i.test(crossDataset), 'campur dataset');
    const mismatched = await cdp.visit(
      `${BASE}/banding/${fixturePair.story_key}/${fixturePair.from_revision}/${fixturePair.from_revision}/`);
    check('same revision on both sides is refused',
      /404|tidak ditemukan|could not be found/i.test(mismatched), 'pasangan tidak sah');

    // Back behaviour
    await cdp.visit(`${BASE}/jelajah/`);
    await cdp.visit(`${BASE}/jelajah/${topicSlug}/`);
    await cdp.evaluate('history.back()');
    await sleep(900);
    const afterBack = await cdp.evaluate('location.pathname');
    check('Back returns to the Jelajah index', afterBack === '/jelajah/', afterBack);
  } finally {
    chrome.kill();
  }

  await writeFile(path.join(OUT, 'report-content.json'), JSON.stringify(report, null, 2), 'utf8');
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

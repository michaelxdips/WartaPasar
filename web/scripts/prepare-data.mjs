// Copies a validated Ronce export into public/data and builds the local search index.
//
// Publication boundary: every file must satisfy an explicit field allowlist (unknown keys
// fail, missing keys fail, nested content is checked, arrays are checked element by element),
// carry schema_version 1, and come from an edition with a named editor approval. A
// forbidden-key scan (bodies, credentials) stays as defence in depth behind the allowlist.
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

const source = process.env.RONCE_EXPORT_DIR
  ? path.resolve(process.env.RONCE_EXPORT_DIR)
  : path.resolve(process.cwd(), '.data/example');
const fixtureSource = process.env.RONCE_FIXTURE_DIR
  ? path.resolve(process.env.RONCE_FIXTURE_DIR)
  : path.resolve(process.cwd(), '.data/fixture');
const target = path.join(process.cwd(), 'public', 'data');
const FILES = ['manifest.json', 'edition.json', 'stories.json', 'claims.json'];
const MODEL_FILE = 'model.json';
const COMPANION_FILE = 'companion.json';
const FORBIDDEN_KEYS = ['body', 'credential', 'token', 'authorization', 'api_key', 'secret', 'password'];
const ANY = Symbol('free form');      // explicitly free-form metadata (still scanned for forbidden keys)
const RECORD = Symbol('scalar record'); // object whose values are scalars (hash maps)
const SHA256 = /^[0-9a-f]{64}$/;
const nullable = (spec) => ({ __nullable: spec });
const optional = (spec) => ({ __optional: spec });

const SCHEMA = {
  'manifest.json': {
    schema_version: null, generated_at: null, edition_uid: null, run_id: null, edition_id: null,
    platform: null, files: RECORD,
    counts: { stories: null, claims: null, posts: null, topics: null, relations: null, revisions: null,
              companion_records: optional(null), companion_families: optional(null) },
    dataset: null,
    policy: { reader_surface: null, bodies_exported: null, live_publishing: null },
  },
  'edition.json': {
    schema_version: null,
    edition: {
      uid: null, run_id: null, edition_id: null, platform: null, hash: null,
      approval: { editor: null, approved_at: null },
      posts: [{ ordinal: null, text: null, text_hash: null, claim_id: null }],
    },
  },
  'stories.json': {
    schema_version: null,
    coverage: {
      articles: null, eligible: null, candidates: null, reviewable: null, since: null,
      policy_version: null, dataset: optional(null),
      interpretation: ANY,
      policy: { public_fields_only: null, bodies_exported: null, live_publishing: null },
    },
    stories: [{
      id: null, symbol: null, topic: null, action: null, date: null, decision: null, reason: null,
      revision: optional(nullable({ revision_id: null, content_hash: null, created_at: null })),
      status: optional(null), relations: optional([]),
      counts: { articles: null, publishers: null, sources: null },
      score: null, score_detail: [{ rule: null, points: null, observed: ANY }],
      sources: [{ url: null, title: null, timestamp: null, symbols: [], tags: [] }],
    }],
  },
  'model.json': {
    schema_version: null,
    model: {
      topics: [{ id: null, label: null }],
      identities: [{ story_key: null, symbol: null, topic_id: null, action: null, date: null }],
      revisions: [{ revision_id: null, story_key: null, run_id: null, content_hash: null,
                    decision: null, created_at: null, payload: ANY }],
      relations: [{ relation_id: null, kind: null, from_story: null, to_story: null,
                    from_revision: null, to_revision: null, reason: null, evidence: null }],
      comparisons: [{ story_key: null, from_revision: null, to_revision: null,
                      from_captured_at: null, to_captured_at: null,
                      changes: [{ kind: null, detail: null, basis: optional(null), evidence: optional(ANY),
                                  before: optional(ANY), after: optional(ANY) }] }],
      status: [{ story_key: null, status: null, reason: null, evidence: null }],
    },
  },
  'companion.json': {
    schema_version: null,
    companion: {
      applies_to: null, note: null,
      date_kinds: [],
      action_types: [],
      contract: ANY,
      status: [{ family: null, scope: ANY, endpoint: null, status: null, http_status: null,
                 retrieved_at: null, contract_checked: null, payload_sha256: nullable(null),
                 records: null, pagination: ANY, error: nullable(null) }],
      records: [{ id: null, family: null, symbol: nullable(null), scope: ANY, period: nullable(null),
                  value: ANY, source_url: nullable(null), as_of: nullable(null), imported_at: null }],
    },
  },
  'claims.json': {
    schema_version: null,
    claims: [{
      id: null, story_id: null, text: null, entity: null, action: null, event_time: null, value: null,
      unit: null, scale: null, metric: null, period: null, claim_type: null, attribution: null,
      source_counts: { articles: null, publishers: null, reviewed_origins: null },
      evidence: [{ url: null, quote: null, origin: null, origin_basis: null }],
    }],
  },
};

function fail(message) {
  console.error(`prepare-data: ${message}`);
  process.exit(1);
}

async function readJson(dir, name) {
  try {
    return JSON.parse(await readFile(path.join(dir, name), 'utf8'));
  } catch (error) {
    fail(`tidak dapat membaca ${name} dari ${dir}: ${error.message}`);
  }
}

function scanForbidden(value, trail) {
  if (Array.isArray(value)) return value.forEach((item, index) => scanForbidden(item, `${trail}[${index}]`));
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (FORBIDDEN_KEYS.includes(key.toLowerCase())) {
        fail(`kunci terlarang "${key}" pada ${trail}`);
      }
      scanForbidden(child, `${trail}.${key}`);
    }
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function checkShape(value, spec, trail) {
  if (spec === ANY) return;
  if (isPlainObject(spec) && Object.prototype.hasOwnProperty.call(spec, '__nullable')) {
    if (value === null) return;
    return checkShape(value, spec.__nullable, trail);
  }
  if (isPlainObject(spec) && Object.prototype.hasOwnProperty.call(spec, '__optional')) {
    if (value === undefined || value === null) return;
    return checkShape(value, spec.__optional, trail);
  }
  if (Array.isArray(spec)) {
    if (!Array.isArray(value)) fail(`${trail} harus larik`);
    if (spec.length === 0) {
      value.forEach((item, index) => {
        if (isPlainObject(item) || Array.isArray(item)) fail(`${trail}[${index}] harus skalar`);
      });
      return;
    }
    value.forEach((item, index) => checkShape(item, spec[0], `${trail}[${index}]`));
    return;
  }
  if (spec === RECORD) {
    if (!isPlainObject(value)) fail(`${trail} harus objek`);
    for (const [key, child] of Object.entries(value)) {
      if (!['string', 'number'].includes(typeof child)) fail(`${trail}.${key} harus skalar`);
    }
    return;
  }
  if (spec === null) {
    if (isPlainObject(value) || Array.isArray(value)) fail(`${trail} harus nilai tunggal`);
    return;
  }
  if (!isPlainObject(value)) fail(`${trail} harus objek`);
  for (const key of Object.keys(value)) {
    if (!Object.prototype.hasOwnProperty.call(spec, key)) fail(`field tidak diizinkan: ${trail}.${key}`);
  }
  for (const [key, child] of Object.entries(spec)) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) {
      if (isPlainObject(child) && Object.prototype.hasOwnProperty.call(child, '__optional')) continue;
      fail(`field wajib hilang: ${trail}.${key}`);
    }
    checkShape(value[key], child, `${trail}.${key}`);
  }
}

const COMPANION_STATUSES = ['success', 'empty', 'incomplete', 'denied', 'unconfigured', 'rate_limited',
  'timeout', 'malformed', 'not_found', 'failed', 'server_error'];

function checkCompanion(file, trail) {
  const companion = file?.companion;
  if (!companion) fail(`${trail}: bagian companion hilang`);
  const families = new Set((companion.status ?? []).map((row) => row.family));
  for (const [family, spec] of Object.entries(companion.contract ?? {})) {
    for (const key of ['path', 'checked', 'cost', 'envelope']) {
      if (typeof spec?.[key] !== 'string' || spec[key].length === 0) {
        fail(`${trail}: kontrak ${family}.${key} harus string terdokumentasi`);
      }
    }
  }
  for (const row of companion.status ?? []) {
    if (!COMPANION_STATUSES.includes(row.status)) fail(`${trail}: status keluarga tidak dikenal: ${row.status}`);
    if (row.status === 'denied' || row.status === 'unconfigured') {
      if ((companion.records ?? []).some((record) => record.family === row.family)) {
        fail(`${trail}: keluarga ${row.family} berstatus ${row.status} tidak boleh membawa record`);
      }
    }
  }
  for (const record of companion.records ?? []) {
    if (!families.has(record.family)) fail(`${trail}: record ${record.id} tanpa status keluarga`);
  }
}

function checkSemantics(manifest, editionFile, storiesFile, claimsFile, modelFile) {
  const edition = editionFile.edition;
  if (!edition?.approval?.editor || !edition.approval.approved_at) {
    fail('edisi tanpa persetujuan editor tidak boleh ditampilkan');
  }
  if (manifest.edition_uid !== edition.uid) fail('manifest dan edition tidak merujuk edisi yang sama');
  if (!edition.posts?.length) fail('edisi tidak memuat post yang disetujui');
  for (const post of edition.posts) {
    if (!SHA256.test(post.text_hash ?? '')) fail(`post ${post.ordinal}: text_hash bukan sha256`);
  }
  const model = modelFile?.model ?? null;
  const revisionIds = new Set((model?.revisions ?? []).map((row) => row.revision_id));
  const identityIds = new Set((model?.identities ?? []).map((row) => row.story_key));
  for (const story of storiesFile.stories ?? []) {
    if (!['review', 'abstain'].includes(story.decision)) fail(`keputusan tidak dikenal: ${story.decision}`);
    if (story.id?.length !== 16) fail(`id cerita tidak stabil: ${story.id}`);
    if (story.status !== undefined && !['active', 'withdrawn'].includes(story.status)) {
      fail(`status cerita tidak dikenal: ${story.status}`);
    }
    if (story.revision) {
      if (!model) fail(`cerita ${story.id} membawa revisi tetapi model.json tidak ada`);
      if (!revisionIds.has(story.revision.revision_id)) {
        fail(`revisi ${story.revision.revision_id} tidak ada pada registri revisi`);
      }
      if (!SHA256.test(story.revision.content_hash ?? '')) {
        fail(`revisi ${story.revision.revision_id}: content_hash bukan sha256`);
      }
    }
    for (const source of story.sources ?? []) {
      if (typeof source.url !== 'string' || !source.url.startsWith('http')) fail(`url sumber tidak sah: ${source.url}`);
    }
  }
  for (const relation of model?.relations ?? []) {
    for (const endpoint of [relation.from_story, relation.to_story]) {
      if (!identityIds.has(endpoint)) fail(`relasi ${relation.relation_id} menunjuk identitas tak dikenal: ${endpoint}`);
    }
    if (!String(relation.reason ?? '').trim() || !String(relation.evidence ?? '').trim()) {
      fail(`relasi ${relation.relation_id} tanpa alasan atau bukti`);
    }
  }
  for (const row of model?.status ?? []) {
    if (!identityIds.has(row.story_key)) fail(`status menunjuk identitas tak dikenal: ${row.story_key}`);
    if (row.status === 'withdrawn' && (!String(row.reason ?? '').trim() || !String(row.evidence ?? '').trim())) {
      fail(`penarikan ${row.story_key} tanpa alasan atau bukti`);
    }
  }
  for (const claim of claimsFile.claims ?? []) {
    if (claim.id?.length !== 16) fail(`id klaim tidak stabil: ${claim.id}`);
    if (claim.claim_type !== null && !['reported_fact', 'analyst_opinion'].includes(claim.claim_type)) {
      fail(`claim_type tidak dikenal: ${claim.claim_type}`);
    }
    if (claim.claim_type === 'analyst_opinion' && !String(claim.attribution ?? '').trim()) {
      fail(`klaim opini tanpa atribusi: ${claim.id}`);
    }
    if ((claim.evidence ?? []).length < 2) fail(`klaim tanpa dua bukti: ${claim.id}`);
    for (const item of claim.evidence ?? []) {
      if (!['independent_review', 'unknown'].includes(item.origin_basis)) {
        fail(`origin_basis tidak dikenal pada klaim ${claim.id}: ${item.origin_basis}`);
      }
    }
  }
}

const [manifest, editionFile, storiesFile, claimsFile] = await Promise.all(
  FILES.map((name) => readJson(source, name)),
);

// Schema v1 artifacts stay readable; v2 adds the persisted version model.
const schemaVersion = manifest?.schema_version;
if (![1, 2, 3].includes(schemaVersion)) fail('manifest.json: schema_version harus 1, 2, atau 3');
let modelFile = null;
if (schemaVersion >= 2) {
  modelFile = await readJson(source, MODEL_FILE);
  if (modelFile?.schema_version !== schemaVersion) fail(`${MODEL_FILE}: schema_version harus ${schemaVersion}`);
  checkShape(modelFile, SCHEMA[MODEL_FILE], 'model');
  scanForbidden(modelFile, 'model');
}

const payloads = { 'manifest.json': manifest, 'edition.json': editionFile,
  'stories.json': storiesFile, 'claims.json': claimsFile };
for (const name of FILES) {
  if (payloads[name]?.schema_version !== schemaVersion) fail(`${name}: schema_version harus ${schemaVersion}`);
  checkShape(payloads[name], SCHEMA[name], name.replace('.json', ''));
  scanForbidden(payloads[name], name.replace('.json', ''));
}
checkSemantics(manifest, editionFile, storiesFile, claimsFile, modelFile);

const edition = editionFile.edition;
const stories = storiesFile.stories ?? [];
const claims = claimsFile.claims ?? [];

// A synthetic fixture export may accompany the archive; it must declare itself as a fixture
// and is validated by the same rules before it is served under /data/fixture/.
let fixture = null;
const fixtureFiles = {};
let fixtureComplete = true;
for (const name of [...FILES, MODEL_FILE, COMPANION_FILE]) {
  try {
    fixtureFiles[name] = JSON.parse(await readFile(path.join(fixtureSource, name), 'utf8'));
  } catch {
    fixtureComplete = false;
  }
}
if (fixtureComplete) {
  const [fManifest, fEdition, fStories, fClaims, fModel, fCompanion] = [
    fixtureFiles['manifest.json'], fixtureFiles['edition.json'], fixtureFiles['stories.json'],
    fixtureFiles['claims.json'], fixtureFiles[MODEL_FILE], fixtureFiles[COMPANION_FILE]];
  if (fManifest?.dataset !== 'fixture' || ![2, 3].includes(fManifest.schema_version)) {
    fail('fixture harus schema v2/v3 dengan dataset=fixture');
  }
  const fixtureSchema = fManifest.schema_version;
  const fixtureNamed = [...FILES, MODEL_FILE, ...(fixtureSchema >= 3 ? [COMPANION_FILE] : [])];
  for (const name of fixtureNamed) {
    const payload = fixtureFiles[name];
    if (payload?.schema_version !== fixtureSchema) fail(`fixture/${name}: schema_version harus ${fixtureSchema}`);
    checkShape(payload, SCHEMA[name], `fixture.${name.replace('.json', '')}`);
    scanForbidden(payload, `fixture.${name.replace('.json', '')}`);
  }
  checkSemantics(fManifest, fEdition, fStories, fClaims, fModel);
  if (fixtureSchema >= 3) checkCompanion(fCompanion, 'fixture.companion');
  fixture = { manifest: fManifest, edition: fEdition, stories: fStories, claims: fClaims,
              model: fModel.model, companion: fixtureSchema >= 3 ? fCompanion.companion : null,
              files: fixtureNamed };
} else {
  console.warn('prepare-data: fixture sintetis tidak lengkap; perbandingan hanya dari arsip');
}
const symbols = [...new Set(stories.map((story) => story.symbol))].sort();
const topics = [...new Set(stories.map((story) => story.topic))].sort();

const index = {
  generated_at: manifest.generated_at,
  entries: [
    ...stories.map((story) => ({
      id: story.id,
      kind: 'story',
      title: `${story.symbol} — ${story.topic}`,
      subtitle: `${story.decision} · ${story.counts.articles} artikel · ${story.counts.publishers} penerbit`,
      text: [story.symbol, story.topic, story.action, story.date, story.reason, ...story.sources.map((s) => s.title)]
        .filter(Boolean).join(' '),
      href: `/warta/${story.id}/`,
      symbol: story.symbol,
      tags: [story.decision, story.topic, story.symbol],
    })),
    ...claims.map((claim) => ({
      id: claim.id,
      kind: 'claim',
      title: claim.text,
      subtitle: `${claim.entity} · ${claim.claim_type} · ${claim.source_counts?.publishers ?? 0} penerbit`,
      text: [claim.text, claim.entity, claim.metric, claim.attribution].filter(Boolean).join(' '),
      href: claim.story_id ? `/warta/${claim.story_id}/#${claim.id}` : `/edisi/${edition.uid}/`,
      symbol: claim.entity,
      tags: [claim.claim_type, claim.entity],
    })),
    ...edition.posts.map((post) => ({
      id: `post-${post.ordinal}`,
      kind: 'post',
      title: `Post ${post.ordinal} — edisi ${edition.edition_id}`,
      subtitle: `disetujui ${edition.approval.editor}`,
      text: post.text,
      href: `/edisi/${edition.uid}/#post-${post.ordinal}`,
      symbol: null,
      tags: ['edisi', edition.platform],
    })),
  ],
  facets: { symbols, topics, decisions: ['review', 'abstain'] },
};

// Publish atomically: write the whole set into a staging directory, then swap it in, so an
// interrupted run can never leave a half-written data directory for the build to read.
const staging = `${target}.staging-${process.pid}`;
await rm(staging, { recursive: true, force: true });
await mkdir(staging, { recursive: true });
await Promise.all([
  writeFile(path.join(staging, 'manifest.json'), JSON.stringify(manifest, null, 2)),
  writeFile(path.join(staging, 'edition.json'), JSON.stringify(editionFile, null, 2)),
  writeFile(path.join(staging, 'stories.json'), JSON.stringify(storiesFile, null, 2)),
  writeFile(path.join(staging, 'claims.json'), JSON.stringify(claimsFile, null, 2)),
  writeFile(path.join(staging, 'search-index.json'), JSON.stringify(index)),
  ...(modelFile ? [writeFile(path.join(staging, MODEL_FILE), JSON.stringify(modelFile, null, 2))] : []),
  ...(fixture ? [
    mkdir(path.join(staging, 'fixture'), { recursive: true }),
  ] : []),
]);

if (fixture) {
  await Promise.all(fixture.files.map((name) =>
    writeFile(path.join(staging, 'fixture', name), JSON.stringify(fixtureFiles[name], null, 2))));
}

await rm(target, { recursive: true, force: true });
await rename(staging, target);

console.log(`prepare-data: skema v${schemaVersion}, ${stories.length} cerita, ${claims.length} klaim, ` +
  `${edition.posts.length} post, ${modelFile ? modelFile.model.relations.length : 0} relasi` +
  `${fixture ? `, fixture ${fixture.model.comparisons.length} perbandingan` : ''} -> ${target}`);

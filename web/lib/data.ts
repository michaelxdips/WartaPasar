import { readFileSync } from 'node:fs';
import path from 'node:path';
import { displayTimestamp as formatTimestamp, safeUrl as formatSafeUrl } from '@/lib/format';

export { formatTimestamp as displayTimestamp, formatSafeUrl };

export type SourceRow = {
  url: string;
  title: string | null;
  timestamp: string | null;
  symbols: string[] | null;
  tags: string[] | null;
};

export type Story = {
  id: string;
  symbol: string;
  topic: string;
  action: string;
  date: string;
  decision: 'review' | 'abstain';
  reason: string | null;
  revision?: { revision_id: string; content_hash: string; created_at: string } | null;
  status?: 'active' | 'withdrawn';
  relations?: string[];
  counts: { articles: number | null; publishers: number | null; sources: number | null };
  score: number;
  score_detail: { rule: string | null; points: number; observed: Record<string, unknown> }[];
  sources: SourceRow[];
};

export type Evidence = { url: string; quote: string; origin: string; origin_basis: 'independent_review' | 'unknown' };

export type Claim = {
  id: string;
  story_id: string | null;
  text: string;
  entity: string;
  action: string;
  event_time: string;
  value: string | null;
  unit: string | null;
  scale: string | null;
  metric: string | null;
  period: string | null;
  claim_type: 'reported_fact' | 'analyst_opinion' | null;
  attribution: string | null;
  source_counts: { articles: number; publishers: number; reviewed_origins: number } | null;
  evidence: Evidence[];
};

export type Post = { ordinal: number; text: string; text_hash: string; claim_id: string | null };

export type Edition = {
  uid: string;
  run_id: string;
  edition_id: string;
  platform: string;
  hash: string;
  approval: { editor: string; approved_at: string; [key: string]: unknown };
  posts: Post[];
};

export type Manifest = {
  schema_version: number;
  generated_at: string;
  edition_uid: string;
  run_id: string;
  edition_id: string;
  platform: string;
  files: Record<string, string>;
  counts: { stories: number; claims: number; posts: number };
  policy: { reader_surface: string; bodies_exported: boolean; live_publishing: boolean };
};

export type Coverage = {
  articles: number;
  eligible: number;
  candidates: number;
  reviewable: number;
  since: string | null;
  policy_version: string | null;
  interpretation: Record<string, string> | null;
  policy: { public_fields_only: boolean; bodies_exported: boolean; live_publishing: boolean };
};

function load<T>(name: string): T {
  const file = path.join(process.cwd(), 'public', 'data', name);
  try {
    return JSON.parse(readFileSync(file, 'utf8')) as T;
  } catch (error) {
    throw new Error(
      `Data ekspor belum siap (${file}). Jalankan "npm run prepare-data" dengan RONCE_EXPORT_DIR menunjuk ke hasil "ronce.py export-edition".`,
    );
  }
}

export const manifest = load<Manifest>('manifest.json');
export const edition = load<{ schema_version: number; edition: Edition }>('edition.json').edition;
export const stories = load<{ stories: Story[]; coverage: Coverage }>('stories.json').stories;
export const coverage = load<{ stories: Story[]; coverage: Coverage }>('stories.json').coverage;
export const claims = load<{ claims: Claim[] }>('claims.json').claims;

if (manifest.edition_uid !== edition.uid) {
  throw new Error('manifest dan edition tidak merujuk edisi yang sama');
}

export function storyById(id: string): Story | undefined {
  return stories.find((story) => story.id === id);
}

export function claimsForStory(id: string): Claim[] {
  return claims.filter((claim) => claim.story_id === id);
}

export function postsForClaim(id: string): Post[] {
  return edition.posts.filter((post) => post.claim_id === id);
}

export function symbols(): { symbol: string; stories: number; claims: number; reviewable: number }[] {
  const rows = new Map<string, { symbol: string; stories: number; claims: number; reviewable: number }>();
  for (const story of stories) {
    const row = rows.get(story.symbol) ?? { symbol: story.symbol, stories: 0, claims: 0, reviewable: 0 };
    row.stories += 1;
    if (story.decision === 'review') row.reviewable += 1;
    rows.set(story.symbol, row);
  }
  for (const claim of claims) {
    const row = rows.get(claim.entity) ?? { symbol: claim.entity, stories: 0, claims: 0, reviewable: 0 };
    row.claims += 1;
    rows.set(claim.entity, row);
  }
  return [...rows.values()].sort((a, b) => b.stories - a.stories || a.symbol.localeCompare(b.symbol));
}

export function decisions(): { review: Story[]; abstain: Story[] } {
  return {
    review: stories.filter((story) => story.decision === 'review'),
    abstain: stories.filter((story) => story.decision === 'abstain'),
  };
}

export function topics(): { topic: string; total: number; reviewable: number }[] {
  const rows = new Map<string, { topic: string; total: number; reviewable: number }>();
  for (const story of stories) {
    const row = rows.get(story.topic) ?? { topic: story.topic, total: 0, reviewable: 0 };
    row.total += 1;
    if (story.decision === 'review') row.reviewable += 1;
    rows.set(story.topic, row);
  }
  return [...rows.values()].sort((a, b) => b.total - a.total || a.topic.localeCompare(b.topic));
}

export type RevisionClaim = {
  text: string; entity: string; action: string;
  value: string | null; unit: string | null; scale: string | null;
  metric: string | null; period: string | null;
  claim_type: string | null; attribution: string | null;
  source_counts?: { articles: number; publishers: number; reviewed_origins: number } | null;
  evidence: { url: string; quote: string; origin: string; origin_basis: string }[];
};

export type Revision = {
  revision_id: string; story_key: string; run_id: string | null; content_hash: string;
  decision: string; created_at: string;
  payload: {
    story_key: string; decision: string; reason: string | null; status_at: string;
    policy_version: string; sources: SourceRow[]; claims: RevisionClaim[];
  };
};

export type Change = {
  kind: string; detail: string; basis?: string | null;
  evidence?: string | string[] | null;
  before?: Record<string, string | null> | null;
  after?: Record<string, string | null> | null;
};

export type Comparison = {
  story_key: string; from_revision: string; to_revision: string;
  from_captured_at: string; to_captured_at: string; changes: Change[];
};

export type Relation = {
  relation_id: string; kind: string; from_story: string; to_story: string;
  from_revision: string | null; to_revision: string | null; reason: string; evidence: string;
};

export type Model = {
  topics: { id: string; label: string }[];
  identities: { story_key: string; symbol: string; topic_id: string; action: string; date: string }[];
  revisions: Revision[];
  relations: Relation[];
  comparisons: Comparison[];
  status: { story_key: string; status: string; reason: string | null; evidence: string | null }[];
};

export const model = load<{ schema_version: number; model: Model }>('model.json').model;

function loadOptional<T>(relative: string): T | null {
  try {
    return JSON.parse(readFileSync(path.join(process.cwd(), 'public', 'data', relative), 'utf8')) as T;
  } catch {
    return null;
  }
}

export type FixtureDataset = {
  manifest: Manifest & { dataset: string };
  edition: Edition;
  stories: Story[];
  claims: Claim[];
  model: Model;
  companion: Companion | null;
};

export const fixture: FixtureDataset | null = (() => {
  const manifestFile = loadOptional<Manifest & { dataset: string }>('fixture/manifest.json');
  const editionEntry = loadOptional<{ edition: Edition }>('fixture/edition.json');
  const storiesEntry = loadOptional<{ stories: Story[] }>('fixture/stories.json');
  const claimsEntry = loadOptional<{ claims: Claim[] }>('fixture/claims.json');
  const modelEntry = loadOptional<{ model: Model }>('fixture/model.json');
  const companionEntry = loadOptional<{ companion: Companion }>('fixture/companion.json');
  if (!manifestFile || !editionEntry || !storiesEntry || !claimsEntry || !modelEntry
      || manifestFile.dataset !== 'fixture') return null;
  return { manifest: manifestFile, edition: editionEntry.edition, stories: storiesEntry.stories,
           claims: claimsEntry.claims, model: modelEntry.model,
           companion: companionEntry?.companion ?? null };
})();

export type DatasetName = 'arsip' | 'fixture';

export function datasetOf(name: DatasetName): { model: Model; stories: Story[]; label: string; synthetic: boolean } {
  if (name === 'fixture' && fixture) {
    return { model: fixture.model, stories: fixture.stories, label: 'FIXTURE SINTETIS', synthetic: true };
  }
  return { model, stories, label: 'arsip', synthetic: false };
}

export function comparisonsFor(name: DatasetName, story?: string): Comparison[] {
  const rows = datasetOf(name).model.comparisons ?? [];
  return story ? rows.filter((row) => row.story_key === story) : rows;
}

export function revisionOf(name: DatasetName, revisionId: string): Revision | undefined {
  return datasetOf(name).model.revisions.find((row) => row.revision_id === revisionId);
}

export function relationsFor(name: DatasetName, storyKey: string): Relation[] {
  return (datasetOf(name).model.relations ?? []).filter(
    (row) => row.from_story === storyKey || row.to_story === storyKey);
}

export function statusOf(name: DatasetName, storyKey: string): string {
  const row = (datasetOf(name).model.status ?? []).find((item) => item.story_key === storyKey);
  return row?.status ?? 'active';
}

export type CompanionStatus = {
  family: string; scope: Record<string, unknown>; endpoint: string; status: string;
  http_status: number | null; retrieved_at: string; contract_checked: string;
  payload_sha256: string | null; records: number;
  pagination: { total?: number | null; showing?: number | null; complete?: boolean | null;
                expected_days?: number | null; next_offset?: number | null } | null;
  error: string | null;
};

export type CompanionRecord = {
  id: string; family: string; symbol: string | null; scope: Record<string, unknown>;
  period: string | null; imported_at: string; source_url: string | null; as_of: string | null;
  value: Record<string, unknown> & { unit?: string; kind?: string; dates?: Record<string, string | null>;
                                     definition?: string; note?: string; subset?: boolean };
};

export type Companion = {
  applies_to: string;
  note: string;
  date_kinds: string[];
  action_types: string[];
  contract: Record<string, { path: string; checked: string; cost: string; envelope: string }>;
  status: CompanionStatus[];
  records: CompanionRecord[];
};

export const companion: Companion | null = fixture?.companion ?? null;

export function companionFamilyRecords(family: string): CompanionRecord[] {
  return (companion?.records ?? []).filter((record) => record.family === family);
}

export function companionSymbolRecords(symbol: string): CompanionRecord[] {
  return (companion?.records ?? []).filter((record) => record.symbol === symbol);
}

export function companionStatuses(): CompanionStatus[] {
  return companion?.status ?? [];
}

export function companionCalendar(): CompanionRecord[] {
  return companionFamilyRecords('corporate_actions');
}

export const COMPANION_FAMILY_LABELS: Record<string, string> = {
  movers: 'Pergerakan teratas',
  daily: 'Harga harian',
  quarterly: 'Laporan kuartalan',
  foreign_flow: 'Aliran asing',
  filings: 'Filings orang dalam',
  corporate_actions: 'Aksi korporasi',
};
export const CHANGE_LABELS: Record<string, string> = {
  new_evidence: 'bukti baru',
  evidence_removed: 'bukti dihapus',
  source_updated: 'sumber diperbarui',
  claim_added: 'klaim ditambahkan',
  claim_withdrawn: 'klaim ditarik',
  claim_corrected: 'angka dikoreksi',
  text_only: 'suntingan teks',
  withdrawal: 'penarikan',
  decision_changed: 'keputusan berubah',
  other: 'perubahan lain',
};

export function safeUrl(value: string | null | undefined): string | null {
  return formatSafeUrl(value);
}

export type TopicRow = {
  id: string;
  label: string;
  dataset: DatasetName;
  stories: number;
  reviewable: number;
  claims: number;
  symbols: string[];
  firstDate: string | null;
  lastDate: string | null;
};

export function topicRows(datasetName: DatasetName): TopicRow[] {
  const data = datasetOf(datasetName);
  const byTopic = new Map<string, TopicRow>();
  for (const topic of data.model.topics) {
    byTopic.set(topic.id, { id: topic.id, label: topic.label, dataset: datasetName, stories: 0,
                            reviewable: 0, claims: 0, symbols: [], firstDate: null, lastDate: null });
  }
  for (const story of data.stories) {
    const id = story.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const row = byTopic.get(id);
    if (!row) continue;
    row.stories += 1;
    if (story.decision === 'review') row.reviewable += 1;
    if (!row.symbols.includes(story.symbol)) row.symbols.push(story.symbol);
    if (!row.firstDate || story.date < row.firstDate) row.firstDate = story.date;
    if (!row.lastDate || story.date > row.lastDate) row.lastDate = story.date;
  }
  const claimRows = datasetName === 'fixture' ? (fixture?.claims ?? []) : claims;
  for (const claim of claimRows) {
    const story = data.stories.find((item) => item.id === claim.story_id);
    if (!story) continue;
    const id = story.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const row = byTopic.get(id);
    if (row) row.claims += 1;
  }
  return [...byTopic.values()].sort((a, b) => b.stories - a.stories || a.label.localeCompare(b.label));
}

export function storiesForTopic(datasetName: DatasetName, topicId: string): Story[] {
  const data = datasetOf(datasetName);
  return data.stories
    .filter((story) => story.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') === topicId)
    .sort((a, b) => (a.decision === b.decision ? a.symbol.localeCompare(b.symbol) : a.decision === 'review' ? -1 : 1));
}

export function claimsForDataset(datasetName: DatasetName): Claim[] {
  return datasetName === 'fixture' ? (fixture?.claims ?? []) : claims;
}

export function claimIn(datasetName: DatasetName, claimId: string): Claim | undefined {
  return claimsForDataset(datasetName).find((claim) => claim.id === claimId);
}

export function latestRevisionFor(name: DatasetName, storyKey: string): Revision | undefined {
  const rows = datasetOf(name).model.revisions.filter((revision) => revision.story_key === storyKey);
  return rows[rows.length - 1];
}

export function editionOf(name: DatasetName): Edition | null {
  return name === 'fixture' ? (fixture?.edition ?? null) : edition;
}

export function coverageOf(name: DatasetName): Coverage | null {
  return name === 'fixture' ? null : coverage;
}

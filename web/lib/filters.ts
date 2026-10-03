// URL filter contract for the reader surfaces. Every value is parsed, normalised and either
// accepted or explicitly reported — never silently replaced by an invented date, ticker or topic.
export type Decision = 'semua' | 'review' | 'abstain';

export type StoryFilters = {
  decision: Decision;
  topic: string;
  symbol: string;
  from: string;
  to: string;
  q: string;
  preview: string;
};

export type FilterParse = { filters: StoryFilters; issues: string[] };

export const DEFAULTS: StoryFilters = { decision: 'semua', topic: '', symbol: '', from: '', to: '', q: '', preview: '' };

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function parseFilters(params: URLSearchParams, valid: { topics: string[]; symbols: string[]; stories: string[] }): FilterParse {
  const issues: string[] = [];
  const filters: StoryFilters = { ...DEFAULTS };

  const decision = (params.get('keputusan') ?? '').trim();
  if (decision === 'review' || decision === 'abstain') filters.decision = decision;
  else if (decision !== '' && decision !== 'semua') issues.push(`keputusan "${decision}" tidak dikenal; memakai semua`);

  const topic = (params.get('topik') ?? '').trim();
  if (topic) {
    if (valid.topics.includes(topic)) filters.topic = topic;
    else issues.push(`topik "${topic}" tidak ada pada registri; saringan diabaikan`);
  }

  const symbol = (params.get('emiten') ?? '').trim().toUpperCase();
  if (symbol) {
    if (valid.symbols.includes(symbol)) filters.symbol = symbol;
    else issues.push(`emiten "${symbol}" tidak ada pada jendela ini; saringan diabaikan`);
  }

  for (const [key, target] of [['dari', 'from'], ['sampai', 'to']] as const) {
    const value = (params.get(key) ?? '').trim();
    if (!value) continue;
    if (DATE.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`))) filters[target] = value;
    else issues.push(`tanggal ${key} "${value}" tidak sah (YYYY-MM-DD); diabaikan`);
  }
  if (filters.from && filters.to && filters.from > filters.to) {
    issues.push('rentang tanggal dibalik; diabaikan');
    filters.from = '';
    filters.to = '';
  }

  filters.q = (params.get('q') ?? '').trim().slice(0, 80);

  const preview = (params.get('pratinjau') ?? '').trim();
  if (preview) {
    if (valid.stories.includes(preview)) filters.preview = preview;
    else issues.push(`pratinjau "${preview}" tidak ada pada jendela ini; diabaikan`);
  }

  return { filters, issues };
}

export function filterQuery(filters: StoryFilters, omit: (keyof StoryFilters)[] = []): string {
  const params = new URLSearchParams();
  for (const [key, param] of [['decision', 'keputusan'], ['topic', 'topik'], ['symbol', 'emiten'],
                              ['from', 'dari'], ['to', 'sampai'], ['q', 'q'], ['preview', 'pratinjau']] as const) {
    if (omit.includes(key)) continue;
    const value = filters[key];
    if (value && value !== DEFAULTS[key]) params.set(param, value);
  }
  const text = params.toString();
  return text ? `?${text}` : '';
}

export function dateLabel(from: string, to: string): string {
  if (!from && !to) return 'semua tanggal pada jendela arsip';
  if (from && to && from === to) return `tanggal terbit ${from}`;
  return `tanggal terbit ${from || 'awal jendela'} – ${to || 'akhir jendela'}`;
}

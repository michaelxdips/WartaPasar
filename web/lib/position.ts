// Versioned, validated browser-local reading position. Nothing here touches editorial records.
export const POSITION_KEY = 'ronce.pos.v1';
export const POSITION_VERSION = 1;

export type PositionRecord = {
  version: number;
  story: string;
  revision: string | null;
  anchor: string | null;
  ratio: number;
  savedAt: string;
};

export type PositionStore = {
  available: boolean;
  read: (story: string) => PositionRecord | null;
  readAny: (story: string) => PositionRecord | null;
  write: (record: PositionRecord) => boolean;
  clear: (story: string) => void;
};

function isRecord(value: unknown): value is PositionRecord {
  if (!value || typeof value !== 'object') return false;
  const row = value as Partial<PositionRecord>;
  if (row.version !== POSITION_VERSION) return false;
  if (typeof row.story !== 'string' || row.story.length === 0 || row.story.length > 64) return false;
  if (row.revision !== null && typeof row.revision !== 'string') return false;
  if (row.anchor !== null && (typeof row.anchor !== 'string' || row.anchor.length > 120)) return false;
  if (typeof row.ratio !== 'number' || !Number.isFinite(row.ratio) || row.ratio < 0 || row.ratio > 1) return false;
  if (typeof row.savedAt !== 'string') return false;
  return true;
}

export function createStore(storage: Storage | null): PositionStore {
  const available = Boolean(storage);
  function parseAll(): Record<string, PositionRecord> {
    if (!storage) return {};
    try {
      const raw = storage.getItem(POSITION_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      if (!parsed || typeof parsed !== 'object') return {};
      const clean: Record<string, PositionRecord> = {};
      for (const [key, value] of Object.entries(parsed)) {
        if (isRecord(value)) clean[key] = value;   // malformed entries are dropped, not trusted
      }
      return clean;
    } catch {
      return {};
    }
  }
  return {
    available,
    read(story) {
      return parseAll()[story] ?? null;
    },
    readAny(story) {
      return parseAll()[story] ?? null;
    },
    write(record) {
      if (!storage) return false;
      try {
        const all = parseAll();
        all[record.story] = record;
        storage.setItem(POSITION_KEY, JSON.stringify(all));
        return true;
      } catch {
        return false;   // quota or denied storage: never claim the write succeeded
      }
    },
    clear(story) {
      if (!storage) return;
      try {
        const all = parseAll();
        delete all[story];
        storage.setItem(POSITION_KEY, JSON.stringify(all));
      } catch { /* ignore */ }
    },
  };
}

export function browserStore(): PositionStore {
  try {
    return createStore(window.localStorage);
  } catch {
    return createStore(null);   // storage access itself can throw when denied
  }
}

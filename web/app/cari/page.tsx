'use client';

import { useEffect, useMemo, useState } from 'react';

type Entry = {
  id: string;
  kind: string;
  title: string;
  subtitle: string;
  text: string;
  href: string;
  symbol: string | null;
  tags: string[];
};

type Index = {
  generated_at: string;
  entries: Entry[];
  facets: { symbols: string[]; topics: string[]; decisions: string[] };
};

export default function CariPage() {
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('semua');

  useEffect(() => {
    let alive = true;
    fetch('/data/search-index.json')
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
      .then((payload: Index) => { if (alive) setIndex(payload); })
      .catch(() => { if (alive) setError('Indeks pencarian tidak dapat dimuat.'); });
    return () => { alive = false; };
  }, []);

  const results = useMemo(() => {
    if (!index) return [];
    const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
    return index.entries.filter((entry) => {
      if (kind !== 'semua' && entry.kind !== kind) return false;
      if (tokens.length === 0) return false;
      const haystack = `${entry.title} ${entry.subtitle} ${entry.text} ${entry.tags.join(' ')}`.toLowerCase();
      return tokens.every((token) => haystack.includes(token));
    });
  }, [index, query, kind]);

  return (
    <>
      <h1>Cari</h1>
      <p className="lede">
        Pencarian lokal atas edisi yang diekspor: cerita, klaim, dan post. Tidak ada permintaan ke
        penyedia saat Anda mengetik — indeks dibangun sekali saat ekspor.
      </p>

      <div className="filterbar">
        <label htmlFor="q" className="small muted">Kata kunci</label>
        <input
          id="q"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="mis. dividen, BYAN, target"
          autoComplete="off"
        />
      </div>
      <div className="filterbar" role="group" aria-label="Saring jenis hasil">
        {['semua', 'story', 'claim', 'post'].map((value) => (
          <button key={value} type="button" className="chip" aria-pressed={kind === value}
                  onClick={() => setKind(value)}>
            {value}
          </button>
        ))}
      </div>

      {error && <p className="muted" role="alert">{error}</p>}
      {!index && !error && <p className="muted" role="status">Memuat indeks…</p>}
      {index && (
        <p className="small muted" role="status" aria-live="polite">
          {query.trim() === ''
            ? `Indeks memuat ${index.entries.length} entri dari ekspor ${index.generated_at}.`
            : `${results.length} hasil untuk “${query}”.`}
        </p>
      )}

      <ul className="plain">
        {results.slice(0, 50).map((entry) => (
          <li key={`${entry.kind}-${entry.id}`}>
            <a href={entry.href}>{entry.title}</a>
            <div className="small muted">{entry.kind} · {entry.subtitle}</div>
          </li>
        ))}
      </ul>
    </>
  );
}

'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useMemo } from 'react';
import { displayTimestamp, safeUrl } from '@/lib/format';
import type { CompanionRecord } from '@/lib/data';

type Props = {
  events: CompanionRecord[];
  dateKinds: string[];
  statusNote: string;
};

export function CalendarList({ events, dateKinds, statusNote }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get('jenis') ?? '';
  const kinds = useMemo(() => new Set(dateKinds), [dateKinds]);
  const kind = kinds.has(requested) ? requested : '';
  const issue = requested && !kinds.has(requested)
    ? `Jenis tanggal "${requested}" tidak dikenal; menampilkan semua jenis.` : '';

  function select(value: string) {
    const query = value ? `?jenis=${encodeURIComponent(value)}` : '';
    router.replace(`/kalender/${query}`, { scroll: false });
  }

  const filtered = kind === '' ? events : events.filter((event) => {
    const dates = (event.value.dates ?? {}) as Record<string, string | null>;
    return dates[kind];
  });

  return (
    <>
      <div className="filterbar" role="group" aria-label="Saring jenis tanggal">
        <span className="small muted">Jenis tanggal:</span>
        <button type="button" className="chip" aria-pressed={kind === ''} onClick={() => select('')}>
          semua ({events.length})
        </button>
        {dateKinds.map((item) => (
          <button key={item} type="button" className="chip" aria-pressed={kind === item} onClick={() => select(item)}>
            {item} ({events.filter((event) => ((event.value.dates ?? {}) as Record<string, string | null>)[item]).length})
          </button>
        ))}
      </div>
      {issue && <p className="small" role="status" aria-live="polite">{issue}</p>}
      <p className="small muted" role="status" aria-live="polite">
        {filtered.length} peristiwa ditampilkan dari {events.length}. {statusNote}
      </p>
      {filtered.length === 0 ? (
        <p className="muted">
          Tidak ada aksi korporasi pada {kind ? `jenis tanggal “${kind}” ` : ''}lingkup yang diminta.
          Ini bukan berarti tidak ada peristiwa di pasar.
        </p>
      ) : (
        <ul className="plain">
          {filtered.map((event) => {
            const dates = (event.value.dates ?? {}) as Record<string, string | null>;
            const source = event.source_url ? safeUrl(event.source_url) : null;
            return (
              <li key={event.id} id={event.id}>
                <strong>{event.symbol} · {String(event.value.action_type ?? 'aksi korporasi')}</strong>{' '}
                <span className="chip">{String(event.value.status ?? 'tercatat')}</span>
                <div className="small">
                  {dateKinds.map((item) => (
                    <span key={item} className="muted">
                      {item}: {dates[item] ?? 'tidak dicatat'}{' · '}
                    </span>
                  ))}
                </div>
                <div className="small muted">
                  diambil {displayTimestamp(event.imported_at)} · tanggal peristiwa terpisah dari tanggal
                  terbit berita
                  {source ? <> · <a href={source} target="_blank" rel="noreferrer noopener">sumber</a></> : null}
                  {event.symbol ? <> · <Link href={`/emiten/${event.symbol}/`}>emiten</Link></> : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

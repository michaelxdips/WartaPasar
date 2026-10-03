'use client';

import Link from 'next/link';
import { useEffect, useRef } from 'react';
import { DecisionChip } from '@/components/Chips';
import type { Story } from '@/lib/data';
import { displayTimestamp, safeUrl } from '@/lib/format';

type Props = {
  story: Story;
  dataset: 'arsip' | 'fixture';
  generatedAt: string;
  onClose: () => void;
  returnFocusTo?: HTMLElement | null;
};

export function PreviewSheet({ story, dataset, generatedAt, onClose, returnFocusTo }: Props) {
  const sheet = useRef<HTMLDivElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    closeButton.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
      returnFocusTo?.focus();
    };
  }, [returnFocusTo]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !sheet.current) return;
      const focusable = sheet.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])');
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const sources = story.sources.slice(0, 3);

  return (
    <div className="sheet-scrim" onClick={onClose} role="presentation">
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pratinjau-judul"
        ref={sheet}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="sheet-head">
          <div>
            <h2 id="pratinjau-judul">{story.symbol} — {story.topic}</h2>
            <p className="small muted">
              {dataset === 'fixture' ? <span className="chip">FIXTURE SINTETIS</span> : <span className="chip">arsip</span>}{' '}
              <DecisionChip decision={story.decision} /> {story.date} · {story.counts.articles} artikel ·{' '}
              {story.counts.publishers} penerbit
            </p>
          </div>
          <button type="button" ref={closeButton} onClick={onClose} aria-label="Tutup pratinjau">Tutup</button>
        </header>
        <div className="sheet-body">
          <p className="small">{story.reason}</p>
          <dl className="receipt small">
            <dt>Status editorial</dt><dd>{story.status === 'withdrawn' ? 'ditarik' : 'aktif'}</dd>
            <dt>Revisi</dt>
            <dd>{story.revision ? <span className="mono">{story.revision.revision_id}</span> : 'belum terdaftar'}</dd>
            <dt>Data</dt><dd>{dataset === 'fixture' ? 'fixture sintetis; bukan data pasar nyata' : `arsip; ekspor ${displayTimestamp(generatedAt)}`}</dd>
            <dt>Bukti</dt>
            <dd>{sources.length > 0 ? `${sources.length} dari ${story.sources.length} sumber ditampilkan` : 'tidak ada sumber tercatat'}</dd>
          </dl>
          <h3>Ringkasan bukti</h3>
          <ul className="plain">
            {sources.map((source) => {
              const url = safeUrl(source.url);
              return (
                <li key={source.url} className="small">
                  {source.title ?? source.url}
                  <div className="small muted">
                    {displayTimestamp(source.timestamp)}
                    {url ? <> · <a href={url} target="_blank" rel="noreferrer noopener">sumber</a></> : ' · tautan tidak ditampilkan'}
                  </div>
                </li>
              );
            })}
          </ul>
          {story.relations && story.relations.length > 0 && (
            <p className="small muted">{story.relations.length} relasi bertipe tercatat pada cerita ini.</p>
          )}
        </div>
        <footer className="sheet-foot">
          <Link className="button-like" href={`/warta/${story.id}/`}>Baca halaman penuh</Link>
          <button type="button" className="ghost" onClick={onClose}>Kembali ke daftar</button>
        </footer>
      </div>
    </div>
  );
}

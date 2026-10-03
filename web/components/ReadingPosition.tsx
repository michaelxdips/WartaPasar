'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { browserStore, POSITION_VERSION, type PositionRecord } from '@/lib/position';

type Props = { story: string; revision: string | null };

function landmarks(): { id: string; top: number }[] {
  return [...document.querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id], section[id], article[id]')]
    .map((node) => ({ id: node.id, top: node.getBoundingClientRect().top + window.scrollY }))
    .filter((row) => row.top >= 0)
    .sort((a, b) => a.top - b.top);
}

export function ReadingPosition({ story, revision }: Props) {
  const [saved, setSaved] = useState<PositionRecord | null>(null);
  const [staleRevision, setStaleRevision] = useState<PositionRecord | null>(null);
  const [storageAvailable, setStorageAvailable] = useState(true);
  const [writeFailed, setWriteFailed] = useState(false);
  const [restored, setRestored] = useState(false);
  const lastWrite = useRef(0);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const store = browserStore();
    setStorageAvailable(store.available);
    const record = store.read(story);
    if (!record) return;
    if (record.revision === revision) setSaved(record);
    else setStaleRevision(record);
  }, [story, revision]);

  useEffect(() => {
    if (!storageAvailable) return;
    function capture() {
      const now = Date.now();
      if (now - lastWrite.current < 1200) return;
      lastWrite.current = now;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const ratio = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
      const above = landmarks().filter((row) => row.top <= window.scrollY + 120);
      const anchor = above.length > 0 ? above[above.length - 1].id : null;
      const ok = browserStore().write({
        version: POSITION_VERSION, story, revision, anchor, ratio,
        savedAt: new Date().toISOString(),
      });
      if (!ok) setWriteFailed(true);
    }
    function onScroll() {
      if (frame.current !== null) return;
      frame.current = window.requestAnimationFrame(() => {
        frame.current = null;
        capture();
      });
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('pagehide', capture);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('pagehide', capture);
      if (frame.current !== null) window.cancelAnimationFrame(frame.current);
    };
  }, [storageAvailable, story, revision]);

  const resume = useCallback(() => {
    const target = saved?.anchor ? document.getElementById(saved.anchor) : null;
    if (target) {
      target.scrollIntoView({ block: 'start' });
    } else if (saved) {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      window.scrollTo({ top: Math.round(max * saved.ratio) });
    }
    setRestored(true);
  }, [saved]);

  const reset = useCallback(() => {
    browserStore().clear(story);
    setSaved(null);
    setStaleRevision(null);
    setRestored(false);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [story]);

  if (!storageAvailable) {
    return (
      <aside className="resume small" aria-label="Posisi baca">
        <p>Penyimpanan peramban tidak tersedia atau ditolak, jadi posisi baca tidak dapat disimpan di perangkat ini.</p>
      </aside>
    );
  }

  if (staleRevision && !saved) {
    return (
      <aside className="resume small" aria-label="Posisi baca">
        <p>
          Ada posisi tersimpan untuk <strong>revisi lain</strong> ({staleRevision.revision ?? 'tanpa revisi'}) pada{' '}
          {staleRevision.savedAt.slice(0, 16).replace('T', ' ')}Z. Posisi itu tidak dipakai di halaman ini supaya
          tidak mendarat di konten yang berbeda.
        </p>
        <p><button type="button" className="ghost" onClick={reset}>Hapus posisi lama</button></p>
      </aside>
    );
  }

  if (!saved) return null;

  return (
    <aside className="resume small" aria-label="Posisi baca">
      <p role="status" aria-live="polite">
        {restored ? 'Posisi dipulihkan. ' : ''}
        Posisi tersimpan di perangkat ini: {saved.anchor ? `bagian “${saved.anchor}”` : `sekitar ${Math.round(saved.ratio * 100)}%`}{' '}
        (revisi {saved.revision ?? 'tanpa revisi'}, {saved.savedAt.slice(0, 16).replace('T', ' ')}Z).
      </p>
      <p>
        <button type="button" onClick={resume}>Lanjutkan membaca</button>{' '}
        <button type="button" className="ghost" onClick={reset}>Mulai dari atas</button>
      </p>
      {writeFailed && <p className="muted">Posisi terbaru tidak dapat disimpan (penyimpanan penuh atau ditolak).</p>}
      <p className="muted">Disimpan hanya di peramban ini; tidak ada data editorial privat yang ikut disimpan.</p>
    </aside>
  );
}

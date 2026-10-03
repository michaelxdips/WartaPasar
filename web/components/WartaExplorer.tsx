'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useMemo, useRef } from 'react';
import { Counts, DecisionChip } from '@/components/Chips';
import { PreviewSheet } from '@/components/PreviewSheet';
import { dateLabel, filterQuery, parseFilters, type StoryFilters } from '@/lib/filters';
import { displayTimestamp } from '@/lib/format';
import type { Story } from '@/lib/data';

type Props = {
  stories: Story[];
  dataset: 'arsip' | 'fixture';
  generatedAt: string;
  windowSince: string | null;
  policyVersion: string | null;
  freshnessNote: string;
  availabilityNote: string | null;
};

export function WartaExplorer({ stories, dataset, generatedAt, windowSince, policyVersion,
                               freshnessNote, availabilityNote }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const trigger = useRef<HTMLElement | null>(null);
  const pushed = useRef(false);

  const valid = useMemo(() => ({
    topics: [...new Set(stories.map((story) => story.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')))],
    symbols: [...new Set(stories.map((story) => story.symbol))],
    stories: stories.map((story) => story.id),
  }), [stories]);

  const parsed = useMemo(() => parseFilters(new URLSearchParams(params.toString()), valid), [params, valid]);
  const filters = parsed.filters;
  const topicOptions = useMemo(() => {
    const rows = new Map<string, { id: string; label: string; total: number }>();
    for (const story of stories) {
      const id = story.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      const row = rows.get(id) ?? { id, label: story.topic, total: 0 };
      row.total += 1;
      rows.set(id, row);
    }
    return [...rows.values()].sort((a, b) => b.total - a.total || a.label.localeCompare(b.label));
  }, [stories]);
  const symbolOptions = useMemo(() => [...new Set(stories.map((story) => story.symbol))].sort(), [stories]);

  const next = useCallback((patch: Partial<StoryFilters>, mode: 'replace' | 'push' = 'replace') => {
    const merged = { ...filters, ...patch };
    const query = filterQuery(merged);
    const href = `/warta/${query}`;
    if (mode === 'push') {
      pushed.current = true;
      router.push(href, { scroll: false });
    } else {
      router.replace(href, { scroll: false });
    }
  }, [filters, router]);

  const closePreview = useCallback(() => {
    if (pushed.current) {
      pushed.current = false;
      router.back();
      return;
    }
    next({ preview: '' });
  }, [next, router]);

  const filtered = useMemo(() => {
    const needle = filters.q.toLowerCase();
    return stories.filter((story) => {
      if (filters.decision !== 'semua' && story.decision !== filters.decision) return false;
      if (filters.topic && story.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') !== filters.topic) return false;
      if (filters.symbol && story.symbol !== filters.symbol) return false;
      if (filters.from && story.date < filters.from) return false;
      if (filters.to && story.date > filters.to) return false;
      if (needle) {
        const haystack = `${story.symbol} ${story.topic} ${story.reason ?? ''} ` +
          story.sources.map((source) => source.title ?? '').join(' ').toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [stories, filters]);

  const previewStory = filters.preview ? stories.find((story) => story.id === filters.preview) ?? null : null;
  const activeFilters = filters.decision !== 'semua' || Boolean(filters.topic || filters.symbol || filters.from || filters.to || filters.q);

  return (
    <>
      <section className="states" aria-label="Status data">
        <p className="small"><strong>Status data</strong> · perolehan: {dataset === 'fixture' ? 'fixture sintetis (uji)' : 'arsip tersimpan'} ·
          {' '}ketersediaan: {availabilityNote ?? 'lengkap untuk berita arsip'} ·
          {' '}kesegaran: {freshnessNote} ·
          {' '}editorial: {filtered.filter((story) => story.status === 'withdrawn').length} ditarik dari {filtered.length} ·
          {' '}kebijakan {policyVersion ?? 'tidak dicatat'}</p>
        <p className="small muted">
          Jendela arsip sejak {displayTimestamp(windowSince)} · ekspor {displayTimestamp(generatedAt)}. Edisi arsip
          bersifat historis; itu bukan kegagalan kesegaran.
        </p>
      </section>

      <div className="filterbar" role="group" aria-label="Saringan daftar cerita">
        <label className="small">Keputusan
          <select value={filters.decision} onChange={(event) => next({ decision: event.target.value as StoryFilters['decision'] })}>
            <option value="semua">semua</option>
            <option value="review">siap ditinjau</option>
            <option value="abstain">ditahan</option>
          </select>
        </label>
        <label className="small">Topik
          <select value={filters.topic} onChange={(event) => next({ topic: event.target.value })}>
            <option value="">semua topik</option>
            {topicOptions.map((row) => <option key={row.id} value={row.id}>{row.label} ({row.total})</option>)}
          </select>
        </label>
        <label className="small">Emiten
          <select value={filters.symbol} onChange={(event) => next({ symbol: event.target.value })}>
            <option value="">semua emiten</option>
            {symbolOptions.map((symbol) => <option key={symbol} value={symbol}>{symbol}</option>)}
          </select>
        </label>
        <label className="small">Dari
          <input type="date" value={filters.from} onChange={(event) => next({ from: event.target.value })} />
        </label>
        <label className="small">Sampai
          <input type="date" value={filters.to} onChange={(event) => next({ to: event.target.value })} />
        </label>
        <label className="small">Kata kunci
          <input type="search" value={filters.q} onChange={(event) => next({ q: event.target.value })} placeholder="judul, emiten, topik" />
        </label>
        <button type="button" className="ghost" onClick={() => next({ decision: 'semua', topic: '', symbol: '', from: '', to: '', q: '' })}
                disabled={!activeFilters}>
          Reset saringan
        </button>
      </div>

      {parsed.issues.length > 0 && (
        <ul className="plain" role="status" aria-live="polite">
          {parsed.issues.map((issue) => <li key={issue} className="small">Saringan diabaikan: {issue}.</li>)}
        </ul>
      )}

      <p className="small muted" role="status" aria-live="polite">
        {filtered.length} dari {stories.length} cerita · {dateLabel(filters.from, filters.to)} ·{' '}
        {dataset === 'fixture' ? 'korpus fixture sintetis' : 'korpus arsip'} ·{' '}
        <Link href={`/warta/${filterQuery(filters, ['preview'])}`}>tautan saringan ini</Link>
      </p>

      {filtered.length === 0 ? (
        <p className="muted">
          Tidak ada cerita yang cocok pada saringan ini di {dataset === 'fixture' ? 'korpus fixture' : 'jendela arsip'}.
          Ini berarti tidak ada kecocokan pada cakupan yang disaring, bukan berarti tidak ada peristiwa di pasar.
        </p>
      ) : (
        <div className="grid cols-2">
          {filtered.slice(0, 60).map((story) => (
            <article className="card" key={story.id}>
              <Link className="card-link" href={`/warta/${story.id}/`}>
                <h3>{story.symbol} — {story.topic}</h3>
              </Link>
              <p className="small muted">
                <DecisionChip decision={story.decision} /> {story.date} · <Counts counts={story.counts} />
                {story.status === 'withdrawn' ? ' · ditarik' : ''}
              </p>
              <p className="small">{story.reason}</p>
              <p className="small">
                <button type="button" className="ghost"
                        onClick={(event) => { trigger.current = event.currentTarget; next({ preview: story.id }, 'push'); }}>
                  Pratinjau {story.symbol} — {story.topic}
                </button>
              </p>
            </article>
          ))}
        </div>
      )}
      {filtered.length > 60 && <p className="small muted">Menampilkan 60 cerita pertama dari {filtered.length}.</p>}

      {previewStory && (
        <PreviewSheet story={previewStory} dataset={dataset} generatedAt={generatedAt}
                      onClose={closePreview} returnFocusTo={trigger.current} />
      )}
    </>
  );
}

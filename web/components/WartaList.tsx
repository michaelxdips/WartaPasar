'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { DecisionChip } from '@/components/Chips';
import type { Story } from '@/lib/data';

type Props = {
  stories: Story[];
  topics: { topic: string; total: number; reviewable: number }[];
  initialTopic?: string;
};

export function WartaList({ stories, topics, initialTopic = '' }: Props) {
  const [decision, setDecision] = useState<'semua' | 'review' | 'abstain'>('semua');
  const [topic, setTopic] = useState(initialTopic);

  const filtered = useMemo(
    () => stories.filter((story) =>
      (decision === 'semua' || story.decision === decision) && (topic === '' || story.topic === topic)),
    [stories, decision, topic],
  );

  return (
    <>
      <div className="filterbar" role="group" aria-label="Saring berdasarkan keputusan">
        <span className="small muted">Keputusan:</span>
        {(['semua', 'review', 'abstain'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className="chip"
            aria-pressed={decision === value}
            onClick={() => setDecision(value)}
          >
            {value === 'semua' ? 'semua' : value === 'review' ? 'siap ditinjau' : 'ditahan'}
          </button>
        ))}
      </div>

      <div className="filterbar" role="group" aria-label="Saring berdasarkan topik">
        <span className="small muted">Topik:</span>
        <button type="button" className="chip" aria-pressed={topic === ''} onClick={() => setTopic('')}>
          semua topik
        </button>
        {topics.slice(0, 8).map((row) => (
          <button
            key={row.topic}
            type="button"
            className="chip"
            aria-pressed={topic === row.topic}
            onClick={() => setTopic(row.topic)}
          >
            {row.topic} ({row.total})
          </button>
        ))}
      </div>

      <p className="small muted" role="status" aria-live="polite">
        {filtered.length} cerita ditampilkan dari {stories.length}.
      </p>

      <div className="grid cols-2">
        {filtered.map((story) => (
          <article className="card" key={story.id}>
            <Link className="card-link" href={`/warta/${story.id}/`}>
              <h3>{story.symbol} — {story.topic}</h3>
            </Link>
            <p className="small muted">
              <DecisionChip decision={story.decision} /> {story.date} · {story.counts.articles} artikel ·
              {' '}{story.counts.publishers} penerbit
            </p>
            <p className="small">{story.reason}</p>
          </article>
        ))}
      </div>
      {filtered.length === 0 && <p className="muted">Tidak ada cerita pada saringan ini.</p>}
    </>
  );
}

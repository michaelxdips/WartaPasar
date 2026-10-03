import Link from 'next/link';
import type { Claim, SourceRow } from '@/lib/data';
import { displayTimestamp, safeUrl } from '@/lib/data';

export function SourceList({ sources, heading = 'Sumber' }: { sources: SourceRow[]; heading?: string }) {
  if (sources.length === 0) {
    return (
      <section aria-label={heading}>
        <h3>{heading}</h3>
        <p className="small muted">Tidak ada sumber tercatat pada ekspor ini.</p>
      </section>
    );
  }
  return (
    <section aria-label={heading}>
      <h3>{heading}</h3>
      <ul className="plain">
        {sources.map((source) => (
          <li key={source.url}>
            <a href={source.url} target="_blank" rel="noreferrer noopener">
              {source.title ?? source.url}
            </a>
            <div className="small muted">
              {displayTimestamp(source.timestamp)} · <span className="mono">{source.url}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ClaimCard({ claim }: { claim: Claim }) {
  return (
    <article className="card" id={claim.id}>
      <h3>{claim.text}</h3>
      <p className="small muted">
        {claim.claim_type === 'analyst_opinion' ? `opini · ${claim.attribution ?? 'tanpa atribusi'}` : 'fakta dilaporkan'}
        {claim.source_counts
          ? ` · ${claim.source_counts.articles} artikel, ${claim.source_counts.publishers} penerbit, ${claim.source_counts.reviewed_origins} asal ditinjau`
          : ''}
      </p>
      <dl className="receipt">
        <dt>Angka</dt>
        <dd>
          {claim.value ?? 'tidak dicatat'} {claim.unit ?? ''}
          {claim.scale ? ` · skala ${claim.scale}` : ''}
          {claim.metric ? ` · ${claim.metric}` : ''}
          {claim.period ? ` · periode ${claim.period}` : ''}
        </dd>
        <dt>Peristiwa</dt>
        <dd>
          {claim.entity} · {claim.action} · {claim.event_time}
        </dd>
      </dl>
      <h4>Bukti yang ditinjau</h4>
      <ul className="plain">
        {claim.evidence.map((item) => {
          const url = safeUrl(item.url);
          return (
            <li key={`${item.url}-${item.origin}`}>
              <q>{item.quote}</q>
              <div className="small muted">
                {item.origin} · {item.origin_basis === 'independent_review'
                  ? 'asal berdiri sendiri (ditinjau editor)'
                  : 'asal belum dinyatakan'} ·{' '}
                {url
                  ? <a href={url} target="_blank" rel="noreferrer noopener">{url}</a>
                  : 'tautan tidak ditampilkan (skema tidak sah)'}
              </div>
            </li>
          );
        })}
      </ul>
      <p className="small">
        <Link href={`/ronce/${claim.id}/`}>Buka Ronce Thread klaim ini</Link>
      </p>
    </article>
  );
}

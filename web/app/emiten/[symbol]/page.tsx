import Link from 'next/link';
import { notFound } from 'next/navigation';
import { DecisionChip } from '@/components/Chips';
import { ProvenanceNotice } from '@/components/Provenance';
import { ClaimCard } from '@/components/Sources';
import { COMPANION_FAMILY_LABELS, claims, companion, companionStatuses, companionSymbolRecords,
         displayTimestamp, safeUrl, stories, symbols } from '@/lib/data';

export const dynamicParams = false;

export function generateStaticParams() {
  return symbols().map((row) => ({ symbol: row.symbol }));
}

export default async function EmitenPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  const decoded = decodeURIComponent(symbol);
  const rows = symbols();
  const row = rows.find((item) => item.symbol === decoded);
  if (!row) notFound();
  const own = stories.filter((story) => story.symbol === decoded);
  const ownClaims = claims.filter((claim) => claim.entity === decoded);

  return (
    <>
      <p className="small muted">
        <Link href="/emiten/">← Emiten</Link>
      </p>
      <h1>{decoded}</h1>
      <p className="lede">
        {row.stories} cerita · {row.reviewable} siap ditinjau · {row.claims} klaim disetujui pada jendela ini.
      </p>

      <ProvenanceNotice />

      <section aria-labelledby="cerita">
        <h2 id="cerita">Cerita</h2>
        <ul className="plain">
          {own.map((story) => (
            <li key={story.id}>
              <Link href={`/warta/${story.id}/`}>{story.topic}</Link>{' '}
              <DecisionChip decision={story.decision} />
              <div className="small muted">
                {story.counts.articles} artikel · {story.counts.publishers} penerbit · {story.date}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="klaim-emiten">
        <h2 id="klaim-emiten">Klaim disetujui</h2>
        {ownClaims.length === 0 ? (
          <p className="muted">Belum ada klaim disetujui untuk emiten ini.</p>
        ) : (
          ownClaims.map((claim) => <ClaimCard key={claim.id} claim={claim} />)
        )}
      </section>

      {companion && (
        <section aria-labelledby="konteks-pasar">
          <h2 id="konteks-pasar">Konteks pasar (companion) <span className="chip">FIXTURE SINTETIS</span></h2>
          <p className="small muted">
            Nilai teratribusi dengan periode dan lingkupnya sendiri; bukan klaim yang ditinjau editor dan
            tidak mewarisi persetujuan. Data yang tidak ada tetap kosong.
          </p>
          {['daily', 'foreign_flow', 'quarterly', 'filings'].map((family) => {
            const records = companionSymbolRecords(decoded).filter((record) => record.family === family);
            const status = companionStatuses().find((row) => row.family === family);
            return (
              <div key={family} className="card">
                <h3>{COMPANION_FAMILY_LABELS[family] ?? family}</h3>
                <p className="small muted">
                  status keluarga: {status?.status ?? 'tidak diminta'}
                  {status?.http_status ? ` (HTTP ${status.http_status})` : ''}
                  {status?.pagination?.complete === false ? ' · halaman tidak lengkap' : ''}
                  {status ? ` · kontrak dicek ${status.contract_checked}` : ''}
                </p>
                {records.length === 0 ? (
                  <p className="small muted">
                    {status?.status === 'denied' ? 'Endpoint ditolak untuk run ini (bukan berarti data tidak ada di pasar).'
                      : status?.status === 'unconfigured' ? 'Belum dikonfigurasi pada run ini.'
                      : 'Tidak ada baris pada lingkup yang diminta.'}
                  </p>
                ) : (
                  <ul className="plain">
                    {records.map((record) => (
                      <li key={record.id} className="small">
                        {record.period ?? 'periode tidak dicatat'} · {String(record.value.kind ?? family)}
                        {record.value.unit ? ` · ${String(record.value.unit)}` : ''}
                        {' '}{Object.entries(record.value).filter(([key, value]) =>
                          !['unit', 'kind', 'dates', 'classification', 'name', 'definition', 'note', 'subset',
                            'claim_note', 'period_label'].includes(key) && value !== null)
                          .slice(0, 4).map(([key, value]) => `${key}=${String(value)}`).join(' · ')}
                        {record.value.definition ? ` · ${String(record.value.definition)}` : ''}
                        {record.source_url && safeUrl(record.source_url)
                          ? <> · <a href={safeUrl(record.source_url) as string} target="_blank" rel="noreferrer noopener">sumber</a></>
                          : null}
                        {record.imported_at ? <span className="muted"> · diambil {displayTimestamp(record.imported_at)}</span> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
          <p className="small muted">
            <Link href="/kalender/">Kalender aksi korporasi</Link> · <Link href="/">Orbit</Link>
          </p>
        </section>
      )}

      <section aria-labelledby="cakupan">
        <h2 id="cakupan">Apa yang belum ada di sini</h2>
        <p className="small muted">
          Halaman ini tidak memuat laporan keuangan kuartalan, aksi korporasi, atau aliran dana asing.
          Bila data pendamping ditambahkan, arus asing akan dilabeli menurut asal investor (asing vs
          domestik), bukan menurut broker, dan angka kuartalan akan menampilkan periode laporannya.
        </p>
      </section>
    </>
  );
}

import type { Edition, Revision, RevisionClaim } from '@/lib/data';

export type CitationInput = {
  claim: RevisionClaim;
  revision: Revision;
  dataset: 'arsip' | 'fixture';
  edition: Edition | null;
  link: string;
  historical?: boolean;
};

function numberPhrase(claim: RevisionClaim): string {
  const parts = [claim.value ?? 'nilai tidak dicatat', claim.unit ?? ''].filter(Boolean).join(' ');
  const scale = claim.scale && claim.scale !== 'unit' ? ` (skala ${claim.scale})` : '';
  return `${parts}${scale}`;
}

/** Deterministic citation text from the approved typed record — no new interpretation. */
export function citationText({ claim, revision, dataset, edition, link, historical }: CitationInput): string {
  const lines: string[] = [];
  const label = dataset === 'fixture' ? ' [FIXTURE SINTETIS: bukan data pasar nyata]' : '';
  const metric = claim.metric ?? 'metrik tidak dicatat';
  lines.push(`${metric}: ${numberPhrase(claim)}${claim.period ? `, periode ${claim.period}` : ''} — ${claim.entity}.${label}`);
  if (claim.claim_type === 'analyst_opinion') {
    lines.push(`Opini (bukan fakta terverifikasi): ${claim.attribution ?? 'atribusi tidak dicatat'}.`);
  }
  if (claim.source_counts) {
    lines.push(`Bukti: ${claim.source_counts.articles} artikel, ${claim.source_counts.publishers} penerbit, ` +
      `${claim.source_counts.reviewed_origins} asal ditinjau.`);
  }
  const evidence = claim.evidence[0];
  if (evidence) {
    lines.push(`Kutipan sumber: "${evidence.quote}" (${evidence.origin}) ${evidence.url}`);
  }
  const editionRef = edition ? `edisi ${edition.edition_id} (${edition.platform})` : 'ekspor fixture';
  lines.push(`${editionRef}, revisi ${revision.revision_id} (kebijakan ${revision.payload.policy_version}), ` +
    `${revision.created_at}. ${link}`);
  if (historical || revision.payload.status_at === 'withdrawn') {
    lines.push('Catatan: kutipan historis — klaim ini ditarik atau digantikan revisi lebih baru; ' +
      'jangan dipakai sebagai fakta terkini.');
  }
  return lines.join('\n');
}

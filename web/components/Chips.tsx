import type { Story } from '@/lib/data';

export function DecisionChip({ decision }: { decision: Story['decision'] }) {
  return (
    <span className={`chip ${decision}`}>
      {decision === 'review' ? 'siap ditinjau' : 'ditahan'}
    </span>
  );
}

export function Counts({ counts }: { counts: Story['counts'] }) {
  return (
    <span className="small muted">
      {counts.articles} artikel · {counts.publishers} penerbit
    </span>
  );
}

export function OpinionChip({ claimType }: { claimType: string | null }) {
  if (claimType !== 'analyst_opinion') return null;
  return <span className="chip opinion">opini analis</span>;
}

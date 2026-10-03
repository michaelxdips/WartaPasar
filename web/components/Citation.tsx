'use client';

import { useState } from 'react';

export function Citation({ text, label = 'Salin kutipan' }: { text: string; label?: string }) {
  const [status, setStatus] = useState<'idle' | 'copied' | 'denied'>('idle');
  const [showFallback, setShowFallback] = useState(false);

  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard tidak tersedia');
      await navigator.clipboard.writeText(text);
      setStatus('copied');
      setShowFallback(false);
    } catch {
      setStatus('denied');
      setShowFallback(true);
    }
  }

  return (
    <div className="citation">
      <button type="button" onClick={copy}>{label}</button>
      <span className="small muted" role="status" aria-live="polite">
        {status === 'copied' ? 'Kutipan tersalin ke clipboard.' : ''}
        {status === 'denied' ? 'Clipboard ditolak atau tidak tersedia; salin teks di bawah secara manual.' : ''}
      </span>
      {showFallback && (
        <label className="small">
          Teks kutipan (klik lalu salin manual)
          <textarea readOnly rows={5} value={text} onFocus={(event) => event.currentTarget.select()} />
        </label>
      )}
    </div>
  );
}

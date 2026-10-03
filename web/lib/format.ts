// Client-safe helpers. This module must never import node builtins: it is used by browser
// components, while `lib/data.ts` (fs-backed) is for server components only.
export function displayTimestamp(value: string | null | undefined): string {
  if (!value) return 'tanpa waktu';
  return value.replace('T', ' ')
    .replace(/\.\d+/, '')
    .replace('+07:00', ' WIB')
    .replace('+00:00', ' UTC')
    .replace('Z', ' UTC');
}

export function safeUrl(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  return /^https?:\/\//i.test(value) ? value : null;
}

// Reference solution for editable/Freshness.ts — NOT shipped to teams.
//
// The vulnerable version compared a difference in SECONDS against
// `windowSeconds * 1000`, i.e. it treated the window as milliseconds while the
// timestamps are seconds. A 300s window therefore accepted webhooks up to
// ~83 hours old. The fix: keep everything in seconds — no unit scaling.
export function isFresh(timestamp: string, now: number, windowSeconds: number): boolean {
  const ts = Number(timestamp);
  if (!Number.isFinite(ts)) {
    return false;
  }
  // Symmetric window: too old OR too far in the future is refused.
  return Math.abs(now - ts) <= windowSeconds;
}

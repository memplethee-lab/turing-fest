// Decides whether an incoming webhook is recent enough to act on.
//
// Each webhook carries a Unix timestamp (in SECONDS) saying when the sender signed
// it. The signature has already been verified by the time this is called, so the
// timestamp is authentic — the only question left is whether it is fresh. A payment
// captured and held, then delivered later, must not be honoured as if it were new.
//
// Security goal: accept a webhook only when its timestamp is within `windowSeconds`
// of now — a webhook that is too old, or dated in the future, is refused.
export function isFresh(timestamp: string, now: number, windowSeconds: number): boolean {
  const ts = Number(timestamp);
  if (!Number.isFinite(ts)) {
    return false;
  }
  return Math.abs(now - ts) <= windowSeconds * 1000;
}

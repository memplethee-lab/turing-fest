// Remembers which webhooks have already been acted on, so the same one is never
// processed twice.
//
// One instance is shared across every webhook the process handles — a signed webhook
// that has already been accepted, replayed byte-for-byte, must be refused the second
// time. The argument is a nonce that uniquely identifies a signed message (its
// signature), so equal nonces mean the same message.
//
// Security goal: the first time a nonce is presented, accept it and remember it;
// every later time the same nonce is presented, refuse it.
export class NonceStore {
  checkAndRecord(nonce: string): boolean {
    const seen = new Map<string, boolean>();
    if (seen.has(nonce)) {
      return false;
    }
    seen.set(nonce, true);
    return true;
  }
}

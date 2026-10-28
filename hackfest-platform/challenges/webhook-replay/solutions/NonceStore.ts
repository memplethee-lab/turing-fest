// Reference solution for editable/NonceStore.ts — NOT shipped to teams.
//
// The vulnerable version created `const seen = new Map()` INSIDE
// checkAndRecord, so the map was thrown away on every call and never actually
// remembered anything — every replay of the same nonce was accepted. The fix:
// hoist the map to an instance field so it lives as long as the shared
// NonceStore instance does.
export class NonceStore {
  private readonly seen = new Map<string, boolean>();

  checkAndRecord(nonce: string): boolean {
    if (this.seen.has(nonce)) {
      return false;
    }
    this.seen.set(nonce, true);
    return true;
  }
}

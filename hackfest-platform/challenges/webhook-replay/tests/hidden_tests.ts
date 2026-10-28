/**
 * Hidden grading suite. The team never sees this file — only its pass/fail
 * output, as one JSON line, via verify.sh.
 *
 * Mirrors the two bug classes the real lab challenge taught:
 *   1. unit mismatch in isFresh (seconds vs ms)
 *   2. NonceStore not actually persisting state across calls
 */
import { isFresh } from "../editable/Freshness";
import { NonceStore } from "../editable/NonceStore";

type Check = { check: string; pass: boolean };
const checks: Check[] = [];

function check(name: string, pass: boolean) {
  checks.push({ check: name, pass });
}

// --- Freshness: legitimate cases ---
const now = 1_700_000_000;
check(
  "a webhook timestamped right now is accepted",
  isFresh(String(now), now, 300) === true
);
check(
  "a webhook timestamped 60s ago is accepted within a 300s window",
  isFresh(String(now - 60), now, 300) === true
);

// --- Freshness: must be refused ---
check(
  "a webhook timestamped 10 minutes ago is refused with a 300s (5 min) window",
  isFresh(String(now - 600), now, 300) === false
);
check(
  "a webhook timestamped 10 minutes in the FUTURE is refused with a 300s window",
  isFresh(String(now + 600), now, 300) === false
);
check(
  // This is the one that catches the *1000 bug: an 83-hour-old webhook
  // must NOT pass a 300-second window, even though 83h * 1000 happens to
  // look "fresh" under the buggy math.
  "a webhook timestamped 83 hours ago is refused with a 300s window",
  isFresh(String(now - 83 * 3600), now, 300) === false
);
check(
  "a non-numeric timestamp is refused",
  isFresh("not-a-number", now, 300) === false
);

// --- NonceStore: must persist across calls on the same instance ---
const store = new NonceStore();
check(
  "the first time a nonce is presented, it is accepted",
  store.checkAndRecord("abc123") === true
);
check(
  "the SAME nonce presented again on the SAME instance is refused",
  store.checkAndRecord("abc123") === false
);
check(
  "a third presentation of the same nonce is still refused",
  store.checkAndRecord("abc123") === false
);
check(
  "a different nonce on the same instance is still accepted",
  store.checkAndRecord("xyz789") === true
);

const passed = checks.every((c) => c.pass);
console.log(JSON.stringify({ passed, checks }));
process.exit(passed ? 0 : 1);

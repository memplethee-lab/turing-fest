/**
 * Standalone, Docker-free grading test for the webhook-replay challenge.
 *
 * Why it exists: the judge worker (worker.py) grades a submission by copying
 * the team's files OVER the image's editable_dir, running verify.sh (which
 * execs `ts-node tests/hidden_tests.ts`), and parsing the LAST line of the
 * combined stdout+stderr as a single JSON object. That whole path normally
 * only runs inside a container. This script reproduces it on the host with
 * Node + ts-node so you can prove, before an event, that:
 *
 *   1. the VULNERABLE app/editable files FAIL the hidden tests (the challenge
 *      is not accidentally already-solved), and
 *   2. the organizer SOLUTIONS in solutions/ PASS them (the challenge is
 *      actually solvable), and
 *   3. the output honors the grader contract worker.py depends on: the final
 *      line is exactly one JSON object { passed: bool, checks: [...] }, and
 *      exit code is 0 on pass / nonzero on fail.
 *
 * Run:  node run_grading_tests.mjs   (from challenges/webhook-replay/)
 * Needs ts-node on the machine (npx ts-node); no network, no Docker.
 */
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));

let failures = 0;
const assert = (cond, msg) => {
  if (cond) {
    console.log(`  ok  - ${msg}`);
  } else {
    console.error(`  FAIL- ${msg}`);
    failures++;
  }
};

/**
 * Replicate the container's flat /app layout in a temp dir and run the real
 * hidden test suite against it, exactly as verify.sh does.
 *
 * @param {string[]} editableFiles filenames (relative to this challenge) to
 *        drop into the temp editable/ dir — the "submitted files".
 */
function gradeWith(editableFiles) {
  const tmp = mkdtempSync(join(tmpdir(), "webhook-replay-"));
  try {
    // /app/tests/hidden_tests.ts imports ../editable/{Freshness,NonceStore}
    cpSync(join(ROOT, "tests", "hidden_tests.ts"), join(tmp, "hidden_tests.ts"));
    // Carry the challenge's tsconfig (target ES2020) so numeric separators in
    // the test source transpile; ts-node would otherwise default to ES5.
    cpSync(join(ROOT, "app", "tsconfig.json"), join(tmp, "tsconfig.json"));
    mkdirSync(join(tmp, "editable"), { recursive: true });
    for (const f of editableFiles) {
      cpSync(join(ROOT, f), join(tmp, "editable", f.split("/").pop()));
    }
    const res = spawnSync("npx", ["--no-install", "ts-node", "--transpile-only", "hidden_tests.ts"], {
      cwd: tmp,
      encoding: "utf8",
      shell: process.platform === "win32", // npx is a .cmd on Windows
    });
    if (res.error) throw res.error;
    return { code: res.status, stdout: res.stdout || "", stderr: res.stderr || "" };
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

// Parse the way worker.py does: combined stdout+stderr, last line is the JSON.
function workerParse(stdout, stderr) {
  const combined = stdout + stderr;
  const last = combined.trim().split("\n").pop();
  try {
    return JSON.parse(last);
  } catch {
    return null;
  }
}

const contract = (parsed) =>
  parsed &&
  typeof parsed.passed === "boolean" &&
  Array.isArray(parsed.checks) &&
  parsed.checks.every((c) => typeof c.check === "string" && typeof c.pass === "boolean");

console.log("Scenario 1: VULNERABLE editable files (expect FAIL)");
let r = gradeWith(["app/editable/Freshness.ts", "app/editable/NonceStore.ts"]);
let p = workerParse(r.stdout, r.stderr);
assert(contract(p), "grader contract: last line is a valid {passed, checks} JSON");
assert(p && p.passed === false, "vulnerable submission does NOT pass");
assert(r.code !== 0, `nonzero exit code on fail (got ${r.code})`);

console.log("Scenario 2: organizer SOLUTIONS dropped over editable (expect PASS)");
r = gradeWith(["solutions/Freshness.ts", "solutions/NonceStore.ts"]);
p = workerParse(r.stdout, r.stderr);
assert(contract(p), "grader contract: last line is a valid {passed, checks} JSON");
assert(p && p.passed === true, "reference solution passes every check");
assert(r.code === 0, `zero exit code on pass (got ${r.code})`);

console.log(failures === 0 ? "\nALL GRADING TESTS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);

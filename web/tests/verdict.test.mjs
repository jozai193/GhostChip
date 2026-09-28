import test from "node:test";
import assert from "node:assert/strict";
import { assertionSummary, PERSISTED_INTEGRITY_MESSAGE, repairVisualState, visualVerdict } from "../lib/verdict.mjs";

test("ERROR cannot be rendered as a pass", () => {
  assert.deepEqual(visualVerdict("ERROR"), { label: "ERROR", tone: "error" });
  assert.notEqual(visualVerdict("ERROR").tone, visualVerdict("PASS").tone);
});

test("assertion counts are copied from the actual result", () => {
  assert.deepEqual(assertionSummary({ assertion_passed: 11, assertion_total: 13 }),
                   { passed: 11, total: 13, text: "11/13 scenario assertions" });
});

test("repair states keep proposal, compile, verification failure, and verified distinct", () => {
  assert.deepEqual(repairVisualState("VERIFIED"), { label: "VERIFIED REPAIR", tone: "pass" });
  assert.deepEqual(repairVisualState("PERSISTED_RECORD_INTEGRITY_ERROR"),
                   { label: "ERROR", tone: "error" });
  assert.deepEqual(repairVisualState("VERIFICATION_FAILED"), { label: "VERIFICATION FAILED", tone: "fail" });
  assert.deepEqual(repairVisualState("COMPILE_ERROR"), { label: "COMPILE ERROR", tone: "error" });
  assert.deepEqual(repairVisualState("EXPIRED"), { label: "RESTART REQUIRED", tone: "error" });
  assert.deepEqual(repairVisualState("INTERRUPTED"), { label: "VERIFICATION INTERRUPTED", tone: "error" });
  assert.notEqual(repairVisualState("VERIFICATION_FAILED").tone, repairVisualState("VERIFIED").tone);
  assert.notEqual(repairVisualState("PERSISTED_RECORD_INTEGRITY_ERROR").tone,
                  repairVisualState("VERIFIED").tone);
});

test("persisted integrity failures use the required user-facing message", () => {
  assert.equal(PERSISTED_INTEGRITY_MESSAGE,
               "Stored verification record failed integrity checks.");
});

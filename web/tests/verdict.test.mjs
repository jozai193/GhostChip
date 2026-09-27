import test from "node:test";
import assert from "node:assert/strict";
import { assertionSummary, visualVerdict } from "../lib/verdict.mjs";

test("ERROR cannot be rendered as a pass", () => {
  assert.deepEqual(visualVerdict("ERROR"), { label: "ERROR", tone: "error" });
  assert.notEqual(visualVerdict("ERROR").tone, visualVerdict("PASS").tone);
});

test("assertion counts are copied from the actual result", () => {
  assert.deepEqual(assertionSummary({ assertion_passed: 11, assertion_total: 13 }),
                   { passed: 11, total: 13, text: "11/13 scenario assertions" });
});

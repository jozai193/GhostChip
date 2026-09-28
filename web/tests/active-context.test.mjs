import test from "node:test";
import assert from "node:assert/strict";
import {
  acceptsRepair, acceptsRun, bindRepair, bindRun, canApplyRepair, nextGeneration, sameGeneration,
} from "../lib/active-context.mjs";

test("a stale run response cannot bind after selecting another case", () => {
  const humidity = nextGeneration(null, "humidity_x4");
  const active = nextGeneration(humidity, "buggy_driver");
  assert.equal(sameGeneration(active, humidity), false);
  assert.equal(bindRun(active, humidity, "old-run"), null);
});

test("a stale repair poll cannot replace the active run or repair", () => {
  const first = bindRun(nextGeneration(null, "buggy_driver"),
    { generation: 1, caseId: "buggy_driver" }, "run-a");
  const withRepair = bindRepair(first, first, "repair-a");
  const secondGeneration = nextGeneration(withRepair, "humidity_x4");
  const second = bindRun(secondGeneration, secondGeneration, "run-b");
  assert.equal(acceptsRun(second, first), false);
  assert.equal(acceptsRepair(second, withRepair), false);
});

test("a delayed or duplicate apply response is accepted only for its exact repair", () => {
  const generation = nextGeneration(null, "buggy_driver");
  const run = bindRun(generation, generation, "run-a");
  const repair = bindRepair(run, run, "repair-a");
  assert.equal(acceptsRepair(repair, repair), true);
  assert.equal(acceptsRepair({ ...repair, repairId: "repair-b" }, repair), false);
  assert.equal(acceptsRepair(nextGeneration(repair, "adxl345_regression"), repair), false);
  assert.equal(canApplyRepair(repair, repair, "PROPOSED", false), true);
  assert.equal(canApplyRepair(repair, repair, "PROPOSED", true), false);
  assert.equal(canApplyRepair(repair, repair, "APPLYING", false), false);
});

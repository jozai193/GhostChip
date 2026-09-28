# Stage 6 bounded repair workflow

Stage 6 adds one curated, inspectable repair path for the existing BME280 humidity-latch failure. It does not add arbitrary repository repair or autonomous changes. The governing rule is:

> A provider may propose a driver patch. Only deterministic recompilation and re-execution against the unchanged reviewed oracle can verify it.

## End-to-end flow

1. Run `buggy_driver`; its immutable result must be `FAIL`.
2. `POST /api/runs/{run_id}/repair` builds and schema-validates a bounded request.
3. A `RepairProvider` returns an explanation, unified diff, file list, optional confidence, and provider/model identity.
4. GhostChip validates the response schema and applies the diff in memory to prove it is well formed and within policy.
5. The UI shows the provider kind, explanation, exact diff, source, evidence, and changed-line count. The proposal remains **NOT YET VERIFIED**.
6. Only an explicit **Apply & verify** request creates a derived source artifact.
7. GhostChip recompiles that artifact and reruns the same reviewed bundle and Scenario.
8. It records identity equality and shows VERIFIED only for deterministic PASS.

The alternative **Discard** action writes no source. The repository fixture is never overwritten by either path.

## Bounded request and proposal contracts

`schema/repair-request-v1.schema.json` requires the failed-run result hash, exact failed assertion and trace, accepted rule semantics, bounded datasheet evidence, one complete controlled source file, reviewed bundle/DeviceSpec/Scenario/compiler identities, and explicit constraints. The request includes neither the repository nor unrelated project files.

`schema/repair-proposal-v1.schema.json` requires one textual unified diff, exactly declared touched files, an explanation, and provider identity. GhostChip computes request, response, patch, original-source, and resulting-source hashes itself. Confidence, when present, never affects verification.

## Provider status

`RepairProvider.propose(request)` is the vendor-neutral boundary. This repository ships only `LocalDemoRepairProvider`, a deterministic offline fixture for the curated demo and tests. It is labeled **OFFLINE DEMO PROVIDER · NOT AI** in the UI and uses model identity `deterministic-rule-v1`. No live provider or credential handling is shipped in Stage 6; selecting an unsupported provider fails with `PROVIDER_UNAVAILABLE`.

A future live provider must remain environment-configured, return the same strict proposal contract, receive no more context than this request, and retain no authority over the verdict.

## Patch policy and oracle protection

The only allowed path is `examples/bme280_buggy.c`. The patch is limited to four changed lines and 4096 bytes. Validation rejects:

- absolute paths, backslashes, `..`, or non-normalized paths;
- multiple files or a provider file list that disagrees with the diff;
- binary patches, renames, file creation, or deletion;
- empty or context-mismatched hunks;
- DeviceSpecs, Scenarios, FaultPlans, reviewed bundles, extraction/review/evidence artifacts, tests, verifier/runtime code, build-integrity metadata, and all `third_party/` Bosch files.

The proposal therefore cannot edit an expected assertion to manufacture PASS. These restrictions are enforced before display and again implicitly by writing only the validated derived source.

## Identity and audit record

The derived artifact records the original source hash, patch hash, and resulting source hash. The audit binds the original run and failed assertion IDs to request/provider/response hashes, compile result, executable hash, reviewed model identity, Scenario identity, rerun result, final status, and source-preservation check.

Re-execution compares:

- reviewed-bundle hash;
- DeviceSpec hash;
- Scenario hash;
- compiler path, version, target, and flags;
- instance identity (`not_applicable` for this fixture);
- FaultPlan identity (`not_applicable` for this fixture).

A mismatch fails closed as `VERIFICATION_ERROR`. A successful compile with a failing Scenario is `VERIFICATION_FAILED`; a compile failure is `COMPILE_ERROR`. Timeout, unavailable provider, malformed response, invalid/forbidden diff, and discard remain distinct non-VERIFIED states.

## API

- `POST /api/runs/{run_id}/repair` — create and generate a proposal for one failed immutable curated run.
- `GET /api/repairs/{repair_id}` — poll status and inspect the bounded public record.
- `POST /api/repairs/{repair_id}/apply-and-verify` — explicit approval, derived compilation, and rerun.
- `POST /api/repairs/{repair_id}/discard` — discard a validated proposal without applying it.

Public records omit the full source-bearing internal request and derived source text. They expose the minimum UI projection plus hashes and audit data.

## Honest limitations

This proves the repair-control boundary for one small, repository-owned C fixture. It does not prove patch quality for arbitrary code, secure execution of untrusted uploads, a live model integration, silicon fidelity, general autonomous repair, or that a passing reviewed abstraction is physically correct. The pristine Bosch SensorAPI is evidence for driver integration and remains outside the repair allowlist.

# Stage 7 remediation: deterministic repair integrity

This remediation closes the four P1 findings in the independent Stage 7 audit. It does not add a new product stage or broaden the supported device surface.

## Trusted execution closure

Every deterministic proof result now records `execution-closure-v1`. The closure contains SHA-256 identities for the proof runner, generic runtime, validators, review/extraction path, API/repair orchestration, relevant JSON Schemas, `gc_hal.c`, `gc_hal.h`, and the resolved compiler executable. Compiler path, binary hash, version, target, and normalized flags are recorded together.

Repair creation requires the current source and execution closure to match the failed run. Apply reservation checks them again. Verification compiles a frozen candidate and copied HAL sources from an immutable per-repair snapshot, then checks the live closure, snapshot, original source, and repair lineage again after the run. Any mismatch produces an error; it cannot produce `VERIFIED`.

This is a local integrity and drift-detection boundary. SHA-256 records are not signatures, the runner is not a security sandbox, and GhostChip does not claim protection from a hostile host that can rewrite the program and its records together.

## Frozen lineage

A repair record binds these identities end to end:

- repair, request, proposal, and failed-run IDs;
- exact canonical request bytes and request SHA-256;
- failed result SHA-256 and exact original source bytes/hash;
- trusted provider identity from provider configuration;
- exact canonical provider-response bytes/hash and normalized proposal hash;
- displayed unified-diff bytes/hash;
- recomputed derived source bytes/hash;
- reviewed bundle, specification, Scenario, compiler, and execution-closure identities;
- execution-snapshot manifest and final executable hash.

The provider response may repeat its identity, but it cannot define it. A contradiction between response metadata and trusted provider configuration is rejected before a proposal can be displayed. `live_ai` origin labels are derived only from the frozen trusted identity.

The provider interface currently returns a dictionary rather than transport bytes. “Raw provider response bytes” therefore means the first canonical UTF-8 JSON serialization at the provider boundary, saved before schema validation or enrichment. The normalized proposal is independently hashed. New proposals keep this identity only at the record level; the redundant proposal-level normalized hash was removed. A matching legacy copy remains readable, but a mismatched copy fails validation.

## Persisted-record integrity

`validate_persisted_repair` is the authoritative cold-read boundary for stored repair JSON. It validates state-appropriate evidence before a record is admitted to memory and before restart transitions are applied. It distinguishes proposal, applying, verified, failed, error, discarded, expired, and interrupted states rather than requiring verification artifacts from records that have not run.

For `VERIFIED`, the validator recomputes request, provider-response, proposal, diff, original-source, and derived-source identities; checks the repair/request/proposal/run binding; cross-checks the reviewed bundle, model, Scenario, compiler, execution closure, staged HAL, snapshot manifest, resulting source, executable, and optional instance/FaultPlan identities; and requires a matching `PASS` verification and `VERIFIED` audit. Every frozen Scenario assertion must be present, and its `passed` flag is recomputed with the comparator semantics used by the runner. An assertion whose expected and actual values differ cannot remain marked passed.

`VERIFICATION_FAILED` must contain a real failed assertion and a matching failed audit. `COMPILE_ERROR` cannot contain a successful executable. `VERIFICATION_ERROR` cannot carry partial or successful terminal evidence, and non-executed states cannot carry verification/audit artifacts.

Invalid persisted JSON is not normalized, rewritten, or returned under its stored status. The store raises `PERSISTED_RECORD_INTEGRITY_ERROR`; repair GET/apply/discard endpoints return HTTP 409 with that top-level status and no misleading `VERIFIED`. The frontend renders it as `ERROR` with “Stored verification record failed integrity checks.”

## Atomic apply and restart policy

`POST /api/repairs/{id}/apply-and-verify` synchronously validates the complete lineage, creates the execution snapshot, atomically changes the in-memory state from `PROPOSED` to `APPLYING`, and persists that reservation before returning HTTP 202. Only the reservation owner can start the worker. A second click, concurrent request, retry after a lost response, apply after discard, or apply after any terminal state receives HTTP 409. Exactly one deterministic verification is launched.

Restart behavior is deliberately non-resumable:

- persisted `GENERATING` or `PROPOSED` records become `EXPIRED / RESTART_REQUIRED`;
- persisted `APPLYING` records become `INTERRUPTED / RESTART_REQUIRED`;
- terminal records remain readable after internal consistency validation.

A user must generate a fresh repair after a restart. GhostChip never resumes a half-complete verification or silently reuses a proposal from an earlier process.

## Frontend active context

The judge UI tracks one active `{generation, case_id, run_id, repair_id}` context. Selecting or starting another case increments the generation, aborts in-flight fetches, and clears polling timers. Run, trace, repair, and apply responses update the UI only when every available identity matches the active context. The Apply button is disabled while its reservation request is pending.

This prevents a delayed humidity response from being shown under a different selected case and prevents stale repair or apply responses from replacing the active run.

## Regression gates

The remediation tests reproduce the Stage 7 counterexamples: verifier/runtime/validator/schema/HAL drift, source drift before request construction, mutation of every lineage hash, displayed-diff and hidden-derived-byte changes, run A/B rebinding, provider spoofing, provider mutation after reservation, contradictory persisted status/audit/verification/assertions, missing terminal payloads, altered executable/model/Scenario/compiler/closure/snapshot/source identities, legacy normalized-hash mismatch, concurrent store/API apply, restart states, stale run/repair/apply UI contexts, and duplicate apply suppression. Valid persisted `VERIFIED` and `VERIFICATION_FAILED` records remain readable.

Run the release checks from the repository root:

```powershell
wsl -d Ubuntu --cd '/mnt/e/LovHack season 3 hackathon' --exec .venv-wsl/bin/python -m unittest discover -s tests -v
cd web
npm test
npm run build
```

Final verification on 2026-09-28:

- backend: 112/112 passed;
- frontend: 7/7 passed and the production Next.js build completed;
- clean source: 108 passed with four intentional optional-PDF skips, followed by the expected BME280 FAIL→PASS pair and all seven Bosch case outcomes;
- focused ADXL345 compiled proof: 4/4 passed;
- readiness smoke: Bosch source `VERIFIED`, flagship `PASS`, repair `VERIFIED`;
- real browser repair flow: final `VERIFIED` at 390×844 and 1440×1000, no horizontal overflow, console errors, or console warnings.

For a `VERIFIED` repair, GhostChip validates both fresh execution and persisted-record consistency across the failed run, approved proposal, derived source, trusted provider configuration, reviewed model, Scenario, and relevant execution/verifier/build closure. This remains local integrity and drift detection—not remote attestation, hostile-host protection, sandboxing, signed provenance, or a fully hermetic build guarantee.

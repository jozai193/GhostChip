# Gated checklist

- [x] **1. Audit architecture and scope**
  Spec ref: `Brief 8, 24; user's limited request`
  What to build: architectural decisions and boundaries.
  Acceptance: behavior, intent, provenance and execution are separate.
  Verify: `docs/architecture.md`.

- [x] **2. Finalize DeviceSpec v1**
  Spec ref: `Brief 9`
  What to build: closed schema, transition semantics and semantic validator.
  Acceptance: malformed, ambiguous or unsupported input is rejected.
  Verify: `python3 -m unittest discover -s tests -v`.

- [x] **3. Pin reviewed BME280 evidence**
  Spec ref: `Brief 14, 28`
  What to build: source hash, exact pages and manual-origin provenance.
  Acceptance: source matches hash; latch semantics match vendor text.
  Verify: local PDF hash test and manual section review.

- [x] **4. Prove deterministic compiled FAIL to PASS**
  Spec ref: `Brief 24, milestone 1`
  What to build: generic event runtime, live C HAL, two driver fixtures.
  Acceptance: same scenario/model yields expected pair; mutations cannot trivially pass.
  Verify: `python3 -m ghostchip.proof` and regression suite.

- [x] **5. Validate evidence extraction for the BME280 proof slice**
  Spec ref: `Brief 10`
  What to build: page-preserving ingestion and candidate extraction.
  Acceptance: the required latch behavior is recovered with two-page provenance; missing prose emits no rule; reviewed extracted output drives the existing proof.
  Verify: `tests/test_extraction.py`, `docs/extraction.md`, and the extracted proof artifact. Broader BME280 behavior coverage remains intentionally open.

- [x] **6. Prove second-device semantics**
  Spec ref: `Brief 5`
  What to build: reviewed ADXL345 read-clear and bypass models plus stimuli.
  Acceptance: two real rules and one compiled scenario with generic runtime.
  Verify: `tests/test_adxl345.py`, `docs/generalization.md`, and the ADXL345 proof artifact.

- [ ] **7. Adapt an existing driver**
  Spec ref: `Brief 13`
  What to build: documented callbacks, source/license record and completion contract.
  Acceptance: live reads affect driver branches; adapter preserves behavior.
  Verify: implementation-plan gate 4.

- [ ] **8. Connect the full pipeline**
  Spec ref: `Brief 19, 22`
  What to build: orchestration over validated immutable artifacts.
  Acceptance: PDF to result without hidden manual model edits.
  Verify: implementation-plan gate 5.

- [ ] **9. Add UI and optional repair**
  Spec ref: `Brief 15, 17`
  What to build: real trace/evidence/diff views and same-scenario rerun.
  Acceptance: understandable flow; no unsupported verification badge.
  Verify: implementation-plan gates 6–7.

- [ ] **10. Package and submit**
  Spec ref: `Brief 21, 26, 29`
  What to build: constrained hosted demo, reproducible deployment and honest submission.
  Acceptance: public links and demonstrated capabilities match submitted claims.
  Verify: implementation-plan gate 8 and fresh event-rules audit.

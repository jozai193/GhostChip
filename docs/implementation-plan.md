# Implementation plan — gated, not authorization to continue

Gates 0–3, including the bounded BME280 extraction and ADXL345 generalization milestones, are complete. Effort estimates below are focused engineering hours, not delivery promises; team availability, model/API access and hosting budget have not been assumed. Event deadline is October 5, 2026, 09:15 IST. Stop or narrow if the remaining gates cannot fit actual capacity.

| Gate | Scope and dependencies | Exit evidence / decision | Estimate |
|---|---|---|---|
| 0 — done | Audit, DeviceSpec v1, source-pinned manual BME280 slice, live compiled C FAIL→PASS. | Original regression baseline remains green and unchanged in behavior. | Completed |
| 1 — done | Deterministic PDF ingestion: file limits, SHA-256, page-indexed normalized text, retained original PDF, reviewed gold page fragments. | Pinned source and layout-whitespace mutation recover the same candidate; source changes cannot overwrite reviewed output. | Completed |
| 2 — proof slice done; breadth open | Candidate semantic extraction behind an untrusted-artifact boundary; CLI review. | The latch transition plus required register semantics are recovered and drive the existing proof. The original three-behavior breadth target is not met: reset commands and measurement-mode semantics remain unsupported rather than guessed. No probabilistic model is currently used. | Partial |
| 3 — done | Second-device design test: ADXL345 selective read-clear and FIFO bypass flush; explicit test-only stimuli; reviewed extraction. | Two independently sourced rules drive compiled C FAIL→PASS without a device branch. DeviceSpec v1 required no revision. | Completed |
| 4 — done | Integrate the pinned Bosch BME280 SensorAPI using its documented read/write/delay callbacks, including wrong-ID and callback-failure branches. | Pristine core hashes verified; all mandatory cases and negative controls pass; compiler, closure, binary, model, scenario, instance and fault identities are recorded. | Completed |
| 5 — CLI slice done | End-to-end orchestration for PDF → candidate → accepted model → fixture driver → result. API/database remain deferred. | CLI path runs without a hidden model edit; unreviewed models cannot execute and changed candidates invalidate review. Real-driver orchestration still depends on gate 4. | Partial |
| 6 | Minimal UI over genuine artifacts: source/rules, trace/failure, diff/rerun. Curated public drivers. | A new viewer can identify the failure, evidence and changed effective setting without opening code. Responsive/browser checks. | 8–12 h |
| 7 | Optional repair suggestion. Depends on stable failure artifacts. A deterministic prewritten diff is acceptable if clearly labeled. | User can inspect patch; identical model/scenario rerun; test weakening cannot produce “verified repair.” | 3–5 h |
| 8 | Reproducibility and presentation. | Clean environment, accessible deployment and real browser checks, short demo video, build-period/license disclosure; all claims match capabilities. | 6–8 h |

Stop after Stage 4. The recommended next milestone is an independent fidelity gate: compare the bounded reset/configuration traces and selected state outcomes against either physical BME280 hardware or a separately maintained trusted reference, before spending time on frontend polish. AI repair, arbitrary uploads, SPI, broad timing, accounts and collaboration remain lower priority than oracle fidelity.

## Proposed second reference device: ADXL345

Choose ADXL345 before MCP23017 for the first generalization attempt. Its [official Rev. G datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL345.pdf) gives two useful behaviors that differ from BME280's write latch:

1. Page 27, `INT_SOURCE` (0x30): reading clears selected event bits, while data-related bits have different clearing conditions. Test that a read returns the pre-clear value and only the appropriate bits clear. Do not simplify the whole byte into read-to-clear.
2. Page 21, FIFO bypass/trigger discussion: entering bypass empties FIFO. Test that a seeded queue/occupancy is cleared when changing into bypass and that returning to trigger mode does not resurrect samples.

These behaviors are now implemented as a reviewed extracted slice; see `docs/generalization.md`. Deterministic stimuli and occupancy observations use a separate test interface, not invented driver-accessible registers or false reset values. Full FIFO sampling, acceleration physics and interrupt timing remain outside this experiment. MCP23017 banking/sequential-address behavior is a useful later stress test, but would immediately expand transport/addressing scope.

## Decisions retained

- Interpreted validated IR first; no generated Python or C from model output.
- Native C on Linux/WSL for the proof; no ISA emulator yet.
- One Python package until stable boundaries justify separately versioned packages.
- Public demo uses curated code unless deployment isolation is independently demonstrated.
- Source extraction, scenario correctness and model execution are separate acceptance gates.
- Freeze a small honest v1 now. Future semantic additions are explicit versioned work, not silently supported fields.

# Implementation plan — gated, not authorization to continue

Gates 0–7, including the bounded BME280 extraction, ADXL345 generalization, Bosch integration, judge UI, and curated repair workflow, are complete. Effort estimates below are focused engineering hours, not delivery promises; team availability, model/API access and hosting budget have not been assumed. Event deadline is October 5, 2026, 09:15 IST.

| Gate | Scope and dependencies | Exit evidence / decision | Estimate |
|---|---|---|---|
| 0 — done | Audit, DeviceSpec v1, source-pinned manual BME280 slice, live compiled C FAIL→PASS. | Original regression baseline remains green and unchanged in behavior. | Completed |
| 1 — done | Deterministic PDF ingestion: file limits, SHA-256, page-indexed normalized text, retained original PDF, reviewed gold page fragments. | Pinned source and layout-whitespace mutation recover the same candidate; source changes cannot overwrite reviewed output. | Completed |
| 2 — proof slice done; breadth open | Candidate semantic extraction behind an untrusted-artifact boundary; CLI review. | The latch transition plus required register semantics are recovered and drive the existing proof. The original three-behavior breadth target is not met: reset commands and measurement-mode semantics remain unsupported rather than guessed. No probabilistic model is currently used. | Partial |
| 3 — done | Second-device design test: ADXL345 selective read-clear and FIFO bypass flush; explicit test-only stimuli; reviewed extraction. | Two independently sourced rules drive compiled C FAIL→PASS without a device branch. DeviceSpec v1 required no revision. | Completed |
| 4 — done | Integrate the pinned Bosch BME280 SensorAPI using its documented read/write/delay callbacks, including wrong-ID and callback-failure branches. | Pristine core hashes verified; all mandatory cases and negative controls pass; compiler, closure, binary, model, scenario, instance and fault identities are recorded. | Completed |
| 5 — CLI slice done | End-to-end orchestration for PDF → candidate → accepted model → fixture driver → result. API/database remain deferred. | CLI path runs without a hidden model edit; unreviewed models cannot execute and changed candidates invalidate review. Real-driver orchestration still depends on gate 4. | Partial |
| 6 — done (Stage 5) | Minimal UI over genuine artifacts: source/rules, source identity, trace, failure/pass/error, curated reruns. | A new viewer can identify the failure, evidence and changed effective setting without opening code. Production build, 1440px and 390px browser checks, real PASS and FAIL flows, and smoke test passed. | Completed |
| 7 — done (Stage 6) | Bounded repair suggestion over one stable failure artifact, with a deterministic provider clearly labeled not AI. | User inspects the patch; explicit approval creates only derived source; identical model/Scenario rerun; test weakening and Bosch modification reject; VERIFIED requires deterministic PASS. | Completed |
| 8 — milestone checks done; submission open | Reproducibility and presentation. | Clean-source reproduction, real browser checks, concise demo script, build-period/license disclosure; public deployment/video/submission remain separate authorized work. | Partial |

Stop after Stage 6. Stage 7 is reserved for an independent adversarial audit. An independent hardware/reference fidelity check remains the highest claim-risk gate before final submission, but it is separate from this product milestone. Arbitrary uploads, SPI, broad timing, accounts, collaboration, autonomous repair, and general repository patching remain out of scope.

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

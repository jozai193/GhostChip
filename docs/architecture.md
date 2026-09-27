# GhostChip architecture audit — 2026-09-27

Decision: the bounded execution proof remains valid, and a page-preserving BME280 extraction slice now feeds it. The architecture is viable for a reviewed, partial peripheral model. Reliable automatic interpretation of arbitrary datasheets remains unproven.

The full supplied brief (sections 0–36 and introductory material) was read. Its priorities are sensible, but its proposed scope combines several separate research and engineering risks. A broad package tree, API, database and UI would conceal those risks before resolving them.

## Corrected component boundaries

```text
Now: PDF bytes → page evidence → pending candidate → validation → hash-bound review
                                                        ↓
                                  reviewed, immutable DeviceSpec v1
                                                        ↓
Compiled C fixture ↔ synchronous HAL RPC ↔ generic register runtime
                                                        ↓
                        trace + final modeled state + separate Scenario contract
                                                        ↓
                              deterministic PASS / FAIL / ERROR
Later: failure + evidence → proposed patch → same model and scenario → rerun
```

Use one Python package now, separated by modules: `spec` validates, `runtime` owns transitions, `proof` owns compilation and test evaluation. Keep the schema and fixture data outside runtime code. Later add extraction and API adapters around these boundaries. FastAPI, Next.js and SQLite remain reasonable options, but are not dependencies of this proof.

### Material corrections to the brief

1. **A hardware rule is not a driver requirement.** Pending humidity configuration is a valid hardware state. The completion scenario requires effective oversampling code 3 when configuration returns successfully. Merely ending a trace after `ctrl_hum` must not create a universal sequence violation. Driver intention cannot reliably be inferred from bus traffic alone.
2. **Deterministic does not mean physically correct.** A wrong model can consistently bless a wrong driver. Review source evidence separately from execution, and validate models against independent traces, vendor drivers or silicon before broader claims. PASS means the stated scenario passed on this model revision.
3. **Stored and effective state must differ.** Reading `ctrl_hum` back can succeed while its setting remains inactive. An ordinary register dictionary misses this bug. A same-value write to `ctrl_meas` still triggers latching; checking only changes is incorrect.
4. **Coverage must be executable.** Unknown registers, unsupported modes and unreviewed evidence cannot silently behave like zero-valued memory. They stop this proof with ERROR. This is a coverage limitation, not a claim that silicon NACKs those transactions.
5. **Do not fabricate electrical semantics.** The HAL models one byte-register read/write, not I²C waveforms, repeated starts, SPI, burst addressing or MCU execution. Neither timestamps nor physical bus errors are synthesized. Sequence numbers are logical order only.
6. **Review and repair must preserve identity.** A run needs hashes of model, scenario and code. Changing the model or weakening a test to make a repair pass is not verifying that repair. Disabled rules later require an explicit coverage reduction, not a reassuring PASS badge.
7. **A subprocess is not a security boundary.** This implementation executes only repository-owned examples. Time, output and memory limits help reliability but do not deny filesystem or network access. Public arbitrary-code compilation is outside scope.

## DeviceSpec decision

Finalize **DeviceSpec 1.0.0 / `i2c-reg8-events-v1`**, a small closed event language described in [devicespec-v1.md](devicespec-v1.md). It includes fields, reserved masks, reset defaults, internal state, read/write side effects, guards, provenance and model coverage. It contains no executable snippets or ambiguous prose assertions.

This deliberately reduces the brief's proposed universal IR. Native W1C/WO modes, timers, self-clearing delays, command reset, multiple address banks and multi-byte transport are not accepted v1 features. Adding them requires a versioned contract and tests; inventing their semantics now would not make v1 more complete. The included BME280 model is a sleep-only configuration slice, not a full BME280 emulator.

The test scenario is a separate trusted fixture, not an extracted datasheet fact. It names a checkpoint, optional bounded pre-run stimuli, and expected values. Stimuli represent external hardware/test setup and never become driver-visible bus operations. A future public Scenario schema and driver adapter manifest should be designed before accepting non-curated inputs.

## What this proof establishes

The original C fixture compiles and runs. Each read/write blocks for an actual reply from the Python peripheral model. Both driver variants check the chip ID, write the same values, read back humidity code 3, and return zero. The only functional fix is write ordering. The buggy run leaves effective code 0; the fixed run leaves code 3. No filename, source-text search, canned PASS value or LLM determines the verdict.

The validator, runtime, proof runner, and schema contain no BME280 or ADXL345 addresses/identifiers. Device-specific layout recognition is isolated in extraction adapters; device selection, register slice and coverage boundary live in visible requests. Relocation plus identifier-scan tests probe runtime separation. Reviewed extracted models reproduce both compiled FAIL→PASS pairs; vendor SDK compatibility, arbitrary-device generality and physical fidelity remain unproven.

## Alternatives and positioning

- [Renode's peripheral modeling guide](https://renode.readthedocs.io/en/latest/advanced/writing-peripherals.html) describes register fields, callbacks and generated register scaffolding with custom behavior. It is a credible future execution/export target. Bringing a complete platform into the first two-register proof adds integration work before the semantics are settled.
- [Zephyr's bus emulator framework](https://docs.zephyrproject.org/latest/hardware/emulator/bus_emulators.html) already runs drivers against I²C/SPI emulators. Prefer a Zephyr adapter later if real target drivers use Zephyr; do not claim pre-hardware driver execution itself is novel.

These sources establish adjacent capabilities, not a comprehensive novelty search. The unproven differentiation is evidence-backed semantic extraction connected to reproducible existing-driver tests. No claim of being first or uniquely capable is justified.

## Sources and event constraints

The [Bosch BME280 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf) was downloaded and SHA-256 pinned. Section 5.4.3, printed/PDF page 27, states the latch dependency; §5.4.5 cross-references it on page 28. The code uses code 3 for ×4, per Table 20 on page 28. Cover revision is 1.24 (February 2024); inner footers retain 1.23. The exact bytes, not the URL filename alone, identify the source. See fixture metadata.

The [current LovHack rules](https://lovhack-season-3.devpost.com/rules) confirm September 26–October 4 build dates, teams up to four, permitted AI tools and required disclosure of prior work. Deadline: October 4, 2026, 23:45 EDT = October 5, 09:15 IST. The [official overview search result](https://lovhack-season-3.devpost.com/) confirms 35/25/20/20 judging weights and a deAPI award. The overview's full page did not load reliably during this audit; its video/access/eligibility details and absence of tracks are not re-certified here. None affects the local proof. Do not build a sponsor integration merely for award eligibility.

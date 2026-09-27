# Stage 4 implementation handoff for Sol High

Planning checkpoint only, 2026-09-28 IST. Start from `8f852784fba00d9c2cefa64d8bf525e3e8b2a77c` plus the Stage 3 audit documents. Do not interpret this file as implementation already completed. Read [the independent audit](stage3-independent-audit.md) before changing code.

**Objective:** compile and execute a pinned external driver's unchanged core through its actual read/write/delay callbacks, including initialization, read-dependent branching, callback-error propagation and the existing humidity latch rule. No frontend, AI repair, MCU emulation, measurements, compensation verification, SPI or arbitrary driver uploads.

## Candidate decision

| Criterion | Bosch BME280 SensorAPI | Adafruit BME280 Library |
|---|---|---|
| License | BSD-3-Clause; preserve LICENSE and source notices | BSD 3-clause terms; preserve LICENSE and notices |
| External credibility | Official sensor-vendor C driver | Established external Arduino sensor library |
| Core changes | None expected; plain C already object-compiles on this host | Could keep core unchanged, but must supply Arduino, Wire/SPI and BusIO infrastructure |
| HAL connection | Public read, write and delay function pointers plus context | Adafruit I2C/SPI device classes and Arduino dependencies |
| Read-dependent branches | Chip-ID rejection, reset status and configuration mode branches | Chip-ID rejection, calibration/measurement status polling |
| Error paths | Explicit `BME280_E_COMM_FAIL`, `BME280_E_DEV_NOT_FOUND` and stored callback result | `begin` can fail, but ordinary `read8`/`write8` ignore BusIO operation return values |
| Reproducible build | One C translation unit and two local headers | C++ plus pinned transitive libraries and host shims |
| New claim | Real vendor initialization/configuration/error path with unchanged core | Real third-party library, but host emulation effort obscures the central proof |
| Hackathon feasibility | Best of the two, provided model expansion remains bounded | Weaker: more integration surface for a less direct callback-error proof |
| Runtime scope | Needs burst reads, reset boundary and explicit calibration values | Similar sensor model additions plus default sampling/Arduino behavior |

Sources inspected: [Bosch repository](https://github.com/boschsensortec/BME280_SensorAPI), [pinned Bosch implementation](https://github.com/boschsensortec/BME280_SensorAPI/blob/c90d419492e26dd95586598a794e65eb2760753a/bme280.c), [Bosch license](https://github.com/boschsensortec/BME280_SensorAPI/blob/c90d419492e26dd95586598a794e65eb2760753a/LICENSE), [pinned Adafruit implementation](https://github.com/adafruit/Adafruit_BME280_Library/blob/ef712e95147de926b4545e379f6296ad271529b5/Adafruit_BME280.cpp), [Adafruit dependencies](https://github.com/adafruit/Adafruit_BME280_Library/blob/ef712e95147de926b4545e379f6296ad271529b5/library.properties), [Adafruit license](https://github.com/adafruit/Adafruit_BME280_Library/blob/ef712e95147de926b4545e379f6296ad271529b5/LICENSE). Feasibility rankings are engineering judgments based on those sources, not upstream compatibility guarantees.

## Exact upstream identity

- Repository: `https://github.com/boschsensortec/BME280_SensorAPI`.
- **Selected commit: `c90d419492e26dd95586598a794e65eb2760753a`**, observed master tip; committer date 2024-11-05.
- The source banner says v3.5.1. Do **not** identify this commit as the `bme280_v3.5.1` tag: that tag resolves to `3ba9abb813660f900365b56e15cac5b7848bb6c4`. The selected newer commit includes upstream compilation fixes and was successfully object-compiled during this audit.
- License: **BSD-3-Clause**.
- Vendor exactly `bme280.c`, `bme280.h`, `bme280_defs.h`, `LICENSE` under `third_party/bosch_bme280/`. Keep README optionally as referenced documentation; no upstream example or platform code is needed.
- Intended modifications to those four files: **none**. Do not reformat or normalize line endings. Record downloaded bytes and hashes; configure Git attributes for byte preservation if necessary.

| File | SHA-256 of downloaded upstream bytes |
|---|---|
| `bme280.c` | `7de1e7d3082b85e90db1daa34573ba77553a7caf44e06e216de5216b7ed4fa12` |
| `bme280.h` | `6f144510e103f0ab1a24244a71f7ff8ab7f23147b4899aa7bfd0f526062d2163` |
| `bme280_defs.h` | `541bbd32498b8603bc8fe8eafac26b15d09fb032d37448ca88e7aa398d6a0769` |
| `LICENSE` | `8c966978a9f67992e824d0b76381eab42f240c0049881f7bf2b46c2c093191aa` |

The audit used `gcc -std=c11 -Wall -Wextra -Werror -O0 -c bme280.c` successfully. This confirms compilation feasibility only; no real-driver execution through GhostChip has yet occurred.

## 0. Correctness gate before integration

Implement these focused fixes first and preserve the old intended proof outcomes:

1. Add a reviewed-bundle loader at the runner boundary. It accepts the original pending candidate, matching review, extraction request and evidence anchors, validates hashes and recomputes the exact executable spec using `accept_review`. Require equality with any saved reviewed spec. Include source identities and bundle hashes in every run. Do not infer `automatic_extraction_reviewed` from editable origin strings. Manual baseline/synthetic models get explicit separate origins; there must be no silent fallback from rejected reviewed input to a raw model.
2. Extend review bundle metadata to bind request and anchors; version that envelope independently from DeviceSpec. Current golden tests can continue testing their legacy candidate hashes, but production runner inputs must cross the new gate. Change acceptance tests to use a genuine verified bundle. Keep negative-control model mutations explicitly unreviewed and never export their result as approved verification.
3. Require both ADXL interrupt evidence matches; missing page 19 overview gives an unresolved interrupt rule with no fabricated evidence and no unhandled exception. Add missing bypass-phrase and mode-encoding controls too.
4. Seed ADXL FIFO mode one before occupancy five; preserve FAIL/PASS and both rule-removal controls. Add a scenario-consistency check/test for this fixture.
5. Make extraction output publication atomic and content-addressed. Failed review must not leave an old executable model apparently paired with a new candidate. Fix the README environment command and stale build-log status wording.

Acceptance: the exact F1 changed-accepted-model reproduction is rejected **before compilation**, while pristine reviewed bundles run. A changed anchor/request or missing review cannot inherit approval. No production runtime device branches are introduced.

## 1. Vendor source and define one build target

Create `third_party/bosch_bme280/UPSTREAM.json` containing repository URL, exact commit, source banner version, license, each upstream path/URL/hash and `modifications: []`. Verify bytes against the table above.

Build one executable from pristine `bme280.c` plus `examples/bosch_bme280/adapter.c` and `main.c`. Use C11 and existing warning flags. Use Bosch defaults (I2C at runtime, default compensation compilation); do not redefine driver APIs, expose static internals, bypass `bme280_init`, or copy its algorithms. Record all flags and macro definitions.

Generalize the existing runner only enough to accept an explicit build target (source list, include paths, approved definitions and entrypoint). Preserve the original two-fixture CLI. Add a separate real-driver command such as `python -m ghostchip.real_driver --case init_ok`; the old CLI deliberately expects a FAIL/PASS pair and is not a suitable result aggregator for expected-error API tests.

Use compiler dependency output to identify actual compiled headers. Hash upstream files, adapter, entrypoint, all project dependency headers, compiler executable/version/target, command, resulting executable, runner/runtime/validator/schema, verified bundle, Scenario, instance data and FaultPlan. Record the source closure before building; use an immutable staged source snapshot or verify it again after building. Reject upstream hash mismatch before compilation. Never reuse an executable merely because its filename exists.

## 2. Adapter and observations

Initialize a `struct bme280_dev` with `BME280_I2C_INTF`, real read/write/delay callbacks and a context containing address 0x76. The adapter may translate callback buffers into bus RPCs; it may not provide sensor values, synthesize reset success, latch humidity, return canned API results or inspect the selected test case.

The test entrypoint calls the public `bme280_init(&dev)`, observes its actual signed return and `dev.intf_rslt`, and calls configuration only when initialization succeeds. In the successful configuration case, call:

```c
struct bme280_settings settings = {0};
settings.osr_h = BME280_OVERSAMPLING_4X;
result = bme280_set_sensor_settings(BME280_SEL_OSR_HUM, &settings, &dev);
```

Both macro names above were verified in the pinned header. Do not call private `set_osr_humidity_settings` directly.

Add explicit typed observations to the harness protocol, e.g. `api.init`, `api.configure`, `interface.result`, `chip_id`, and selected parsed calibration fields. Preserve signed `int8_t` API values: `-2` must not be confused with Unix exit 254. Normal harness exit zero means observations were emitted; assertions over observed API results determine case success. A crash, malformed protocol or missing observation is ERROR. `process_exit` alone is insufficient to prove upstream error propagation.

Keep protocol messages distinct from diagnostics. Current stderr is merged into protocol stdout; either separate stderr with the same output limit or use a dedicated protocol channel. Add a strict Scenario/observation schema with reference/type/range validation, nonempty assertions and declared required observations before compilation.

## 3. Minimal bus support and FaultPlan

Add bounded callback-level reads carrying start address and length. Preflight the complete range and maximum length before accessing memory. For these calibration banks, use documented incrementing register reads, preserve one callback transfer ID, and associate individual byte events with that transfer. Do not claim electrical I2C or general burst atomicity. A transfer with an unmodeled byte must be ERROR, not filled with zero.

The required path uses reads of lengths **1, 26 and 7**, and writes of length **1**. Bound lengths at an explicit maximum (e.g. 32 for this profile). Reject unsupported multi-byte writes. Bosch's optional multi-register write format interleaves register addresses and values; it is **not** ordinary auto-incrementing writes. Supporting that format is unnecessary for humidity-only configuration.

Fault injection belongs to a separate validated, hashed `FaultPlan`, not the HAL's case switch or DeviceSpec behavior. A fault names operation/address/register/occurrence and callback status; initially support one-shot failure before a whole callback transfer. Validate coverage first. A matching injected read failure returns a nonzero callback status without reading bytes or firing read effects. A failed write has no register/state effects. Record the injection and require it to fire exactly once when expected. OUT_OF_MODEL remains ERROR and must never be mapped to `BME280_E_COMM_FAIL` as a substitute for actual error testing.

## 4. Expand the reviewed BME280 slice honestly

Actual pinned upstream initialization sequence, read from `bme280.c`:

```text
read  0xD0, length 1           chip ID
write 0xE0, byte 0xB6          actual upstream soft reset
delay 2000 microseconds       actual upstream callback
read  0xF3, length 1           status / im_update
read  0x88, length 26          temperature/pressure bank, including H1
read  0xE1, length 7           humidity calibration bank
```

The existing three-register sleep slice cannot execute this. Do not drop reset/delay/calibration callbacks to force it through.

Create a separate `fixtures/bme280-sensorapi/` extraction request/golden/review/instance/cases directory. Preserve the Stage 2 three-register slice as regression coverage. Extract register locations/access/fields and reset semantics from the same pinned Bosch PDF. Relevant evidence: page 8 Table 1 (2 ms maximum startup), page 27 Table 18 and sections 5.4.1–5.4.3 (map, ID, reset and latch), page 28 status/ctrl_meas, pages 24–25 section 4.2.2 / Table 16 (calibration layout), and pages 32–33 incrementing reads versus address/data-pair writes. These source passages were inspected during the audit; the new extraction output still needs its own review.

Use a narrowly versioned **DeviceSpec 1.1.0 / `i2c-reg8-settle-v1` profile**, keeping all 1.0.0 behavior and fixtures unchanged. This is an explicit planned capability addition, not a claim that Stage 3 already supports startup. Limit additions to:

- **Parameterized instance bytes:** allow a register's initial/reset source to reference a required declared byte parameter instead of a literal. The reviewed template binds parameter IDs/widths/addresses; a separate hashed instance image supplies deterministic test values. Missing values reject execution. Calibration values are device-individual; the datasheet does not supply universal numeric defaults. Never label the chosen test image as extracted calibration values. The 26-byte upstream read includes an unused byte at 0xA0: Table 16 assigns it no coefficient, while the section describes the encompassing 0x88–0xA1 bank. Represent its chosen value explicitly as an opaque test input in that readable bank; do not invent a calibration coefficient or a guaranteed zero default for it.
- **A bounded settle interval:** an `after_write` rule may declare `settle_us`, with evidence and an explicit modeling basis. It applies its existing generic assignments and makes the device unavailable to further bus transactions until virtual elapsed microseconds reach the interval end. `advance_time_us(n)` only increments a bounded integer logical clock; it executes no device-specific Python and uses no wall-clock sleep. Access before settlement is OUT_OF_MODEL (coverage rejection, not an assertion that silicon NACKs). This is an observation-boundary abstraction, not simulation of every internal reset phase or a general event scheduler.
- **Declared incrementing read capability:** the model profile/transport metadata must explicitly permit the selected multi-byte reads and bound them. Do not change the semantics of 1.0.0 one-byte transactions silently.

For a matching `reset=0xB6` write, existing generic guarded field/state assignments reset the modeled configuration, effective humidity and status to the documented post-reset state; preserve the chosen device's NVM instance values. Apply a 2000-us settle interval before any subsequent observation. A later unconditional rule clears the stored reset word to zero, matching the documented constant zero readout. Non-0xB6 writes do not reset configuration or begin settling and still read back zero. Table 18 calls this a write-only reset register; section 5.4.2 explicitly defines zero readout, so document the use of a command byte plus effects rather than claiming ordinary storage semantics. No native W1C, physical reset waveform or general timing engine is needed.

The 2000-us interval is a **conservative supported observation boundary** derived from the maximum startup bound and the upstream wait. It does not assert that every chip takes exactly 2000 us or that earlier communication is necessarily wrong. Reset completion/status polling inside that interval is unsupported. If source review does not justify applying the startup bound to the complete soft-reset procedure, stop this model gate and report the evidence gap rather than hiding it in the adapter.

The delay callback must send its duration to the generic clock and be traced. A no-op delay is not acceptable. No Scenario stimulus is permitted after execution starts. All reset/configuration transitions stay in reviewed DeviceSpec rules. Keep mode constrained to sleep and omit measurement/data-register and compensation claims.

Extracted templates and manually supplied instance bytes must have distinct provenance labels. Any manually selected model abstraction (including the settle boundary) must be visibly declared in the request/review and resulting run. A mixed reviewed model must never receive a blanket fully-automatic origin badge.

## 5. Required executable cases

| Case | Controlled input | Required observations / acceptance |
|---|---|---|
| `init_ok` | Correct ID 0x60; deterministic nontrivial calibration image; no fault | Actual `bme280_init` returns 0; reset write, 2000-us delay, status read and 26/7-byte reads appear in order; parsed calibration fields equal independently calculated expectations; all callbacks hit GhostChip |
| `wrong_chip_id` | Same model/core/harness, ID stimulus 0x58 | Actual init result `BME280_E_DEV_NOT_FOUND` (-4); no reset, delay or calibration transfers; distinguish this explicit fault/identity stimulus from a normal BME280 reset default |
| `chip_id_bus_error` | Correct ID, injected first ID-read callback failure -1 | Callback observation -1; actual upstream `dev.intf_rslt=-1` and init result `BME280_E_COMM_FAIL` (-2); no later initialization transfers |
| `calibration_bus_error` | Fail first calibration transfer at 0x88 | Genuine reset/delay/status happened; actual init -2; no second calibration-bank read; no failed-read side effects |
| `humidity_x4` | Successful init, call public humidity-only settings API | Actual configuration result 0; runtime observes ctrl_hum=3 then ctrl_meas read/rewrite; effective humidity=3; same-value ctrl_meas write still fires the existing latch |
| `humidity_x4_no_latch` | Explicit unreviewed model negative control only | Same pristine driver and request; final effective humidity remains 0 and contract FAILS; never label this altered model approved |
| `reset_after_configuration` | Test entrypoint calls public soft reset after successful humidity configuration | Real command clears modeled pending/effective humidity and requires the traced delay; NVM instance unchanged; verifies reset is more than an ACK stub |
| Optional `mutated_missing_latch_write` | Separate derivative source artifact with exactly the final humidity latch write omitted | Build same harness/model/scenario; actual API can return success but effective-state assertion fails; preserve original upstream source and show exact mutation diff/hash |

These cases should use the same executable wherever possible, with the same entrypoint path `init; if success, optionally configure/reset`, and vary only separately hashed Scenario/instance/fault inputs. Assert callback sequence and API observations, not just a green final badge. One set of independently calculated signed/nontrivial calibration fields is sufficient; do not turn Stage 4 into validating sensor compensation mathematics.

The optional mutation must be called **“mutated test variant”**, never an upstream bug. Skip it if the mandatory cases are not yet reliable.

## 6. Acceptance gate

Stage 4 is complete only when all of these hold:

1. F1/F2/F3 regression tests pass and stale reviewed semantics cannot reach compiled execution.
2. Vendored upstream core bytes exactly match the pinned commit; changed source/header causes an integrity rejection before build.
3. The unchanged `bme280_init` really executes reset, wait, status and calibration reads through live callbacks. No canned replies live in the C adapter.
4. Correct/wrong ID cases take different actual upstream branches with trace evidence.
5. At least one actual callback failure produces observed upstream -2, with the intended callback status recorded; coverage errors remain ERROR.
6. Public humidity-setting API triggers the original extracted latch; effective-state assertion passes. The removed-rule negative control fails for the expected reason.
7. Calibration values and reset observation assumptions are explicit, hashed and honestly classified; early access, unsupported mode/address/length and missing instance parameter reject.
8. Generic settle/parameter/burst features have synthetic device tests proving no Bosch identifier/address dispatch is needed. Test partial delays (1999 then 1 us), repeat resets after settlement and no state leak across runs.
9. Every result identifies compiler/build inputs, dependency files, binary, model/review/request/anchor bundle, scenario, instance and fault plan. Unexpected process termination and missing observations are ERROR.
10. Existing 39 tests retain their intended coverage and both original FAIL/PASS proofs; do not preserve a flawed test merely to preserve its count. Report the new total honestly.
11. Run fresh real-PDF extraction with dependencies installed, and source-only reproduction including vendored C and golden fixtures with exactly documented PDF skips. No cached executable/generated model is required.
12. Commit the verified milestone and update build log, verification, scope and README with the exact command and limitations. No frontend or AI repair is added.

## Expected changes

| Path / module | Purpose |
|---|---|
| `third_party/bosch_bme280/{bme280.c,bme280.h,bme280_defs.h,LICENSE,UPSTREAM.json}` | Pristine pinned upstream plus provenance |
| `examples/bosch_bme280/{adapter.c,adapter.h,main.c}` | Thin callbacks and public API test entrypoint |
| `ghostchip/review.py` or equivalent focused addition to `extraction.py` | Verified review-bundle loading and atomic artifact identity |
| `ghostchip/adxl345_extraction.py`; ADXL scenario/tests | Missing-evidence and FIFO setup fixes |
| `schema/devicespec-v1.1.schema.json`; `spec.py`; `runtime.py` | Bounded parameters/settle profile, existing generic reset rules; maintain old profile |
| `ghostchip/bus.py`; optional shared C RPC helper | Transfer framing, typed observations, virtual delay and explicit fault injection |
| `ghostchip/proof.py`; `ghostchip/real_driver.py` | Multi-source target, signed observations and trustworthy build/run manifest |
| `schema/scenario-v1.schema.json`; `schema/fault-plan-v1.schema.json` | Validate test intent, observations and transport faults |
| `ghostchip/extraction.py` and/or focused BME extension adapter | Extended evidence-backed register/reset/instance template extraction |
| `fixtures/bme280-sensorapi/` | New request, golden evidence, review, parameter image and cases |
| `tests/test_review_integrity.py`, `test_bus.py`, `test_bosch_sensorapi.py`, existing tests | Targeted boundary/causality/integrity and regression coverage |
| `.gitattributes` if needed; `scripts/verify_clean.py`; README and docs | Byte preservation, reproduction and honest claims |

Do not restructure working packages merely to match these suggested names. Each production change must serve a listed acceptance requirement.

## Biggest risk, budget and stop conditions

**The biggest risk is accommodating initialization by quietly moving chip behavior into the adapter or hard-coded replies.** Reset readiness and calibration reads are the pressure points. The pristine driver can compile while the model remains a misleading mock. Keeping those semantics and assumptions visible is more important than the number of supported API calls.

Planning estimate: approximately **14–24 focused engineering hours**, including correctness fixes, model review, callback integration and regression verification; this is an estimate, not a deadline commitment. The earlier 6–10-hour integration estimate omitted the demonstrated review defect and initialization-model work.

Stop and report if the selected public APIs require a major scheduler, measurement simulation, upstream algorithm changes, synthetic success responses, or unsupported transfers beyond this slice. Do not silently substitute a hand-written mini-driver. Do not publish the broad judge claim until the mandatory cases pass.

After acceptance, the defensible statement is:

> GhostChip compiles Bosch's pinned BME280 SensorAPI unchanged at its core and connects its actual hardware callbacks to a reviewed, bounded virtual peripheral derived from the datasheet. We demonstrate real initialization, read-dependent branching, communication-error propagation and humidity latching, using explicit test calibration bytes and a scoped reset-settling model.

The user's shorter statement becomes defensible with those scope qualifications nearby. Stage 4 does **not** establish arbitrary datasheet extraction, all-driver compatibility, silicon equivalence, or discovery of a real upstream defect. Frontend work remains deferred until this acceptance gate is met.

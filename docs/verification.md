# Verification record — Stage 4

Environment: Ubuntu WSL, Python 3.12.3, GCC 13.3.0 targeting `x86_64-linux-gnu`, jsonschema 4.10.3, pypdf 6.1.1 and cryptography 50.0.1. Every real-driver run creates a fresh immutable staged source tree and executable.

## Correctness gate

- **F1:** the runner reconstructs candidate + review + extraction request + evidence anchors and compares any saved reviewed spec before compilation. Changed semantics, request, anchor, identity table, or missing bundle approval reject. Raw models require an explicit manual/unreviewed origin and cannot inherit an extracted-review badge.
- **F2:** missing ADXL345 page-19 overview evidence now emits an unresolved `interrupt_clear` record and no rule, rather than dereferencing a missing match.
- **F3:** the ADXL Scenario now seeds `fifo_mode=1` before five FIFO entries and then enters bypass. Buggy/fixed remains FAIL/PASS; removing the interrupt rule still makes buggy PASS and removing the FIFO rule still makes fixed FAIL.

## Bosch upstream and build identity

Repository `https://github.com/boschsensortec/BME280_SensorAPI`, commit `c90d419492e26dd95586598a794e65eb2760753a`, source banner v3.5.1, BSD-3-Clause. Vendored files have `modifications: []` and are checked before and after every build:

| File | SHA-256 |
|---|---|
| `bme280.c` | `7de1e7d3082b85e90db1daa34573ba77553a7caf44e06e216de5216b7ed4fa12` |
| `bme280.h` | `6f144510e103f0ab1a24244a71f7ff8ab7f23147b4899aa7bfd0f526062d2163` |
| `bme280_defs.h` | `541bbd32498b8603bc8fe8eafac26b15d09fb032d37448ca88e7aa398d6a0769` |
| `LICENSE` | `8c966978a9f67992e824d0b76381eab42f240c0049881f7bf2b46c2c093191aa` |

Build flags are `-std=c11 -Wall -Wextra -Werror -O0 -MMD`. No macro definitions alter upstream behavior. Compiler dependency output must include `bme280.h`, `bme280_defs.h`, and the GhostChip adapter header. The result records compiler path/hash/version/target, exact command, source/header closure, adapter, entrypoint and executable hashes. Deliberately changed upstream source or headers reject before compilation.

## Mandatory real-driver cases

| Case | Result | Observed upstream result | Callback evidence |
|---|---|---|---|
| `init_ok` | PASS | `api.init=0`, interface `0` | read D0/1; write E0/1; delay 2000 us; read F3/1; read 88/26; read E1/7 |
| `wrong_chip_id` | PASS | `api.init=-4`, interface `0` | only read D0/1; no reset, delay or calibration |
| `chip_id_bus_error` | PASS | `api.init=-2`, interface `-1` | injected first read D0 failure; no later callback |
| `calibration_bus_error` | PASS | `api.init=-2`, interface `-1` | reset/delay/status complete; injected read 88/26 failure; no E1 read |
| `humidity_x4` | PASS | init `0`, configure `0` | real public API reads F4, writes F2=3, reads and rewrites F4; effective humidity becomes 3 |
| `humidity_x4_no_latch` | expected FAIL | init `0`, configure `0` | same pristine driver; explicitly UNREVIEWED model lacks latch; effective-state assertion alone fails |
| `reset_after_configuration` | PASS | init/configure/reset all `0` | second real E0 reset + delay/status; pending/effective humidity return to 0; instance NVM preserved |

The nontrivial calibration image is classified `deterministic_test_instance`, not extracted data. Independent expected parses include `dig_t1=513`, `dig_t2=1027`, `dig_h1=26`, `dig_h2=26213`, `dig_h4=1673`, `dig_h5=1702`, and `dig_h6=107`.

## Falsification and negative controls

- Stale, changed or absent reviewed bundles cannot compile as approved.
- Missing observations, malformed Scenarios, unsupported lengths/ranges/writes, missing instance parameters, early settle access, unexpected callbacks/process exits, and unmodeled bytes become ERROR.
- FaultPlan failures are injected before a complete callback, cause no read/write effects, fire exactly once, and yield real upstream `-2`; OUT_OF_MODEL is never converted into a bus failure.
- Generic synthetic tests cover 26/7-style incrementing reads, 1999 + 1 us partial delay, repeat settle operations, fresh-run isolation, and instance completeness without Bosch identifiers or addresses in runtime/schema/validator.
- The original BME280 and corrected ADXL345 FAIL/PASS proofs remain intact, including causal rule-removal checks.

The final local suite ran **58/58 test methods passed** with both pinned PDFs present.

## Extraction and clean-source reproduction

The checked-in Stage 4 golden fragments and the full pinned Bosch PDF independently reproduce candidate SHA-256 `251d44cd1a12b75a9b7b85ba6e74a772f22dbaa6bc50294a7c6ecb6dde6ba189`. The full-PDF path is optional in a source-only copy and skips only when the ignored vendor PDF is absent.

`python3 scripts/verify_clean.py` copies source without `.git`, caches, virtual environments, artifacts or PDFs; runs the entire suite; rebuilds the original proof; then rebuilds and runs all seven real-driver cases. The clean copy produced **54 passes and four documented optional-PDF skips** across 58 test methods, followed by the expected legacy FAIL/PASS and all mandatory Bosch case outcomes. No cached executable or generated model is required.

## Claim boundary

Defensible: **GhostChip compiles Bosch's pinned BME280 SensorAPI unchanged at its core and connects its actual hardware callbacks to a reviewed, bounded virtual peripheral derived from the datasheet. We demonstrate real initialization, read-dependent branching, communication-error propagation and humidity latching, using explicit test calibration bytes and a scoped reset-settling model.**

Not established: arbitrary datasheet comprehension, arbitrary driver compatibility, physical/silicon equivalence, measurement or compensation behavior, general MCU emulation, or a real Bosch driver bug.

# GhostChip — reviewed virtual peripherals running real driver callbacks

GhostChip now compiles Bosch's pinned BME280 SensorAPI unchanged at its core and connects its actual read, write, and delay callbacks to a reviewed bounded virtual peripheral. Stage 4 demonstrates real initialization, wrong-ID branching, communication-error propagation, calibration parsing, humidity latching, and reset-after-configuration. It remains a bounded reviewed proof—not a complete sensor emulator, arbitrary driver platform, or frontend.

- [Architecture audit](docs/architecture.md)
- [DeviceSpec v1 contract](docs/devicespec-v1.md) and [machine-readable schema](schema/devicespec-v1.schema.json)
- [DeviceSpec 1.1 bounded additions](docs/devicespec-v1.1.md)
- [Five highest-risk assumptions](docs/risks.md)
- [Gated implementation plan](docs/implementation-plan.md)
- [Verification record](docs/verification.md)
- [Extraction boundary and artifacts](docs/extraction.md)
- [ADXL345 generalization and anti-hardcoding audit](docs/generalization.md)

## Run on this Windows machine

The existing Ubuntu WSL environment has Python 3.12.3, GCC and jsonschema 4.10.3. From PowerShell:

```powershell
wsl -d Ubuntu --cd '/mnt/e/LovHack season 3 hackathon' --exec .venv-wsl/bin/python -m ghostchip.proof
wsl -d Ubuntu --cd '/mnt/e/LovHack season 3 hackathon' --exec .venv-wsl/bin/python -m unittest discover -s tests -v
wsl -d Ubuntu --cd '/mnt/e/LovHack season 3 hackathon' --exec .venv-wsl/bin/python -m ghostchip.real_driver --case init_ok
```

On another Linux/WSL environment, install a C11 GCC toolchain and Python 3.10+, create a Python virtual environment, then:

```sh
python3 -m pip install -r requirements.txt
python3 -m ghostchip.extract fixtures/bme280/datasheet.pdf \
  --request fixtures/bme280/extraction-request.json \
  --review fixtures/bme280/extraction-review.json \
  --output-dir artifacts/bme280-extraction
python3 -m ghostchip.proof \
  --bundle artifacts/bme280-extraction/reviewed-bundle-<hash>.json \
  --output artifacts/bme280-extraction/proof.json
python3 -m ghostchip.proof
python3 -m unittest discover -s tests -v
python3 scripts/verify_clean.py
```

Run any mandatory real-driver case with:

```sh
python3 -m ghostchip.real_driver --case init_ok
python3 -m ghostchip.real_driver --case wrong_chip_id
python3 -m ghostchip.real_driver --case chip_id_bus_error
python3 -m ghostchip.real_driver --case calibration_bus_error
python3 -m ghostchip.real_driver --case humidity_x4
python3 -m ghostchip.real_driver --case humidity_x4_no_latch
python3 -m ghostchip.real_driver --case reset_after_configuration
```

The no-latch case is an explicitly **UNREVIEWED negative-control model** and is expected to report FAIL. Every other case is expected to PASS. Each invocation recompiles the pristine vendored core in a new temporary directory, verifies upstream hashes before and after the build, and records compiler, dependency, executable, model-bundle, Scenario, instance, FaultPlan, callback, observation, and runtime identities under `artifacts/bosch-bme280/`.

The ADXL345 Stage 3 path is:

```sh
python3 -m ghostchip.extract fixtures/adxl345/datasheet.pdf \
  --request fixtures/adxl345/extraction-request.json \
  --review fixtures/adxl345/extraction-review.json \
  --output-dir artifacts/adxl345-extraction
python3 -m ghostchip.proof \
  --bundle artifacts/adxl345-extraction/reviewed-bundle-<hash>.json \
  --scenario fixtures/adxl345/scenario.json \
  --drivers examples/adxl345_buggy.c examples/adxl345_fixed.c \
  --output artifacts/adxl345-extraction/proof.json
```

Expected ADXL345 result: buggy **FAIL (1/2)** with exit 2 after a logging read consumes `SINGLE_TAP`; fixed **PASS (2/2)** by caching the first read. Both select FIFO bypass, which clears the scenario-seeded occupancy through a separately extracted rule.

Expected proof output:

```text
bme280_buggy.c: FAIL (1/2 scenario assertions)
  Completion contract unmet: expected 3, observed 0
bme280_fixed.c: PASS (2/2 scenario assertions)
```

The command returns zero only for that expected FAIL/PASS pair. Detailed state transitions, rule evidence and artifact hashes are written to `artifacts/proof.json`. No API key or internet connection is used by the proof. It compiles the C sources on each run rather than relying on checked-in executables.

Both drivers read back humidity code 3 and return successfully. Only the fixed driver writes `ctrl_meas` after `ctrl_hum`, making the setting effective. This test runs in sleep mode; it does not simulate measurements. PASS is scoped to the two completion assertions on this model.

## Source evidence

The [official Bosch PDF](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf) is cached locally as `fixtures/bme280/datasheet.pdf` and ignored by Git. To reproduce source-byte verification after copying/cloning, download it to that path and check:

```powershell
Invoke-WebRequest -Uri 'https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf' -OutFile 'fixtures/bme280/datasheet.pdf'
Get-FileHash 'fixtures/bme280/datasheet.pdf' -Algorithm SHA256
```

Expected SHA-256: `a2ccdb449fec94380742fe8eec851a11d9bd4142252d332b34682b4deecd7d89`.
The source test skips when the optional PDF is absent and fails if present bytes differ. A changed vendor download requires review, not changing the hash merely to get green tests. The default proof remains the hand-authored regression baseline. The extraction commands above parse the pinned PDF, emit a pending candidate, apply a request/anchor/candidate-hash-bound review, and pass its reconstructed bundle explicitly to the proof runner. Its `model_origin` is `automatic_extraction_reviewed_bundle`.

## Automatic versus reviewed

Automatic: PDF hash/page ingestion; register heading, address, reset, access and bit-field extraction for the requested slice; recognition of the write-latch sentence; creation of `effective_osrs_h` and the generic `after_write` transition; page/section evidence and source-page hashes; schema and semantic validation.

Explicit manual inputs: which register slice to model, the board-selected 0x76 address, the sleep-only coverage constraint, the conservative reset-settle abstraction, deterministic device-instance calibration bytes, stable rule naming, Scenario expectations, and evidence acceptance. Review only changes `pending` to `accepted`; it cannot inject semantics. Execution reconstructs the exact candidate/review/request/anchor bundle, so stale reviewed semantics cannot reach compilation.

## Scope and execution limits

Implemented: bounded PDF ingestion, source-layout extraction for reviewed slices, execution-time review-bundle verification, strict DeviceSpec/Scenario/FaultPlan validation, byte registers, internal state, bounded incrementing reads, explicit virtual delay/settle time, parameterized instance bytes, callback faults, typed API observations, pristine Bosch core compilation, build/source identity, and deterministic scenario evaluation.

Not implemented: general arbitrary-datasheet or LLM extraction, UI/API, automated repair, arbitrary vendor SDKs, real I²C/SPI signaling, measurement/compensation, MCU emulation, remote uploads, or deployment. The deterministic source-layout adapters are device-document-specific; their candidates must pass one shared validator/reviewer/runtime. The Stage 4 adapter never supplies sensor bytes or canned API results; those come from reviewed model, instance, and FaultPlan inputs.

Run only trusted code with this local runner. Its subprocess limits are not filesystem/network isolation. No remote repository or product deployment was created. Original project code is newly authored; no project distribution license has been selected. The vendor PDF remains vendor material and dependencies retain their licenses.

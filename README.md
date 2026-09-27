# GhostChip — evidence-backed extraction and deterministic proof

This repository contains DeviceSpec v1, the original hand-authored BME280 regression baseline, and an automatic PDF-to-candidate pipeline whose reviewed output drives compiled C FAIL → PASS proofs through a live virtual bus. Stage 3 generalizes that pipeline to two materially different ADXL345 behaviors without device-specific runtime branches. It is still a bounded proof, not a complete sensor emulator or frontend.

- [Architecture audit](docs/architecture.md)
- [DeviceSpec v1 contract](docs/devicespec-v1.md) and [machine-readable schema](schema/devicespec-v1.schema.json)
- [Five highest-risk assumptions](docs/risks.md)
- [Gated implementation plan](docs/implementation-plan.md)
- [Verification record](docs/verification.md)
- [Extraction boundary and artifacts](docs/extraction.md)
- [ADXL345 generalization and anti-hardcoding audit](docs/generalization.md)

## Run on this Windows machine

The existing Ubuntu WSL environment has Python 3.12.3, GCC and jsonschema 4.10.3. From PowerShell:

```powershell
wsl -d Ubuntu --cd '/mnt/e/LovHack season 3 hackathon' --exec python3 -m ghostchip.proof
wsl -d Ubuntu --cd '/mnt/e/LovHack season 3 hackathon' --exec python3 -m unittest discover -s tests -v
```

On another Linux/WSL environment, install a C11 GCC toolchain and Python 3.10+, create a Python virtual environment, then:

```sh
python3 -m pip install -r requirements.txt
python3 -m ghostchip.extract fixtures/bme280/datasheet.pdf \
  --request fixtures/bme280/extraction-request.json \
  --review fixtures/bme280/extraction-review.json \
  --output-dir artifacts/bme280-extraction
python3 -m ghostchip.proof \
  --spec artifacts/bme280-extraction/reviewed.devicespec.json \
  --output artifacts/bme280-extraction/proof.json
python3 -m ghostchip.proof
python3 -m unittest discover -s tests -v
python3 scripts/verify_clean.py
```

The ADXL345 Stage 3 path is:

```sh
python3 -m ghostchip.extract fixtures/adxl345/datasheet.pdf \
  --request fixtures/adxl345/extraction-request.json \
  --review fixtures/adxl345/extraction-review.json \
  --output-dir artifacts/adxl345-extraction
python3 -m ghostchip.proof \
  --spec artifacts/adxl345-extraction/reviewed.devicespec.json \
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
The source test skips when the optional PDF is absent and fails if present bytes differ. A changed vendor download requires review, not changing the hash merely to get green tests. The default proof remains the hand-authored regression baseline. The extraction commands above parse the pinned PDF, emit a pending candidate, apply a hash-bound evidence review, and pass that extracted specification explicitly to the proof runner. Its `model_origin` is `automatic_extraction_reviewed`.

## Automatic versus reviewed

Automatic: PDF hash/page ingestion; register heading, address, reset, access and bit-field extraction for the requested slice; recognition of the write-latch sentence; creation of `effective_osrs_h` and the generic `after_write` transition; page/section evidence and source-page hashes; schema and semantic validation.

Explicit manual inputs: which register slice to model, the board-selected 0x76 address, the sleep-only coverage constraint, stable rule naming for the existing Scenario link, and evidence acceptance. Review only changes `pending` to `accepted`; it cannot inject semantics, and it is invalidated by any candidate hash change. Missing latch prose produces an unresolved report and no rule.

## Scope and execution limits

Implemented: bounded PDF ingestion, heuristic candidate extraction for this BME280 slice, hash-bound review, strict schema and semantic validation, byte registers, internal state, guarded read/write effects, source provenance, live one-byte I²C-style HAL, bounded local processes and deterministic scenario evaluation.

Not implemented: general arbitrary-datasheet or LLM extraction, UI/API, automated repair, full vendor SDK, real I²C/SPI signaling, measurement/timing, remote uploads or deployment. The two deterministic source-layout adapters are device-document-specific; their candidate output must pass one shared validator/reviewer/runtime. Unsupported or missing prose is reported rather than approximated. Corrected C sources are manually prepared fixtures, not AI-generated patches.

Run only trusted code with this local runner. Its subprocess limits are not filesystem/network isolation. No remote repository or product deployment was created. Original project code is newly authored; no project distribution license has been selected. The vendor PDF remains vendor material and dependencies retain their licenses.

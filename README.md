# GhostChip

> **Test driver behavior before the hardware arrives.**

GhostChip turns reviewed datasheet behavior into an executable virtual peripheral, runs real driver code against it, and traces behavioral failures back to cited datasheet rules.

The current release is a bounded, reproducible proof. It does **not** claim arbitrary datasheet understanding, silicon equivalence, formal verification, or guaranteed hardware correctness.

## The problem

An embedded driver can compile, write a register, and read the value back successfully while the chip never activates the requested behavior. Those semantic failures often remain hidden until scarce hardware arrives.

## What GhostChip does

GhostChip brings a reviewed slice of peripheral behavior into the development loop:

1. pin the source datasheet and extract a bounded register/rule slice;
2. bind explicit human review to the candidate, request, and source identity;
3. reconstruct the reviewed bundle at execution time;
4. compile trusted C driver code;
5. route its real callbacks through a deterministic virtual peripheral;
6. evaluate an explicit Scenario and show the trace, cited rule, and verdict.

## 30-second workflow

Open the local product, choose the **Original buggy driver** demonstration, and run it. The fixture requests fourfold humidity oversampling but writes `ctrl_meas` before `ctrl_hum`, so the reviewed BME280 latch rule is never completed. GhostChip reports **FAIL**, links the mismatch to page 27, and exposes the callback order. A bounded deterministic provider can propose the two-line reorder. Only after explicit approval, recompilation, and rerunning the identical reviewed model + Scenario does the derived fixture become **VERIFIED**.

## Flagship BME280 demonstration

The repair demonstration uses a small, controlled BME280 fixture authored for this project. It intentionally contains a register-order bug:

```text
observed:  ctrl_meas -> ctrl_hum    (setting remains pending)
required:  ctrl_hum  -> ctrl_meas   (setting becomes effective)
```

The offline proposal provider is `ghostchip-local-demo` / `deterministic-rule-v1`. It is **not AI**. It can modify only the controlled fixture; it cannot alter the model, Scenario, evidence, assertions, verifier, tests, or Bosch source. “VERIFIED” means **verified against this reviewed model + Scenario**.

## Real Bosch SensorAPI proof

This is deliberately separate from the repair fixture. GhostChip also compiles Bosch Sensortec’s real BME280 SensorAPI, unchanged at its core, and routes its actual read, write, and delay callbacks through the reviewed virtual peripheral. Every run verifies the pinned upstream source hashes before and after compilation and records build, dependency, executable, model, Scenario, instance, fault-plan, callback, observation, and runtime identity.

GhostChip did not find or repair a Bosch bug.

## ADXL345 second-device evidence

The same generic runtime executes a reviewed ADXL345 slice with different stateful semantics: reading `INT_SOURCE` can clear event state, and writing `FIFO_CTL` changes FIFO state. The verifier contains no ADXL345-specific branch; extraction uses a device-document-specific source adapter.

## Architecture

```text
Pinned datasheet
      |
Bounded extraction -> explicit review -> hash-bound reviewed bundle
                                           |
Trusted C driver -> callback protocol -> generic virtual peripheral
                                           |
                              Scenario assertions + evidence
                                           |
                                PASS / FAIL / VERIFIED
```

The frontend presents backend artifacts; it cannot manufacture a verdict. The local service runs only repository-owned curated drivers. See [architecture](docs/architecture.md), [DeviceSpec 1.0](docs/devicespec-v1.md), [DeviceSpec 1.1 additions](docs/devicespec-v1.1.md), and the [verification record](docs/verification.md).

## How verification works

- DeviceSpec and Scenario inputs are strictly validated.
- Review acceptance cannot inject semantics; execution reconstructs the exact reviewed candidate.
- C sources are compiled in a fresh temporary directory.
- Callbacks are recorded with register, length, status, and logical-time effects.
- Scenario assertions compare observed behavior with explicit expectations.
- Results retain evidence and identity hashes so a stale label cannot substitute for execution.

## Repair workflow

The bounded workflow is **FAIL -> proposal -> explicit approval -> compile -> execute -> verify**. The original source is preserved and the proposal is applied only to a temporary derived variant. The current provider is an offline deterministic demonstration, not an AI repair system. See [repair boundary](docs/stage6-repair.md) and [integrity remediation](docs/stage7-remediation.md).

## Tech stack

- Python 3.10+ with FastAPI and Pydantic
- C11 drivers compiled with GCC
- Next.js 16, React 19, and TypeScript
- JSON Schema for DeviceSpec contracts
- Playwright-based browser QA and deterministic CLI smoke checks

## Running locally

Prerequisites: Windows with WSL/Ubuntu, Python 3.10+, GCC, and Node.js. On the prepared Windows environment:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1
```

Open `http://localhost:8765`.

After dependencies are installed, the readiness and real-driver smoke gate is:

```sh
python3 -m pip install -r requirements.txt
python3 -m ghostchip.demo --check --smoke
```

Run the full backend suite:

```sh
python3 -m unittest discover -s tests -v
```

Run frontend checks:

```sh
cd web
npm ci
npm test
npm run build
```

The optional official Bosch PDF is intentionally not tracked. To reproduce source-byte verification, download it from the [Bosch BME280 product page](https://www.bosch-sensortec.com/products/environmental-sensors/humidity-sensors-bme280/) to `fixtures/bme280/datasheet.pdf`. The expected SHA-256 is `a2ccdb449fec94380742fe8eec851a11d9bd4142252d332b34682b4deecd7d89`; a changed vendor file requires review rather than silently changing the pin.

## Scope and limitations

Implemented: reviewed register slices, hash-bound evidence, byte registers, explicit internal state, bounded reads, logical delay/settle time, deterministic device-instance bytes, callback fault injection, pristine Bosch core compilation, source/build identity, and deterministic Scenario evaluation.

Not implemented: arbitrary datasheet or repository ingestion, general AI repair, physical I²C/SPI signaling, measurement/compensation simulation, MCU emulation, remote uploads, multi-user accounts, public deployment, or physical-silicon certification. The runner executes trusted local code; its subprocess limits are not a security sandbox.

Historical engineering records remain under `docs/` and are labeled as checkpoint documents where their scope predates the current release.

## Open-source attribution

Bosch Sensortec’s BME280 SensorAPI is vendored under `third_party/bosch_bme280/` with its BSD-3-Clause [license](third_party/bosch_bme280/LICENSE) and [upstream metadata](third_party/bosch_bme280/UPSTREAM.json). Dependency licenses remain with their respective packages.

No root project license has been selected. Until one is added, copyright defaults apply to the original GhostChip code, so public viewing does not grant general permission to copy, modify, or redistribute it.

## Release identity

- Independently audited technical baseline: `cb446bd00f0112b6239925b68140a01a5bbaa168`
- Cinematic presentation/UI baseline: `78e4f32431fc73ffadcaee02ed080b90af5300b0`

These identities separate the audited verification behavior from the later presentation-only UI pass.

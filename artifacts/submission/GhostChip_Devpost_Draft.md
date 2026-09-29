# GhostChip Devpost submission draft

## Project name

GhostChip

## Tagline

Test driver behavior before the hardware arrives.

## Short description

GhostChip turns reviewed chip-datasheet behavior into a virtual device, runs real driver code against it, and explains failures using the exact datasheet rules involved.

## The problem

Embedded drivers can compile, write a register, and read that value back while still failing to activate the intended chip behavior. Those semantic mistakes may remain invisible until hardware is available, when debugging is slower and access may be scarce.

## Who this helps

Firmware engineers, embedded teams, driver authors, reviewers, and students who need an earlier, inspectable way to exercise bounded device behavior before a physical board is available.

## What GhostChip does

GhostChip converts a reviewed slice of a peripheral datasheet into a deterministic executable model. It compiles trusted C code, routes real callbacks through that model, evaluates an explicit Scenario, and presents the callback trace, assertion results, cited evidence, and source identities together.

## How it works

1. Pin a datasheet and extract a deliberately bounded register/rule slice.
2. Bind explicit review to the source, request, anchors, and candidate hash.
3. Reconstruct that reviewed bundle at execution time.
4. Compile trusted driver code in a fresh temporary directory.
5. Execute its read, write, and delay callbacks against the virtual peripheral.
6. Evaluate explicit Scenario assertions and retain evidence and identity hashes.

## Why it matters

Compilation and register readback are not enough to prove that a device behavior became effective. GhostChip makes that gap visible earlier and explains a failure in terms a reviewer can trace: what the driver did, what the reviewed model expected, and which cited rule connects the two.

## What makes it different

GhostChip connects cited datasheet evidence → human-reviewed behavior → an executable peripheral model → real driver execution → a traceable failure → a bounded repair → deterministic re-verification. GhostChip does not hide uncertainty behind a generic simulator claim. Its model is reviewed, bounded, and evidence-linked. The UI distinguishes automatic steps from manual judgment, the verifier reconstructs reviewed semantics rather than trusting a label, and the frontend cannot manufacture a verdict. A second-device proof exercises the same generic runtime with genuinely different stateful behavior.

## BME280 flagship demo

The controlled repair fixture requests fourfold humidity oversampling but writes the BME280 control-measurement register before the humidity-control register. The writes succeed and the pending value reads back, yet the effective setting remains disabled. GhostChip reports FAIL, shows the incorrect order, and links it to the reviewed humidity-latch rule on page 27.

A local deterministic provider proposes moving one write. It is not AI. After explicit approval, GhostChip creates temporary derived source, recompiles it, re-executes the callbacks, and reruns the identical reviewed model + Scenario. Only then does the derived fixture become VERIFIED. The original source is preserved.

## Real Bosch driver validation

The repair demo uses a small controlled fixture authored for this project. Separately, GhostChip compiles Bosch Sensortec’s real BME280 SensorAPI unchanged at its core. It verifies pinned upstream source hashes and routes the library’s actual read, write, and delay callbacks through the reviewed virtual peripheral. GhostChip did not find or repair a Bosch bug.

## ADXL345 generalization

The same runtime executes a reviewed ADXL345 slice with different semantics: reading `INT_SOURCE` can clear event state, and writing `FIFO_CTL` changes FIFO state. The generic verifier has no ADXL345-specific branch. Extraction uses a device-document-specific source adapter.

## How we built it

We defined strict DeviceSpec and Scenario contracts, implemented a deterministic register/state runtime, added bounded PDF ingestion and review binding, built C callback harnesses, integrated the pinned Bosch SensorAPI, and created an execution-time integrity chain for model, driver, build, and result identities. A FastAPI service exposes curated runs to a Next.js interface designed as an engineering instrument rather than a dashboard.

## Technologies used

- Python, FastAPI, Pydantic, and JSON Schema
- C11 and GCC
- Next.js 16, React 19, and TypeScript
- Bosch BME280 SensorAPI under its BSD-3-Clause license
- Deterministic fixture/runtime tests and real-driver smoke gates
- Playwright for browser QA and reproducible demo capture

## Challenges we ran into

The hardest boundary was integrity, not animation: a reviewed label could never be allowed to stand in for reconstructed semantics and fresh execution. We also had to keep three claims separate—automatic extraction, explicit human review, and deterministic verification—and keep the controlled repair fixture distinct from the real Bosch integration.

## Accomplishments

- Reproducible FAIL-to-VERIFIED workflow with explicit approval and fresh execution
- Pinned, unchanged-at-core Bosch SensorAPI integration with source identity checks
- Shared runtime evidence across BME280 and ADXL345
- Evidence-linked failure explanation and actual callback traces
- 112 backend tests, 7 frontend tests, production build, and full smoke gate passing at submission preparation

## What we learned

A register returning the requested bits does not necessarily mean the requested behavior is active. We also learned that trustworthy tooling must show its boundary: what came from a source, what was reviewed, what was automatic, and exactly what a verdict establishes.

## What we built during LovHack

During LovHack we built the GhostChip contracts, extraction and review path, generic runtime, deterministic verifier, BME280 and ADXL345 proofs, real Bosch callback integration, bounded repair workflow, integrity hardening, local API, cinematic judge interface, automated tests, and submission media.

## Open-source / prior-work disclosure

Original GhostChip project code was authored for this project. Bosch Sensortec’s BME280 SensorAPI is vendored with its BSD-3-Clause license and upstream metadata; it remains unchanged at its core. Datasheets and product names belong to their respective vendors. The optional Bosch PDF is not tracked in the repository. No root license has yet been selected for the original GhostChip code.

## AI-assisted development disclosure

AI coding tools assisted with implementation, review, testing, documentation, and submission production. Deepgram Aura-2 Orion generated the submission narration, and FFmpeg assembled the submission media; neither is part of the GhostChip runtime. GhostChip’s current repair proposal provider is not AI: it is the local deterministic `ghostchip-local-demo` / `deterministic-rule-v1` provider. Every displayed product verdict comes from deterministic execution and explicit assertions, not an AI judgment.

## Current limitations

GhostChip supports reviewed slices of register-based peripherals. It does not claim arbitrary datasheet understanding, arbitrary driver support, silicon equivalence, formal verification, physical bus timing, measurement/compensation simulation, MCU emulation, hardware accuracy, or guaranteed correctness. The local runner executes trusted repository code and is not a security sandbox. There has been no user adoption, production deployment, or physical-hardware validation claim.

## What’s next

Future work could add more reviewed device adapters, stronger authoring/review tooling, hardware-in-the-loop comparison, richer fault plans, and a sandboxed execution service. Each extension should preserve the current evidence, identity, and explicit-scope boundaries.

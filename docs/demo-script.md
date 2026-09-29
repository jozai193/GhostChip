# GhostChip final demo narration

Selected voice: Deepgram `aura-2-orpheus-en` (professional, clear, confident, trustworthy). Pronunciation text is written for speech; the UI retains exact identifiers.

## Narration segments

### 1 — Hook

An embedded driver can compile, write a setting, and read it back correctly—while the chip never activates it. That failure may stay hidden until hardware arrives.

### 2 — What GhostChip does

GhostChip moves that test earlier. It turns reviewed datasheet behavior into an executable virtual peripheral, runs compiled driver callbacks through it, and evaluates explicit scenarios against cited rules. The model is bounded and reviewed; it is not a silicon digital twin.

### 3 — Run the controlled fixture

Here is the controlled B-M-E two-eighty repair demo. GhostChip reconstructs the reviewed bundle, creates the virtual chip, compiles trusted source, records callbacks, and checks the result. These stages come from the real backend.

### 4 — Failure

The driver fails one of two assertions. It requested four-times humidity oversampling, but the effective setting remained disabled. The writes succeeded; their order was wrong. Bosch documents that the humidity setting becomes effective only after the next control-measurement write.

### 5 — Trace and evidence

The trace makes that sequence concrete, and the failure links it to the reviewed rule on page twenty-seven. This is the difference between register readback and behavior.

### 6 — Proposal boundary

Now I request a bounded repair. The provider is GhostChip Local Demo, using Deterministic Rule V One. It is not AI. The proposal can change only the controlled fixture—not the model, Scenario, evidence, verifier, tests, or Bosch source.

### 7 — Diff and re-execution

The diff moves one write: humidity control first, then control measurement. GhostChip still does not trust the proposal. Apply and Verify creates temporary derived source, recompiles it, executes the callbacks again, and reruns the identical reviewed model and Scenario.

### 8 — Verified scope

Only after those gates pass is the repair marked VERIFIED. That means verified against this reviewed model plus Scenario—not formal proof or silicon certification. The original fixture is preserved.

### 9 — Real Bosch driver proof

The repair demo uses our small controlled fixture. Separately, GhostChip compiles Bosch’s real B-M-E two-eighty Sensor A-P-I unchanged at its core, verifies pinned source identity, and routes its actual callbacks through the virtual peripheral. GhostChip did not find a Bosch bug.

### 10 — Second device

The same generic runtime also executes a reviewed A-D-X-L three-forty-five slice, including read-clear interrupt state and F-I-F-O behavior. The verifier contains no device-specific A-D-X-L branch.

### 11 — Close

GhostChip helps firmware teams test reviewed driver behavior before the hardware arrives—with evidence they can inspect, limits they can see, and results they can reproduce.

## On-screen facts to preserve

- Repair provider: `ghostchip-local-demo` / `deterministic-rule-v1` / `local_demo`; not AI.
- Repair fixture: small controlled BME280 fixture authored for the demo.
- Real-driver proof: Bosch BME280 SensorAPI unchanged at its core.
- VERIFIED scope: verified against this reviewed model + Scenario.
- Generalization: one generic runtime, with a device-specific ADXL345 source adapter and no ADXL345 verifier branch.

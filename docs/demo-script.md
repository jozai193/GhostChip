# GhostChip 2–3 minute demo script

## 0:00–0:20 — the problem

Open the landing screen.

> Embedded drivers can compile and pass shallow mocks while still violating one sentence hidden deep in a datasheet. GhostChip tests that behavior before the hardware arrives.

Point to the one-line mechanism and click **Run BME280 demo**.

## 0:20–1:05 — the real flagship run

As the backend runs, name only the completed stages: reviewed-model reconstruction, pinned Bosch source verification, compilation, virtual BME280 startup, callbacks and assertions. Do not pause for theatrical timing.

On **VERIFIED**, point out:

- the actual assertion count;
- the Bosch API return;
- callback count and measured elapsed time;
- the trace sequence: ID, reset, 2,000 us delay, status, calibration banks, then humidity-control and latch writes.

> This is Bosch's unchanged SensorAPI core at pinned commit `c90d419…`, not a driver written for the demo.

## 1:05–1:45 — make the failure obvious

Choose **Original buggy driver** and run it.

> The driver requested humidity x4 and even read the register back successfully. But the datasheet says the setting becomes effective only after a later `ctrl_meas` write. That write is missing, so GhostChip reports FAIL—not a compiler error.

Point to Expected, Observed, the plain-English translation, the two assertions and the short trace.

## 1:45–2:15 — prove it is evidence-backed

Scroll to the BME280 model card. Show the reviewed latch rule, page/section, explicit limitations and expandable identity. Show the real-driver card: unchanged core, commit, BSD-3-Clause, source integrity verified.

> The model is bounded and reviewed. We do not claim GhostChip understands every datasheet or matches physical silicon.

## 2:15–2:35 — limited generalization and boundary

Show the ADXL345 card.

> A second device exercises read side-effects and FIFO state rather than the BME280 latch. The runtime has no ADXL-specific branch, although extraction still uses a device-document-specific adapter.

Finish on **How automatic is this?** Distinguish deterministic automation from reviewed/manual choices.

## Recording fallback

Prepare the machine with the start command and run `python -m ghostchip.demo --check --smoke` before recording. Keep a prerecorded local capture available because the Windows Node/WSL toolchain split is the main operational demo risk. Do not substitute a canned result inside the product.

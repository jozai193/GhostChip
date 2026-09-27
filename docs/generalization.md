# ADXL345 Stage 3 generalization

## Outcome

The official Analog Devices ADXL345 Rev. G PDF is pinned by SHA-256 `87ae2212498c35a6759d8732adee0ec9b9d8d60fa95688bc5904f1f07ceb8ff6`. The real PDF and the checked-in offline golden page map both produce candidate hash `5700e02cd260997e5a498fa66950c5b2a3e852f3e6c64940a25df6cb4c757e74` with two rules and no unresolved target behavior.

1. `int_source_nondata_clear`: after reading `INT_SOURCE`, clear `SINGLE_TAP`, `DOUBLE_TAP`, Activity, Inactivity, and `FREE_FALL`; preserve DATA_READY, watermark, and overrun. The returned byte is captured before effects. Rule evidence is PDF/printed pages 19 and 27.
2. `fifo_bypass_clear`: after writing `FIFO_CTL`, when `FIFO_MODE == 0`, clear six-bit internal `fifo_entries`. Rule evidence is pages 21 and 28.

The reviewed candidate drives the generic runtime and manually authored Scenario. The buggy C fixture reads `INT_SOURCE` for logging and reads again for handling; exit 2 becomes FAIL because the first read clears `SINGLE_TAP`. The fixed fixture reads once and caches the byte. Both write FIFO bypass. Result: buggy FAIL 1/2, fixed PASS 2/2.

## Automation and review classification

| Category | Stage 3 contents |
|---|---|
| Automatically extracted | PDF hash/page text; register addresses, access, resets and fields; I2C address alternatives; exact clear exception set; bypass encoding; page/section evidence anchors. |
| Automatically inferred, pending review | Five field-clear effects after `INT_SOURCE` read; a six-bit occupancy state and guarded clear effect after a bypass write. These are never executable while evidence is pending. |
| Manually selected/configured | Official source identity/revision; two-register slice; board address 0x53; behavior categories to attempt; stable rule ids; explicit unsupported boundary. |
| Manually accepted | Evidence ids in the source- and candidate-hash-bound review manifest. Acceptance changes review status only and cannot add semantics. |
| Unsupported | Interrupt/event physics; clearing DATA_READY/watermark/overrun through data reads; FIFO contents/pop/bursts/timing; pin mapping/electrical behavior; SPI; all other registers. |

External `SINGLE_TAP` and FIFO occupancy are Scenario stimuli with explicit test-intent basis. They are not extracted transitions, reset values, invented registers, or driver-accessible operations. Driver intent (`exit == 0`, FIFO empty at checkpoint) remains outside DeviceSpec.

## Anti-hardcoding audit

| Addition | Device-specific? | Layer and justification |
|---|---:|---|
| `adxl345_extraction.py` | Yes | Fallible source-layout adapter only; emits pending data and is never imported by validator/runtime. |
| ADXL request, golden, review, Scenario | Yes | Transparent source selection, expected extraction, human decision, and test intent artifacts. |
| ADXL C buggy/fixed fixtures | Yes | Trusted demonstration inputs; not runtime behavior or an adapted vendor driver. |
| `Peripheral.stimulate` | No | Generic bounded pre-run field/state assignment with explicit basis; tested against arbitrary references. |
| `process_exit` assertion reference | No | Generic Scenario observation; original successful-exit behavior remains unchanged. |
| CLI `--scenario` / `--drivers` | No | Generic artifact selection; relative paths are resolved before temporary compilation. |
| DeviceSpec schema/version | No change | Existing `after_read`, `after_write`, guards, field effects and state effects express both behaviors. |
| Validator/runtime/proof device branches | None | Regression scans reject ADXL/register identifiers in the generic execution core. |

Rule-removal falsification closes the most obvious silent dependency: removing the interrupt rule makes the buggy driver PASS, while removing the FIFO rule leaves occupancy at five and fails the FIFO assertion. The hand-authored BME280 fixture is not loaded anywhere in the ADXL proof.

## Honest limit

This demonstrates that one shared IR/runtime supports a second vendor and two different stateful behaviors. It does not demonstrate general arbitrary-PDF extraction, silicon fidelity, full ADXL345 support, timing/burst semantics, or compatibility with an existing third-party driver. The next gate targets the last of those claims.

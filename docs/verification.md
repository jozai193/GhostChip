# Verification record — 2026-09-28

Environment: existing Ubuntu WSL, Python 3.12.3, GCC 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1), jsonschema 4.10.3, pypdf 6.1.1 and cryptography 50.0.1. No compiler or OS installation was needed.

## Local regression suite

Command: `python3 -m unittest discover -s tests -v`

Result after Stage 3: **39 tests passed**, including both local source PDF checksum/live re-extraction paths. The original BME280 tests remain present and green. One parameterized test covers **23 malformed-spec mutations**; another covers six out-of-model accesses. The reported 39 test methods should not be confused with either proof's two scenario assertions.

Covered: all prior runtime/proof cases plus source-hash rejection, both golden candidate hashes, layout-whitespace tolerance, three missing-prose negative extraction paths, board-address alternatives, page/section rule anchors, pending execution refusal, review status-only enforcement, semantic-change review invalidation, selective read side effects, guarded FIFO clearing, bounded pre-run stimuli, two reviewed extracted FAIL/PASS proofs, rule-removal falsification, and an execution-core identifier scan.

## ADXL345 extracted-model proof

The pinned official Rev. G source hash is `87ae2212498c35a6759d8732adee0ec9b9d8d60fa95688bc5904f1f07ceb8ff6`; the pending candidate hash is `5700e02cd260997e5a498fa66950c5b2a3e852f3e6c64940a25df6cb4c757e74`. The reviewed sorted-JSON execution hash is `543a104992aefd7fea40bd9ae392c5f88d0ff352b7f7fd9ee50677ed15c4744e`; Scenario hash is `d2b4f45f1afa94cf2e16a9d0d1d37d74ffbfa9f03a8e22930bcdfb738fbada5d`.

The buggy fixture exits 2 after three HAL events and is **FAIL (1/2)**. The fixed fixture exits 0 after two HAL events and is **PASS (2/2)**. Both report `model_origin: automatic_extraction_reviewed`. The failed single-tap assertion links to extracted evidence on pages 19 and 27; FIFO clearing links to pages 21 and 28. Removing the interrupt-clear rule makes the buggy fixture PASS; removing the FIFO rule makes the fixed fixture fail with occupancy still five.

## Extracted-model proof

Commands: `python3 -m ghostchip.extract ... --review ...` followed by `python3 -m ghostchip.proof --spec artifacts/bme280-extraction/reviewed.devicespec.json`.

Result: the pending candidate hash is `5fe6b9f5cdb727dca13ca6a3831e52057ead996dc5cf1bbaaf2194c49a896731`. Review supplies evidence statuses only. The reviewed model's sorted-JSON execution hash is `8e51aeacb5a712185662f7e995ff38f69a2fef8297b00926e3fd967ce10b4c40`.

The buggy C fixture is **FAIL (1/2)** and the fixed fixture is **PASS (2/2)** with `model_origin: automatic_extraction_reviewed`. The failure carries extracted evidence from PDF pages 27/28, sections 5.4.3/5.4.5. Both runs use the same extracted model and existing Scenario. Removing only the extracted rule makes the fixed fixture fail, which proves the PASS is not coming from register readback or the manual BME280 fixture.

## Deterministic proof

Command: `python3 -m ghostchip.proof`

| Fixture | C exit | HAL events | Pending code | Effective code | Scenario result |
|---|---:|---:|---:|---:|---|
| buggy | 0 | 4 | 3 | 0 | FAIL: 1/2 assertions |
| fixed | 0 | 4 | 3 | 3 | PASS: 2/2 assertions |

Both use the same model hash `fc3b0393a90e5608ec94955cd91948e837fb5b5df66735aeddad85aa1bcbe4f4` and scenario hash `b860ff9fdecb260e4261032bf26b2cd3842d5633c02332c8346b8611447a322a`. These are SHA-256 hashes of sorted-key JSON serialization used by the runner, not hashes of the pretty-printed fixture files. Source PDF hashes instead cover original PDF bytes.

The full live trace is saved in `artifacts/proof.json`. It includes before/after register and internal state, operation order, triggered rule ids, returned read values, evidence and code/schema hashes. Neither driver receives its expected verdict from the harness.

## Clean-source reproduction

Command: `python3 scripts/verify_clean.py`

Result: reproduction passed from a separate temporary source copy, excluding `.git`, caches, previous artifacts, both virtual environments and downloaded PDFs. The suite ran 39 test methods: 36 passed and three optional local-PDF checks were explicitly skipped. Both golden extractors still drove their compiled FAIL → PASS tests, and the default BME280 proof rebuilt and produced FAIL → PASS again.

This checks path independence and absence of cached-build dependencies using the same installed WSL toolchain. It is not a fresh operating-system installation, a Git clone test, a cross-platform certification or a hosted deployment check. No commit/remote was created.

## Unverified boundaries

No physical BME280/ADXL345 comparison, arbitrary-datasheet/probabilistic extraction, independent vendor-driver adaptation, measurement/timing simulation, browser flow or hostile-code sandbox validation has occurred. Evidence acceptance and board/scope selection remain manual. Those remain future gates, not implied by these green tests.

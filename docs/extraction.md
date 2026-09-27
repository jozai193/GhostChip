# Evidence-backed extraction milestones

## Pipeline boundary

```text
pinned PDF bytes
  -> bounded page-preserving ingestion
  -> untrusted heuristic candidate + evidence anchors
  -> DeviceSpec structural/cross-reference validation
  -> pending review gate
  -> candidate-hash-bound evidence decisions
  -> executable reviewed DeviceSpec
  -> unchanged runtime + Scenario + compiled C proof
```

`ghostchip.pdf_ingest` owns byte limits, SHA-256 verification, PDF parsing and one-based page text. `ghostchip.extraction` owns fallible candidate inference. `ghostchip.spec` and `ghostchip.runtime` remain deterministic and do not import the extraction layer. No probabilistic model is used in this milestone; a future model-backed extractor must emit the same pending artifact and pass the same deterministic gates.

## What is extracted

The request names a bounded register slice: `id`, `ctrl_hum` and `ctrl_meas`. From the pinned PDF, the extractor recovers their heading addresses, memory-map reset bytes, access direction and bit fields. It recognizes the source-neutral sentence shape “changes to this register only become effective after a write operation to …”. Because `ctrl_hum` has one extracted field in this slice, it derives `effective_osrs_h` and a generic `after_write(ctrl_meas)` copy effect. A second sentence in the `ctrl_meas` description is attached as independent cross-check evidence.

The resulting rule has evidence on PDF/printed page 27, section 5.4.3, and page 28, section 5.4.5. Register addresses, resets and field definitions have separate evidence records and page-text hashes in `evidence-anchors.json`; they are not collapsed into a misleading single citation.

## What is not inferred

- The extraction request chooses address `0x76`; the PDF lists both `0x76` and `0x77`, so board wiring remains manual input.
- The request chooses the three-register slice and constrains `ctrl_meas.mode` to sleep. This is a coverage decision, not an extracted universal behavior.
- `humidity_latch` is a stable identifier supplied only so the existing Scenario can link failures to the rule. The event, trigger, source field, state and effect are extracted.
- Evidence acceptance is human/review input. Confidence values are uncalibrated annotations and never auto-accept evidence.
- Reset command behavior, measurement timing, forced/normal mode, compensation, SPI, bursts and ambiguous “may” behavior are not represented by DeviceSpec v1 and are not silently approximated.

## Review integrity

The candidate validates while all evidence is `pending`, but the runtime refuses to execute it. `extraction-review.json` binds the source SHA-256 and canonical candidate SHA-256 and lists evidence decisions only. Applying it changes only review statuses. Unknown semantic keys are rejected, and any changed register, field, state, rule or evidence invalidates the candidate hash.

The checked-in golden fixture contains only the small reviewed page fragments needed for offline regression. The optional full PDF integration test re-extracts the source and requires the same canonical candidate hash. The full PDF itself remains ignored vendor material.

## ADXL345 adapter

`ghostchip.adxl345_extraction` is a second deterministic source-layout adapter behind the same `extract_candidate` interface. It parses Rev. G register-map rows and field tables, matches two complete behavior evidence sets, and emits a pending DeviceSpec v1 candidate. Selective `INT_SOURCE` clearing is emitted only when the page 27 exception paragraph and page 19 overview are both found. FIFO clearing is emitted only when page 21 states both that bypass remains empty and entering bypass clears FIFO, and page 28 supplies the `00` encoding. Missing any required behavior phrase yields an explicit `unresolved` record and omits that rule/state.

The extractor choice and desired register slice are configuration, not runtime behavior. This is automatic for a pinned ADXL345 Rev. G layout, not a claim of arbitrary-datasheet comprehension. No probabilistic model is currently used; if added later, its output remains an untrusted pending candidate and cannot bypass schema, semantic validation, hash-bound review, or deterministic execution.

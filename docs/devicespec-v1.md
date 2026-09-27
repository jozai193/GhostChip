# DeviceSpec v1 — frozen execution contract

Version: **1.0.0**. Profile: **i2c-reg8-events-v1**. Structural authority: [JSON Schema](../schema/devicespec-v1.schema.json), Draft 2020-12. Cross-reference authority: [validator](../ghostchip/spec.py). Both must pass. This is a bounded executable specification, not an extensible bag of optional hints.

## Envelope and representations

| Member | Meaning |
|---|---|
| `schema_version`, `profile` | Exact supported version and capability set; reject unknown values. |
| `device` | Display name/vendor, I²C bus, unshifted 7-bit address (8–119). |
| `scope` | Coverage description, explicit unsupported features, structured write constraints. Constraints apply to incoming host writes before mutation. |
| `sources` | HTTPS origin, SHA-256 of PDF bytes, page count, revision notes. |
| `evidence` | Stable id, source id, one-based PDF page, separate printed-page label, section, bounded summary, origin, review status and confidence. |
| `registers` | Unique id and byte address, width exactly 8, explicit reset byte, RO/RW access, reserved mask and named fields. |
| `state` | Non-bus-visible unsigned variables, widths 1–8, reset values and evidence. |
| `rules` | Ordered event handlers with guards and simultaneous assignments within each handler. |

Integers use JSON numbers, not hexadecimal strings; UI formatting may use hex. Every register bit belongs to one field or the reserved mask, never both. Fields use `lsb` and `width`; access is inherited from the register. Mixed-access fields are outside this profile. Reset values are known initial values at the declared model boundary; unknown silicon defaults must not be guessed as zero. This proof's boundary is after startup, not power application.

All objects reject extra properties. Integer fields reject floating-point representations such as `3.0` even when JSON Schema considers them integral. Semantic validation rejects duplicate identifiers/addresses, overlaps, uncovered bits, invalid widths/defaults, dangling references/evidence, out-of-range source pages and assignments that might overflow. Unknown features fail closed. State/rule evidence is mandatory even when manually authored.

`confidence` is nullable: it is an extractor's uncalibrated estimate, never a probability of correctness. A manual fixture uses null. Candidate specs may contain pending/rejected evidence and validate structurally. Execution requires every evidence item referenced by active registers, state and rules to be accepted. This review gate does not independently prove that a source supports a claim; that remains a review obligation.

## Expression and event semantics

References are exactly one of:

```json
{"kind":"field","register":"ctrl_hum","field":"osrs_h"}
{"kind":"state","id":"effective_osrs_h"}
```

A rule has an `id`, `on: {event, register}`, optional `when: {ref, equals}`, an `effects` array and evidence ids. Each effect has `target` (one reference) and `value` (literal unsigned byte or reference). There is no eval, code generation, arithmetic, recursion, arbitrary predicate, implicit conversion or implicit truncation.

For each transaction:

1. Append an event with a stable sequence number and snapshot of prior state.
2. Check device/register coverage and allowed operation. An RO host write, unknown location, changed reserved bit or failed write constraint is OUT_OF_MODEL: no mutation and the run becomes ERROR. This is a tooling policy, not a hardware response model.
3. A valid RW write stores the byte. A read captures the byte to return.
4. Run handlers for `after_write` or `after_read` in array order. Evaluate a guard against current state at the start of its handler. A false guard skips that handler.
5. Evaluate all right-hand sides in a handler against the same pre-handler snapshot; then apply its assignments. Duplicate targets within a handler are invalid. Later handlers see earlier effects. Different fields of the same register preserve each other's bits. Internal effects may update RO fields because device-side mutation is distinct from host access.
6. Record fired rule ids, returned value and after-state. The captured read value is returned before any read side effect. Rule effects do not themselves dispatch further events.

Every valid write dispatches `after_write`, even if its byte equals the existing byte. BME280 latching depends on this distinction. All state is new for every run. No wall-clock value appears in semantic traces, and no physical latency is implied.

ADXL345 required no DeviceSpec revision. Its selective clear uses one `after_read` rule with five field effects; the read returns the captured pre-effect byte. FIFO bypass uses an `after_write` rule guarded by the extracted `fifo_mode == 0` field and clears a six-bit internal occupancy state. External event/occupancy setup is Scenario test intent applied through a generic, bounded, pre-transaction stimulus hook; it is not device behavior, a driver-visible register, or an evidence-derived transition.

## BME280 rule

The complete fixture is [devicespec.json](../fixtures/bme280/devicespec.json). The central rule is:

```json
{
  "id": "humidity_latch",
  "on": {"event": "after_write", "register": "ctrl_meas"},
  "effects": [{
    "target": {"kind": "state", "id": "effective_osrs_h"},
    "value": {"kind": "field", "register": "ctrl_hum", "field": "osrs_h"}
  }],
  "evidence": ["humidity_latch"]
}
```

`ctrl_hum` stores the pending code. The scenario expects both the stored code and effective code to equal 3 at successful driver exit. A pending change is allowed until that checkpoint. The same DeviceSpec and scenario hashes are used for buggy and fixed runs. Both stay in sleep mode to avoid unsupported measurement timing.

## Results and provenance

- PASS: all scenario assertions hold, the driver completed successfully and no unsupported behavior occurred.
- FAIL: a reached completion checkpoint contradicts one or more explicit scenario assertions. A `process_exit` checkpoint can explicitly assert an exit code, allowing a driver-reported missed event to be a behavioral FAIL; the original `successful_driver_exit` checkpoint still treats nonzero exit as ERROR. Report expected/actual values, rule link, source evidence and trace ids.
- ERROR: compile/process/protocol/model coverage failure; no correctness verdict. Validation errors may reject a spec before a run is created.

The proof reports two scenario assertions, not the illustrative 37 tests from the brief. Rule execution and assertion coverage are distinct; triggering a rule alone does not establish test coverage. Successful register readback alone does not establish effective configuration.

## Version policy and deferred semantics

Version 1.0.0 and its profile are frozen by this document, schema and tests. Breaking transition semantics require a new major version. A new operation/capability requires an explicit schema/profile revision and runtime support; an old runtime rejects it. There is no fallback to ignoring it.

Planned but not part of v1: timers with integer virtual time and defined same-time ordering; reset commands with cancellation rules; WO/W1C and mixed access; read constants/unknown values; burst/SPI framing; modeled external interrupt-generation transitions; nondeterministic hardware alternatives and source-revision migrations. In particular, a datasheet statement that a write *may* be ignored cannot be reduced to an arbitrary single deterministic behavior and still justify a broad PASS. Test both allowed outcomes or stop as unsupported.

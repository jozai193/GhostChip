# DeviceSpec 1.1 bounded profile

DeviceSpec **1.1.0 / `i2c-reg8-settle-v1`** is a narrow additive profile used only by the Bosch SensorAPI milestone. DeviceSpec 1.0.0 and its fixtures remain supported without altered semantics.

The profile adds three reusable categories:

1. A register reset may reference a declared eight-bit parameter. A separate, hashed device-instance artifact must bind every parameter exactly once. The reviewed template fixes the parameter identifiers and addresses; the instance supplies values and provenance.
2. A reviewed `after_write` rule may set `settle_us`. Effects happen immediately, but subsequent bus access is OUT_OF_MODEL until the integer logical clock reaches the boundary. `advance_time_us` only advances this clock; it does not sleep or run device code.
3. Transport metadata declares a maximum read length and exact incrementing-read ranges. The runtime preflights the complete range before reading any byte. Multi-byte writes remain unsupported.

The BME280 profile models chip ID, reset, status, humidity/measurement control, and the 26-byte and 7-byte calibration banks. The calibration image is explicit synthetic test-instance data, not a datasheet default. A matching `0xB6` command resets modeled configuration state, preserves instance-backed NVM bytes, and starts a reviewed 2000 us observation boundary. That boundary is a conservative abstraction based on the documented startup maximum and the upstream driver's wait; it is not a cycle-accurate reset simulator or a claim that earlier silicon communication necessarily fails.

All new behavior remains data-driven. `runtime.py`, `spec.py`, and the 1.1 schema contain no Bosch identifiers, addresses, or dispatch.

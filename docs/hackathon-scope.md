# Current scope boundary

Authorized and completed through Stage 4: preserve the original BME280 and ADXL345 proofs, repair the Stage 3 integrity defects, and execute the pinned Bosch SensorAPI through real callbacks. Frontend and AI repair remain deferred.

Completed: execution-time reviewed-bundle identity; explicit unresolved ADXL evidence handling; physically consistent FIFO setup; DeviceSpec 1.1 parameter/settle/burst categories; separate Scenario, instance, and FaultPlan inputs; pristine Bosch initialization/configuration/reset; signed API-result observations; communication-failure injection; and complete source/build identities.

Today's strongest accurate claim is: **GhostChip compiles Bosch's pinned BME280 SensorAPI unchanged at its core and connects its actual hardware callbacks to a reviewed, bounded virtual peripheral derived from the datasheet. It demonstrates real initialization, read-dependent branching, communication-error propagation and humidity latching using explicit test calibration bytes and a scoped reset-settling model.**

No frontend/API, database, cloud resources, probabilistic model calls, AI repair, arbitrary driver upload, measurement simulator or submission assets were created. General arbitrary-datasheet comprehension, broad driver compatibility, silicon equivalence, full BME280 behavior, and discovery of a Bosch bug are not claimed.

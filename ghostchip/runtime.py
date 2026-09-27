"""Single-byte transaction runtime. No device names or register addresses in code."""
from copy import deepcopy

from .spec import validate


class OutOfModel(ValueError):
    """Behavior outside declared coverage; must never turn into PASS."""


class Peripheral:
    def __init__(self, spec, instance=None):
        self.spec = deepcopy(validate(spec))
        referenced = {e for item in [*spec["registers"], *spec["state"], *spec["rules"]]
                      for e in item["evidence"]}
        if any(e["review"] != "accepted" for e in spec["evidence"] if e["id"] in referenced):
            raise OutOfModel("Execution requires accepted evidence for all active semantics")
        self.defs = {r["id"]: r for r in self.spec["registers"]}
        self.by_address = {r["address"]: r["id"] for r in self.defs.values()}
        parameter_defs = {p["id"]: p for p in self.spec.get("parameters", [])}
        supplied = (instance or {}).get("parameters", {})
        if parameter_defs:
            if set(supplied) != set(parameter_defs):
                raise OutOfModel("Instance must provide every declared parameter exactly")
            if any(type(value) is not int or not 0 <= value <= 255 for value in supplied.values()):
                raise OutOfModel("Instance parameters must be bytes")
        elif instance and supplied:
            raise OutOfModel("Instance parameters are not declared by this DeviceSpec")
        self.registers = {
            r["id"]: (supplied[r["reset"]["parameter"]]
                      if isinstance(r["reset"], dict) else r["reset"])
            for r in self.defs.values()
        }
        self.state = {s["id"]: s["reset"] for s in self.spec["state"]}
        self.trace = []
        self.transfers = []
        self.stimuli = []
        self.time_us = 0
        self.settle_until_us = 0

    def stimulate(self, ref, value, basis):
        """Set pre-run hardware state without exposing a driver operation.

        Scenarios use this generic hook to represent an external sensor event or
        pre-existing FIFO occupancy. Stimulus is forbidden once bus traffic has
        begun and is kept separate from the device/driver trace.
        """
        if self.trace:
            raise OutOfModel("Stimulus is only allowed before bus transactions")
        if not isinstance(basis, str) or not basis.strip():
            raise OutOfModel("Stimulus requires an explicit test-intent basis")
        try:
            if ref["kind"] == "state":
                width = next(s["width"] for s in self.spec["state"] if s["id"] == ref["id"])
            else:
                field = next(f for f in self.defs[ref["register"]]["fields"]
                             if f["id"] == ref["field"])
                width = field["width"]
        except (KeyError, StopIteration):
            raise OutOfModel("Unknown stimulus reference") from None
        if type(value) is not int or not 0 <= value < 1 << width:
            raise OutOfModel("Stimulus value exceeds target width")
        self._assign(ref, value)
        self.stimuli.append({"ref": deepcopy(ref), "value": value, "basis": basis})

    def value(self, ref):
        if ref["kind"] == "state":
            return self.state[ref["id"]]
        f = next(f for f in self.defs[ref["register"]]["fields"] if f["id"] == ref["field"])
        return (self.registers[ref["register"]] >> f["lsb"]) & ((1 << f["width"]) - 1)

    def _assign(self, ref, value):
        if ref["kind"] == "state":
            self.state[ref["id"]] = value
        else:
            f = next(f for f in self.defs[ref["register"]]["fields"] if f["id"] == ref["field"])
            mask = ((1 << f["width"]) - 1) << f["lsb"]
            old = self.registers[ref["register"]]
            self.registers[ref["register"]] = (old & ~mask) | (value << f["lsb"])

    def transact(self, operation, address, register, value=None, transfer_id=None):
        event = {"seq": len(self.trace) + 1, "operation": operation,
                 "device_address": address, "register_address": register,
                 "value": value, "rules_triggered": [], "time_us": self.time_us}
        if transfer_id is not None:
            event["transfer_id"] = transfer_id
        self.trace.append(event)
        before = {"registers": dict(self.registers), "state": dict(self.state)}
        event["before"] = before
        try:
            if operation not in ("read", "write"):
                raise OutOfModel("Unsupported operation")
            if self.time_us < self.settle_until_us:
                raise OutOfModel("Device access before declared settle interval completed")
            if address != self.spec["device"]["address"]:
                raise OutOfModel("Unmodeled device address")
            if register not in self.by_address:
                raise OutOfModel("Unmodeled register")
            name = self.by_address[register]
            r = self.defs[name]
            event["register"] = name
            if operation == "write":
                if type(value) is not int or not 0 <= value <= 255:
                    raise OutOfModel("Expected one byte")
                if r["access"] != "rw":
                    raise OutOfModel("RO write behavior not modeled")
                if (value ^ self.registers[name]) & r["reserved_mask"]:
                    raise OutOfModel("Reserved-bit change outside model coverage")
                for c in self.spec["scope"]["write_constraints"]:
                    if c["register"] == name and value & c["mask"] != c["equals"]:
                        raise OutOfModel(c["reason"])
                self.registers[name] = value
                returned = 0
            else:
                returned = self.registers[name]  # Capture before read side effects.
            for rule in self.spec["rules"]:  # Array order is normative.
                if rule["on"] != {"event": "after_" + operation, "register": name}:
                    continue
                guard = rule.get("when")
                if guard and self.value(guard["ref"]) != guard["equals"]:
                    continue
                # Evaluate all RHS values before this rule's assignments.
                assignments = [(e["target"], self.value(e["value"]) if isinstance(e["value"], dict)
                                else e["value"]) for e in rule["effects"]]
                for target, v in assignments:
                    self._assign(target, v)
                if "settle_us" in rule:
                    self.settle_until_us = self.time_us + rule["settle_us"]
                event["rules_triggered"].append(rule["id"])
            event["returned"] = returned
            event["status"] = "OK"
            return returned
        except OutOfModel as exc:
            event["status"] = "OUT_OF_MODEL"
            event["reason"] = str(exc)
            raise
        finally:
            event["after"] = {"registers": dict(self.registers), "state": dict(self.state)}

    def read(self, address, register, length):
        """One callback-level bounded incrementing read."""
        if type(length) is not int or length < 1:
            raise OutOfModel("Read length must be a positive integer")
        maximum = self.spec.get("transport", {}).get("max_read_length", 1)
        if length > maximum:
            raise OutOfModel("Read length exceeds declared transport maximum")
        if register + length > 256:
            raise OutOfModel("Read transfer exceeds register address space")
        if length > 1:
            allowed = any(register >= item["start"] and
                          register + length <= item["start"] + item["length"]
                          for item in self.spec.get("transport", {}).get("incrementing_read_ranges", []))
            if not allowed:
                raise OutOfModel("Incrementing read range is not declared")
        if address != self.spec["device"]["address"] or any(
                byte_address not in self.by_address for byte_address in range(register, register + length)):
            raise OutOfModel("Read transfer contains an unmodeled byte")
        transfer_id = len(self.transfers) + 1
        transfer = {"id": transfer_id, "operation": "read", "device_address": address,
                    "register_address": register, "length": length, "time_us": self.time_us,
                    "status": "OK"}
        self.transfers.append(transfer)
        try:
            data = [self.transact("read", address, byte_address, transfer_id=transfer_id)
                    for byte_address in range(register, register + length)]
            transfer["data"] = data
            return data
        except OutOfModel:
            transfer["status"] = "OUT_OF_MODEL"
            raise

    def write(self, address, register, data):
        """One callback-level write; v1.1 intentionally supports one byte only."""
        if not isinstance(data, (list, tuple)) or len(data) != 1:
            raise OutOfModel("Only one-byte writes are declared")
        transfer_id = len(self.transfers) + 1
        transfer = {"id": transfer_id, "operation": "write", "device_address": address,
                    "register_address": register, "length": 1, "data": list(data),
                    "time_us": self.time_us, "status": "OK"}
        self.transfers.append(transfer)
        try:
            self.transact("write", address, register, data[0], transfer_id=transfer_id)
        except OutOfModel:
            transfer["status"] = "OUT_OF_MODEL"
            raise

    def advance_time_us(self, duration):
        if type(duration) is not int or duration < 0 or self.time_us + duration > (1 << 63) - 1:
            raise OutOfModel("Virtual delay is outside the bounded clock")
        before = self.time_us
        self.time_us += duration
        self.transfers.append({"id": len(self.transfers) + 1, "operation": "delay",
                               "duration_us": duration, "before_us": before,
                               "time_us": self.time_us, "status": "OK"})

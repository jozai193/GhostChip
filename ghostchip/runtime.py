"""Single-byte transaction runtime. No device names or register addresses in code."""
from copy import deepcopy

from .spec import validate


class OutOfModel(ValueError):
    """Behavior outside declared coverage; must never turn into PASS."""


class Peripheral:
    def __init__(self, spec):
        self.spec = deepcopy(validate(spec))
        referenced = {e for item in [*spec["registers"], *spec["state"], *spec["rules"]]
                      for e in item["evidence"]}
        if any(e["review"] != "accepted" for e in spec["evidence"] if e["id"] in referenced):
            raise OutOfModel("Execution requires accepted evidence for all active semantics")
        self.defs = {r["id"]: r for r in self.spec["registers"]}
        self.by_address = {r["address"]: r["id"] for r in self.defs.values()}
        self.registers = {r["id"]: r["reset"] for r in self.defs.values()}
        self.state = {s["id"]: s["reset"] for s in self.spec["state"]}
        self.trace = []
        self.stimuli = []

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

    def transact(self, operation, address, register, value=None):
        event = {"seq": len(self.trace) + 1, "operation": operation,
                 "device_address": address, "register_address": register,
                 "value": value, "rules_triggered": []}
        self.trace.append(event)
        before = {"registers": dict(self.registers), "state": dict(self.state)}
        event["before"] = before
        try:
            if operation not in ("read", "write"):
                raise OutOfModel("Unsupported operation")
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

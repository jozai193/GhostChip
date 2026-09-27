"""DeviceSpec v1 structural and cross-reference validation."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/devicespec-v1.schema.json").read_text())


def validate(spec):
    Draft202012Validator(SCHEMA).validate(spec)

    def integer_representation(value, key=None):
        # JSON Schema accepts 3.0 as an integer; bit operations require true ints.
        if isinstance(value, float) and key != "confidence":
            raise ValueError("Integer fields must not use floating-point representation")
        if isinstance(value, dict):
            for child_key, child in value.items():
                integer_representation(child, child_key)
        elif isinstance(value, list):
            for child in value:
                integer_representation(child)

    integer_representation(spec)

    def require(ok, message):
        if not ok:
            raise ValueError(message)

    def indexed(items, label):
        result = {x["id"]: x for x in items}
        require(len(result) == len(items), f"Duplicate {label} id")
        return result

    sources = indexed(spec["sources"], "source")
    evidence = indexed(spec["evidence"], "evidence")
    regs = indexed(spec["registers"], "register")
    states = indexed(spec["state"], "state")
    indexed(spec["rules"], "rule")
    require(len({r["address"] for r in regs.values()}) == len(regs), "Duplicate address")
    for e in evidence.values():
        require(e["source_id"] in sources, "Unknown evidence source")
        require(e["pdf_page"] <= sources[e["source_id"]]["page_count"], "Evidence page out of range")
    for item in [*regs.values(), *states.values(), *spec["rules"]]:
        require(all(e in evidence for e in item["evidence"]), "Unknown evidence id")
    for r in regs.values():
        fields = indexed(r["fields"], "field")
        mask = 0
        for f in fields.values():
            require(f["lsb"] + f["width"] <= 8, "Field exceeds register width")
            fm = ((1 << f["width"]) - 1) << f["lsb"]
            require(not mask & fm, "Overlapping fields")
            mask |= fm
        require(mask & r["reserved_mask"] == 0, "Reserved bits overlap fields")
        require(mask | r["reserved_mask"] == 255, "Every bit must be classified")

    def ref_width(ref):
        if ref["kind"] == "state":
            require(ref["id"] in states, "Unknown state reference")
            return states[ref["id"]]["width"]
        require(ref["register"] in regs, "Unknown register reference")
        fields = {f["id"]: f for f in regs[ref["register"]]["fields"]}
        require(ref["field"] in fields, "Unknown field reference")
        return fields[ref["field"]]["width"]

    for s in states.values():
        require(s["reset"] < 1 << s["width"], "State reset exceeds width")
    for c in spec["scope"]["write_constraints"]:
        require(c["register"] in regs, "Unknown constrained register")
        require(c["equals"] & ~c["mask"] == 0, "Constraint value outside mask")
    for rule in spec["rules"]:
        require(rule["on"]["register"] in regs, "Unknown trigger register")
        if "when" in rule:
            width = ref_width(rule["when"]["ref"])
            require(rule["when"]["equals"] < 1 << width, "Guard value exceeds width")
        targets = set()
        for effect in rule["effects"]:
            width = ref_width(effect["target"])
            target = json.dumps(effect["target"], sort_keys=True)
            require(target not in targets, "Duplicate effect target in rule")
            targets.add(target)
            value = effect["value"]
            if isinstance(value, dict):
                require(ref_width(value) <= width, "Assignment may overflow target")
            else:
                require(value < 1 << width, "Assignment exceeds target width")
    return spec


def load(path):
    return validate(json.loads(Path(path).read_text()))

"""Strict validation for real-driver Scenario, instance, and FaultPlan inputs."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .spec import ROOT


SCENARIO_SCHEMA = json.loads((ROOT / "schema/scenario-v1.schema.json").read_text())
FAULT_SCHEMA = json.loads((ROOT / "schema/fault-plan-v1.schema.json").read_text())


def load_json(value):
    return json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else value


def validate_scenario(value):
    value = load_json(value)
    Draft202012Validator(SCENARIO_SCHEMA).validate(value)
    ids = [item["id"] for item in value["assertions"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate Scenario assertion id")
    required = set(value["required_observations"])
    if any(item["source"] == "observation" and item["observation"] not in required
           for item in value["assertions"]):
        raise ValueError("Observation assertions must be declared as required")
    for callback in value["expected_callbacks"]:
        if callback["operation"] == "delay":
            if set(callback) != {"operation", "duration_us", "status"}:
                raise ValueError("Delay callback shape is invalid")
        elif set(callback) != {"operation", "register_address", "length", "status"}:
            raise ValueError("Bus callback shape is invalid")
    return value


def validate_fault_plan(value):
    value = load_json(value)
    Draft202012Validator(FAULT_SCHEMA).validate(value)
    ids = [item["id"] for item in value["faults"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate FaultPlan id")
    selectors = [(item["operation"], item["device_address"], item["register_address"], item["occurrence"])
                 for item in value["faults"]]
    if len(selectors) != len(set(selectors)):
        raise ValueError("Duplicate FaultPlan selector")
    return value


def validate_instance(value, spec):
    value = load_json(value)
    if set(value) != {"schema_version", "provenance", "parameters"} or \
            value["schema_version"] != "device-instance-v1":
        raise ValueError("Malformed device instance envelope")
    provenance = value["provenance"]
    if set(provenance) != {"classification", "basis"} or not all(
            isinstance(provenance[key], str) and provenance[key].strip() for key in provenance):
        raise ValueError("Device instance requires explicit provenance")
    declared = {item["id"] for item in spec.get("parameters", [])}
    if set(value["parameters"]) != declared:
        raise ValueError("Device instance must bind every declared parameter exactly")
    if any(type(item) is not int or not 0 <= item <= 255 for item in value["parameters"].values()):
        raise ValueError("Device instance values must be bytes")
    return value

"""Build and execute the pristine pinned Bosch SensorAPI through GhostChip callbacks."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import shutil
import signal
import subprocess
import tempfile
import time

from .contracts import load_json, validate_fault_plan, validate_instance, validate_scenario
from .extraction import canonical_sha256
from .review import load_review_bundle
from .runtime import OutOfModel, Peripheral
from .spec import ROOT, validate


FIXTURE = ROOT / "fixtures/bme280-sensorapi"
UPSTREAM = ROOT / "third_party/bosch_bme280"
EXAMPLE = ROOT / "examples/bosch_bme280"
DEFAULT_BUNDLE = next(FIXTURE.glob("reviewed-bundle-*.json"))
MAX_PROTOCOL_BYTES = 131072


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_upstream():
    metadata = json.loads((UPSTREAM / "UPSTREAM.json").read_text())
    if metadata.get("commit") != "c90d419492e26dd95586598a794e65eb2760753a" or \
            metadata.get("modifications") != []:
        raise ValueError("Unexpected Bosch upstream provenance metadata")
    actual = {}
    for item in metadata["files"]:
        path = UPSTREAM / item["path"]
        actual[item["path"]] = digest(path)
        if actual[item["path"]] != item["sha256"]:
            raise ValueError(f"Upstream integrity mismatch before compilation: {item['path']}")
    return metadata, actual


def _limits():
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _compiler_text(compiler, flag):
    completed = subprocess.run([compiler, flag], check=True, capture_output=True, text=True, timeout=5)
    return (completed.stdout or completed.stderr).strip()


def build(temp, progress=None):
    progress = progress or (lambda *_: None)
    progress("verifying_source_identity", "running", "Checking the pinned Bosch source manifest")
    metadata, original_hashes = verify_upstream()
    progress("verifying_source_identity", "complete", "Pinned Bosch source bytes verified")
    stage = Path(temp) / "source"
    upstream_stage = stage / "third_party/bosch_bme280"
    example_stage = stage / "examples/bosch_bme280"
    upstream_stage.mkdir(parents=True)
    example_stage.mkdir(parents=True)
    for name in ("bme280.c", "bme280.h", "bme280_defs.h", "LICENSE", "UPSTREAM.json"):
        shutil.copy2(UPSTREAM / name, upstream_stage / name)
    for name in ("adapter.c", "adapter.h", "main.c"):
        shutil.copy2(EXAMPLE / name, example_stage / name)
    staged_upstream = {item["path"]: digest(upstream_stage / item["path"])
                       for item in metadata["files"]}
    if staged_upstream != original_hashes:
        raise RuntimeError("Staged upstream snapshot differs from pinned source")
    compiler = shutil.which("gcc")
    if not compiler:
        raise RuntimeError("gcc is required")
    exe = Path(temp) / "bosch-bme280"
    deps = Path(temp) / "dependencies.d"
    command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O0",
               "-MMD", "-MF", str(deps), "-I", str(upstream_stage), "-I", str(example_stage),
               str(upstream_stage / "bme280.c"), str(example_stage / "adapter.c"),
               str(example_stage / "main.c"), "-o", str(exe)]
    progress("compiling_real_driver", "running", "Compiling the unchanged Bosch SensorAPI core")
    completed = subprocess.run(command, cwd=temp, capture_output=True, text=True, timeout=20)
    if completed.returncode:
        raise RuntimeError("Compilation failed: " + completed.stdout + completed.stderr)
    if {item["path"]: digest(upstream_stage / item["path"])
            for item in metadata["files"]} != staged_upstream:
        raise RuntimeError("Staged upstream source changed during build")
    _, after_hashes = verify_upstream()
    if after_hashes != original_hashes:
        raise RuntimeError("Upstream source changed during build")
    dependency_text = deps.read_text().replace("\\\n", " ")
    dependency_paths = [Path(token.replace("\\ ", " ")) for token in dependency_text.split(":", 1)[1].split()]
    closure = {}
    for path in dependency_paths:
        resolved = path.resolve()
        if resolved.exists():
            closure[str(resolved.relative_to(stage))] = digest(resolved)
    expected_headers = {"third_party/bosch_bme280/bme280.h",
                        "third_party/bosch_bme280/bme280_defs.h",
                        "examples/bosch_bme280/adapter.h"}
    if not expected_headers <= set(closure):
        raise RuntimeError("Compiler dependency closure omitted an expected project header")
    identity = {
        "upstream_repository": metadata["repository"], "upstream_commit": metadata["commit"],
        "upstream_license": metadata["license"], "upstream_hashes": original_hashes,
        "upstream_manifest_sha256": digest(UPSTREAM / "UPSTREAM.json"),
        "adapter_sha256": digest(EXAMPLE / "adapter.c"),
        "adapter_header_sha256": digest(EXAMPLE / "adapter.h"),
        "entrypoint_sha256": digest(EXAMPLE / "main.c"),
        "compiler_executable": str(Path(compiler).resolve()),
        "compiler_sha256": digest(Path(compiler).resolve()),
        "compiler_version": _compiler_text(compiler, "--version").splitlines()[0],
        "compiler_target": _compiler_text(compiler, "-dumpmachine"),
        "compiler_command": command, "definitions": [], "dependency_headers": closure,
        "executable_sha256": digest(exe),
    }
    progress("compiling_real_driver", "complete", "Real driver compilation succeeded")
    return exe, identity


def _execute(exe, action, handler, timeout=5):
    proc = subprocess.Popen([str(exe), action], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True, preexec_fn=_limits)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ, "protocol")
    selector.register(proc.stderr, selectors.EVENT_READ, "diagnostic")
    pending = bytearray()
    diagnostics = bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Process timeout")
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > MAX_PROTOCOL_BYTES:
                    raise RuntimeError("Process output limit exceeded")
                if key.data == "diagnostic":
                    diagnostics.extend(chunk)
                    continue
                pending.extend(chunk)
                if len(pending) > 4096:
                    raise RuntimeError("Protocol message limit exceeded")
                while b"\n" in pending:
                    raw, _, pending = pending.partition(b"\n")
                    response = handler(raw.decode("ascii"))
                    if response is not None:
                        proc.stdin.write(response.encode("ascii"))
                        proc.stdin.flush()
        if pending:
            raise RuntimeError("Incomplete protocol message")
        code = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        return code, diagnostics.decode("utf-8", errors="replace")
    finally:
        selector.close()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()


def _validate_observation(kind, value):
    bounds = {"i8": (-128, 127), "i16": (-32768, 32767), "u16": (0, 65535)}
    if kind not in bounds or not bounds[kind][0] <= value <= bounds[kind][1]:
        raise RuntimeError("Malformed typed observation")


def _callback_shape(event):
    return {key: event[key] for key in ("operation", "register_address", "length",
                                        "duration_us", "status") if key in event}


def run_case(scenario, fault_plan, *, bundle=DEFAULT_BUNDLE, instance=FIXTURE / "instance.json",
             experimental_spec=None, model_origin=None, progress=None):
    progress = progress or (lambda *_: None)
    progress("verifying_reviewed_model", "running", "Reconstructing candidate, review, request, and evidence anchors")
    scenario = validate_scenario(scenario)
    faults = validate_fault_plan(fault_plan)
    reviewed = load_review_bundle(bundle)
    if experimental_spec is None:
        spec = reviewed["reviewed_spec"]
        origin = "reviewed_bundle"
    else:
        if not model_origin or "unreviewed" not in model_origin:
            raise ValueError("Experimental DeviceSpec requires an explicit unreviewed origin")
        spec = validate(deepcopy(experimental_spec))
        origin = model_origin
    progress("verifying_reviewed_model", "complete", "Execution-time reviewed-model checks completed")
    instance = validate_instance(instance, spec)
    progress("starting_virtual_device", "running", "Instantiating the bounded virtual peripheral")
    model = Peripheral(spec, instance)
    modeled_addresses = set(model.by_address)
    for fault in faults["faults"]:
        if fault["device_address"] != spec["device"]["address"] or \
                fault["register_address"] not in modeled_addresses:
            raise ValueError("FaultPlan selector is outside modeled coverage")
    for stimulus in scenario["initial"]:
        model.stimulate(stimulus["ref"], stimulus["value"], stimulus["basis"])
    for assertion in scenario["assertions"]:
        if assertion["source"] == "model":
            model.value(assertion["ref"])
    progress("starting_virtual_device", "complete", "Virtual BME280 is ready")
    result = {"status": "ERROR", "case": scenario["id"], "model_origin": origin,
              "observations": {}, "callbacks": [], "faults_fired": [], "assertions": [],
              "violations": [], "trace": model.trace, "transfers": model.transfers,
              "scenario_sha256": canonical_sha256(scenario),
              "instance_sha256": canonical_sha256(instance),
              "fault_plan_sha256": canonical_sha256(faults),
              "review_bundle": reviewed["identities"],
              "review_bundle_sha256": canonical_sha256(reviewed),
              "component_hashes": {
                  "runner": digest(ROOT / "ghostchip/real_driver.py"),
                  "runtime": digest(ROOT / "ghostchip/runtime.py"),
                  "validator": digest(ROOT / "ghostchip/spec.py"),
                  "devicespec_schema": digest(ROOT / "schema/devicespec-v1.1.schema.json"),
                  "scenario_schema": digest(ROOT / "schema/scenario-v1.schema.json"),
                  "fault_schema": digest(ROOT / "schema/fault-plan-v1.schema.json"),
              }}
    occurrences = Counter()
    fault_by_selector = {(item["operation"], item["device_address"], item["register_address"],
                          item["occurrence"]): item for item in faults["faults"]}

    try:
        with tempfile.TemporaryDirectory(prefix="ghostchip-bosch-") as temp:
            exe, build_identity = build(temp, progress=progress)
            result["build"] = build_identity

            def handler(line):
                parts = line.split()
                if not parts:
                    raise RuntimeError("Empty protocol message")
                if parts[0] == "O":
                    if len(parts) != 4 or parts[1] in result["observations"]:
                        raise RuntimeError("Malformed or duplicate observation")
                    value = int(parts[3])
                    _validate_observation(parts[2], value)
                    result["observations"][parts[1]] = {"type": parts[2], "value": value}
                    return None
                if parts[0] == "D":
                    if len(parts) != 2:
                        raise RuntimeError("Malformed delay callback")
                    duration = int(parts[1])
                    model.advance_time_us(duration)
                    result["callbacks"].append({"operation": "delay", "duration_us": duration,
                                                "status": 0})
                    return "0\n"
                if parts[0] not in ("R", "W") or len(parts) < 4:
                    raise RuntimeError("Malformed bus callback")
                operation = "read" if parts[0] == "R" else "write"
                address, register, length = map(int, parts[1:4])
                data = list(map(int, parts[4:]))
                if operation == "read" and data or operation == "write" and len(data) != length:
                    raise RuntimeError("Malformed callback payload")
                key3 = (operation, address, register)
                occurrences[key3] += 1
                fault = fault_by_selector.get((*key3, occurrences[key3]))
                event = {"operation": operation, "device_address": address,
                         "register_address": register, "length": length,
                         "status": fault["callback_status"] if fault else 0}
                result["callbacks"].append(event)
                if fault:
                    result["faults_fired"].append(fault["id"])
                    return f"{fault['callback_status']}\n"
                if operation == "read":
                    values = model.read(address, register, length)
                    return "0 " + " ".join(map(str, values)) + "\n"
                model.write(address, register, data)
                return "0\n"

            progress("executing_callbacks", "running", "Running the real driver through GhostChip callbacks")
            code, diagnostics = _execute(exe, scenario["action"], handler)
            progress("executing_callbacks", "complete", "Callback execution completed")
            result["process_exit"] = code
            result["diagnostics"] = diagnostics
            if code != 0:
                raise RuntimeError(f"Harness exited unexpectedly with {code}")
        progress("checking_assertions", "running", "Evaluating the validated Scenario contract")
        missing = set(scenario["required_observations"]) - set(result["observations"])
        if missing:
            raise RuntimeError("Missing required observations: " + ", ".join(sorted(missing)))
        if result["faults_fired"] != scenario["expected_faults"]:
            raise RuntimeError("FaultPlan firing did not match Scenario")
        actual_callbacks = [_callback_shape(item) for item in result["callbacks"]]
        if actual_callbacks != scenario["expected_callbacks"]:
            raise RuntimeError("Callback sequence differs from the validated Scenario")
        for assertion in scenario["assertions"]:
            actual = (result["observations"][assertion["observation"]]["value"]
                      if assertion["source"] == "observation" else model.value(assertion["ref"]))
            passed = actual == assertion["equals"]
            result["assertions"].append({**assertion, "actual": actual, "passed": passed})
            if not passed:
                result["violations"].append({"assertion_id": assertion["id"],
                                             "expected": assertion["equals"], "actual": actual})
        result["status"] = "FAIL" if result["violations"] else "PASS"
        result["final_state"] = deepcopy(model.state)
        result["final_registers"] = deepcopy(model.registers)
        result["logical_time_us"] = model.time_us
        progress("checking_assertions", "complete", "Behavioral assertions evaluated")
    except (ValueError, RuntimeError, OSError, OutOfModel, subprocess.SubprocessError) as exc:
        result["status"] = "ERROR"
        result["error"] = str(exc)
    progress("finalizing_result", "complete", f"Result finalized as {result['status']}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True,
                        choices=[path.stem for path in (FIXTURE / "cases").glob("*.json")])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scenario = FIXTURE / "cases" / f"{args.case}.json"
    fault_name = {"chip_id_bus_error": "fault-chip-id.json",
                  "calibration_bus_error": "fault-calibration.json"}.get(args.case, "fault-none.json")
    kwargs = {}
    if args.case == "humidity_x4_no_latch":
        reviewed = load_review_bundle(DEFAULT_BUNDLE)
        changed = deepcopy(reviewed["reviewed_spec"])
        changed["rules"] = [rule for rule in changed["rules"] if rule["id"] != "humidity_latch"]
        kwargs = {"experimental_spec": changed,
                  "model_origin": "unreviewed_negative_control_no_latch"}
    result = run_case(scenario, FIXTURE / fault_name, **kwargs)
    output = args.output or ROOT / "artifacts/bosch-bme280" / f"{args.case}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{args.case}: {result['status']}")
    if "error" in result:
        print(result["error"])
    print(f"Evidence and trace: {output}")
    expected = "FAIL" if args.case == "humidity_x4_no_latch" else "PASS"
    return 0 if result["status"] == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())

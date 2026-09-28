"""Compile trusted fixtures, exchange live HAL RPCs, evaluate separate test intent.

Linux/WSL only. Resource limits reduce accidental hangs; this is NOT a sandbox.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import shutil
import subprocess
import tempfile
import time

from .runtime import Peripheral
from .spec import ROOT, load
from .review import load_review_bundle

FIXTURE = ROOT / "fixtures/bme280"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _limits():
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def bounded_process(argv, cwd, handler=None, timeout=10, limit=65536):
    """Bound combined output bytes and wall time; kill/reap on every error path."""
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True,
                            preexec_fn=_limits if handler else None)
    deadline = time.monotonic() + timeout
    output = bytearray()
    pending = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
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
                output.extend(chunk)
                if len(output) > limit:
                    raise RuntimeError("Process output limit exceeded")
                if handler:
                    pending.extend(chunk)
                    if len(pending) > 1024:
                        raise RuntimeError("HAL message limit exceeded")
                    while b"\n" in pending:
                        line, _, pending = pending.partition(b"\n")
                        response = handler(line.decode("ascii"))
                        proc.stdin.write(response.encode("ascii"))
                        proc.stdin.flush()
        if handler and pending:
            raise RuntimeError("Incomplete HAL message")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Process timeout")
        return proc.wait(timeout=remaining), output.decode("utf-8", errors="replace")
    finally:
        selector.close()
        # Also clean up descendants if the parent exited early.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        proc.stdin.close()
        proc.stdout.close()


def run_fixture(driver, *, spec=None, scenario=None, review_bundle=None, model_origin=None):
    if review_bundle is not None:
        bundle = load_review_bundle(review_bundle)
        spec = bundle["reviewed_spec"]
        bundle_identity = bundle["identities"]
        model_origin = "automatic_extraction_reviewed_bundle"
    else:
        bundle_identity = None
        if spec is None:
            spec = load(FIXTURE / "devicespec.json")
            model_origin = model_origin or "hand_authored_reviewed_fixture"
        elif model_origin is None:
            raise ValueError("Raw DeviceSpec execution requires an explicit non-bundle model_origin")
    scenario = json.loads((FIXTURE / "scenario.json").read_text()) if scenario is None else scenario
    model = Peripheral(spec)
    for stimulus in scenario.get("initial", []):
        model.stimulate(stimulus["ref"], stimulus["value"], stimulus["basis"])
    result = {"status": "ERROR", "driver": Path(driver).name,
              "model_origin": model_origin, "scenario": scenario["id"],
              "scope": spec["scope"], "driver_sha256": digest(driver),
              "hal_sha256": digest(ROOT / "examples/gc_hal.c"),
              "hal_header_sha256": digest(ROOT / "examples/gc_hal.h"),
              "runtime_sha256": digest(ROOT / "ghostchip/runtime.py"),
              "validator_sha256": digest(ROOT / "ghostchip/spec.py"),
              "schema_sha256": digest(ROOT / "schema/devicespec-v1.schema.json"),
              "spec_sha256": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
              "scenario_sha256": hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest(),
              "review_bundle": bundle_identity,
              "stimuli": model.stimuli, "trace": model.trace, "assertions": [], "violations": []}
    try:
        with tempfile.TemporaryDirectory(prefix="ghostchip-") as temp:
            exe = str(Path(temp) / "driver")
            compiler = shutil.which("gcc")
            if not compiler:
                raise RuntimeError("gcc is required")
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O0", "-I", str(ROOT / "examples")]
            version = subprocess.run([compiler, "--version"], capture_output=True, text=True,
                                     check=True, timeout=5).stdout.splitlines()[0]
            target = subprocess.run([compiler, "-dumpmachine"], capture_output=True, text=True,
                                    check=True, timeout=5).stdout.strip()
            result["build"] = {
                "compiler_configuration": {
                    "path": str(Path(compiler).resolve()), "version": version,
                    "target": target, "flags": flags,
                },
            }
            command = [compiler, *flags, str(driver), str(ROOT / "examples/gc_hal.c"), "-o", exe]
            code, log = bounded_process(command, temp, timeout=20)
            if code:
                raise RuntimeError("Compilation failed: " + log)
            result["build"]["executable_sha256"] = digest(exe)

            def handle(line):
                if len(model.trace) >= 128:
                    raise RuntimeError("Transaction limit exceeded")
                parts = line.split()
                if len(parts) != 4 or parts[0] not in ("R", "W"):
                    raise RuntimeError("Malformed HAL message")
                address, register, value = map(int, parts[1:])
                returned = model.transact("read" if parts[0] == "R" else "write",
                                          address, register, value if parts[0] == "W" else None)
                return f"0 {returned}\n"

            code, _ = bounded_process([exe], temp, handler=handle, timeout=3)
            result["driver_exit"] = code
            if scenario["checkpoint"] == "successful_driver_exit" and code != 0:
                raise RuntimeError(f"Driver exited with {code}; completion contract was not reached")
        if not scenario["assertions"] or scenario["checkpoint"] not in ("successful_driver_exit", "process_exit"):
            raise ValueError("Missing assertions or unsupported checkpoint")
        rule_map = {r["id"]: r for r in spec["rules"]}
        for assertion in scenario["assertions"]:
            actual = (result["driver_exit"] if assertion["ref"] == {"kind": "driver_exit"}
                      else model.value(assertion["ref"]))
            passed = actual == assertion["equals"]
            check = {**assertion, "actual": actual, "passed": passed}
            result["assertions"].append(check)
            if not passed:
                rule = rule_map.get(assertion.get("rule_id"))
                result["violations"].append({"assertion_id": assertion["id"],
                    "rule_id": assertion.get("rule_id"),
                    "summary": f"Completion contract unmet: expected {assertion['equals']}, observed {actual}",
                    "trace_event_ids": [e["seq"] for e in model.trace],
                    "evidence": [e for e in spec["evidence"] if rule and e["id"] in rule["evidence"]]})
        result["status"] = "FAIL" if result["violations"] else "PASS"
        result["final_state"] = dict(model.state)
        result["final_registers"] = dict(model.registers)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        result["status"] = "ERROR"
        result["error"] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/proof.json")
    parser.add_argument("--spec", type=Path, help="Explicit raw/manual DeviceSpec; extracted reviewed models require --bundle")
    parser.add_argument("--bundle", type=Path, help="Verified reviewed-bundle envelope for extracted execution")
    parser.add_argument("--scenario", type=Path, help="Scenario to execute instead of the BME280 baseline")
    parser.add_argument("--drivers", type=Path, nargs=2, metavar=("BUGGY", "FIXED"),
                        help="Two trusted C fixtures expected to produce FAIL then PASS")
    args = parser.parse_args()
    if args.spec and args.bundle:
        parser.error("--spec and --bundle are mutually exclusive")
    spec = load(args.spec) if args.spec else None
    bundle = load_review_bundle(args.bundle) if args.bundle else None
    scenario = json.loads(args.scenario.read_text()) if args.scenario else None
    drivers = ([path.resolve() for path in args.drivers] if args.drivers else
               [ROOT / "examples" / f"bme280_{name}.c" for name in ("buggy", "fixed")])
    results = [run_fixture(driver, spec=spec, scenario=scenario, review_bundle=bundle,
                           model_origin="explicit_raw_manual") for driver in drivers]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    for result in results:
        print(f"{result['driver']}: {result['status']} ({sum(a['passed'] for a in result['assertions'])}/{len(result['assertions'])} scenario assertions)")
        for violation in result["violations"]:
            print("  " + violation["summary"])
        if "error" in result:
            print("  " + result["error"])
    print(f"Evidence and live trace: {args.output}")
    return 0 if [r["status"] for r in results] == ["FAIL", "PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

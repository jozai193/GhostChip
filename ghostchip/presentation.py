"""Judge-facing projections of existing GhostChip artifacts and executions.

This module adds labels and explanations, never device behavior or verdicts.
Every execution result comes from ``proof`` or ``real_driver``.
"""
from copy import deepcopy
import json
from pathlib import Path
import time

from .extraction import accept_review, extract_candidate
from .pdf_ingest import document_from_page_map
from .proof import run_fixture
from .real_driver import DEFAULT_BUNDLE, EXAMPLE, FIXTURE, UPSTREAM, run_case, verify_upstream
from .review import build_review_bundle, load_review_bundle
from .spec import ROOT


LEGACY_BME = ROOT / "fixtures/bme280"
ADXL = ROOT / "fixtures/adxl345"


CASE_PRESENTATION = {
    "init_ok": {
        "label": "Normal initialization", "group": "Flagship", "expected": "PASS",
        "summary": "Bosch SensorAPI identifies the device, resets it, waits, and reads calibration data.",
    },
    "wrong_chip_id": {
        "label": "Wrong chip ID", "group": "Flagship", "expected": "PASS",
        "summary": "The real driver rejects a device that returns the wrong identity.",
    },
    "chip_id_bus_error": {
        "label": "Bus failure", "group": "Flagship", "expected": "PASS",
        "summary": "A callback failure is preserved as Bosch's communication error.",
    },
    "calibration_bus_error": {
        "label": "Calibration read failure", "group": "Engineering", "expected": "PASS",
        "summary": "A later callback fault stops initialization without inventing read effects.",
    },
    "humidity_x4": {
        "label": "Humidity x4", "group": "Flagship", "expected": "PASS", "featured": True,
        "summary": "Bosch's public settings API activates fourfold humidity oversampling through the reviewed latch rule.",
    },
    "reset_after_configuration": {
        "label": "Reset after configuration", "group": "Flagship", "expected": "PASS",
        "summary": "A real soft reset clears modeled configuration while preserving test-instance calibration bytes.",
    },
    "buggy_driver": {
        "label": "Original buggy driver", "group": "Failure demo", "expected": "FAIL",
        "summary": "A trusted demo driver writes the setting but omits the write that makes it effective.",
    },
    "humidity_x4_no_latch": {
        "label": "No-latch negative control", "group": "Engineering / negative control",
        "expected": "FAIL", "unreviewed": True,
        "summary": "The pristine Bosch driver runs against an explicitly UNREVIEWED model with the latch removed.",
    },
    "adxl345_regression": {
        "label": "ADXL345 generalization", "group": "Generalization", "expected": "PASS",
        "summary": "The same generic runtime reproduces the existing ADXL345 buggy FAIL then fixed PASS pair.",
    },
}


REGISTER_LABELS = {
    0xD0: "Chip ID", 0xE0: "Soft reset", 0xF3: "Status",
    0x88: "Calibration bank", 0xE1: "Humidity calibration",
    0xF2: "Humidity control", 0xF4: "Measurement control",
}


RULE_COPY = {
    "soft_reset": (
        "Soft reset and settle",
        "A soft-reset command clears the modeled configuration and begins a conservative 2,000 us observation boundary.",
    ),
    "reset_reads_zero": (
        "Reset command reads as zero",
        "The command byte triggers reset behavior but does not remain stored as ordinary register state.",
    ),
    "humidity_latch": (
        "Humidity configuration latch",
        "Changes written to ctrl_hum become effective after a subsequent write to ctrl_meas.",
    ),
}


def _read(path):
    return json.loads(Path(path).read_text())


def _candidate_bundle(root):
    golden = _read(root / "extraction-golden.json")
    request = _read(root / "extraction-request.json")
    review = _read(root / "extraction-review.json")
    document = document_from_page_map(
        golden["page_count"], golden["pages"], sha256=golden["source_sha256"],
        page_hashes=golden.get("page_text_sha256"),
    )
    extracted = extract_candidate(document, request)
    reviewed = accept_review(extracted["spec"], review)
    return build_review_bundle(extracted["spec"], review, request, extracted["anchors"], reviewed)


def _rule_cards(spec):
    evidence = {item["id"]: item for item in spec["evidence"]}
    cards = []
    for rule in spec["rules"]:
        title, plain = RULE_COPY.get(rule["id"], (rule["id"].replace("_", " ").title(), "Reviewed device behavior."))
        sources = [evidence[item] for item in rule["evidence"]]
        cards.append({
            "id": rule["id"], "title": title, "plain_english": plain, "status": "REVIEWED",
            "evidence": [{
                "source": spec["sources"][0]["id"], "page": item["pdf_page"],
                "printed_page": item.get("printed_page"), "section": item["section"],
                "summary": item["summary"], "origin": item["origin"],
            } for item in sources],
        })
    return cards


def devices():
    bme = load_review_bundle(DEFAULT_BUNDLE)["reviewed_spec"]
    adxl = _candidate_bundle(ADXL)["reviewed_spec"]
    return [
        {"id": "bme280", "name": "BME280", "vendor": bme["device"]["vendor"],
         "role": "Flagship real-driver proof", "review_status": "REVIEWED"},
        {"id": "adxl345", "name": "ADXL345", "vendor": adxl["device"]["vendor"],
         "role": "Limited generalization evidence", "review_status": "REVIEWED"},
    ]


def device_detail(device_id):
    if device_id == "bme280":
        bundle = load_review_bundle(DEFAULT_BUNDLE)
        spec = bundle["reviewed_spec"]
        review = bundle["review"]
        upstream, hashes = verify_upstream()
        return {
            "id": device_id, "name": "Bosch BME280", "vendor": spec["device"]["vendor"],
            "bus": spec["device"]["bus"].upper(), "profile": spec["profile"],
            "register_count": len(spec["registers"]), "rule_count": len(spec["rules"]),
            "review_status": "REVIEWED", "source_status": "HASH VERIFIED",
            "scope": spec["scope"]["description"], "limitations": review["limitations"] + spec["scope"]["unsupported"],
            "rules": _rule_cards(spec), "source": spec["sources"][0],
            "bundle_identity": bundle["identities"],
            "driver": {
                "name": "Bosch Sensortec BME280 SensorAPI", "core": "unchanged",
                "commit": upstream["commit"], "license": upstream["license"],
                "source_integrity": "VERIFIED", "hashes": hashes,
            },
            "automation": {
                "automatic": ["PDF ingestion and hash verification", "Bounded source-layout extraction",
                              "Schema validation", "Reviewed-bundle reconstruction", "Driver compilation",
                              "Callback execution", "Deterministic verification", "Build and source identity"],
                "reviewed_manual": ["Modeled slice", "Address selection", "Evidence acceptance",
                                    "Conservative settle abstraction", "Deterministic calibration test bytes",
                                    "Scenario intent"],
            },
        }
    if device_id == "adxl345":
        bundle = _candidate_bundle(ADXL)
        spec = bundle["reviewed_spec"]
        return {
            "id": device_id, "name": "Analog Devices ADXL345", "vendor": spec["device"]["vendor"],
            "bus": spec["device"]["bus"].upper(), "profile": spec["profile"],
            "register_count": len(spec["registers"]), "rule_count": len(spec["rules"]),
            "review_status": "REVIEWED", "source_status": "HASH VERIFIED",
            "scope": spec["scope"]["description"], "limitations": bundle["review"]["limitations"],
            "rules": _rule_cards(spec), "source": spec["sources"][0],
            "bundle_identity": bundle["identities"],
            "generalization": {
                "semantics": ["Read side effects and selective interrupt clearing", "FIFO mode state change"],
                "statement": "The same runtime interprets a second reviewed device model; there is no ADXL345 branch inside the generic verifier.",
                "boundary": "Extraction still uses a device-document-specific source adapter.",
            },
        }
    raise KeyError(device_id)


def cases():
    available = {path.stem for path in (FIXTURE / "cases").glob("*.json")}
    ordered = ["humidity_x4", "init_ok", "wrong_chip_id", "chip_id_bus_error",
               "reset_after_configuration", "buggy_driver", "calibration_bus_error",
               "humidity_x4_no_latch", "adxl345_regression"]
    return [{"id": case_id, **CASE_PRESENTATION[case_id]}
            for case_id in ordered if case_id in available or case_id in {"buggy_driver", "adxl345_regression"}]


def _run_sensorapi(case_id, progress):
    scenario = FIXTURE / "cases" / f"{case_id}.json"
    fault_name = {"chip_id_bus_error": "fault-chip-id.json",
                  "calibration_bus_error": "fault-calibration.json"}.get(case_id, "fault-none.json")
    kwargs = {"progress": progress}
    if case_id == "humidity_x4_no_latch":
        reviewed = load_review_bundle(DEFAULT_BUNDLE)
        changed = deepcopy(reviewed["reviewed_spec"])
        changed["rules"] = [rule for rule in changed["rules"] if rule["id"] != "humidity_latch"]
        kwargs.update(experimental_spec=changed, model_origin="unreviewed_negative_control_no_latch")
    return run_case(scenario, FIXTURE / fault_name, **kwargs)


def _run_buggy(progress):
    progress("verifying_reviewed_model", "running", "Reconstructing the reviewed Stage 2 bundle")
    bundle = _candidate_bundle(LEGACY_BME)
    progress("verifying_reviewed_model", "complete", "Reviewed bundle reconstructed")
    progress("compiling_real_driver", "running", "Compiling the trusted buggy C fixture")
    result = run_fixture(ROOT / "examples/bme280_buggy.c", review_bundle=bundle)
    progress("compiling_real_driver", "complete", "Fixture compiled and executed")
    return result


def _run_adxl(progress):
    progress("verifying_reviewed_model", "running", "Reconstructing the reviewed ADXL345 bundle")
    bundle = _candidate_bundle(ADXL)
    progress("verifying_reviewed_model", "complete", "Reviewed bundle reconstructed")
    scenario = _read(ADXL / "scenario.json")
    progress("executing_callbacks", "running", "Running buggy and fixed drivers through the generic runtime")
    buggy = run_fixture(ROOT / "examples/adxl345_buggy.c", scenario=scenario, review_bundle=bundle)
    fixed = run_fixture(ROOT / "examples/adxl345_fixed.c", scenario=scenario, review_bundle=bundle)
    status = "PASS" if (buggy["status"], fixed["status"]) == ("FAIL", "PASS") else "ERROR"
    progress("executing_callbacks", "complete", "Both trusted fixtures executed")
    return {"status": status, "case": "adxl345_regression", "buggy": buggy, "fixed": fixed,
            "assertions": [], "violations": [] if status == "PASS" else [{"summary": "Regression pair changed"}],
            "trace": fixed.get("trace", []), "callbacks": [],
            "model_origin": "automatic_extraction_reviewed_bundle",
            "review_bundle": bundle["identities"]}


def run_demo_case(case_id, progress=lambda *_: None):
    """Execute one curated trusted case and return its real engine result."""
    if case_id not in {item["id"] for item in cases()}:
        raise KeyError(case_id)
    started = time.perf_counter()
    try:
        if case_id == "buggy_driver":
            result = _run_buggy(progress)
        elif case_id == "adxl345_regression":
            result = _run_adxl(progress)
        else:
            result = _run_sensorapi(case_id, progress)
    except Exception as exc:  # Product boundary: unexpected orchestration failure is ERROR.
        result = {"status": "ERROR", "case": case_id, "error": str(exc), "assertions": [],
                  "violations": [], "trace": [], "callbacks": []}
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    result["presentation"] = deepcopy(CASE_PRESENTATION[case_id])
    return result


def serialize_trace(result):
    source = result.get("callbacks") or result.get("trace") or []
    rows = []
    for index, event in enumerate(source, 1):
        address = event.get("register_address")
        operation = event.get("operation", "unknown")
        row = {"seq": event.get("seq", index), "operation": operation.upper(),
               "status": event.get("status", "OK")}
        if address is not None:
            row.update(register_address=address, register_hex=f"0x{address:02X}",
                       label=REGISTER_LABELS.get(address, event.get("register", "Modeled register")))
        if "length" in event:
            row["length"] = event["length"]
        if "duration_us" in event:
            row.update(duration_us=event["duration_us"], label="Virtual delay")
        if "value" in event and event["value"] is not None:
            row["value"] = event["value"]
        if "rules_triggered" in event:
            row["rules_triggered"] = event["rules_triggered"]
        rows.append(row)
    return rows


def summarize_result(result):
    status = result.get("status")
    if status not in {"PASS", "FAIL", "ERROR"}:
        status = "ERROR"
    assertions = result.get("assertions", [])
    summary = {
        "status": status, "case": result.get("case") or result.get("scenario"),
        "presentation": result.get("presentation", {}),
        "assertions": assertions, "assertion_total": len(assertions),
        "assertion_passed": sum(item.get("passed") is True for item in assertions),
        "callback_count": len(result.get("callbacks") or result.get("trace") or []),
        "elapsed_ms": result.get("elapsed_ms"), "model_origin": result.get("model_origin"),
        "violations": result.get("violations", []), "error": result.get("error"),
        "observations": result.get("observations", {}),
        "source_identity": result.get("build") or {},
        "review_bundle": result.get("review_bundle"),
    }
    if summary["presentation"].get("id") == "buggy_driver" or result.get("driver") == "bme280_buggy.c":
        summary["failure_explanation"] = {
            "expected": "Humidity oversampling x4 became effective",
            "observed": "Requested x4; effective setting remained disabled",
            "cause": "The required ctrl_meas latch write did not occur.",
            "translation": "The driver wrote the setting, but according to the chip's documented behavior, that setting was never activated.",
        }
    return summary

"""Bounded repair proposals over one curated fixture; verification remains deterministic."""
from abc import ABC, abstractmethod
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from threading import RLock
import time
from uuid import uuid4

from jsonschema import Draft202012Validator

from .presentation import LEGACY_BME, _candidate_bundle, serialize_trace
from .proof import digest, run_fixture
from .spec import ROOT
from .integrity import (ExecutionClosureError, canonical_sha256 as closure_sha256,
                        validate_execution_closure)


TARGET = ROOT / "examples/bme280_buggy.c"
TARGET_REL = "examples/bme280_buggy.c"
SCENARIO = LEGACY_BME / "scenario.json"
REPAIR_ROOT = ROOT / "artifacts/demo-repairs"
REQUEST_SCHEMA = ROOT / "schema/repair-request-v1.schema.json"
PROPOSAL_SCHEMA = ROOT / "schema/repair-proposal-v1.schema.json"
FORBIDDEN_PATHS = [
    "schema/", "fixtures/", "tests/", "ghostchip/", "third_party/",
    "examples/bme280_fixed.c", "examples/bosch_bme280/",
]
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class RepairError(RuntimeError):
    """Base class for repair boundary failures."""


class PatchRejected(RepairError):
    """A proposed patch crossed the repair allowlist or was malformed."""


class ProviderUnavailable(RepairError):
    """No configured proposal provider is available."""


class PersistedRecordIntegrityError(RepairError):
    """A stored repair record is incomplete or internally contradictory."""

    code = "PERSISTED_RECORD_INTEGRITY_ERROR"


def canonical_sha256(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _schema(path):
    return json.loads(Path(path).read_text())


def validate_repair_request(request):
    Draft202012Validator(_schema(REQUEST_SCHEMA)).validate(request)
    return request


def validate_provider_response(proposal):
    Draft202012Validator(_schema(PROPOSAL_SCHEMA)).validate(proposal)
    return proposal


def _safe_path(raw):
    if "\\" in raw or raw.startswith("/"):
        raise PatchRejected("Patch contains an absolute or non-POSIX path")
    path = PurePosixPath(raw)
    if not raw or any(part in ("", ".", "..") for part in path.parts):
        raise PatchRejected("Patch contains path traversal")
    return path.as_posix()


def _header_path(line, prefix):
    if not line.startswith(prefix):
        raise PatchRejected("Patch is missing unified-diff file headers")
    value = line[len(prefix):].split("\t", 1)[0].strip()
    if value == "/dev/null":
        raise PatchRejected("File creation or deletion is not allowed")
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return _safe_path(value)


def validate_and_apply_patch(source, unified_diff, constraints):
    """Validate one text-only unified diff and return its derived source bytes."""
    encoded = unified_diff.encode("utf-8")
    if len(encoded) > constraints["max_patch_bytes"]:
        raise PatchRejected("Patch exceeds the byte limit")
    forbidden_tokens = ("GIT binary patch", "Binary files ", "rename from ", "rename to ",
                        "new file mode ", "deleted file mode ")
    if any(token in unified_diff for token in forbidden_tokens):
        raise PatchRejected("Binary, rename, creation, or deletion patches are forbidden")
    lines = unified_diff.splitlines()
    try:
        old_header = next(index for index, line in enumerate(lines) if line.startswith("--- "))
    except StopIteration as exc:
        raise PatchRejected("Patch has no file header") from exc
    if any(line.strip() for line in lines[:old_header]):
        raise PatchRejected("Unexpected content before the unified-diff header")
    if old_header + 1 >= len(lines):
        raise PatchRejected("Patch has an incomplete file header")
    old_path = _header_path(lines[old_header], "--- ")
    new_path = _header_path(lines[old_header + 1], "+++ ")
    if old_path != new_path:
        raise PatchRejected("Patch may not rename its target")
    allowed = constraints["allowed_files"]
    if old_path not in allowed:
        raise PatchRejected(f"Patch target is not allowed: {old_path}")
    if any(old_path == prefix.rstrip("/") or old_path.startswith(prefix) for prefix in constraints["forbidden_paths"]):
        raise PatchRejected(f"Patch targets a protected path: {old_path}")
    if sum(line.startswith("--- ") for line in lines) != 1 or sum(line.startswith("+++ ") for line in lines) != 1:
        raise PatchRejected("Exactly one file may be modified")

    original = source.splitlines()
    output = []
    source_index = 0
    changed = 0
    index = old_header + 2
    hunks = 0
    while index < len(lines):
        match = HUNK.match(lines[index])
        if not match:
            if lines[index].strip():
                raise PatchRejected("Unexpected content outside a diff hunk")
            index += 1
            continue
        hunks += 1
        old_start = int(match.group(1))
        old_count = int(match.group(2) or 1)
        new_count = int(match.group(4) or 1)
        target_index = old_start - 1
        if target_index < source_index or target_index > len(original):
            raise PatchRejected("Patch hunk range is invalid or overlapping")
        output.extend(original[source_index:target_index])
        source_index = target_index
        consumed = produced = 0
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line == "\\ No newline at end of file":
                index += 1
                continue
            if not line or line[0] not in " +-":
                raise PatchRejected("Malformed unified-diff hunk")
            payload = line[1:]
            if line[0] in " -":
                if source_index >= len(original) or original[source_index] != payload:
                    raise PatchRejected("Patch context does not match the original source")
                source_index += 1
                consumed += 1
            if line[0] in " +":
                output.append(payload)
                produced += 1
            if line[0] in "+-":
                changed += 1
            index += 1
        if consumed != old_count or produced != new_count:
            raise PatchRejected("Patch hunk counts do not match its contents")
    if not hunks or not changed:
        raise PatchRejected("Patch is empty")
    if changed > constraints["max_changed_lines"]:
        raise PatchRejected("Patch exceeds the changed-line limit")
    output.extend(original[source_index:])
    return "\n".join(output) + "\n", old_path, changed


class RepairProvider(ABC):
    @property
    @abstractmethod
    def identity(self):
        """Return identity from trusted provider configuration, not its response."""

    @abstractmethod
    def propose(self, request):
        """Return a RepairProposal dictionary."""


class LocalDemoRepairProvider(RepairProvider):
    """Offline deterministic provider for the curated demo. It is not an AI model."""

    @property
    def identity(self):
        return {"id": "ghostchip-local-demo", "kind": "local_demo",
                "model": "deterministic-rule-v1"}

    def propose(self, request):
        if request["source"]["path"] != TARGET_REL or request["rule"]["id"] != "humidity_latch":
            raise ProviderUnavailable("The local demo provider supports only the curated humidity-latch fixture")
        return {
            "version": "1.0.0",
            "explanation": (
                "Move the ctrl_meas write after ctrl_hum so that the reviewed humidity-latch "
                "rule activates the pending x4 setting."
            ),
            "unified_diff": (
                "--- a/examples/bme280_buggy.c\n"
                "+++ b/examples/bme280_buggy.c\n"
                "@@ -4,7 +4,7 @@\n"
                " static int configure_humidity_x4(void) {\n"
                "     uint8_t id, humidity = 3, measurement = 0; /* Stay in sleep; no timing claims. */\n"
                "     if (gc_i2c_read(0x76, 0xD0, &id, 1) || id != 0x60) return -1;\n"
                "-    if (gc_i2c_write(0x76, 0xF4, &measurement, 1)) return -1;\n"
                "     if (gc_i2c_write(0x76, 0xF2, &humidity, 1)) return -1;\n"
                "+    if (gc_i2c_write(0x76, 0xF4, &measurement, 1)) return -1;\n"
                "     /* Readback alone gives false reassurance: pending is not effective. */\n"
                "     if (gc_i2c_read(0x76, 0xF2, &humidity, 1) || humidity != 3) return -1;\n"
            ),
            "files_touched": [TARGET_REL],
            "provider": deepcopy(self.identity),
            "confidence": None,
        }


def provider_from_environment():
    selected = os.environ.get("GHOSTCHIP_REPAIR_PROVIDER", "local-demo")
    if selected == "local-demo":
        return LocalDemoRepairProvider()
    raise ProviderUnavailable(
        f"Repair provider '{selected}' is unavailable. This build ships only the explicitly labeled local-demo provider."
    )


def _provider_identity(provider):
    identity = deepcopy(provider.identity)
    if not isinstance(identity, dict) or set(identity) != {"id", "kind", "model"}:
        raise ProviderUnavailable("Repair provider has no valid configured identity")
    if identity["kind"] not in {"local_demo", "live_ai", "test"}:
        raise ProviderUnavailable("Repair provider has an unsupported configured kind")
    if not all(isinstance(identity[key], str) and identity[key] for key in identity):
        raise ProviderUnavailable("Repair provider identity fields must be non-empty strings")
    return identity


def _model_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def build_repair_request(run_record, *, repair_id=None, request_id=None):
    if run_record.get("status") != "FAIL" or run_record.get("case_id") != "buggy_driver":
        raise RepairError("Repairs require the immutable failed buggy_driver run")
    result = run_record.get("result")
    if not result or result.get("status") != "FAIL":
        raise RepairError("Failed run has no deterministic failure result")
    if run_record.get("id") is None:
        raise RepairError("Failed run has no stable identity")
    if result.get("driver_sha256") != digest(TARGET):
        raise RepairError("Original source changed after the failed run")
    closure = result.get("execution_closure")
    if not closure:
        raise RepairError("Failed run did not record its execution closure")
    try:
        validate_execution_closure(closure, ROOT)
    except ExecutionClosureError as exc:
        raise RepairError(str(exc)) from exc
    failed = [item for item in result.get("assertions", []) if not item.get("passed")]
    if not failed:
        raise RepairError("Failed run contains no failed assertion")
    rule_id = next((item.get("rule_id") for item in failed if item.get("rule_id")), None)
    bundle = _candidate_bundle(LEGACY_BME)
    spec = bundle["reviewed_spec"]
    rule = next((item for item in spec["rules"] if item["id"] == rule_id), None)
    if rule is None:
        raise RepairError("Failed assertion is not bound to an active reviewed rule")
    evidence_map = {item["id"]: item for item in spec["evidence"]}
    source_bytes = TARGET.read_bytes()
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepairError("Repair target is not UTF-8 text") from exc
    compiler = (result.get("build") or {}).get("compiler_configuration")
    if not compiler:
        raise RepairError("Failed run did not record compiler configuration")
    request = {
        "version": "1.0.0",
        "request": {
            "id": request_id or uuid4().hex,
            "repair_id": repair_id or uuid4().hex,
            "run_id": run_record["id"],
        },
        "run": {
            "id": run_record["id"], "case_id": run_record["case_id"], "status": "FAIL",
            "result_sha256": canonical_sha256(result),
        },
        "failure": {
            "assertion_ids": [item["id"] for item in failed],
            "expected": failed[0]["equals"], "observed": failed[0]["actual"],
            "summary": result["violations"][0]["summary"],
            "scenario_intent": [{key: value for key, value in item.items() if key in ("id", "ref", "equals", "basis", "rule_id")} for item in result["assertions"]],
            "trace": serialize_trace(result),
        },
        "rule": {
            "id": rule["id"], "status": "accepted", "on": rule["on"],
            "effects": rule["effects"],
            "evidence": [
                {key: deepcopy(evidence_map[item][key]) for key in
                 ("id", "pdf_page", "printed_page", "section", "summary", "origin")
                 if key in evidence_map[item]}
                for item in rule["evidence"]
            ],
        },
        "source": {
            "path": TARGET_REL, "sha256": hashlib.sha256(source_bytes).hexdigest(), "start_line": 1,
            "end_line": len(source.splitlines()), "content": source,
        },
        "identities": {
            "reviewed_bundle": deepcopy(result["review_bundle"]),
            "spec_sha256": result["spec_sha256"], "scenario_sha256": result["scenario_sha256"],
            "instance_sha256": None, "fault_plan_sha256": None,
            "compiler_configuration": deepcopy(compiler),
            "execution_closure": deepcopy(closure),
        },
        "constraints": {
            "allowed_files": [TARGET_REL], "forbidden_paths": list(FORBIDDEN_PATHS),
            "max_changed_lines": 4, "max_patch_bytes": 4096,
        },
    }
    return validate_repair_request(request)


def _public_record(record):
    hidden = {"request", "request_bytes", "provider_response_raw", "provider_response",
              "derived_source"}
    visible = {key: deepcopy(value) for key, value in record.items()
               if key not in hidden and not key.startswith("_")}
    if "request" in record:
        request = record["request"]
        visible["request"] = {
            "id": request["request"]["id"], "sha256": record["request_sha256"],
            "run": request["run"], "failure": request["failure"],
            "rule": request["rule"], "source": {key: request["source"][key] for key in ("path", "sha256", "start_line", "end_line")},
            "identities": request["identities"], "constraints": request["constraints"],
        }
    return visible


def _require(condition, message):
    if not condition:
        raise RepairError(message)


def _proposal_payload(proposal):
    keys = ("version", "explanation", "unified_diff", "files_touched", "provider", "confidence")
    try:
        return {key: deepcopy(proposal[key]) for key in keys}
    except (KeyError, TypeError) as exc:
        raise RepairError("Repair proposal is incomplete") from exc


def _validate_record_lineage(record, *, require_proposal=True):
    """Recompute the frozen request, proposal, patch, and derived-source lineage."""
    request = record.get("request")
    _require(isinstance(request, dict), "Repair record has no frozen request")
    validate_repair_request(request)
    identity = request.get("request") or {}
    _require(record.get("id") == identity.get("repair_id"),
             "Repair identity does not match the request")
    _require(record.get("request_id") == identity.get("id"),
             "Request identity does not match the record")
    _require(record.get("run_id") == identity.get("run_id") == (request.get("run") or {}).get("id"),
             "Run identity does not match the frozen request")
    _require((request.get("run") or {}).get("result_sha256"),
             "Frozen failed-result identity is missing")

    request_text = record.get("request_bytes")
    _require(isinstance(request_text, str), "Frozen request bytes are missing")
    request_bytes = request_text.encode("utf-8")
    _require(request_bytes == canonical_json_bytes(request) and
             hashlib.sha256(request_bytes).hexdigest() == record.get("request_sha256"),
             "Frozen request bytes or hash changed")

    source = request.get("source") or {}
    source_text = source.get("content")
    _require(isinstance(source_text, str) and
             hashlib.sha256(source_text.encode("utf-8")).hexdigest() == source.get("sha256"),
             "Frozen original source bytes do not match their hash")

    identities = request.get("identities") or {}
    _require(isinstance(identities.get("reviewed_bundle"), dict),
             "Frozen reviewed-bundle identity is missing")
    _require(isinstance(identities.get("spec_sha256"), str) and identities["spec_sha256"],
             "Frozen reviewed-model identity is missing")
    _require(isinstance(identities.get("scenario_sha256"), str) and identities["scenario_sha256"],
             "Frozen Scenario identity is missing")
    closure = identities.get("execution_closure") or {}
    closure_body = {key: closure.get(key) for key in ("version", "files", "compiler")}
    _require(closure_sha256(closure_body) == closure.get("sha256"),
             "Frozen execution-closure hash is inconsistent")
    compiler = identities.get("compiler_configuration") or {}
    closure_compiler = closure.get("compiler") or {}
    _require(all(compiler.get(key) == closure_compiler.get(key)
                 for key in ("path", "version", "target", "sha256")) and
             isinstance(compiler.get("flags"), list),
             "Frozen compiler configuration contradicts the execution closure")

    if not require_proposal:
        return

    proposal = record.get("proposal")
    provider_response = record.get("provider_response")
    _require(isinstance(proposal, dict) and isinstance(provider_response, dict),
             "Repair record has no frozen proposal")
    legacy_normalized_hash = proposal.get("normalized_proposal_sha256")
    _require(proposal.get("repair_id") == record.get("id") and
             proposal.get("request_id") == record.get("request_id"),
             "Proposal identity does not match its request")
    _require(proposal.get("proposal_id") == record.get("proposal_id"),
             "Proposal identity does not match the record")
    _require(proposal.get("request_sha256") == record.get("request_sha256"),
             "Proposal is bound to a different request hash")
    raw_text = record.get("provider_response_raw")
    _require(isinstance(raw_text, str), "Raw provider response is missing")
    raw = raw_text.encode("utf-8")
    _require(hashlib.sha256(raw).hexdigest() == proposal.get("response_sha256"),
             "Raw provider response hash changed")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError("Raw provider response is no longer valid JSON") from exc
    validate_provider_response(provider_response)
    _require(decoded == provider_response and canonical_json_bytes(provider_response) == raw,
             "Raw and normalized provider response differ")
    _require(canonical_sha256(provider_response) == record.get("normalized_proposal_sha256"),
             "Normalized proposal hash changed")
    _require(legacy_normalized_hash is None or
             legacy_normalized_hash == record.get("normalized_proposal_sha256"),
             "Legacy proposal normalized-proposal hash changed")
    _require(_proposal_payload(proposal) == provider_response,
             "Displayed proposal differs from the provider response")
    _require(proposal.get("provider") == record.get("trusted_provider"),
             "Proposal provider differs from trusted configuration")
    trusted = record.get("trusted_provider")
    _require(isinstance(trusted, dict) and set(trusted) == {"id", "kind", "model"} and
             trusted.get("kind") in {"local_demo", "live_ai", "test"} and
             all(isinstance(trusted.get(key), str) and trusted[key]
                 for key in ("id", "kind", "model")),
             "Trusted provider identity is invalid")
    patch = proposal.get("unified_diff", "")
    _require(hashlib.sha256(patch.encode("utf-8")).hexdigest() == proposal.get("patch_sha256"),
             "Patch bytes or hash changed")
    derived, touched, changed = validate_and_apply_patch(
        source_text, patch, request["constraints"]
    )
    _require(proposal.get("files_touched") == [touched] and
             proposal.get("changed_lines") == changed,
             "Proposal file or changed-line metadata changed")
    derived_hash = hashlib.sha256(derived.encode("utf-8")).hexdigest()
    _require(derived == record.get("derived_source") and
             derived_hash == proposal.get("resulting_source_sha256"),
             "Derived source bytes or hash changed")


def _validate_snapshot_manifest(record):
    manifest = record.get("snapshot_manifest")
    _require(isinstance(manifest, dict), "Execution snapshot manifest is missing")
    files = manifest.get("files")
    required = {"gc_hal.c", "gc_hal.h", "original.c", "candidate.c", "scenario.json",
                "reviewed-bundle.json", "execution-closure.json"}
    _require(isinstance(files, dict) and set(files) == required,
             "Execution snapshot manifest is incomplete")
    body = {"version": manifest.get("version"), "files": files}
    _require(manifest.get("version") == "repair-execution-snapshot-v1" and
             canonical_sha256(body) == manifest.get("sha256"),
             "Execution snapshot manifest hash changed")
    request = record["request"]
    closure = request["identities"]["execution_closure"]
    _require(files["original.c"] == request["source"]["sha256"] and
             files["candidate.c"] == record["proposal"]["resulting_source_sha256"] and
             files["gc_hal.c"] == closure["files"].get("examples/gc_hal.c") and
             files["gc_hal.h"] == closure["files"].get("examples/gc_hal.h") and
             files["execution-closure.json"] == hashlib.sha256(
                 canonical_json_bytes(closure)).hexdigest(),
             "Execution snapshot identities contradict the frozen inputs")


def _validate_snapshot_files(record, snapshot):
    """Rehash the persisted execution snapshot and bind its stored inputs."""
    snapshot = Path(snapshot)
    manifest = record["snapshot_manifest"]
    payloads = {}
    for name, expected in manifest["files"].items():
        path = snapshot / name
        _require(path.is_file(), f"Execution snapshot file is missing: {name}")
        payload = path.read_bytes()
        _require(hashlib.sha256(payload).hexdigest() == expected,
                 f"Execution snapshot changed: {name}")
        payloads[name] = payload

    request = record["request"]
    identities = request["identities"]
    _require(payloads["original.c"] == request["source"]["content"].encode("utf-8") and
             payloads["candidate.c"] == record["derived_source"].encode("utf-8"),
             "Execution snapshot source bytes changed")
    try:
        scenario = json.loads(payloads["scenario.json"])
        bundle = json.loads(payloads["reviewed-bundle.json"])
        closure = json.loads(payloads["execution-closure.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError("Execution snapshot JSON is malformed") from exc
    _require(_model_sha256(scenario) == identities["scenario_sha256"],
             "Execution snapshot Scenario identity changed")
    _require(bundle.get("identities") == identities["reviewed_bundle"] and
             _model_sha256(bundle.get("reviewed_spec")) == identities["spec_sha256"],
             "Execution snapshot reviewed-model identity changed")
    _require(closure == identities["execution_closure"],
             "Execution snapshot closure identity changed")


def _assertion_passes(assertion):
    """Evaluate the comparator semantics implemented by the deterministic runner."""
    comparators = [name for name in ("equals",) if name in assertion]
    _require(comparators == ["equals"], "Assertion has unsupported comparator semantics")
    _require("actual" in assertion, "Assertion has no observed value")
    return assertion["actual"] == assertion["equals"]


def _validate_verification_evidence(record, expected_result):
    verification = record.get("verification")
    audit = record.get("audit")
    _require(isinstance(verification, dict), "Verification payload is missing")
    _require(isinstance(audit, dict), "Repair audit payload is missing")
    _require(verification.get("status") == expected_result,
             "Verification result contradicts the repair status")
    _require(audit.get("rerun_result") == expected_result and
             audit.get("final_repair_status") == record.get("status"),
             "Audit result contradicts the repair status")

    request = record["request"]
    identities = request["identities"]
    proposal = record["proposal"]
    expected_audit = {
        "repair_id": record["id"], "request_id": record["request_id"],
        "proposal_id": record["proposal_id"], "original_run_id": record["run_id"],
        "failed_result_sha256": request["run"]["result_sha256"],
        "failed_assertion_ids": request["failure"]["assertion_ids"],
        "original_source_sha256": request["source"]["sha256"],
        "repair_request_sha256": record["request_sha256"],
        "provider": record["trusted_provider"],
        "provider_response_sha256": proposal["response_sha256"],
        "normalized_proposal_sha256": record["normalized_proposal_sha256"],
        "patch_sha256": proposal["patch_sha256"],
        "resulting_source_sha256": proposal["resulting_source_sha256"],
        "execution_closure_sha256": identities["execution_closure"]["sha256"],
        "snapshot_manifest_sha256": record["snapshot_manifest"]["sha256"],
        "reviewed_model_identity": identities["reviewed_bundle"],
        "scenario_sha256": identities["scenario_sha256"],
        "instance_sha256": identities.get("instance_sha256"),
        "fault_plan_sha256": identities.get("fault_plan_sha256"),
        "compiler_configuration": identities["compiler_configuration"],
    }
    _require(all(audit.get(key) == value for key, value in expected_audit.items()),
             "Persisted audit does not match frozen repair identities")
    _require(audit.get("original_source_preserved") is True,
             "Audit does not preserve the original source identity")

    build = verification.get("build") or {}
    executable = build.get("executable_sha256")
    _require(verification.get("driver_sha256") == proposal["resulting_source_sha256"],
             "Verification source identity changed")
    _require(verification.get("review_bundle") == identities["reviewed_bundle"] and
             verification.get("spec_sha256") == identities["spec_sha256"] and
             verification.get("scenario_sha256") == identities["scenario_sha256"],
             "Verification model or Scenario identity changed")
    _require(verification.get("execution_closure") == identities["execution_closure"] and
             build.get("compiler_configuration") == identities["compiler_configuration"],
             "Verification execution closure or compiler identity changed")
    closure_files = identities["execution_closure"]["files"]
    _require(verification.get("hal_sha256") == closure_files.get("examples/gc_hal.c") and
             verification.get("hal_header_sha256") == closure_files.get("examples/gc_hal.h"),
             "Verification HAL snapshot identity changed")
    _require(verification.get("instance_sha256") == identities.get("instance_sha256") and
             verification.get("fault_plan_sha256") == identities.get("fault_plan_sha256"),
             "Verification instance or FaultPlan identity changed")

    required_checks = {"reviewed_bundle", "spec_sha256", "scenario_sha256",
                       "instance_sha256", "fault_plan_sha256", "compiler_configuration",
                       "execution_closure", "staged_hal"}
    checks = audit.get("identity_checks")
    _require(isinstance(checks, dict) and required_checks.issubset(checks) and
             all(checks.get(name) is True for name in required_checks),
             "Audit identity checks are incomplete or failed")

    recomputed = []
    if expected_result in {"PASS", "FAIL"}:
        expected_assertions = request["failure"].get("scenario_intent") or []
        actual_assertions = verification.get("assertions")
        _require(isinstance(actual_assertions, list) and
                 len(actual_assertions) == len(expected_assertions),
                 "Verification assertions are incomplete")
        actual_by_id = {item.get("id"): item for item in actual_assertions
                        if isinstance(item, dict)}
        _require(len(actual_by_id) == len(actual_assertions),
                 "Verification assertions have missing or duplicate identities")
        _require(set(actual_by_id) == {item.get("id") for item in expected_assertions},
                 "Verification assertions do not match the frozen Scenario")
        for expected in expected_assertions:
            assertion = actual_by_id[expected["id"]]
            _require(all(assertion.get(key) == value for key, value in expected.items()),
                     "Verification assertion changed from the frozen Scenario")
            passed = _assertion_passes(assertion)
            _require(isinstance(assertion.get("passed"), bool) and
                     assertion["passed"] == passed,
                     "Verification assertion pass flag contradicts its comparator")
            recomputed.append(passed)

    violations = verification.get("violations")
    _require(isinstance(violations, list), "Verification violations are missing")
    if expected_result == "PASS":
        _require(all(recomputed) and not violations,
                 "VERIFIED repair contains a failed effective assertion")
        _require(audit.get("compile_result") == "PASS" and
                 isinstance(executable, str) and executable and
                 audit.get("executable_sha256") == executable,
                 "VERIFIED repair has no matching successful executable")
    elif expected_result == "FAIL":
        _require(not all(recomputed) and violations,
                 "VERIFICATION_FAILED record contains no effective failure")
        failed_ids = {item["id"] for item, passed in zip(expected_assertions, recomputed)
                      if not passed}
        violation_ids = {item.get("assertion_id") for item in violations
                         if isinstance(item, dict)}
        _require(failed_ids == violation_ids,
                 "Verification violations contradict the failed assertions")
        _require(audit.get("compile_result") == "PASS" and
                 isinstance(executable, str) and executable and
                 audit.get("executable_sha256") == executable,
                 "Failed verification has no matching compiled executable")
    else:
        _require(audit.get("compile_result") == "ERROR",
                 "Error verification has a successful compile result")
        if record.get("status") == "COMPILE_ERROR":
            _require(not executable and not audit.get("executable_sha256"),
                     "COMPILE_ERROR contains a successful executable result")
        else:
            _require(audit.get("executable_sha256") == executable,
                     "Verification error executable identity is inconsistent")


def validate_persisted_repair(record, *, snapshot=None):
    """Return a consistent stored repair record or raise an explicit integrity error."""
    try:
        _require(isinstance(record, dict), "Stored repair record is not an object")
        status = record.get("status")
        allowed = {"GENERATING", "PROPOSED", "APPLYING", "VERIFIED",
                   "VERIFICATION_FAILED", "VERIFICATION_ERROR", "COMPILE_ERROR",
                   "PATCH_REJECTED", "PROPOSAL_ERROR", "DISCARDED", "EXPIRED",
                   "INTERRUPTED"}
        _require(status in allowed, "Stored repair record has an unknown state")
        _validate_record_lineage(record, require_proposal=False)

        proposal_required = {"PROPOSED", "APPLYING", "VERIFIED", "VERIFICATION_FAILED",
                             "COMPILE_ERROR", "INTERRUPTED"}
        if status in proposal_required or (status in {"DISCARDED", "EXPIRED",
                                                      "VERIFICATION_ERROR"} and
                                           record.get("proposal") is not None):
            _validate_record_lineage(record)

        if status in {"APPLYING", "INTERRUPTED", "VERIFIED", "VERIFICATION_FAILED",
                      "COMPILE_ERROR"}:
            _validate_snapshot_manifest(record)
            if snapshot is not None:
                _validate_snapshot_files(record, snapshot)

        if status == "VERIFIED":
            _validate_verification_evidence(record, "PASS")
        elif status == "VERIFICATION_FAILED":
            _validate_verification_evidence(record, "FAIL")
        elif status == "COMPILE_ERROR":
            _validate_verification_evidence(record, "ERROR")
        elif status == "VERIFICATION_ERROR":
            verification, audit = record.get("verification"), record.get("audit")
            _require((verification is None) == (audit is None),
                     "Verification error has partial terminal evidence")
            if verification is not None:
                _validate_record_lineage(record)
                _validate_snapshot_manifest(record)
                if snapshot is not None:
                    _validate_snapshot_files(record, snapshot)
                _validate_verification_evidence(record, "ERROR")
            else:
                _require(record.get("error_code") and record.get("error"),
                         "Verification error has no explicit failure")
        else:
            _require(record.get("verification") is None and record.get("audit") is None,
                     f"{status} record contains verification evidence")
            if status not in {"APPLYING", "INTERRUPTED"}:
                _require(record.get("snapshot_manifest") is None and
                         record.get("derived_path") is None,
                         f"{status} record contains applied execution evidence")
        return record
    except PersistedRecordIntegrityError:
        raise
    except Exception as exc:
        raise PersistedRecordIntegrityError(str(exc)) from exc


class RepairStore:
    TERMINAL = {"VERIFIED", "VERIFICATION_FAILED", "COMPILE_ERROR", "VERIFICATION_ERROR",
                "PROPOSAL_ERROR", "PATCH_REJECTED", "DISCARDED", "EXPIRED", "INTERRUPTED"}

    def __init__(self, run_store, provider=None, root=REPAIR_ROOT):
        self.run_store = run_store
        self.provider = provider
        self.root = Path(root)
        self._repairs = {}
        self._reservations = {}
        self._lock = RLock()

    def _save(self, record):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{record['id']}.tmp"
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        os.replace(temporary, self.root / f"{record['id']}.json")

    def _event(self, repair_id, stage, state, detail):
        with self._lock:
            record = self._repairs[repair_id]
            record["events"].append({"stage": stage, "state": state, "detail": detail,
                                     "at_ms": round((time.time() - record["created_at"]) * 1000, 3)})

    @staticmethod
    def _lineage_fingerprint(record):
        keys = ("id", "run_id", "request_id", "proposal_id", "request",
                "request_bytes", "request_sha256", "trusted_provider",
                "provider_response_raw", "provider_response",
                "normalized_proposal_sha256", "proposal", "derived_source")
        return canonical_sha256({key: record.get(key) for key in keys})

    def _validate_internal_lineage(self, record, *, require_proposal=True):
        _validate_record_lineage(record, require_proposal=require_proposal)

    def _validate_active_lineage(self, record):
        self._validate_internal_lineage(record)
        validate_repair_request(record["request"])
        provider = self.provider or provider_from_environment()
        if _provider_identity(provider) != record.get("trusted_provider"):
            raise RepairError("Configured provider identity changed after proposal generation")
        current_run = self.run_store.get(record["run_id"])
        request = record["request"]
        if (current_run.get("id") != record["run_id"] or
                current_run.get("case_id") != request["run"]["case_id"] or
                current_run.get("status") != "FAIL"):
            raise RepairError("The bound failed run identity or state changed")
        if canonical_sha256(current_run.get("result")) != request["run"]["result_sha256"]:
            raise RepairError("The bound failed result bytes changed")
        if digest(TARGET) != request["source"]["sha256"]:
            raise RepairError("Original source changed after the failed run")
        validate_execution_closure(request["identities"]["execution_closure"], ROOT)
        scenario = json.loads(SCENARIO.read_text())
        if _model_sha256(scenario) != request["identities"]["scenario_sha256"]:
            raise RepairError("Scenario bytes changed after the failed run")
        bundle = _candidate_bundle(LEGACY_BME)
        if bundle["identities"] != request["identities"]["reviewed_bundle"]:
            raise RepairError("Reviewed bundle identity changed after the failed run")
        if _model_sha256(bundle["reviewed_spec"]) != request["identities"]["spec_sha256"]:
            raise RepairError("Reviewed specification changed after the failed run")
        return bundle, scenario

    @staticmethod
    def _write_atomic(path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("." + path.name + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)

    def _stage_snapshot(self, record, bundle, scenario):
        snapshot = self.root / record["id"] / "execution-snapshot"
        files = {
            "gc_hal.c": (ROOT / "examples/gc_hal.c").read_bytes(),
            "gc_hal.h": (ROOT / "examples/gc_hal.h").read_bytes(),
            "original.c": record["request"]["source"]["content"].encode("utf-8"),
            "candidate.c": record["derived_source"].encode("utf-8"),
            "scenario.json": canonical_json_bytes(scenario),
            "reviewed-bundle.json": canonical_json_bytes(bundle),
            "execution-closure.json": canonical_json_bytes(record["request"]["identities"]["execution_closure"]),
        }
        manifest = {}
        for name, payload in files.items():
            self._write_atomic(snapshot / name, payload)
            manifest[name] = hashlib.sha256(payload).hexdigest()
        body = {"version": "repair-execution-snapshot-v1", "files": manifest}
        body["sha256"] = canonical_sha256(body)
        self._write_atomic(snapshot / "manifest.json", json.dumps(body, indent=2).encode("utf-8") + b"\n")
        return snapshot, body

    @staticmethod
    def _validate_snapshot(snapshot, manifest):
        snapshot = Path(snapshot)
        body = {"version": manifest.get("version"), "files": manifest.get("files")}
        if canonical_sha256(body) != manifest.get("sha256"):
            raise RepairError("Execution snapshot manifest hash changed")
        for name, expected in manifest["files"].items():
            path = snapshot / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RepairError(f"Execution snapshot changed: {name}")

    def _integrity_failure(self, repair_id, exc, *, code="LINEAGE_INTEGRITY_ERROR"):
        with self._lock:
            record = self._repairs[repair_id]
            record.update(status="VERIFICATION_ERROR", origin="demo_repair_error",
                          error_code=code, error=str(exc), completed_at=time.time())
            saved = deepcopy(record)
        self._save(saved)

    def create(self, run_id):
        run = self.run_store.get(run_id)
        repair_id = uuid4().hex
        request_id = uuid4().hex
        request = build_repair_request(run, repair_id=repair_id, request_id=request_id)
        request_bytes = canonical_json_bytes(request)
        record = {
            "id": repair_id, "request_id": request_id, "run_id": run_id,
            "status": "GENERATING", "events": [], "created_at": time.time(),
            "request": request, "request_bytes": request_bytes.decode("utf-8"),
            "request_sha256": hashlib.sha256(request_bytes).hexdigest(), "proposal": None,
        }
        with self._lock:
            self._repairs[repair_id] = record
            saved = deepcopy(record)
        self._save(saved)
        return _public_record(record)

    def generate(self, repair_id):
        self._event(repair_id, "constructing_request", "complete", "Frozen request bytes, closure, and failed-run binding verified")
        try:
            provider = self.provider or provider_from_environment()
            trusted_provider = _provider_identity(provider)
            with self._lock:
                record = self._repairs[repair_id]
                request = deepcopy(record["request"])
                request_sha = record["request_sha256"]
            self._event(repair_id, "requesting_proposal", "running", "Requesting one bounded single-file proposal")
            raw_response = provider.propose(deepcopy(request))
            raw_bytes = canonical_json_bytes(raw_response)
            normalized = json.loads(raw_bytes.decode("utf-8"))
            validate_provider_response(normalized)
            if normalized["provider"] != trusted_provider:
                raise PatchRejected("Provider response identity contradicts trusted configuration")
            derived, touched, changed = validate_and_apply_patch(
                request["source"]["content"], normalized["unified_diff"], request["constraints"]
            )
            if normalized["files_touched"] != [touched]:
                raise PatchRejected("Provider file list does not match the unified diff")
            proposal_id = uuid4().hex
            enriched = {
                **normalized,
                "repair_id": repair_id,
                "request_id": request["request"]["id"],
                "proposal_id": proposal_id,
                "request_sha256": request_sha,
                "response_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "patch_sha256": hashlib.sha256(normalized["unified_diff"].encode("utf-8")).hexdigest(),
                "resulting_source_sha256": hashlib.sha256(derived.encode("utf-8")).hexdigest(),
                "changed_lines": changed,
            }
            with self._lock:
                record = self._repairs[repair_id]
                record.update(
                    status="PROPOSED", proposal_id=proposal_id,
                    trusted_provider=deepcopy(trusted_provider),
                    provider_response_raw=raw_bytes.decode("utf-8"),
                    provider_response=normalized,
                    normalized_proposal_sha256=canonical_sha256(normalized),
                    proposal=enriched, derived_source=derived,
                )
                self._validate_internal_lineage(record)
            self._event(repair_id, "validating_patch", "complete", "Patch bytes and derived source are frozen and hash-bound")
        except TimeoutError as exc:
            with self._lock:
                self._repairs[repair_id].update(status="PROPOSAL_ERROR", error_code="PROVIDER_TIMEOUT", error=str(exc))
        except ProviderUnavailable as exc:
            with self._lock:
                self._repairs[repair_id].update(status="PROPOSAL_ERROR", error_code="PROVIDER_UNAVAILABLE", error=str(exc))
        except PatchRejected as exc:
            with self._lock:
                self._repairs[repair_id].update(status="PATCH_REJECTED", error_code="PATCH_REJECTED", error=str(exc))
        except Exception as exc:
            with self._lock:
                self._repairs[repair_id].update(status="PROPOSAL_ERROR", error_code="MALFORMED_PROVIDER_RESPONSE", error=str(exc))
        with self._lock:
            saved = deepcopy(self._repairs[repair_id])
        self._save(saved)

    def reserve_apply(self, repair_id):
        """Atomically validate, persist APPLYING, and reserve exactly one worker."""
        with self._lock:
            if repair_id not in self._repairs:
                self._load(repair_id)
            record = self._repairs[repair_id]
            if record["status"] != "PROPOSED":
                raise RepairError("Only a validated proposal can be applied")
            try:
                bundle, scenario = self._validate_active_lineage(record)
                snapshot, manifest = self._stage_snapshot(record, bundle, scenario)
            except Exception as exc:
                record.update(status="VERIFICATION_ERROR", origin="demo_repair_error",
                              error_code="LINEAGE_INTEGRITY_ERROR", error=str(exc),
                              completed_at=time.time())
                self._save(deepcopy(record))
                raise RepairError(str(exc)) from exc
            record["status"] = "APPLYING"
            record["snapshot_manifest"] = manifest
            record["events"].append({
                "stage": "apply_reserved", "state": "complete",
                "detail": "Atomic apply reservation persisted before verification",
                "at_ms": round((time.time() - record["created_at"]) * 1000, 3),
            })
            lineage_sha = self._lineage_fingerprint(record)
            self._reservations[repair_id] = {
                "record": deepcopy(record), "bundle": deepcopy(bundle),
                "scenario": deepcopy(scenario), "snapshot": str(snapshot),
                "manifest": deepcopy(manifest), "lineage_sha256": lineage_sha,
                "worker_started": False,
            }
            saved = deepcopy(record)
            self._save(saved)
            return _public_record(record)

    def apply_and_verify(self, repair_id):
        with self._lock:
            reservation = self._reservations.get(repair_id)
        if reservation is None:
            try:
                self.reserve_apply(repair_id)
            except RepairError:
                # Direct/background callers can inspect the persisted integrity
                # failure.  API callers reserve synchronously and still receive
                # the required HTTP 409.
                with self._lock:
                    if self._repairs.get(repair_id, {}).get("status") == "VERIFICATION_ERROR":
                        return
                raise
        with self._lock:
            reservation = self._reservations[repair_id]
            if reservation["worker_started"]:
                raise RepairError("Verification is already running for this repair")
            reservation["worker_started"] = True
            work = deepcopy(reservation)
        record = work["record"]
        request = record["request"]
        provider = record["trusted_provider"]
        self._event(repair_id, "applying_patch", "running", "Using the frozen derived source; original remains read-only")
        try:
            with self._lock:
                current = self._repairs[repair_id]
                if self._lineage_fingerprint(current) != work["lineage_sha256"]:
                    raise RepairError("Repair lineage changed after apply reservation")
            self._validate_active_lineage(record)
            self._validate_snapshot(work["snapshot"], work["manifest"])
            snapshot = Path(work["snapshot"])
            derived_path = snapshot / "candidate.c"
            self._event(repair_id, "compiling_candidate", "running", "Compiling the immutable staged candidate and HAL snapshot")
            result = run_fixture(
                derived_path, scenario=work["scenario"], review_bundle=work["bundle"],
                hal_root=snapshot,
            )
            self._event(repair_id, "deterministic_rerun", "complete", f"Frozen oracle returned {result['status']}")
            validate_execution_closure(request["identities"]["execution_closure"], ROOT)
            self._validate_snapshot(snapshot, work["manifest"])
            if digest(TARGET) != request["source"]["sha256"]:
                raise RepairError("Original source was modified during verification")
            with self._lock:
                if self._lineage_fingerprint(self._repairs[repair_id]) != work["lineage_sha256"]:
                    raise RepairError("Repair lineage changed while verification was running")
            identity_checks = {
                "reviewed_bundle": result.get("review_bundle") == request["identities"]["reviewed_bundle"],
                "spec_sha256": result.get("spec_sha256") == request["identities"]["spec_sha256"],
                "scenario_sha256": result.get("scenario_sha256") == request["identities"]["scenario_sha256"],
                "instance_sha256": request["identities"]["instance_sha256"] is None,
                "fault_plan_sha256": request["identities"]["fault_plan_sha256"] is None,
                "compiler_configuration": (result.get("build") or {}).get("compiler_configuration") == request["identities"]["compiler_configuration"],
                "execution_closure": result.get("execution_closure") == request["identities"]["execution_closure"],
                "staged_hal": (result.get("hal_sha256") == request["identities"]["execution_closure"]["files"]["examples/gc_hal.c"] and
                               result.get("hal_header_sha256") == request["identities"]["execution_closure"]["files"]["examples/gc_hal.h"]),
            }
            if not all(identity_checks.values()):
                raise RepairError("Deterministic rerun identity does not match the failed run")
            live_provider = provider["kind"] == "live_ai"
            if result["status"] == "PASS":
                status, origin = "VERIFIED", "ai_repair_verified" if live_provider else "demo_repair_verified"
            elif result["status"] == "FAIL":
                status, origin = "VERIFICATION_FAILED", "ai_repair_unverified" if live_provider else "demo_repair_unverified"
            elif "Compilation failed" in result.get("error", ""):
                status, origin = "COMPILE_ERROR", "ai_repair_error" if live_provider else "demo_repair_error"
            else:
                status, origin = "VERIFICATION_ERROR", "ai_repair_error" if live_provider else "demo_repair_error"
            audit = {
                "repair_id": record["id"], "request_id": record["request_id"],
                "proposal_id": record["proposal_id"], "original_run_id": record["run_id"],
                "failed_result_sha256": request["run"]["result_sha256"],
                "failed_assertion_ids": request["failure"]["assertion_ids"],
                "original_source_sha256": request["source"]["sha256"],
                "repair_request_sha256": record["request_sha256"],
                "provider": deepcopy(provider),
                "provider_response_sha256": record["proposal"]["response_sha256"],
                "normalized_proposal_sha256": record["normalized_proposal_sha256"],
                "patch_sha256": record["proposal"]["patch_sha256"],
                "resulting_source_sha256": digest(derived_path),
                "execution_closure_sha256": request["identities"]["execution_closure"]["sha256"],
                "snapshot_manifest_sha256": work["manifest"]["sha256"],
                "compile_result": "PASS" if result["status"] != "ERROR" else "ERROR",
                "reviewed_model_identity": result.get("review_bundle"),
                "scenario_sha256": result.get("scenario_sha256"),
                "instance_sha256": None, "fault_plan_sha256": None,
                "compiler_configuration": (result.get("build") or {}).get("compiler_configuration"),
                "executable_sha256": (result.get("build") or {}).get("executable_sha256"),
                "rerun_result": result["status"], "final_repair_status": status,
                "identity_checks": identity_checks, "original_source_preserved": True,
            }
            try:
                derived_label = str(derived_path.relative_to(ROOT))
            except ValueError:
                derived_label = str(derived_path)
            with self._lock:
                current = self._repairs[repair_id]
                current.update(status=status, origin=origin, audit=audit, verification=result,
                               completed_at=time.time(), derived_path=derived_label)
                saved = deepcopy(current)
        except Exception as exc:
            error_origin = "ai_repair_error" if provider.get("kind") == "live_ai" else "demo_repair_error"
            with self._lock:
                current = self._repairs[repair_id]
                current.update(status="VERIFICATION_ERROR", origin=error_origin,
                               error_code="VERIFICATION_ERROR", error=str(exc),
                               completed_at=time.time())
                saved = deepcopy(current)
        self._save(saved)

    def discard(self, repair_id):
        with self._lock:
            if repair_id not in self._repairs:
                self._load(repair_id)
            record = self._repairs[repair_id]
            if record["status"] not in ("PROPOSED", "PROPOSAL_ERROR", "PATCH_REJECTED"):
                raise RepairError("This repair can no longer be discarded")
            record["status"] = "DISCARDED"
            record["completed_at"] = time.time()
            saved = deepcopy(record)
        self._save(saved)
        return _public_record(saved)

    def _load(self, repair_id):
        path = self.root / f"{repair_id}.json"
        if not path.exists():
            raise KeyError(repair_id)
        record = json.loads(path.read_text())
        if record.get("id") != repair_id:
            raise KeyError(repair_id)
        snapshot = self.root / repair_id / "execution-snapshot"
        validate_persisted_repair(record, snapshot=snapshot)
        status = record.get("status")
        if status in {"GENERATING", "PROPOSED"}:
            record.update(status="EXPIRED", error_code="RESTART_REQUIRED",
                          error="Nonterminal repair expired after process restart",
                          completed_at=time.time())
            self._save(record)
        elif status == "APPLYING":
            record.update(status="INTERRUPTED", error_code="RESTART_REQUIRED",
                          error="Verification was interrupted by process restart",
                          completed_at=time.time())
            self._save(record)
        validate_persisted_repair(record, snapshot=snapshot)
        with self._lock:
            self._repairs[repair_id] = record
        return record

    def get(self, repair_id):
        with self._lock:
            record = self._repairs.get(repair_id)
        if record is None:
            record = self._load(repair_id)
        return _public_record(record)

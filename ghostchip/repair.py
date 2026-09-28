"""Bounded repair proposals over one curated fixture; verification remains deterministic."""
from abc import ABC, abstractmethod
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from threading import Lock
import time
from uuid import uuid4

from jsonschema import Draft202012Validator

from .presentation import LEGACY_BME, _candidate_bundle, serialize_trace
from .proof import digest, run_fixture
from .spec import ROOT


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


def canonical_sha256(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


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
    @abstractmethod
    def propose(self, request):
        """Return a RepairProposal dictionary."""


class LocalDemoRepairProvider(RepairProvider):
    """Offline deterministic provider for the curated demo. It is not an AI model."""

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
            "provider": {"id": "ghostchip-local-demo", "kind": "local_demo", "model": "deterministic-rule-v1"},
            "confidence": None,
        }


def provider_from_environment():
    selected = os.environ.get("GHOSTCHIP_REPAIR_PROVIDER", "local-demo")
    if selected == "local-demo":
        return LocalDemoRepairProvider()
    raise ProviderUnavailable(
        f"Repair provider '{selected}' is unavailable. This build ships only the explicitly labeled local-demo provider."
    )


def build_repair_request(run_record):
    if run_record.get("status") != "FAIL" or run_record.get("case_id") != "buggy_driver":
        raise RepairError("Repairs require the immutable failed buggy_driver run")
    result = run_record.get("result")
    if not result or result.get("status") != "FAIL":
        raise RepairError("Failed run has no deterministic failure result")
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
    source = TARGET.read_text()
    compiler = (result.get("build") or {}).get("compiler_configuration")
    if not compiler:
        raise RepairError("Failed run did not record compiler configuration")
    request = {
        "version": "1.0.0",
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
            "path": TARGET_REL, "sha256": digest(TARGET), "start_line": 1,
            "end_line": len(source.splitlines()), "content": source,
        },
        "identities": {
            "reviewed_bundle": deepcopy(result["review_bundle"]),
            "spec_sha256": result["spec_sha256"], "scenario_sha256": result["scenario_sha256"],
            "instance_sha256": None, "fault_plan_sha256": None,
            "compiler_configuration": deepcopy(compiler),
        },
        "constraints": {
            "allowed_files": [TARGET_REL], "forbidden_paths": list(FORBIDDEN_PATHS),
            "max_changed_lines": 4, "max_patch_bytes": 4096,
        },
    }
    return validate_repair_request(request)


def _public_record(record):
    visible = {key: deepcopy(value) for key, value in record.items() if key not in ("request", "derived_source")}
    if "request" in record:
        request = record["request"]
        visible["request"] = {
            "sha256": record["request_sha256"], "run": request["run"], "failure": request["failure"],
            "rule": request["rule"], "source": {key: request["source"][key] for key in ("path", "sha256", "start_line", "end_line")},
            "identities": request["identities"], "constraints": request["constraints"],
        }
    return visible


class RepairStore:
    def __init__(self, run_store, provider=None, root=REPAIR_ROOT):
        self.run_store = run_store
        self.provider = provider
        self.root = Path(root)
        self._repairs = {}
        self._lock = Lock()

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

    def create(self, run_id):
        run = self.run_store.get(run_id)
        request = build_repair_request(run)
        repair_id = uuid4().hex
        record = {
            "id": repair_id, "run_id": run_id, "status": "GENERATING", "events": [],
            "created_at": time.time(), "request": request,
            "request_sha256": canonical_sha256(request), "proposal": None,
        }
        with self._lock:
            self._repairs[repair_id] = record
        return _public_record(record)

    def generate(self, repair_id):
        self._event(repair_id, "constructing_request", "complete", "Bounded request schema and failed-run binding verified")
        try:
            provider = self.provider or provider_from_environment()
            with self._lock:
                request = deepcopy(self._repairs[repair_id]["request"])
            self._event(repair_id, "requesting_proposal", "running", "Requesting one bounded single-file proposal")
            proposal = validate_provider_response(provider.propose(deepcopy(request)))
            derived, touched, changed = validate_and_apply_patch(request["source"]["content"], proposal["unified_diff"], request["constraints"])
            if proposal["files_touched"] != [touched]:
                raise PatchRejected("Provider file list does not match the unified diff")
            response_sha = canonical_sha256(proposal)
            enriched = {**proposal, "request_sha256": self._repairs[repair_id]["request_sha256"],
                        "response_sha256": response_sha,
                        "patch_sha256": hashlib.sha256(proposal["unified_diff"].encode()).hexdigest(),
                        "resulting_source_sha256": hashlib.sha256(derived.encode()).hexdigest(),
                        "changed_lines": changed}
            with self._lock:
                record = self._repairs[repair_id]
                record.update(status="PROPOSED", proposal=enriched, derived_source=derived)
            self._event(repair_id, "validating_patch", "complete", "Patch changes only the allowlisted driver fixture")
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

    def apply_and_verify(self, repair_id):
        with self._lock:
            record = self._repairs[repair_id]
            if record["status"] != "PROPOSED":
                raise RepairError("Only a validated proposal can be applied")
            record["status"] = "APPLYING"
            request = deepcopy(record["request"])
            derived = record["derived_source"]
        self._event(repair_id, "applying_patch", "running", "Creating a derived source artifact; original remains read-only")
        try:
            current_run = self.run_store.get(record["run_id"])
            if canonical_sha256(current_run["result"]) != request["run"]["result_sha256"]:
                raise RepairError("The bound failed run changed after proposal generation")
            if digest(TARGET) != request["source"]["sha256"]:
                raise RepairError("Original source changed after proposal generation")
            repair_dir = self.root / repair_id
            repair_dir.mkdir(parents=True, exist_ok=True)
            derived_path = repair_dir / "bme280_buggy.repaired.c"
            temporary = repair_dir / ".source.tmp"
            temporary.write_text(derived)
            os.replace(temporary, derived_path)
            self._event(repair_id, "compiling_candidate", "running", "Compiling the derived fixture with the original runner")
            bundle = _candidate_bundle(LEGACY_BME)
            scenario = json.loads(SCENARIO.read_text())
            result = run_fixture(derived_path, scenario=scenario, review_bundle=bundle)
            self._event(repair_id, "deterministic_rerun", "complete", f"Unchanged oracle returned {result['status']}")
            identity_checks = {
                "reviewed_bundle": result.get("review_bundle") == request["identities"]["reviewed_bundle"],
                "spec_sha256": result.get("spec_sha256") == request["identities"]["spec_sha256"],
                "scenario_sha256": result.get("scenario_sha256") == request["identities"]["scenario_sha256"],
                "instance_sha256": request["identities"]["instance_sha256"] is None,
                "fault_plan_sha256": request["identities"]["fault_plan_sha256"] is None,
                "compiler_configuration": (result.get("build") or {}).get("compiler_configuration") == request["identities"]["compiler_configuration"],
            }
            if digest(TARGET) != request["source"]["sha256"]:
                raise RepairError("Original source was modified during verification")
            if not all(identity_checks.values()):
                raise RepairError("Deterministic rerun identity does not match the failed run")
            live_provider = record["proposal"]["provider"]["kind"] == "live_ai"
            if result["status"] == "PASS":
                status, origin = "VERIFIED", "ai_repair_verified" if live_provider else "demo_repair_verified"
            elif result["status"] == "FAIL":
                status, origin = "VERIFICATION_FAILED", "ai_repair_unverified" if live_provider else "demo_repair_unverified"
            elif "Compilation failed" in result.get("error", ""):
                status, origin = "COMPILE_ERROR", "ai_repair_error" if live_provider else "demo_repair_error"
            else:
                status, origin = "VERIFICATION_ERROR", "ai_repair_error" if live_provider else "demo_repair_error"
            audit = {
                "original_run_id": record["run_id"],
                "failed_assertion_ids": request["failure"]["assertion_ids"],
                "original_source_sha256": request["source"]["sha256"],
                "repair_request_sha256": record["request_sha256"],
                "provider": record["proposal"]["provider"],
                "provider_response_sha256": record["proposal"]["response_sha256"],
                "patch_sha256": record["proposal"]["patch_sha256"],
                "resulting_source_sha256": digest(derived_path),
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
                self._repairs[repair_id].update(status=status, origin=origin, audit=audit, verification=result,
                                                completed_at=time.time(), derived_path=derived_label)
        except Exception as exc:
            proposal = record.get("proposal") or {}
            provider = proposal.get("provider") or {}
            error_origin = "ai_repair_error" if provider.get("kind") == "live_ai" else "demo_repair_error"
            with self._lock:
                self._repairs[repair_id].update(status="VERIFICATION_ERROR", origin=error_origin,
                                                error_code="VERIFICATION_ERROR", error=str(exc), completed_at=time.time())
        with self._lock:
            saved = deepcopy(self._repairs[repair_id])
        self._save(saved)

    def discard(self, repair_id):
        with self._lock:
            record = self._repairs[repair_id]
            if record["status"] not in ("PROPOSED", "PROPOSAL_ERROR", "PATCH_REJECTED"):
                raise RepairError("This repair can no longer be discarded")
            record["status"] = "DISCARDED"
            record["completed_at"] = time.time()
            saved = deepcopy(record)
        self._save(saved)
        return _public_record(saved)

    def get(self, repair_id):
        with self._lock:
            if repair_id in self._repairs:
                return _public_record(self._repairs[repair_id])
        path = self.root / f"{repair_id}.json"
        if path.exists():
            return _public_record(json.loads(path.read_text()))
        raise KeyError(repair_id)

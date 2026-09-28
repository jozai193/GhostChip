from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from threading import Lock
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ghostchip.api import RunStore, create_app
from ghostchip.presentation import run_demo_case
from ghostchip.proof import digest
from ghostchip.repair import (LocalDemoRepairProvider, PersistedRecordIntegrityError,
                              RepairError, RepairStore, TARGET, build_repair_request,
                              canonical_sha256)
from ghostchip.spec import ROOT


class FakeRunStore:
    def __init__(self, records):
        self.records = {record["id"]: deepcopy(record) for record in records}

    def get(self, run_id):
        if run_id not in self.records:
            raise KeyError(run_id)
        return deepcopy(self.records[run_id])


class SpoofedLiveProvider(LocalDemoRepairProvider):
    def propose(self, request):
        proposal = super().propose(request)
        proposal["provider"] = {"id": "spoof", "kind": "live_ai", "model": "pretend"}
        return proposal


class IrrelevantRepairProvider(LocalDemoRepairProvider):
    def propose(self, request):
        proposal = super().propose(request)
        proposal["explanation"] = "Add a compilable comment that does not change behavior."
        proposal["unified_diff"] = (
            "--- a/examples/bme280_buggy.c\n"
            "+++ b/examples/bme280_buggy.c\n"
            "@@ -2,2 +2,3 @@\n"
            " \n"
            " /* Original small configuration fixture, not the Bosch vendor driver. */\n"
            "+/* Irrelevant compilable edit for verifier-drift regression. */\n"
        )
        return proposal


class Stage7RemediationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run_demo_case("buggy_driver")
        assert result["status"] == "FAIL", result
        cls.failed_a = {
            "id": "failed-a", "case_id": "buggy_driver", "status": "FAIL",
            "created_at": 1.0, "completed_at": 2.0, "events": [], "result": result,
        }
        cls.failed_b = {**deepcopy(cls.failed_a), "id": "failed-b"}

    def make_store(self, provider=None, records=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "repairs"
        store = RepairStore(
            FakeRunStore(records or [self.failed_a, self.failed_b]),
            provider=provider or LocalDemoRepairProvider(), root=root,
        )
        return store, root

    def proposed(self, provider=None):
        store, root = self.make_store(provider)
        created = store.create("failed-a")
        store.generate(created["id"])
        self.assertEqual(store.get(created["id"])["status"], "PROPOSED")
        return store, root, created["id"]

    def persisted_terminal(self, provider=None):
        store, root, repair_id = self.proposed(provider)
        store.apply_and_verify(repair_id)
        path = root / f"{repair_id}.json"
        return store, root, repair_id, path, json.loads(path.read_text())

    def assert_persisted_integrity_error(self, store, root, repair_id, path, record):
        path.write_text(json.dumps(record, indent=2) + "\n")
        restarted = RepairStore(store.run_store, provider=LocalDemoRepairProvider(), root=root)
        with self.assertRaises(PersistedRecordIntegrityError):
            restarted.get(repair_id)
        self.assertEqual(json.loads(path.read_text()), record,
                         "Integrity failure must not rewrite or normalize the forged record")

    def assert_refused(self, store, repair_id):
        with self.assertRaises(RepairError):
            store.reserve_apply(repair_id)
        self.assertEqual(store.get(repair_id)["status"], "VERIFICATION_ERROR")
        self.assertNotIn("audit", store.get(repair_id))

    def test_failed_run_records_full_execution_closure_and_compiler_binary(self):
        result = self.failed_a["result"]
        closure = result["execution_closure"]
        expected = {
            "ghostchip/proof.py", "ghostchip/runtime.py", "ghostchip/spec.py",
            "schema/devicespec-v1.schema.json", "examples/gc_hal.c", "examples/gc_hal.h",
        }
        self.assertTrue(expected.issubset(closure["files"]))
        self.assertEqual(closure["compiler"]["sha256"], digest(closure["compiler"]["path"]))
        self.assertEqual(result["build"]["compiler_configuration"]["sha256"],
                         closure["compiler"]["sha256"])

    def test_verifier_runtime_validator_schema_and_hal_drift_cannot_verify(self):
        mutations = {
            "ghostchip/runtime.py": lambda data: data + b"\n# stage7 drift\n",
            "ghostchip/spec.py": lambda data: data + b"\n# stage7 drift\n",
            "schema/devicespec-v1.schema.json": lambda data: data + b" \n",
            "examples/gc_hal.c": lambda data: data + b"\n/* stage7 drift */\n",
        }
        for relative, mutate in mutations.items():
            with self.subTest(relative=relative):
                store, _, repair_id = self.proposed()
                path = ROOT / relative
                original = path.read_bytes()
                changed = mutate(original)
                self.assertNotEqual(changed, original)
                try:
                    path.write_bytes(changed)
                    self.assert_refused(store, repair_id)
                    self.assertIn(relative, store.get(repair_id)["error"])
                finally:
                    path.write_bytes(original)

    def test_irrelevant_repair_plus_verifier_comparison_mutation_cannot_verify(self):
        store, _, repair_id = self.proposed(IrrelevantRepairProvider())
        proof_path = ROOT / "ghostchip/proof.py"
        original = proof_path.read_bytes()
        changed = original.replace(
            b'passed = actual == assertion["equals"]', b"passed = True", 1
        )
        self.assertNotEqual(changed, original)
        try:
            proof_path.write_bytes(changed)
            store.apply_and_verify(repair_id)
            final = store.get(repair_id)
            self.assertEqual(final["status"], "VERIFICATION_ERROR")
            self.assertNotIn("verification", final)
            self.assertNotIn("audit", final)
            self.assertIn("ghostchip/proof.py", final["error"])
        finally:
            proof_path.write_bytes(original)

    def test_source_drift_between_failed_run_and_request_is_rejected(self):
        original = TARGET.read_bytes()
        try:
            TARGET.write_bytes(original + b"\n/* late source drift */\n")
            with self.assertRaisesRegex(RepairError, "Original source changed"):
                build_repair_request(self.failed_a)
        finally:
            TARGET.write_bytes(original)

    def test_every_hash_and_displayed_or_hidden_byte_mutation_is_rejected(self):
        mutations = {
            "request hash": lambda record: record.update(request_sha256="0" * 64),
            "response hash": lambda record: record["proposal"].update(response_sha256="0" * 64),
            "patch hash": lambda record: record["proposal"].update(patch_sha256="0" * 64),
            "result hash": lambda record: record["proposal"].update(resulting_source_sha256="0" * 64),
            "displayed diff": lambda record: record["proposal"].update(
                unified_diff=record["proposal"]["unified_diff"] + "\n"),
            "hidden derived bytes": lambda record: record.update(
                derived_source=record["derived_source"] + "/* hidden */\n"),
            "request bytes": lambda record: record["request"]["source"].update(
                content=record["request"]["source"]["content"] + "\n"),
            "compiler identity": lambda record: record["request"]["identities"]["compiler_configuration"].update(
                sha256="0" * 64),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                store, _, repair_id = self.proposed()
                mutate(store._repairs[repair_id])
                self.assert_refused(store, repair_id)

    def test_identical_result_cannot_rebind_run_a_to_run_b(self):
        store, _, repair_id = self.proposed()
        self.assertEqual(self.failed_a["result"], self.failed_b["result"])
        store._repairs[repair_id]["run_id"] = "failed-b"
        self.assert_refused(store, repair_id)

    def test_provider_response_cannot_self_declare_live_ai(self):
        # Build explicitly because a spoofed response must never reach PROPOSED.
        store, _ = self.make_store(SpoofedLiveProvider())
        created = store.create("failed-a")
        store.generate(created["id"])
        record = store.get(created["id"])
        self.assertEqual(record["status"], "PATCH_REJECTED")
        self.assertNotIn("audit", record)

    def test_provider_metadata_change_after_applying_begins_fails(self):
        store, _, repair_id = self.proposed()
        store.reserve_apply(repair_id)
        from ghostchip import repair as repair_module
        original = repair_module.run_fixture

        def mutate_during_run(*args, **kwargs):
            store._repairs[repair_id]["proposal"]["provider"]["kind"] = "live_ai"
            return original(*args, **kwargs)

        with patch("ghostchip.repair.run_fixture", side_effect=mutate_during_run):
            store.apply_and_verify(repair_id)
        final = store.get(repair_id)
        self.assertEqual(final["status"], "VERIFICATION_ERROR")
        self.assertNotIn("audit", final)
        self.assertNotEqual(final.get("origin"), "ai_repair_verified")

    def test_verifier_change_during_verification_is_detected_post_run(self):
        store, _, repair_id = self.proposed()
        store.reserve_apply(repair_id)
        proof_path = ROOT / "ghostchip/proof.py"
        original_bytes = proof_path.read_bytes()
        from ghostchip import repair as repair_module
        original_run = repair_module.run_fixture

        def mutate_after_runner(*args, **kwargs):
            result = original_run(*args, **kwargs)
            proof_path.write_bytes(original_bytes + b"\n# during-run drift\n")
            return result

        try:
            with patch("ghostchip.repair.run_fixture", side_effect=mutate_after_runner):
                store.apply_and_verify(repair_id)
            self.assertEqual(store.get(repair_id)["status"], "VERIFICATION_ERROR")
            self.assertIn("ghostchip/proof.py", store.get(repair_id)["error"])
        finally:
            proof_path.write_bytes(original_bytes)

    def test_atomic_store_reservation_allows_exactly_one_verification(self):
        store, _, repair_id = self.proposed()
        from ghostchip import repair as repair_module
        original = repair_module.run_fixture
        calls = 0
        calls_lock = Lock()

        def delayed(*args, **kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.15)
            return original(*args, **kwargs)

        def apply():
            try:
                store.apply_and_verify(repair_id)
                return "accepted"
            except RepairError:
                return "rejected"

        with patch("ghostchip.repair.run_fixture", side_effect=delayed):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: apply(), range(2)))
        self.assertEqual(sorted(outcomes), ["accepted", "rejected"])
        self.assertEqual(calls, 1)
        self.assertEqual(store.get(repair_id)["status"], "VERIFIED")

    def test_sequential_double_apply_runs_verification_once(self):
        store, _, repair_id = self.proposed()
        from ghostchip import repair as repair_module
        original = repair_module.run_fixture
        calls = 0

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        with patch("ghostchip.repair.run_fixture", side_effect=counted):
            store.apply_and_verify(repair_id)
            with self.assertRaises(RepairError):
                store.apply_and_verify(repair_id)
        self.assertEqual(calls, 1)
        self.assertEqual(store.get(repair_id)["status"], "VERIFIED")

    def test_concurrent_http_apply_returns_one_202_and_one_409(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run_store = RunStore(root=Path(temporary.name) / "runs")
        run_store._runs["failed-a"] = deepcopy(self.failed_a)
        repairs = RepairStore(run_store, provider=LocalDemoRepairProvider(),
                              root=Path(temporary.name) / "repairs")
        client = TestClient(create_app(store=run_store, repair_store=repairs,
                                       static_dir=Path(temporary.name) / "missing"))
        created = repairs.create("failed-a")
        repairs.generate(created["id"])
        from ghostchip import repair as repair_module
        original = repair_module.run_fixture
        calls = 0
        calls_lock = Lock()

        def delayed(*args, **kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.2)
            return original(*args, **kwargs)

        with patch("ghostchip.repair.run_fixture", side_effect=delayed):
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(
                    lambda _: client.post(f"/api/repairs/{created['id']}/apply-and-verify"), range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [202, 409])
        self.assertEqual(calls, 1)
        self.assertEqual(client.post(f"/api/repairs/{created['id']}/apply-and-verify").status_code, 409)

    def test_restart_policy_expires_proposal_interrupts_applying_and_reads_terminal(self):
        store, root, repair_id = self.proposed()
        restarted = RepairStore(store.run_store, provider=LocalDemoRepairProvider(), root=root)
        self.assertEqual(restarted.get(repair_id)["status"], "EXPIRED")
        with self.assertRaises(RepairError):
            restarted.reserve_apply(repair_id)

        store2, root2, repair_id2 = self.proposed()
        store2.reserve_apply(repair_id2)
        restarted2 = RepairStore(store2.run_store, provider=LocalDemoRepairProvider(), root=root2)
        self.assertEqual(restarted2.get(repair_id2)["status"], "INTERRUPTED")

        store3, root3, repair_id3 = self.proposed()
        store3.apply_and_verify(repair_id3)
        restarted3 = RepairStore(store3.run_store, provider=LocalDemoRepairProvider(), root=root3)
        self.assertEqual(restarted3.get(repair_id3)["status"], "VERIFIED")

    def test_apply_after_discard_is_rejected_without_verification(self):
        store, _, repair_id = self.proposed()
        store.discard(repair_id)
        with patch("ghostchip.repair.run_fixture") as runner:
            with self.assertRaises(RepairError):
                store.reserve_apply(repair_id)
        runner.assert_not_called()

    def test_persisted_audit_tampering_raises_without_rewriting_record(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        record["audit"]["provider"]["kind"] = "live_ai"
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_contradictory_persisted_verified_status_is_rejected(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        record["audit"]["final_repair_status"] = "VERIFICATION_FAILED"
        record["audit"]["rerun_result"] = "FAIL"
        record["verification"]["status"] = "FAIL"
        assertion = next(item for item in record["verification"]["assertions"]
                         if item["id"] == "effective_request")
        assertion.update(actual=0, passed=False)
        record["verification"]["violations"] = [{"assertion_id": "effective_request"}]
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_persisted_verified_requires_verification_payload(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        record.pop("verification")
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_persisted_verified_requires_audit_payload(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        record.pop("audit")
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_persisted_verified_recomputes_assertion_comparator(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        assertion = next(item for item in record["verification"]["assertions"]
                         if item["id"] == "effective_request")
        assertion.update(actual=0, passed=True)
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_persisted_verified_rejects_altered_executable_identity(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        record["audit"]["executable_sha256"] = "0" * 64
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_persisted_verified_rejects_altered_model_scenario_and_compiler(self):
        store, root, repair_id, path, original = self.persisted_terminal()
        mutations = {
            "Scenario": lambda record: record["verification"].update(scenario_sha256="0" * 64),
            "reviewed bundle": lambda record: record["verification"].update(review_bundle={}),
            "compiler": lambda record: record["verification"]["build"]["compiler_configuration"].update(
                flags=["-O3"]),
        }
        for label, mutate in mutations.items():
            with self.subTest(identity=label):
                record = deepcopy(original)
                mutate(record)
                self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_persisted_verified_rejects_altered_closure_and_snapshot(self):
        store, root, repair_id, path, original = self.persisted_terminal()

        changed_closure = deepcopy(original)
        changed_closure["verification"]["execution_closure"]["sha256"] = "0" * 64
        self.assert_persisted_integrity_error(store, root, repair_id, path, changed_closure)

        changed_snapshot = deepcopy(original)
        manifest = changed_snapshot["snapshot_manifest"]
        manifest["files"]["candidate.c"] = "0" * 64
        manifest["sha256"] = canonical_sha256({
            "version": manifest["version"], "files": manifest["files"],
        })
        changed_snapshot["audit"]["snapshot_manifest_sha256"] = manifest["sha256"]
        self.assert_persisted_integrity_error(store, root, repair_id, path, changed_snapshot)

        store2, root2, repair_id2, _, _ = self.persisted_terminal()
        scenario_path = root2 / repair_id2 / "execution-snapshot" / "scenario.json"
        scenario_path.write_text("{}")
        restarted = RepairStore(store2.run_store, provider=LocalDemoRepairProvider(), root=root2)
        with self.assertRaises(PersistedRecordIntegrityError):
            restarted.get(repair_id2)

    def test_persisted_verified_rejects_altered_source_lineage(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        record["derived_source"] += "/* forged stored bytes */\n"
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_redundant_proposal_normalized_hash_is_removed_and_legacy_mismatch_rejected(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        self.assertNotIn("normalized_proposal_sha256", record["proposal"])
        legacy = deepcopy(record)
        legacy["proposal"]["normalized_proposal_sha256"] = legacy["normalized_proposal_sha256"]
        path.write_text(json.dumps(legacy, indent=2) + "\n")
        restarted = RepairStore(store.run_store, provider=LocalDemoRepairProvider(), root=root)
        self.assertEqual(restarted.get(repair_id)["status"], "VERIFIED")
        record["proposal"]["normalized_proposal_sha256"] = "0" * 64
        self.assert_persisted_integrity_error(store, root, repair_id, path, record)

    def test_valid_persisted_verified_record_loads(self):
        store, root, repair_id, _, _ = self.persisted_terminal()
        restarted = RepairStore(store.run_store, provider=LocalDemoRepairProvider(), root=root)
        self.assertEqual(restarted.get(repair_id)["status"], "VERIFIED")

    def test_valid_persisted_verification_failed_record_loads(self):
        store, root, repair_id, _, record = self.persisted_terminal(IrrelevantRepairProvider())
        self.assertEqual(record["status"], "VERIFICATION_FAILED")
        restarted = RepairStore(store.run_store, provider=IrrelevantRepairProvider(), root=root)
        self.assertEqual(restarted.get(repair_id)["status"], "VERIFICATION_FAILED")

    def test_restart_http_forged_terminal_returns_explicit_integrity_error(self):
        store, root, repair_id, path, record = self.persisted_terminal()
        record["audit"]["final_repair_status"] = "VERIFICATION_FAILED"
        record["verification"]["status"] = "FAIL"
        path.write_text(json.dumps(record, indent=2) + "\n")
        restarted = RepairStore(store.run_store, provider=LocalDemoRepairProvider(), root=root)
        client = TestClient(create_app(store=store.run_store, repair_store=restarted,
                                       static_dir=root / "missing"))
        response = client.get(f"/api/repairs/{repair_id}")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {
            "status": "PERSISTED_RECORD_INTEGRITY_ERROR",
            "repair_id": repair_id,
            "message": "Stored repair evidence is internally inconsistent.",
        })
        self.assertNotEqual(response.json()["status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from ghostchip.api import RunStore, create_app
from ghostchip.presentation import run_demo_case
from ghostchip.repair import (LocalDemoRepairProvider, PatchRejected, ProviderUnavailable,
                              RepairStore, TARGET, TARGET_REL, build_repair_request,
                              validate_and_apply_patch)


class StaticProvider:
    def __init__(self, diff, *, touched=None, kind="test"):
        self.diff = diff
        self.touched = touched or [TARGET_REL]
        self.kind = kind

    def propose(self, request):
        return {
            "version": "1.0.0", "explanation": "Test proposal",
            "unified_diff": self.diff, "files_touched": self.touched,
            "provider": {"id": "test-provider", "kind": self.kind, "model": "fixture-v1"},
            "confidence": None,
        }


class TimeoutProvider:
    def propose(self, request):
        raise TimeoutError("provider timed out")


class MalformedProvider:
    def propose(self, request):
        return {"explanation": "missing required fields"}


class UnavailableProvider:
    def propose(self, request):
        raise ProviderUnavailable("provider is not configured")


class FakeRunStore:
    def __init__(self, record):
        self.record = record

    def get(self, run_id):
        if run_id != self.record["id"]:
            raise KeyError(run_id)
        return deepcopy(self.record)


def proposal_for(path, body, *, header="@@ -1,1 +1,1 @@"):
    return f"--- a/{path}\n+++ b/{path}\n{header}\n{body}"


class Stage6RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run_demo_case("buggy_driver")
        assert result["status"] == "FAIL", result
        cls.failed = {"id": "failed-run", "case_id": "buggy_driver", "status": "FAIL",
                      "created_at": 1.0, "completed_at": 2.0, "events": [], "result": result}
        cls.source = TARGET.read_text()
        cls.good_diff = LocalDemoRepairProvider().propose(build_repair_request(cls.failed))["unified_diff"]

    def store(self, provider):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return RepairStore(FakeRunStore(self.failed), provider=provider, root=Path(temporary.name))

    def generated(self, provider):
        store = self.store(provider)
        created = store.create("failed-run")
        store.generate(created["id"])
        return store, store.get(created["id"])

    def test_request_is_schema_valid_bound_and_minimal(self):
        request = build_repair_request(self.failed)
        self.assertEqual(request["run"]["id"], "failed-run")
        self.assertEqual(request["failure"]["assertion_ids"], ["effective_request"])
        self.assertEqual(request["rule"]["id"], "humidity_latch")
        self.assertEqual({item["pdf_page"] for item in request["rule"]["evidence"]}, {27, 28})
        self.assertEqual(request["source"]["path"], TARGET_REL)
        self.assertNotIn("third_party", request["source"]["content"])
        self.assertEqual(request["identities"]["scenario_sha256"], self.failed["result"]["scenario_sha256"])

    def test_valid_diff_applies_only_to_derived_source(self):
        request = build_repair_request(self.failed)
        derived, path, changed = validate_and_apply_patch(self.source, self.good_diff, request["constraints"])
        self.assertEqual(path, TARGET_REL)
        self.assertEqual(changed, 2)
        self.assertLess(derived.index("0xF2"), derived.index("0xF4"))
        self.assertEqual(hashlib.sha256(TARGET.read_bytes()).hexdigest(), request["source"]["sha256"])

    def test_oracle_modification_is_rejected(self):
        request = build_repair_request(self.failed)
        diff = proposal_for("fixtures/bme280/scenario.json", '-{\n+{"weakened":true}\n')
        with self.assertRaises(PatchRejected):
            validate_and_apply_patch("{}\n", diff, request["constraints"])

    def test_bosch_source_modification_is_rejected(self):
        request = build_repair_request(self.failed)
        diff = proposal_for("third_party/bosch_bme280/bme280.c", "-old\n+new\n")
        with self.assertRaises(PatchRejected):
            validate_and_apply_patch("old\n", diff, request["constraints"])

    def test_path_traversal_is_rejected(self):
        request = build_repair_request(self.failed)
        diff = proposal_for("../tests/test_proof.py", "-old\n+new\n")
        with self.assertRaises(PatchRejected):
            validate_and_apply_patch("old\n", diff, request["constraints"])

    def test_non_diff_preamble_is_rejected(self):
        request = build_repair_request(self.failed)
        with self.assertRaises(PatchRejected):
            validate_and_apply_patch(self.source, "model commentary\n" + self.good_diff, request["constraints"])

    def test_patch_size_and_changed_line_bounds_are_enforced(self):
        request = build_repair_request(self.failed)
        diff = ("--- a/examples/bme280_buggy.c\n+++ b/examples/bme280_buggy.c\n"
                "@@ -1,1 +1,6 @@\n" + self.source.splitlines()[0] + "\n" +
                "".join(f"+/* extra {index} */\n" for index in range(5)))
        with self.assertRaises(PatchRejected):
            validate_and_apply_patch(self.source, diff, request["constraints"])
        tiny = deepcopy(request["constraints"])
        tiny["max_patch_bytes"] = 10
        with self.assertRaises(PatchRejected):
            validate_and_apply_patch(self.source, self.good_diff, tiny)

    def test_provider_file_list_must_match_validated_diff(self):
        _, repair = self.generated(StaticProvider(self.good_diff, touched=["tests/test_proof.py"]))
        self.assertEqual(repair["status"], "PATCH_REJECTED")

    def test_correct_patch_is_deterministically_verified_with_same_identities(self):
        original = hashlib.sha256(TARGET.read_bytes()).hexdigest()
        store, proposal = self.generated(LocalDemoRepairProvider())
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertEqual(proposal["proposal"]["provider"]["kind"], "local_demo")
        store.apply_and_verify(proposal["id"])
        final = store.get(proposal["id"])
        self.assertEqual(final["status"], "VERIFIED", final.get("error"))
        self.assertEqual(final["origin"], "demo_repair_verified")
        self.assertEqual(final["verification"]["status"], "PASS")
        self.assertTrue(all(final["audit"]["identity_checks"].values()))
        self.assertTrue(final["audit"]["original_source_preserved"])
        self.assertNotEqual(final["audit"]["original_source_sha256"], final["audit"]["resulting_source_sha256"])
        self.assertEqual(hashlib.sha256(TARGET.read_bytes()).hexdigest(), original)
        self.assertTrue(final["audit"]["executable_sha256"])
        self.assertTrue(Path(final["derived_path"]).is_file())

    def test_incorrect_patch_is_verification_failed(self):
        diff = ("--- a/examples/bme280_buggy.c\n+++ b/examples/bme280_buggy.c\n"
                "@@ -3,1 +3,2 @@\n"
                " /* Original small configuration fixture, not the Bosch vendor driver. */\n"
                "+/* This comment does not repair behavior. */\n")
        store, proposal = self.generated(StaticProvider(diff))
        self.assertEqual(proposal["status"], "PROPOSED")
        store.apply_and_verify(proposal["id"])
        final = store.get(proposal["id"])
        self.assertEqual(final["status"], "VERIFICATION_FAILED")
        self.assertEqual(final["origin"], "demo_repair_unverified")
        self.assertEqual(final["verification"]["status"], "FAIL")

    def test_compile_error_is_distinct_from_verification_failure(self):
        diff = ("--- a/examples/bme280_buggy.c\n+++ b/examples/bme280_buggy.c\n"
                "@@ -5,1 +5,1 @@\n"
                "-    uint8_t id, humidity = 3, measurement = 0; /* Stay in sleep; no timing claims. */\n"
                "+    this is not valid C;\n")
        store, proposal = self.generated(StaticProvider(diff))
        store.apply_and_verify(proposal["id"])
        final = store.get(proposal["id"])
        self.assertEqual(final["status"], "COMPILE_ERROR")
        self.assertEqual(final["origin"], "demo_repair_error")
        self.assertEqual(final["verification"]["status"], "ERROR")

    def test_timeout_and_malformed_provider_are_proposal_errors(self):
        _, timeout = self.generated(TimeoutProvider())
        self.assertEqual((timeout["status"], timeout["error_code"]), ("PROPOSAL_ERROR", "PROVIDER_TIMEOUT"))
        _, malformed = self.generated(MalformedProvider())
        self.assertEqual((malformed["status"], malformed["error_code"]),
                         ("PROPOSAL_ERROR", "MALFORMED_PROVIDER_RESPONSE"))
        _, unavailable = self.generated(UnavailableProvider())
        self.assertEqual((unavailable["status"], unavailable["error_code"]),
                         ("PROPOSAL_ERROR", "PROVIDER_UNAVAILABLE"))

    def test_only_failed_curated_run_can_generate_repair(self):
        changed = deepcopy(self.failed)
        changed["status"] = changed["result"]["status"] = "PASS"
        with self.assertRaises(Exception):
            build_repair_request(changed)

    def test_discard_requires_no_source_write(self):
        store, proposal = self.generated(LocalDemoRepairProvider())
        original = hashlib.sha256(TARGET.read_bytes()).hexdigest()
        discarded = store.discard(proposal["id"])
        self.assertEqual(discarded["status"], "DISCARDED")
        self.assertEqual(hashlib.sha256(TARGET.read_bytes()).hexdigest(), original)

    def test_api_maps_fail_to_proposal_to_verified(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run_store = RunStore(root=Path(temporary.name) / "runs")
        run_store._runs["failed-run"] = deepcopy(self.failed)
        repairs = RepairStore(run_store, provider=LocalDemoRepairProvider(), root=Path(temporary.name) / "repairs")
        client = TestClient(create_app(store=run_store, repair_store=repairs,
                                       static_dir=Path(temporary.name) / "missing"))
        created = client.post("/api/runs/failed-run/repair")
        self.assertEqual(created.status_code, 202)
        repair_id = created.json()["id"]
        proposal = client.get(f"/api/repairs/{repair_id}").json()
        self.assertEqual(proposal["status"], "PROPOSED")
        applied = client.post(f"/api/repairs/{repair_id}/apply-and-verify")
        self.assertEqual(applied.status_code, 202)
        final = client.get(f"/api/repairs/{repair_id}").json()
        self.assertEqual(final["status"], "VERIFIED")
        self.assertEqual(final["audit"]["original_run_id"], "failed-run")

    def test_api_exposes_provider_failure_without_a_verified_state(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run_store = RunStore(root=Path(temporary.name) / "runs")
        run_store._runs["failed-run"] = deepcopy(self.failed)
        repairs = RepairStore(run_store, provider=TimeoutProvider(), root=Path(temporary.name) / "repairs")
        client = TestClient(create_app(store=run_store, repair_store=repairs,
                                       static_dir=Path(temporary.name) / "missing"))
        created = client.post("/api/runs/failed-run/repair")
        self.assertEqual(created.status_code, 202)
        record = client.get(f"/api/repairs/{created.json()['id']}").json()
        self.assertEqual((record["status"], record["error_code"]),
                         ("PROPOSAL_ERROR", "PROVIDER_TIMEOUT"))
        self.assertNotIn("audit", record)


if __name__ == "__main__":
    unittest.main()

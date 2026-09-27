import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ghostchip.api import RunStore, create_app
from ghostchip.presentation import (cases, device_detail, run_demo_case,
                                    serialize_trace, summarize_result)


def result_for(status):
    result = {
        "status": status,
        "case": "test_case",
        "presentation": {"label": "Test case"},
        "assertions": [{"id": "actual_check", "equals": 3, "actual": 3,
                        "basis": "Fixture result", "passed": status == "PASS"}],
        "violations": [],
        "callbacks": [{"operation": "read", "register_address": 0xD0,
                       "length": 1, "status": 0}],
        "elapsed_ms": 1.25,
        "model_origin": "test_origin",
        "review_bundle": {"candidate_sha256": "a" * 64},
        "build": {"upstream_commit": "c90d419"},
    }
    if status == "FAIL":
        result["violations"] = [{"assertion_id": "actual_check", "evidence": [
            {"pdf_page": 27, "section": "5.4.3", "summary": "Latch rule"}
        ]}]
    if status == "ERROR":
        result["error"] = "intentional runner error"
    return result


class Stage5ApiTests(unittest.TestCase):
    def client(self, status):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        def runner(case_id, progress):
            progress("executing_callbacks", "running", "Real work started")
            progress("executing_callbacks", "complete", "Real work completed")
            result = result_for(status)
            result["case"] = case_id
            return result

        store = RunStore(runner=runner, root=Path(temporary.name))
        return TestClient(create_app(store=store, static_dir=Path(temporary.name) / "missing"))

    def run_status(self, status):
        client = self.client(status)
        response = client.post("/api/cases/init_ok/run")
        self.assertEqual(response.status_code, 202)
        final = client.get(f"/api/runs/{response.json()['id']}")
        self.assertEqual(final.status_code, 200)
        return client, final.json()

    def test_pass_response_preserves_actual_verdict_and_counts(self):
        _, final = self.run_status("PASS")
        self.assertEqual(final["status"], "PASS")
        self.assertEqual(final["result"]["assertion_passed"], 1)
        self.assertEqual(final["result"]["callback_count"], 1)

    def test_fail_response_is_not_converted_to_error_or_pass(self):
        _, final = self.run_status("FAIL")
        self.assertEqual(final["status"], "FAIL")
        self.assertEqual(final["result"]["assertion_passed"], 0)

    def test_error_response_is_distinct(self):
        _, final = self.run_status("ERROR")
        self.assertEqual(final["status"], "ERROR")
        self.assertIn("intentional", final["result"]["error"])

    def test_trace_and_evidence_serialization(self):
        client, final = self.run_status("FAIL")
        trace = client.get(f"/api/runs/{final['id']}/trace").json()["trace"]
        self.assertEqual((trace[0]["operation"], trace[0]["register_hex"], trace[0]["label"]),
                         ("READ", "0xD0", "Chip ID"))
        evidence = client.get(f"/api/runs/{final['id']}/evidence").json()
        self.assertEqual(evidence["evidence"][0]["pdf_page"], 27)
        self.assertEqual(evidence["source_identity"]["upstream_commit"], "c90d419")

    def test_unknown_case_and_run_are_404(self):
        client = self.client("PASS")
        self.assertEqual(client.post("/api/cases/not-curated/run").status_code, 404)
        self.assertEqual(client.get("/api/runs/not-a-run").status_code, 404)


class Stage5PresentationTests(unittest.TestCase):
    def test_bosch_identity_and_reviewed_evidence_come_from_artifacts(self):
        detail = device_detail("bme280")
        self.assertEqual(detail["driver"]["commit"],
                         "c90d419492e26dd95586598a794e65eb2760753a")
        self.assertEqual(detail["driver"]["source_integrity"], "VERIFIED")
        latch = next(rule for rule in detail["rules"] if rule["id"] == "humidity_latch")
        self.assertEqual(latch["status"], "REVIEWED")
        self.assertEqual({item["page"] for item in latch["evidence"]}, {27, 28})

    def test_adxl_metadata_states_generalization_boundary(self):
        detail = device_detail("adxl345")
        self.assertEqual(detail["vendor"], "Analog Devices")
        self.assertIn("device-document-specific", detail["generalization"]["boundary"])
        self.assertGreaterEqual(detail["rule_count"], 2)

    def test_negative_control_is_unambiguously_unreviewed(self):
        negative = next(item for item in cases() if item["id"] == "humidity_x4_no_latch")
        self.assertTrue(negative["unreviewed"])
        self.assertIn("negative control", negative["group"].lower())
        self.assertIn("UNREVIEWED", negative["summary"])

    def test_trace_serialization_uses_recorded_values(self):
        rows = serialize_trace({"callbacks": [
            {"operation": "delay", "duration_us": 2000, "status": 0},
            {"operation": "write", "register_address": 0xF2, "length": 1, "status": -1},
        ]})
        self.assertEqual(rows[0]["duration_us"], 2000)
        self.assertEqual((rows[1]["register_hex"], rows[1]["status"]), ("0xF2", -1))

    def test_malformed_status_summarizes_as_error(self):
        summary = summarize_result({"status": "SUCCESS", "assertions": [], "callbacks": []})
        self.assertEqual(summary["status"], "ERROR")

    def test_actual_runner_integration_init_ok(self):
        result = run_demo_case("init_ok")
        self.assertEqual(result["status"], "PASS", result.get("error"))
        self.assertEqual(result["observations"]["api.init"]["value"], 0)
        self.assertEqual(len(result["callbacks"]), 6)


if __name__ == "__main__":
    unittest.main()

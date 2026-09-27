import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

from ghostchip.contracts import validate_fault_plan, validate_scenario
from ghostchip.extraction import canonical_sha256, extract_candidate
from ghostchip.pdf_ingest import document_from_page_map, ingest_pdf
from ghostchip.real_driver import FIXTURE, UPSTREAM, run_case, verify_upstream
from ghostchip.runtime import OutOfModel, Peripheral
from ghostchip.spec import ROOT, validate


def synthetic_spec():
    evidence = [{"id":"source_fact","source_id":"synthetic_source","pdf_page":1,
                 "printed_page":"1","section":"test","summary":"Synthetic generic semantics",
                 "origin":"manual_review","review":"accepted","confidence":None}]
    full = lambda name: [{"id":name,"lsb":0,"width":8}]
    return {
        "schema_version":"1.1.0","profile":"i2c-reg8-settle-v1",
        "device":{"name":"Generic device","vendor":"Test","bus":"i2c","address":42},
        "scope":{"description":"Generic settle and incrementing-read test",
                 "unsupported":["all other behavior"],"write_constraints":[]},
        "sources":[{"id":"synthetic_source","url":"https://example.invalid/source.pdf",
                    "sha256":"0"*64,"page_count":1,"revision":"test"}],
        "evidence":evidence,
        "registers":[
            {"id":"command","address":10,"width":8,"reset":0,"access":"rw",
             "reserved_mask":0,"fields":full("value"),"evidence":["source_fact"]},
            {"id":"byte_a","address":16,"width":8,"reset":{"parameter":"image_a"},"access":"ro",
             "reserved_mask":0,"fields":full("value"),"evidence":["source_fact"]},
            {"id":"byte_b","address":17,"width":8,"reset":{"parameter":"image_b"},"access":"ro",
             "reserved_mask":0,"fields":full("value"),"evidence":["source_fact"]}],
        "state":[{"id":"ready","width":1,"reset":0,"evidence":["source_fact"]}],
        "rules":[{"id":"bounded_settle","on":{"event":"after_write","register":"command"},
                  "when":{"ref":{"kind":"field","register":"command","field":"value"},"equals":9},
                  "effects":[{"target":{"kind":"state","id":"ready"},"value":1}],
                  "settle_us":2000,"evidence":["source_fact"]}],
        "parameters":[{"id":"image_a","width":8,"address":16,"evidence":["source_fact"]},
                      {"id":"image_b","width":8,"address":17,"evidence":["source_fact"]}],
        "transport":{"max_read_length":4,"incrementing_read_ranges":[{"start":16,"length":2}]}}


class GenericProfileTests(unittest.TestCase):
    def test_parameters_burst_and_partial_settle_are_generic(self):
        spec = validate(synthetic_spec())
        instance = {"parameters":{"image_a":11,"image_b":22}}
        model = Peripheral(spec, instance)
        self.assertEqual(model.read(42, 16, 2), [11, 22])
        model.write(42, 10, [9])
        with self.assertRaisesRegex(OutOfModel, "settle"):
            model.read(42, 16, 1)
        model.advance_time_us(1999)
        with self.assertRaisesRegex(OutOfModel, "settle"):
            model.read(42, 16, 1)
        model.advance_time_us(1)
        self.assertEqual(model.read(42, 16, 2), [11, 22])
        model.write(42, 10, [9])
        model.advance_time_us(2000)
        self.assertEqual(model.read(42, 16, 2), [11, 22])

    def test_missing_parameters_lengths_and_ranges_reject(self):
        spec = validate(synthetic_spec())
        with self.assertRaisesRegex(OutOfModel, "every declared"):
            Peripheral(spec, {"parameters":{"image_a":1}})
        model = Peripheral(spec, {"parameters":{"image_a":1,"image_b":2}})
        for operation in (lambda: model.read(42, 16, 5),
                          lambda: model.read(42, 15, 2),
                          lambda: model.write(42, 10, [1, 2])):
            with self.subTest(operation=operation):
                with self.assertRaises(OutOfModel):
                    operation()

    def test_state_and_time_do_not_leak_across_runs(self):
        spec = validate(synthetic_spec())
        instance = {"parameters":{"image_a":1,"image_b":2}}
        first = Peripheral(spec, instance)
        first.write(42, 10, [9])
        first.advance_time_us(2000)
        fresh = Peripheral(spec, instance)
        self.assertEqual((fresh.time_us, fresh.settle_until_us, fresh.state["ready"]), (0, 0, 0))

    def test_generic_core_has_no_bosch_dispatch(self):
        forbidden = ("bme280", "bosch", "ctrl_hum", "0xd0", "calib_88")
        for path in (ROOT / "ghostchip/runtime.py", ROOT / "ghostchip/spec.py",
                     ROOT / "schema/devicespec-v1.1.schema.json"):
            text = path.read_text().lower()
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} leaked into {path.name}")


class InputContractTests(unittest.TestCase):
    def test_scenario_and_fault_plan_fail_closed(self):
        scenario = json.loads((FIXTURE / "cases/init_ok.json").read_text())
        broken = copy.deepcopy(scenario)
        broken["assertions"] = []
        with self.assertRaises(ValidationError):
            validate_scenario(broken)
        broken = copy.deepcopy(scenario)
        broken["assertions"][0]["observation"] = "not.required"
        with self.assertRaisesRegex(ValueError, "declared"):
            validate_scenario(broken)
        fault = json.loads((FIXTURE / "fault-chip-id.json").read_text())
        fault["faults"].append(copy.deepcopy(fault["faults"][0]))
        fault["faults"][1]["id"] = "second"
        with self.assertRaisesRegex(ValueError, "Duplicate FaultPlan selector"):
            validate_fault_plan(fault)


class Stage4ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.golden = json.loads((FIXTURE / "extraction-golden.json").read_text())
        self.request = json.loads((FIXTURE / "extraction-request.json").read_text())

    def test_golden_reproduces_reviewed_candidate(self):
        document = document_from_page_map(self.golden["page_count"], self.golden["pages"],
                                          sha256=self.golden["source_sha256"],
                                          page_hashes=self.golden.get("page_text_sha256"))
        result = extract_candidate(document, self.request)
        self.assertEqual(canonical_sha256(result["spec"]),
                         "251d44cd1a12b75a9b7b85ba6e74a772f22dbaa6bc50294a7c6ecb6dde6ba189")
        self.assertEqual(result["report"]["unresolved"], [])

    def test_optional_full_pdf_reproduces_candidate(self):
        pdf = ROOT / "fixtures/bme280/datasheet.pdf"
        if not pdf.exists():
            self.skipTest("Pinned Bosch PDF is optional in a clean source copy")
        result = extract_candidate(ingest_pdf(pdf, expected_sha256=self.golden["source_sha256"]),
                                   self.request)
        self.assertEqual(canonical_sha256(result["spec"]),
                         "251d44cd1a12b75a9b7b85ba6e74a772f22dbaa6bc50294a7c6ecb6dde6ba189")


class UpstreamIntegrityTests(unittest.TestCase):
    def test_exact_upstream_hashes(self):
        metadata, hashes = verify_upstream()
        self.assertEqual(metadata["modifications"], [])
        self.assertEqual(hashes["bme280.c"], "7de1e7d3082b85e90db1daa34573ba77553a7caf44e06e216de5216b7ed4fa12")

    def test_changed_upstream_header_rejects_before_compilation(self):
        with tempfile.TemporaryDirectory() as temp:
            copy_root = Path(temp) / "upstream"
            copy_root.mkdir()
            for path in UPSTREAM.iterdir():
                if path.is_file():
                    (copy_root / path.name).write_bytes(path.read_bytes())
            with (copy_root / "bme280.h").open("ab") as stream:
                stream.write(b"changed")
            with patch("ghostchip.real_driver.UPSTREAM", copy_root):
                with self.assertRaisesRegex(ValueError, "before compilation"):
                    verify_upstream()


class RealDriverTests(unittest.TestCase):
    def run_named(self, name, fault="fault-none.json", **kwargs):
        return run_case(FIXTURE / "cases" / f"{name}.json", FIXTURE / fault, **kwargs)

    def test_initialization_and_calibration_use_real_callbacks(self):
        result = self.run_named("init_ok")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["observations"]["api.init"]["value"], 0)
        self.assertEqual([item["operation"] for item in result["callbacks"]],
                         ["read", "write", "delay", "read", "read", "read"])
        self.assertIn("third_party/bosch_bme280/bme280.h", result["build"]["dependency_headers"])

    def test_wrong_id_takes_actual_upstream_branch(self):
        result = self.run_named("wrong_chip_id")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["observations"]["api.init"]["value"], -4)
        self.assertEqual(len(result["callbacks"]), 1)

    def test_bus_failures_are_not_coverage_errors(self):
        chip = self.run_named("chip_id_bus_error", "fault-chip-id.json")
        calibration = self.run_named("calibration_bus_error", "fault-calibration.json")
        self.assertEqual((chip["status"], calibration["status"]), ("PASS", "PASS"))
        self.assertEqual((chip["observations"]["api.init"]["value"],
                          calibration["observations"]["api.init"]["value"]), (-2, -2))
        self.assertNotIn("OUT_OF_MODEL", json.dumps([chip, calibration]))
        self.assertFalse(any(item.get("register_address") == 0x88
                             for item in calibration["transfers"]))

    def test_profile_rejects_unmodeled_address_and_mode(self):
        reviewed = load_review_bundle_for_test()
        spec = reviewed["reviewed_spec"]
        instance = json.loads((FIXTURE / "instance.json").read_text())
        model = Peripheral(spec, instance)
        with self.assertRaisesRegex(OutOfModel, "unmodeled"):
            model.read(0x77, 0xD0, 1)
        with self.assertRaisesRegex(OutOfModel, "Measurement modes"):
            model.write(0x76, 0xF4, [1])

    def test_public_humidity_api_and_negative_control(self):
        passed = self.run_named("humidity_x4")
        reviewed = load_review_bundle_for_test()
        changed = copy.deepcopy(reviewed["reviewed_spec"])
        changed["rules"] = [rule for rule in changed["rules"] if rule["id"] != "humidity_latch"]
        failed = self.run_named("humidity_x4_no_latch", experimental_spec=changed,
                                model_origin="unreviewed_negative_control_no_latch")
        self.assertEqual((passed["status"], failed["status"]), ("PASS", "FAIL"))
        self.assertEqual(passed["observations"]["api.configure"]["value"], 0)
        self.assertEqual(failed["observations"]["api.configure"]["value"], 0)
        self.assertEqual(failed["violations"][0]["assertion_id"], "effective_humidity")

    def test_public_reset_clears_configuration_but_preserves_nvm(self):
        result = self.run_named("reset_after_configuration")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["observations"]["api.reset"]["value"], 0)
        self.assertEqual(result["final_registers"]["calib_88"], 1)
        self.assertEqual(result["final_state"]["effective_osrs_h"], 0)

    def test_missing_observation_is_error(self):
        scenario = json.loads((FIXTURE / "cases/init_ok.json").read_text())
        scenario["required_observations"].append("api.missing")
        result = run_case(scenario, FIXTURE / "fault-none.json")
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Missing required observations", result["error"])


def load_review_bundle_for_test():
    from ghostchip.review import load_review_bundle
    from ghostchip.real_driver import DEFAULT_BUNDLE
    return load_review_bundle(DEFAULT_BUNDLE)


if __name__ == "__main__":
    unittest.main()

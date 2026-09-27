import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import ValidationError

from ghostchip.proof import FIXTURE, bounded_process, run_fixture
from ghostchip.runtime import OutOfModel, Peripheral
from ghostchip.spec import ROOT, load, validate


class DeviceSpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(FIXTURE / "devicespec.json")

    def test_rejects_invalid_specs(self):
        mutations = {
            "unknown version": lambda s: s.update(schema_version="2.0.0"),
            "arbitrary code": lambda s: s["rules"][0].update(python="exec('bad')"),
            "unknown event": lambda s: s["rules"][0]["on"].update(event="after_delay"),
            "duplicate address": lambda s: s["registers"][1].update(address=208),
            "duplicate rule": lambda s: s["rules"].append(copy.deepcopy(s["rules"][0])),
            "overlap": lambda s: s["registers"][2]["fields"][1].update(lsb=0),
            "unclassified bits": lambda s: s["registers"][1].update(reserved_mask=0),
            "reserved overlap": lambda s: s["registers"][1].update(reserved_mask=255),
            "reset overflow": lambda s: s["state"][0].update(reset=8),
            "register overflow": lambda s: s["registers"][0].update(reset=256),
            "field overflow": lambda s: s["registers"][0]["fields"][0].update(lsb=1),
            "float bit offset": lambda s: s["registers"][0]["fields"][0].update(lsb=0.0),
            "dangling trigger": lambda s: s["rules"][0]["on"].update(register="missing"),
            "dangling field": lambda s: s["rules"][0]["effects"][0]["value"].update(field="missing"),
            "dangling state": lambda s: s["rules"][0]["effects"][0]["target"].update(id="missing"),
            "effect overflow": lambda s: s["rules"][0]["effects"][0].update(value=8),
            "wide reference": lambda s: s["rules"][0]["effects"][0].update(value={"kind":"field","register":"id","field":"chip_id"}),
            "duplicate effect": lambda s: s["rules"][0]["effects"].append(copy.deepcopy(s["rules"][0]["effects"][0])),
            "missing provenance": lambda s: s["rules"][0].update(evidence=[]),
            "dangling evidence": lambda s: s["rules"][0].update(evidence=["missing"]),
            "dangling source": lambda s: s["evidence"][0].update(source_id="missing"),
            "page overflow": lambda s: s["evidence"][0].update(pdf_page=61),
            "scope overflow": lambda s: s["scope"]["write_constraints"][0].update(equals=4),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                spec = copy.deepcopy(self.spec)
                mutate(spec)
                with self.assertRaises((ValueError, ValidationError)):
                    validate(spec)

    def test_review_gate(self):
        self.spec["evidence"][1]["review"] = "pending"
        validate(self.spec)  # Valid extraction artifact, not an executable artifact.
        with self.assertRaises(OutOfModel):
            Peripheral(self.spec)

    def test_optional_local_source_matches_hash(self):
        path = FIXTURE / "datasheet.pdf"
        if not path.exists():
            self.skipTest("Source PDF not cached; download to verify provenance bytes")
        self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.spec["sources"][0]["sha256"])


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(FIXTURE / "devicespec.json")
        self.model = Peripheral(self.spec)

    def write(self, reg, value):
        return self.model.transact("write", 118, reg, value)

    def test_pending_is_not_effective_and_read_does_not_latch(self):
        self.write(242, 3)
        self.assertEqual(self.model.transact("read", 118, 242), 3)
        self.assertEqual(self.model.state["effective_osrs_h"], 0)
        self.assertTrue(all(e["status"] == "OK" for e in self.model.trace))

    def test_same_value_trigger_latches_latest_pending_value(self):
        self.write(244, 0)
        self.write(242, 2)
        self.write(242, 3)
        self.write(244, 0)  # A write matters even if ctrl_meas does not change.
        self.assertEqual(self.model.state["effective_osrs_h"], 3)
        self.write(242, 4)
        self.assertEqual(self.model.state["effective_osrs_h"], 3)
        self.write(244, 0)
        self.assertEqual(self.model.state["effective_osrs_h"], 4)

    def test_model_is_fresh_each_run(self):
        self.write(242, 3)
        self.write(244, 0)
        fresh = Peripheral(self.spec)
        self.assertEqual(fresh.state["effective_osrs_h"], 0)
        self.assertEqual(fresh.trace, [])

    def test_unsupported_accesses_never_silently_succeed(self):
        cases = [("write",118,242,128),("write",118,244,1),
                 ("write",118,208,0),("read",118,255,None),
                 ("read",119,208,None),("write",118,242,256)]
        for op, addr, reg, value in cases:
            with self.subTest(case=(op,addr,reg,value)):
                with self.assertRaises(OutOfModel):
                    self.model.transact(op,addr,reg,value)
                self.assertEqual(self.model.trace[-1]["status"], "OUT_OF_MODEL")
                self.assertEqual(self.model.trace[-1]["before"],self.model.trace[-1]["after"])

    def test_read_side_effect_and_guard_use_pre_effect_read_value(self):
        self.spec["rules"] = [{"id":"synthetic_read_clear", "on":{"event":"after_read","register":"ctrl_hum"},
            "when":{"ref":{"kind":"field","register":"ctrl_hum","field":"osrs_h"},"equals":3},
            "effects":[{"target":{"kind":"field","register":"ctrl_hum","field":"osrs_h"},"value":0}],
            "evidence":["humidity_latch"]}]
        # Synthetic language test only; this is NOT a claimed BME280 rule.
        model = Peripheral(self.spec)
        model.transact("write",118,242,2)
        self.assertEqual(model.transact("read",118,242),2)
        self.assertEqual(model.registers["ctrl_hum"],2)
        model.transact("write",118,242,3)
        self.assertEqual(model.transact("read",118,242),3)
        self.assertEqual(model.registers["ctrl_hum"],0)

    def test_runtime_does_not_depend_on_device_names_or_addresses(self):
        spec = copy.deepcopy(self.spec)
        spec["device"]["name"] = "Synthetic renamed fixture"
        spec["device"]["address"] = 42
        spec["registers"][1]["address"] = 16
        spec["registers"][2]["address"] = 17
        model = Peripheral(spec)
        model.transact("write",42,16,5)
        model.transact("write",42,17,0)
        self.assertEqual(model.state["effective_osrs_h"],5)


class IntegrationTests(unittest.TestCase):
    def test_compiled_fail_pass_same_scenario_and_model(self):
        buggy = run_fixture(ROOT / "examples/bme280_buggy.c")
        fixed = run_fixture(ROOT / "examples/bme280_fixed.c")
        self.assertEqual((buggy["status"],fixed["status"]),("FAIL","PASS"))
        self.assertEqual((buggy["driver_exit"],fixed["driver_exit"]),(0,0))
        self.assertEqual(buggy["spec_sha256"],fixed["spec_sha256"])
        self.assertEqual(buggy["scenario_sha256"],fixed["scenario_sha256"])
        self.assertTrue(buggy["assertions"][0]["passed"])
        self.assertEqual(buggy["violations"][0]["rule_id"],"humidity_latch")
        self.assertEqual(buggy["violations"][0]["evidence"][0]["pdf_page"],27)
        self.assertEqual(len(buggy["trace"]),4)
        self.assertEqual(fixed,run_fixture(ROOT / "examples/bme280_fixed.c"))

    def test_removed_latch_cannot_pass_fixed_driver(self):
        spec = load(FIXTURE / "devicespec.json")
        spec["rules"] = []
        result = run_fixture(ROOT / "examples/bme280_fixed.c",spec=spec)
        self.assertEqual(result["status"],"FAIL")

    def test_noop_and_wrong_humidity_cannot_pass(self):
        original = (ROOT / "examples/bme280_fixed.c").read_text()
        sources = ["int main(void) { return 0; }", original.replace("humidity = 3", "humidity = 2").replace("humidity != 3", "humidity != 2")]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "driver.c"
            for source in sources:
                path.write_text(source)
                self.assertEqual(run_fixture(path)["status"],"FAIL")

    def test_build_and_driver_errors_are_not_behavioral_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "driver.c"
            for source in ["invalid C", "int main(void) { return 1; }"]:
                path.write_text(source)
                self.assertEqual(run_fixture(path)["status"],"ERROR")

    def test_process_timeout_and_output_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,"timeout"):
                bounded_process([sys.executable,"-c","import time; time.sleep(5)"],temp,timeout=0.1)
            with self.assertRaisesRegex(RuntimeError,"output limit"):
                bounded_process([sys.executable,"-c","print('x'*4096)"],temp,limit=1024)


if __name__ == "__main__":
    unittest.main()

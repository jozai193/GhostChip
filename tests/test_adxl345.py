import copy
import json
from pathlib import Path
import unittest

from ghostchip.extraction import ReviewError, accept_review, canonical_sha256, extract_candidate
from ghostchip.pdf_ingest import document_from_page_map, ingest_pdf
from ghostchip.proof import run_fixture
from ghostchip.runtime import OutOfModel, Peripheral
from ghostchip.spec import ROOT, validate


FIXTURE = ROOT / "fixtures/adxl345"


class ADXL345Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads((FIXTURE / "extraction-golden.json").read_text())
        cls.request = json.loads((FIXTURE / "extraction-request.json").read_text())
        cls.review = json.loads((FIXTURE / "extraction-review.json").read_text())
        cls.scenario = json.loads((FIXTURE / "scenario.json").read_text())

    def document(self, pages=None):
        return document_from_page_map(
            self.golden["page_count"], pages or self.golden["pages"],
            sha256=self.golden["source_sha256"],
        )

    def candidate(self, pages=None):
        return extract_candidate(self.document(pages), self.request)

    def accepted(self):
        return accept_review(self.candidate()["spec"], self.review)


class ADXL345ExtractionTests(ADXL345Fixture):
    def test_golden_extracts_two_rules_with_disjoint_behavior_evidence(self):
        result = self.candidate()
        spec = result["spec"]
        self.assertEqual(canonical_sha256(spec), self.golden["expected_candidate_sha256"])
        self.assertEqual(result["report"]["unresolved"], [])
        self.assertEqual([rule["id"] for rule in spec["rules"]],
                         ["int_source_nondata_clear", "fifo_bypass_clear"])
        evidence = {item["id"]: item for item in spec["evidence"]}
        int_pages = {evidence[item]["pdf_page"] for item in spec["rules"][0]["evidence"]}
        fifo_pages = {evidence[item]["pdf_page"] for item in spec["rules"][1]["evidence"]}
        self.assertEqual(int_pages, {19, 27})
        self.assertEqual(fifo_pages, {21, 28})
        self.assertTrue(set(spec["rules"][0]["evidence"]).isdisjoint(spec["rules"][1]["evidence"]))
        anchors = {item["evidence_id"]: item for item in result["anchors"]}
        for rule in spec["rules"]:
            for evidence_id in rule["evidence"]:
                self.assertIn("quote", anchors[evidence_id])
                self.assertEqual(anchors[evidence_id]["pdf_page"], evidence[evidence_id]["pdf_page"])

    def test_missing_interrupt_prose_emits_no_interrupt_rule(self):
        pages = copy.deepcopy(self.golden["pages"])
        pages["27"] = pages["27"].replace(
            "Other bits, and the corresponding interrupts, are cleared by reading the INT_SOURCE register.",
            "The remaining clearing behavior is not stated in this reduced source.",
        )
        result = self.candidate(pages)
        self.assertEqual([rule["id"] for rule in result["spec"]["rules"]], ["fifo_bypass_clear"])
        self.assertEqual(result["report"]["unresolved"][0]["kind"], "interrupt_clear")
        self.assertNotIn("selective INT_SOURCE clear exception set",
                         result["report"]["automatically_extracted"])

    def test_missing_fifo_clear_prose_emits_no_fifo_rule_or_state(self):
        pages = copy.deepcopy(self.golden["pages"])
        pages["21"] = pages["21"].replace(
            "placing the device into bypass mode clears FIFO",
            "the effect of entering bypass is not stated",
        )
        result = self.candidate(pages)
        self.assertEqual([rule["id"] for rule in result["spec"]["rules"]],
                         ["int_source_nondata_clear"])
        self.assertEqual(result["spec"]["state"], [])
        self.assertEqual(result["report"]["unresolved"][0]["kind"], "fifo_bypass_clear")
        self.assertNotIn("FIFO bypass encoding and FIFO-clear transition",
                         result["report"]["automatically_extracted"])

    def test_optional_pinned_pdf_reproduces_golden(self):
        pdf = FIXTURE / "datasheet.pdf"
        if not pdf.exists():
            self.skipTest("Pinned vendor PDF is optional in a clean source copy")
        result = extract_candidate(ingest_pdf(pdf, expected_sha256=self.golden["source_sha256"]),
                                   self.request)
        self.assertEqual(result["report"]["candidate_sha256"],
                         self.golden["expected_candidate_sha256"])


class ADXL345ReviewTests(ADXL345Fixture):
    def test_pending_validates_but_cannot_execute(self):
        pending = self.candidate()["spec"]
        validate(pending)
        with self.assertRaises(OutOfModel):
            Peripheral(pending)

    def test_review_is_hash_bound_and_cannot_inject_semantics(self):
        pending = self.candidate()["spec"]
        accepted = accept_review(pending, self.review)
        self.assertTrue(all(item["review"] == "accepted" for item in accepted["evidence"]))
        changed = copy.deepcopy(pending)
        changed["rules"][0]["effects"].pop()
        with self.assertRaisesRegex(ReviewError, "candidate hash"):
            accept_review(changed, self.review)
        injected = copy.deepcopy(self.review)
        injected["state"] = []
        with self.assertRaisesRegex(ReviewError, "not semantic overrides"):
            accept_review(pending, injected)


class ADXL345RuntimeTests(ADXL345Fixture):
    def test_int_source_read_returns_pre_clear_value_and_preserves_data_bits(self):
        model = Peripheral(self.accepted())
        for field in model.defs["int_source"]["fields"]:
            model.stimulate({"kind": "field", "register": "int_source", "field": field["id"]},
                            1, "Exercise each extracted interrupt-source field")
        self.assertEqual(model.transact("read", 0x53, 0x30), 0xFF)
        self.assertEqual(model.registers["int_source"], 0x83)
        self.assertEqual(model.transact("read", 0x53, 0x30), 0x83)
        self.assertEqual(model.trace[0]["rules_triggered"], ["int_source_nondata_clear"])

    def test_fifo_only_clears_when_fifo_mode_becomes_bypass(self):
        model = Peripheral(self.accepted())
        model.stimulate({"kind": "state", "id": "fifo_entries"}, 5,
                        "Represent FIFO samples produced before driver execution")
        model.transact("write", 0x53, 0x38, 0x40)
        self.assertEqual(model.state["fifo_entries"], 5)
        self.assertEqual(model.trace[-1]["rules_triggered"], [])
        model.transact("write", 0x53, 0x38, 0x00)
        self.assertEqual(model.state["fifo_entries"], 0)
        self.assertEqual(model.trace[-1]["rules_triggered"], ["fifo_bypass_clear"])

    def test_stimulus_is_bounded_and_pre_run_only(self):
        model = Peripheral(self.accepted())
        with self.assertRaises(OutOfModel):
            model.stimulate({"kind": "state", "id": "fifo_entries"}, 64, "Overflow")
        model.transact("read", 0x53, 0x30)
        with self.assertRaisesRegex(OutOfModel, "before bus"):
            model.stimulate({"kind": "state", "id": "fifo_entries"}, 1, "Too late")


class ADXL345CompiledProofTests(ADXL345Fixture):
    def test_extracted_reviewed_spec_drives_compiled_fail_pass(self):
        spec = self.accepted()
        buggy = run_fixture(ROOT / "examples/adxl345_buggy.c", spec=spec, scenario=self.scenario)
        fixed = run_fixture(ROOT / "examples/adxl345_fixed.c", spec=spec, scenario=self.scenario)
        self.assertEqual((buggy["status"], fixed["status"]), ("FAIL", "PASS"))
        self.assertEqual((buggy["driver_exit"], fixed["driver_exit"]), (2, 0))
        self.assertEqual([item["passed"] for item in buggy["assertions"]], [False, True])
        self.assertEqual({item["pdf_page"] for item in buggy["violations"][0]["evidence"]},
                         {19, 27})
        self.assertEqual((len(buggy["trace"]), len(fixed["trace"])), (3, 2))
        self.assertEqual(buggy["model_origin"], "automatic_extraction_reviewed")

    def test_interrupt_rule_is_necessary_to_expose_bug(self):
        spec = self.accepted()
        spec["rules"] = [rule for rule in spec["rules"]
                         if rule["id"] != "int_source_nondata_clear"]
        result = run_fixture(ROOT / "examples/adxl345_buggy.c", spec=spec, scenario=self.scenario)
        self.assertEqual(result["status"], "PASS")

    def test_fifo_rule_is_necessary_for_fifo_assertion(self):
        spec = self.accepted()
        spec["rules"] = [rule for rule in spec["rules"] if rule["id"] != "fifo_bypass_clear"]
        result = run_fixture(ROOT / "examples/adxl345_fixed.c", spec=spec, scenario=self.scenario)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["violations"][0]["assertion_id"], "bypass_clears_fifo")

    def test_generic_execution_core_contains_no_adxl_identifiers(self):
        forbidden = ("adxl345", "int_source", "fifo_ctl", "single_tap")
        for path in (ROOT / "ghostchip/runtime.py", ROOT / "ghostchip/spec.py",
                     ROOT / "ghostchip/proof.py", ROOT / "schema/devicespec-v1.schema.json"):
            text = path.read_text().lower()
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} leaked into {path.name}")


if __name__ == "__main__":
    unittest.main()

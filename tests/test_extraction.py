import copy
import json
from pathlib import Path
import tempfile
import unittest

from ghostchip.extraction import (
    ExtractionError,
    ReviewError,
    accept_review,
    canonical_sha256,
    extract_candidate,
)
from ghostchip.pdf_ingest import IngestionError, document_from_page_map, ingest_pdf
from ghostchip.proof import FIXTURE, run_fixture
from ghostchip.runtime import OutOfModel, Peripheral
from ghostchip.spec import ROOT, validate


class ExtractionFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads((FIXTURE / "extraction-golden.json").read_text())
        cls.request = json.loads((FIXTURE / "extraction-request.json").read_text())
        cls.review = json.loads((FIXTURE / "extraction-review.json").read_text())

    def document(self, pages=None):
        return document_from_page_map(
            self.golden["page_count"], pages or self.golden["pages"],
            sha256=self.golden["source_sha256"],
        )

    def candidate(self, pages=None):
        return extract_candidate(self.document(pages), self.request)


class CandidateExtractionTests(ExtractionFixture):
    def test_golden_candidate_and_rule_provenance(self):
        result = self.candidate()
        spec = result["spec"]
        self.assertEqual(canonical_sha256(spec), self.golden["expected_candidate_sha256"])
        self.assertEqual(result["report"]["unresolved"], [])
        self.assertEqual(spec["rules"], [{
            "id": "humidity_latch",
            "on": {"event": "after_write", "register": "ctrl_meas"},
            "effects": [{
                "target": {"kind": "state", "id": "effective_osrs_h"},
                "value": {"kind": "field", "register": "ctrl_hum", "field": "osrs_h"},
            }],
            "evidence": ["humidity_latch", "humidity_latch_crosscheck"],
        }])
        evidence = {item["id"]: item for item in spec["evidence"]}
        self.assertEqual((evidence["humidity_latch"]["pdf_page"],
                          evidence["humidity_latch_crosscheck"]["pdf_page"]), (27, 28))
        anchors = {item["evidence_id"]: item for item in result["anchors"]}
        active_evidence = {evidence_id for item in [*spec["registers"], *spec["state"], *spec["rules"]]
                           for evidence_id in item["evidence"]}
        self.assertLessEqual(active_evidence, set(anchors))
        self.assertEqual(evidence["register_ctrl_hum_fields"]["pdf_page"], 28)
        self.assertEqual(evidence["register_ctrl_meas_fields"]["pdf_page"], 29)
        for evidence_id in spec["rules"][0]["evidence"]:
            self.assertIn(evidence_id, anchors)
            self.assertIn("quote", anchors[evidence_id])
            self.assertEqual(anchors[evidence_id]["pdf_page"], evidence[evidence_id]["pdf_page"])

    def test_layout_whitespace_changes_do_not_change_semantics(self):
        pages = copy.deepcopy(self.golden["pages"])
        for number in ("27", "28", "29", "32"):
            pages[number] = pages[number].replace(" ", "   ").replace('"', "\u201c")
        changed = self.candidate(pages)["spec"]
        self.assertEqual(canonical_sha256(changed), self.golden["expected_candidate_sha256"])

    def test_missing_behavior_is_reported_not_invented(self):
        pages = copy.deepcopy(self.golden["pages"])
        pages["27"] = pages["27"].replace(
            'Changes to this register only become effective after a write operation to "ctrl_meas".',
            "The effect timing is not stated in this reduced source.",
        )
        result = self.candidate(pages)
        self.assertEqual(result["spec"]["rules"], [])
        self.assertEqual(result["spec"]["state"], [])
        self.assertEqual(result["report"]["unresolved"][0]["status"], "not_extracted")

    def test_board_address_must_be_a_listed_option(self):
        request = copy.deepcopy(self.request)
        request["device_address"] = 0x75
        with self.assertRaisesRegex(ExtractionError, "not a datasheet-listed"):
            extract_candidate(self.document(), request)

    def test_optional_pinned_pdf_reproduces_golden_candidate(self):
        pdf = FIXTURE / "datasheet.pdf"
        if not pdf.exists():
            self.skipTest("Pinned vendor PDF is optional in a clean source copy")
        document = ingest_pdf(pdf, expected_sha256=self.golden["source_sha256"])
        result = extract_candidate(document, self.request)
        self.assertEqual(result["report"]["candidate_sha256"], self.golden["expected_candidate_sha256"])
        self.assertEqual(document.page_count, 60)

    def test_non_pdf_and_hash_mismatch_fail_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "not.pdf"
            path.write_bytes(b"not a PDF")
            with self.assertRaisesRegex(IngestionError, "signature"):
                ingest_pdf(path)
        wrong = copy.deepcopy(self.request)
        wrong["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ExtractionError, "hash"):
            extract_candidate(self.document(), wrong)


class ReviewBoundaryTests(ExtractionFixture):
    def setUp(self):
        self.pending = self.candidate()["spec"]

    def test_pending_candidate_validates_but_cannot_execute(self):
        validate(self.pending)
        with self.assertRaises(OutOfModel):
            Peripheral(self.pending)

    def test_hash_bound_review_only_changes_status(self):
        accepted = accept_review(self.pending, self.review)
        pending_without_status = copy.deepcopy(self.pending)
        accepted_without_status = copy.deepcopy(accepted)
        for item in pending_without_status["evidence"]:
            item.pop("review")
        for item in accepted_without_status["evidence"]:
            item.pop("review")
        self.assertEqual(accepted_without_status, pending_without_status)
        self.assertTrue(all(item["review"] == "accepted" for item in accepted["evidence"]))
        Peripheral(accepted)

    def test_semantic_change_invalidates_review(self):
        changed = copy.deepcopy(self.pending)
        changed["rules"][0]["on"]["register"] = "ctrl_hum"
        with self.assertRaisesRegex(ReviewError, "candidate hash"):
            accept_review(changed, self.review)

    def test_review_cannot_contain_semantic_overrides(self):
        review = copy.deepcopy(self.review)
        review["rules"] = []
        with self.assertRaisesRegex(ReviewError, "not semantic overrides"):
            accept_review(self.pending, review)


class ExtractedProofTests(ExtractionFixture):
    def test_extracted_reviewed_spec_drives_compiled_fail_pass(self):
        accepted = accept_review(self.candidate()["spec"], self.review)
        buggy = run_fixture(ROOT / "examples/bme280_buggy.c", spec=accepted)
        fixed = run_fixture(ROOT / "examples/bme280_fixed.c", spec=accepted)
        self.assertEqual((buggy["status"], fixed["status"]), ("FAIL", "PASS"))
        self.assertEqual((buggy["model_origin"], fixed["model_origin"]),
                         ("automatic_extraction_reviewed", "automatic_extraction_reviewed"))
        self.assertEqual(buggy["spec_sha256"], fixed["spec_sha256"])
        self.assertEqual(buggy["violations"][0]["evidence"][0]["origin"], "model_extraction")
        self.assertEqual({item["pdf_page"] for item in buggy["violations"][0]["evidence"]}, {27, 28})

    def test_extracted_rule_is_necessary_for_pass(self):
        accepted = accept_review(self.candidate()["spec"], self.review)
        accepted["rules"] = []
        result = run_fixture(ROOT / "examples/bme280_fixed.c", spec=accepted)
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()

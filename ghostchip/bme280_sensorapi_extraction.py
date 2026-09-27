"""Evidence-gated BME280 SensorAPI initialization-slice extractor.

This is deliberately a source-layout adapter for the pinned Bosch document,
not a general datasheet interpreter.  Every semantic category remains pending
until the review bundle accepts its source evidence and declared abstraction.
"""
from .extraction import ExtractionError, canonical_sha256
from .spec import validate


def _page(document, number, phrases):
    page = document.page(number)
    lowered = page.text.lower()
    if not all(phrase.lower() in lowered for phrase in phrases):
        raise ExtractionError(f"Required BME280 SensorAPI evidence is missing on PDF page {number}")
    return page


def _evidence(request, evidence_id, page, section, summary, origin="model_extraction"):
    return {
        "id": evidence_id, "source_id": request["source_id"], "pdf_page": page.pdf_page,
        "printed_page": str(page.pdf_page), "section": section, "summary": summary,
        "origin": origin, "review": "pending", "confidence": None if origin != "model_extraction" else 0.95,
    }


def extract_candidate(document, request):
    if document.sha256 != request["source_sha256"].lower():
        raise ExtractionError("Document hash does not match extraction request")
    p8 = _page(document, 8, ["Start-up time"])
    p24 = _page(document, 24, ["0x88", "0xA1", "0xE1", "0xE7", "calib"])
    p25 = _page(document, 25, ["0xE7", "dig_H6"])
    p27 = _page(document, 27, ["reset", "0xB6", "ctrl_hum", "ctrl_meas", "0xE0"])
    p28 = _page(document, 28, ["status", "im_update", "ctrl_meas", "effective"])
    p32 = _page(document, 32, ["multiple byte read", "auto-incremented"])
    p33 = _page(document, 33, ["multiple byte write", "not auto-incremented"])
    evidence = [
        _evidence(request, "startup_bound", p8, "1, Table 1",
                  "The specified startup time bound is 2 ms."),
        _evidence(request, "calibration_bank_layout", p24, "4.2.2, Table 16",
                  "Device-individual calibration bytes occupy 0x88..0xA1 and 0xE1..0xE7."),
        _evidence(request, "humidity_calibration_tail", p25, "4.2.2, Table 16",
                  "The humidity calibration layout continues through 0xE7."),
        _evidence(request, "register_map_reset", p27, "5.3 Table 18; 5.4.1-5.4.3",
                  "The map identifies chip ID, reset, status and control registers; reset command 0xB6 performs complete reset."),
        _evidence(request, "status_and_control", p28, "5.4.4-5.4.5",
                  "Status exposes im_update and ctrl_meas completes the humidity-control latch."),
        _evidence(request, "incrementing_reads", p32, "6.3",
                  "Multiple-byte reads use an auto-incremented register address."),
        _evidence(request, "paired_address_writes", p33, "6.3",
                  "Multiple-byte writes are address/data pairs rather than ordinary incrementing writes."),
        _evidence(request, "soft_reset_settle_abstraction", p8, "Reviewed modeling basis",
                  "A 2000 us observation boundary conservatively combines the source startup maximum with the upstream wait.",
                  "reviewed_abstraction"),
    ]
    evidence_ids = {item["id"]: item for item in evidence}
    anchors = [{"evidence_id": item["id"], "pdf_page": item["pdf_page"],
                "page_text_sha256": document.page(item["pdf_page"]).sha256}
               for item in evidence]

    def register(name, address, access, reset, fields, reserved_mask, refs):
        return {"id": name, "address": address, "width": 8, "reset": reset,
                "access": access, "reserved_mask": reserved_mask, "fields": fields,
                "evidence": refs}

    full = lambda field: [{"id": field, "lsb": 0, "width": 8}]
    registers = [
        register("chip_id", 0xD0, "ro", 0x60, full("value"), 0, ["register_map_reset"]),
        register("reset", 0xE0, "rw", 0, full("command"), 0, ["register_map_reset"]),
        register("ctrl_hum", 0xF2, "rw", 0, [{"id": "osrs_h", "lsb": 0, "width": 3}],
                 0xF8, ["register_map_reset", "status_and_control"]),
        register("status", 0xF3, "ro", 0,
                 [{"id": "im_update", "lsb": 0, "width": 1},
                  {"id": "measuring", "lsb": 3, "width": 1}],
                 0xF6, ["register_map_reset", "status_and_control"]),
        register("ctrl_meas", 0xF4, "rw", 0,
                 [{"id": "mode", "lsb": 0, "width": 2},
                  {"id": "osrs_p", "lsb": 2, "width": 3},
                  {"id": "osrs_t", "lsb": 5, "width": 3}],
                 0, ["register_map_reset", "status_and_control"]),
    ]
    parameters = []
    for address in [*range(0x88, 0xA2), *range(0xE1, 0xE8)]:
        parameter = f"calib_{address:02x}"
        refs = ["calibration_bank_layout"] + (["humidity_calibration_tail"] if address >= 0xE1 else [])
        registers.append(register(parameter, address, "ro", {"parameter": parameter},
                                  full("value"), 0, refs))
        parameters.append({"id": parameter, "width": 8, "address": address, "evidence": refs})
    reset_effects = [
        {"target": {"kind": "field", "register": "ctrl_hum", "field": "osrs_h"}, "value": 0},
        {"target": {"kind": "field", "register": "ctrl_meas", "field": "mode"}, "value": 0},
        {"target": {"kind": "field", "register": "ctrl_meas", "field": "osrs_p"}, "value": 0},
        {"target": {"kind": "field", "register": "ctrl_meas", "field": "osrs_t"}, "value": 0},
        {"target": {"kind": "field", "register": "status", "field": "im_update"}, "value": 0},
        {"target": {"kind": "field", "register": "status", "field": "measuring"}, "value": 0},
        {"target": {"kind": "state", "id": "effective_osrs_h"}, "value": 0},
    ]
    rules = [
        {"id": "soft_reset", "on": {"event": "after_write", "register": "reset"},
         "when": {"ref": {"kind": "field", "register": "reset", "field": "command"}, "equals": 0xB6},
         "effects": reset_effects, "settle_us": 2000,
         "evidence": ["register_map_reset", "startup_bound", "soft_reset_settle_abstraction"]},
        {"id": "reset_reads_zero", "on": {"event": "after_write", "register": "reset"},
         "effects": [{"target": {"kind": "field", "register": "reset", "field": "command"}, "value": 0}],
         "evidence": ["register_map_reset"]},
        {"id": "humidity_latch", "on": {"event": "after_write", "register": "ctrl_meas"},
         "effects": [{"target": {"kind": "state", "id": "effective_osrs_h"},
                      "value": {"kind": "field", "register": "ctrl_hum", "field": "osrs_h"}}],
         "evidence": ["register_map_reset", "status_and_control"]},
    ]
    spec = {
        "schema_version": "1.1.0", "profile": "i2c-reg8-settle-v1",
        "device": {"name": request["device_name"], "vendor": request["vendor"],
                   "bus": "i2c", "address": request["device_address"]},
        "scope": {"description": request["scope_description"], "unsupported": request["unsupported"],
                  "write_constraints": [{"register": "ctrl_meas", "mask": 3, "equals": 0,
                                         "reason": "Measurement modes are outside the Stage 4 slice"}]},
        "sources": [{"id": request["source_id"], "url": request["source_url"],
                     "sha256": document.sha256, "page_count": document.page_count,
                     "revision": request["source_revision"]}],
        "evidence": list(evidence_ids.values()), "registers": registers,
        "state": [{"id": "effective_osrs_h", "width": 3, "reset": 0,
                   "evidence": ["register_map_reset", "status_and_control"]}],
        "rules": rules, "parameters": parameters,
        "transport": {"max_read_length": 32,
                      "incrementing_read_ranges": [{"start": 0x88, "length": 26},
                                                   {"start": 0xE1, "length": 7}]},
    }
    validate(spec)
    return {"spec": spec, "anchors": anchors,
            "report": {"extractor": request["extractor"], "candidate_status": "pending_review",
                       "source_sha256": document.sha256, "candidate_sha256": canonical_sha256(spec),
                       "automatic": ["register map and bounded calibration/read/latch categories"],
                       "manual_inputs": ["register slice", "board address", "settle abstraction",
                                         "calibration instance values", "evidence acceptance"],
                       "unresolved": []}}

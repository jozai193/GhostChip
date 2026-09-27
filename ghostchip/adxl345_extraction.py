"""Deterministic Rev. G table/prose extraction for the ADXL345 proof slice.

This is a source-layout adapter, not executable device behavior. It converts
the vendor's register-map tables and two supported prose patterns into a
pending DeviceSpec consumed by the same validator/reviewer/runtime as BME280.
"""
import re

from .extraction import ExtractionError, canonical_sha256, _slug
from .spec import validate


def _printed_page(page):
    match = re.search(r"Rev\.\s*G\s*\|\s*(\d+)\s+of\s+\d+", page.text, re.I)
    return match.group(1) if match else str(page.pdf_page)


def _page_with(document, pattern):
    regex = re.compile(pattern, re.I | re.S)
    for page in document.pages:
        match = regex.search(page.text)
        if match:
            return page, match
    return None, None


def _register_map_row(document, requested_name):
    pattern = re.compile(
        r"(?m)^0x([0-9A-Fa-f]{2})\s+\d+\s+([A-Za-z][A-Za-z0-9_]*)\s+"
        r"(R/W|R)\s+([01]{8})\s+.+$"
    )
    for page in document.pages:
        for match in pattern.finditer(page.text):
            if _slug(match.group(2)) == requested_name:
                return {
                    "address": int(match.group(1), 16),
                    "source_name": match.group(2),
                    "access": "rw" if match.group(3) == "R/W" else "ro",
                    "reset": int(match.group(4), 2),
                    "page": page,
                    "quote": match.group(0).strip(),
                }
    raise ExtractionError(f"Register-map row for {requested_name!r} was not found")


def _int_source_fields(document):
    page, _ = _page_with(document, r"Register\s+0x30[^\n]*INT_SOURCE\s*\(Read Only\)")
    if not page:
        raise ExtractionError("INT_SOURCE register definition was not found")
    patterns = [
        (r"D7\s+D6\s+D5\s+D4\s+DATA_READY\s+SINGLE_TAP\s+DOUBLE_TAP\s+Activity",
         [7, 6, 5, 4]),
        (r"D3\s+D2\s+D1\s+D0\s+Inactivity\s+FREE_FALL\s+Watermark\s+Overrun",
         [3, 2, 1, 0]),
    ]
    fields = []
    for pattern, bits in patterns:
        match = re.search(pattern, page.text, re.I | re.S)
        if not match:
            raise ExtractionError("INT_SOURCE field table is incomplete")
        names = re.findall(r"[A-Za-z][A-Za-z0-9_]*", match.group(0).split("\n")[-1])
        if len(names) != 4:
            # Page extraction may keep the bit header and labels on one logical line.
            names = re.findall(
                r"DATA_READY|SINGLE_TAP|DOUBLE_TAP|Activity|Inactivity|FREE_FALL|Watermark|Overrun",
                match.group(0), re.I,
            )[-4:]
        if len(names) != 4:
            raise ExtractionError("INT_SOURCE bit labels could not be mapped")
        fields.extend({"id": _slug(name), "lsb": bit, "width": 1}
                      for name, bit in zip(names, bits))
    return fields, page


def _fifo_ctl_fields(document):
    page, table = _page_with(
        document,
        r"Register\s+0x38[^\n]*FIFO_CTL\s*\(Read/Write\).*?"
        r"D7\s+D6\s+D5\s+D4\s+D3\s+D2\s+D1\s+D0\s+FIFO_MODE\s+Trigger\s+Samples",
    )
    if not page:
        raise ExtractionError("FIFO_CTL field table was not found")
    mode_page, mode = _page_with(document, r"FIFO_MODE\s+bits\s*\(Bits\[D7:D6\]\)")
    if not mode:
        raise ExtractionError("FIFO_MODE bit range was not found")
    labels = re.findall(r"FIFO_MODE|Trigger|Samples", table.group(0), re.I)[-3:]
    if [_slug(label) for label in labels] != ["fifo_mode", "trigger", "samples"]:
        raise ExtractionError("FIFO_CTL field ordering is ambiguous")
    # FIFO_MODE's explicit D7:D6 range plus the singular Trigger Bit heading
    # determines D5; the remaining lower bits belong to Samples.
    return [
        {"id": _slug(labels[0]), "lsb": 6, "width": 2},
        {"id": _slug(labels[1]), "lsb": 5, "width": 1},
        {"id": _slug(labels[2]), "lsb": 0, "width": 5},
    ], page, mode_page


def _address_options(document):
    page, _ = _page_with(document, r"7-bit\s+I2C\s+address\s+for\s+the\s+device\s+is\s+0x([0-9A-Fa-f]{2})")
    if not page:
        raise ExtractionError("ADXL-style I2C address paragraph was not found")
    primary = re.search(r"7-bit\s+I2C\s+address\s+for\s+the\s+device\s+is\s+0x([0-9A-Fa-f]{2})",
                        page.text, re.I).group(1)
    alternate = re.search(r"alternate\s+I2C\s+address\s+of\s+0x([0-9A-Fa-f]{2})",
                          page.text, re.I)
    if not alternate:
        raise ExtractionError("Alternate I2C address was not found")
    return {int(primary, 16), int(alternate.group(1), 16)}, page


def _evidence(request, evidence_id, page, section, summary, confidence):
    return {
        "id": evidence_id,
        "source_id": request["source_id"],
        "pdf_page": page.pdf_page,
        "printed_page": _printed_page(page),
        "section": section,
        "summary": summary,
        "origin": "model_extraction",
        "review": "pending",
        "confidence": confidence,
    }


def extract_candidate(document, request):
    if document.sha256 != request["source_sha256"].lower():
        raise ExtractionError("Document hash does not match extraction request")
    selected = [_slug(name) for name in request["registers"]]
    if set(selected) != {"int_source", "fifo_ctl"}:
        raise ExtractionError("This extraction adapter supports the reviewed INT_SOURCE/FIFO_CTL slice")
    options, address_page = _address_options(document)
    if request["device_address"] not in options:
        raise ExtractionError("Selected board address is not a datasheet-listed I2C address")

    int_fields, int_field_page = _int_source_fields(document)
    fifo_fields, fifo_field_page, fifo_range_page = _fifo_ctl_fields(document)
    fields_by_register = {"int_source": (int_fields, int_field_page),
                          "fifo_ctl": (fifo_fields, fifo_field_page)}
    evidence = []
    anchors = []
    registers = []
    definitions = {}
    for name in selected:
        row = _register_map_row(document, name)
        fields, field_page = fields_by_register[name]
        heading_page = field_page
        base = "register_" + name
        address_id, reset_id, fields_id = base, base + "_reset", base + "_fields"
        evidence.extend([
            _evidence(request, address_id, heading_page, "REGISTER MAP / register definition",
                      f"The register definition identifies {name} at address 0x{row['address']:02X}.", 0.95),
            _evidence(request, reset_id, row["page"], "REGISTER MAP, Table 19",
                      f"Table 19 gives {name} reset value 0x{row['reset']:02X} and {row['access']} access.", 0.98),
            _evidence(request, fields_id, field_page, "REGISTER MAP / field table",
                      f"The field table supplies the extracted {name} bit ranges.", 0.94),
        ])
        anchors.extend([
            {"evidence_id": address_id, "pdf_page": heading_page.pdf_page,
             "page_text_sha256": heading_page.sha256},
            {"evidence_id": reset_id, "pdf_page": row["page"].pdf_page,
             "page_text_sha256": row["page"].sha256, "quote": row["quote"]},
            {"evidence_id": fields_id, "pdf_page": field_page.pdf_page,
             "page_text_sha256": field_page.sha256},
        ])
        register = {
            "id": name, "address": row["address"], "width": 8, "reset": row["reset"],
            "access": row["access"], "reserved_mask": 0, "fields": fields,
            "evidence": [address_id, reset_id, fields_id],
        }
        definitions[name] = register
        registers.append(register)

    unresolved = []
    state = []
    rules = []

    int_page, int_match = _page_with(
        document,
        r"The\s+DATA_READY,\s*watermark,\s*and\s*overrun\s+bits.*?"
        r"are\s+cleared\s+by\s+reading\s+data\s+from\s+the\s+DATAX,\s*DATAY,\s*and\s*DATAZ\s+registers\.\s*"
        r".*?Other\s+bits,\s*and\s+the\s+corresponding\s+interrupts,\s*are\s+cleared\s+by\s+reading\s+the\s+INT_SOURCE\s+register\.",
    )
    int_general_page, int_general = _page_with(
        document,
        r"interrupt\s+functions\s+are\s+latched\s+and\s+cleared.*?reading\s+the\s+INT_SOURCE\s+register",
    )
    if not int_match:
        unresolved.append({"kind": "interrupt_clear", "status": "not_extracted",
                           "detail": "Selective INT_SOURCE clear prose was not found; no read-clear rule was emitted."})
    else:
        exceptions = {"data_ready", "watermark", "overrun"}
        clear_fields = [field for field in definitions["int_source"]["fields"]
                        if field["id"] not in exceptions]
        if len(clear_fields) != 5:
            raise ExtractionError("INT_SOURCE exception set does not match the extracted field table")
        rule_id = _slug(request["rule_ids"]["int_source_read"])
        exact_id = rule_id
        general_id = rule_id + "_overview"
        evidence.extend([
            _evidence(request, exact_id, int_page, "REGISTER MAP / Register 0x30—INT_SOURCE",
                      "Reading INT_SOURCE clears non-data interrupt fields but not DATA_READY, watermark, or overrun.", 0.98),
            _evidence(request, general_id, int_general_page, "INTERRUPTS",
                      "Data-related interrupts clear through data reads; remaining interrupts clear through INT_SOURCE.", 0.96),
        ])
        anchors.extend([
            {"evidence_id": exact_id, "pdf_page": int_page.pdf_page,
             "page_text_sha256": int_page.sha256, "quote": int_match.group(0).strip()},
            {"evidence_id": general_id, "pdf_page": int_general_page.pdf_page,
             "page_text_sha256": int_general_page.sha256, "quote": int_general.group(0).strip()},
        ])
        rules.append({
            "id": rule_id, "on": {"event": "after_read", "register": "int_source"},
            "effects": [{"target": {"kind": "field", "register": "int_source", "field": field["id"]},
                         "value": 0} for field in clear_fields],
            "evidence": [exact_id, general_id],
        })

    fifo_page, fifo_match = _page_with(
        document,
        r"placing\s+the\s+device\s+into\s+bypass\s+mode\s+clears\s+FIFO",
    )
    bypass_page, bypass_match = _page_with(
        document,
        r"In\s+bypass\s+mode,\s*FIFO\s+is\s+not\s+operational\s+and,\s*therefore,\s*re-?\s*mains\s+empty",
    )
    encoding_page, encoding_match = _page_with(
        document,
        r"0\s+0\s+Bypass\s+FIFO\s+is\s+bypassed",
    )
    if not (fifo_match and bypass_match and encoding_match):
        unresolved.append({"kind": "fifo_bypass_clear", "status": "not_extracted",
                           "detail": "Bypass encoding/clear evidence was incomplete; no FIFO clear rule was emitted."})
    else:
        rule_id = _slug(request["rule_ids"]["fifo_bypass"])
        exact_id = rule_id
        mode_id = rule_id + "_mode"
        evidence.extend([
            _evidence(request, exact_id, fifo_page, "FIFO / TRIGGER MODE",
                      "Placing the device into bypass mode clears FIFO.", 0.99),
            _evidence(request, mode_id, encoding_page, "REGISTER MAP / Table 37",
                      "FIFO_MODE value 00 selects bypass, in which FIFO is bypassed.", 0.98),
        ])
        anchors.extend([
            {"evidence_id": exact_id, "pdf_page": fifo_page.pdf_page,
             "page_text_sha256": fifo_page.sha256, "quote": fifo_match.group(0).strip()},
            {"evidence_id": mode_id, "pdf_page": encoding_page.pdf_page,
             "page_text_sha256": encoding_page.sha256, "quote": encoding_match.group(0).strip()},
        ])
        state.append({"id": "fifo_entries", "width": 6, "reset": 0,
                      "evidence": [exact_id, mode_id]})
        rules.append({
            "id": rule_id, "on": {"event": "after_write", "register": "fifo_ctl"},
            "when": {"ref": {"kind": "field", "register": "fifo_ctl", "field": "fifo_mode"},
                     "equals": 0},
            "effects": [{"target": {"kind": "state", "id": "fifo_entries"}, "value": 0}],
            "evidence": [exact_id, mode_id],
        })

    address_id = "i2c_address_options"
    evidence.append(_evidence(request, address_id, address_page, "SERIAL COMMUNICATIONS / I2C",
                              "The ALT ADDRESS pin selects 7-bit address 0x1D or 0x53.", 0.99))
    anchors.append({"evidence_id": address_id, "pdf_page": address_page.pdf_page,
                    "page_text_sha256": address_page.sha256})
    spec = {
        "schema_version": "1.0.0", "profile": "i2c-reg8-events-v1",
        "device": {"name": request["device_name"], "vendor": request["vendor"],
                   "bus": "i2c", "address": request["device_address"]},
        "scope": {"description": request["scope_description"],
                  "unsupported": request["unsupported"], "write_constraints": []},
        "sources": [{"id": request["source_id"], "url": request["source_url"],
                     "sha256": document.sha256, "page_count": document.page_count,
                     "revision": request["source_revision"]}],
        "evidence": evidence, "registers": registers, "state": state, "rules": rules,
    }
    validate(spec)
    extracted = [
        "PDF bytes and page-indexed text", "INT_SOURCE/FIFO_CTL address, access, reset and fields",
        "I2C address alternatives", "page/section evidence anchors",
    ]
    inferred = []
    if any(rule["id"] == _slug(request["rule_ids"]["int_source_read"]) for rule in rules):
        extracted.append("selective INT_SOURCE clear exception set")
        inferred.append("five non-data INT_SOURCE fields clear after read")
    if any(rule["id"] == _slug(request["rule_ids"]["fifo_bypass"]) for rule in rules):
        extracted.append("FIFO bypass encoding and FIFO-clear transition")
        inferred.append("FIFO occupancy is generic six-bit internal state cleared by a guarded FIFO_CTL write")
    report = {
        "extractor": request["extractor"], "candidate_status": "pending_review",
        "source_sha256": document.sha256, "candidate_sha256": canonical_sha256(spec),
        "automatically_extracted": extracted,
        "automatically_inferred_pending_review": inferred,
        "manually_selected_configured": [
            "official source identity/revision", "two-register extraction slice", "0x53 board address",
            "behavior categories to attempt", "stable rule identifiers", "unsupported coverage boundary",
        ],
        "manually_accepted": ["evidence IDs listed in the hash-bound review manifest"],
        "unsupported": request["unsupported"],
        "unresolved": unresolved,
        "field_range_crosscheck_page": fifo_range_page.pdf_page,
    }
    return {"spec": spec, "anchors": anchors, "report": report}

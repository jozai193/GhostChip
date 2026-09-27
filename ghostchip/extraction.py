"""Untrusted candidate extraction and deterministic acceptance for DeviceSpec v1.

The heuristic extractor is deliberately outside the runtime and validator. Its
output is pending evidence until a hash-bound review manifest accepts it.
"""
from copy import deepcopy
import hashlib
import json
import re

from .pdf_ingest import normalize_text
from .spec import validate


class ExtractionError(ValueError):
    """The requested extraction cannot produce a complete candidate safely."""


class ReviewError(ValueError):
    """A review decision does not exactly bind the candidate being accepted."""


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _slug(value):
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not value or not value[0].isalpha():
        raise ExtractionError(f"Cannot create DeviceSpec identifier from {value!r}")
    return value


def _clean_lines(text):
    return [line.strip() for line in normalize_text(text).splitlines() if line.strip()]


def _printed_page(text, fallback):
    match = re.search(r"Data sheet\s+(\d+)\s*\|\s*\d+", text, re.I)
    return match.group(1) if match else str(fallback)


def _section(text, register_name):
    match = re.search(
        r"(?m)^(\d+(?:\.\d+)+)\s+Register\s+0x[0-9A-Fa-f]+\s+[\"']?" +
        re.escape(register_name) + r"[\"']?",
        text,
    )
    return match.group(1) if match else "register description"


def _find_register_header(document, name):
    pattern = re.compile(r"(?m)^\d+(?:\.\d+)+\s+Register\s+0x([0-9A-Fa-f]{2})\s+[\"']?" + re.escape(name) + r"[\"']?.*$", re.I)
    for page in document.pages:
        match = pattern.search(page.text)
        if match and "..." not in match.group(0):
            return page, int(match.group(1), 16)
    raise ExtractionError(f"Requested register {name!r} was not found in a register heading")


def _memory_map_reset(document, name, address):
    pattern = re.compile(r"(?m)^" + re.escape(name) + r"\s+0x" + f"{address:02X}" + r"\s+0x([0-9A-Fa-f]{2})\s*$", re.I)
    for page in document.pages:
        match = pattern.search(page.text)
        if match:
            return int(match.group(1), 16), page
    raise ExtractionError(f"Reset value for {name!r} was not found as a memory-map row")


def _register_section_text(page, name):
    match = re.search(
        r"(?m)^\d+(?:\.\d+)+\s+Register\s+0x[0-9A-Fa-f]+\s+[\"']?" +
        re.escape(name) + r"[\"']?",
        page.text,
        re.I,
    )
    if not match:
        return page.text
    following = re.search(r"(?m)^\d+(?:\.\d+)+\s+Register\s+0x", page.text[match.end():])
    end = match.end() + following.start() if following else len(page.text)
    return page.text[match.start():end]


def _fields_for_register(document, page, name, address):
    local_text = _register_section_text(page, name)
    field_page = page
    table_pattern = re.compile(
        r"Table\s+\d+:\s+Register\s+0x" + f"{address:02X}" +
        r"\s+[\"']?" + re.escape(name) + r"[\"']?",
        re.I,
    )
    for candidate_page in document.pages[page.pdf_page - 1:min(page.pdf_page + 2, document.page_count)]:
        match = table_pattern.search(candidate_page.text)
        if not match:
            continue
        following = re.search(r"(?m)^(?:Table\s+\d+:\s+Register|\d+(?:\.\d+)+\s+Register)",
                              candidate_page.text[match.end():])
        end = match.end() + following.start() if following else len(candidate_page.text)
        local_text += "\n" + candidate_page.text[match.start():end]
        field_page = candidate_page
        break
    lines = _clean_lines(local_text)
    fields = []
    bit_line = re.compile(r"^Bit\s+([0-7](?:\s*,\s*[0-7])*)\s+([A-Za-z][A-Za-z0-9_]*)\[(\d+):0\]", re.I)
    for line in lines:
        match = bit_line.match(line)
        if not match:
            continue
        bits = [int(value) for value in re.findall(r"[0-7]", match.group(1))]
        declared_msb = int(match.group(3))
        if sorted(bits) != list(range(min(bits), max(bits) + 1)) or len(bits) != declared_msb + 1:
            raise ExtractionError(f"Non-contiguous or inconsistent field declaration: {line}")
        fields.append({"id": _slug(match.group(2)), "lsb": min(bits), "width": declared_msb + 1})
    if fields:
        return fields, field_page
    # Full-byte identity fields are frequently expressed in prose rather than a table row.
    full_byte = re.search(r"\b([A-Za-z][A-Za-z0-9_]*)\[7:0\]", local_text)
    if full_byte:
        return [{"id": _slug(full_byte.group(1)), "lsb": 0, "width": 8}], page
    raise ExtractionError(f"No supported field declaration found for register {name!r}")


def _access_for_register(page, name):
    local = re.sub(r"\s+", " ", _register_section_text(page, name).lower())
    if "can be read" in local and "write" not in local:
        return "ro"
    if "write" in local or "sets the" in local:
        return "rw"
    raise ExtractionError(f"Access for register {name!r} is ambiguous")


def _find_latches(document, included_registers):
    """Find 'changes only become effective after a write' dependencies."""
    results = []
    pattern = re.compile(
        r"register\s+only\s+become\s+effective\s+after\s+a\s+write\s+operation\s+to\s+[\"']?([a-z][a-z0-9_]*)[\"']?",
        re.I,
    )
    for page in document.pages:
        match = pattern.search(page.text)
        if not match:
            continue
        prefix = page.text[:match.start()]
        headers = list(re.finditer(r"Register\s+0x[0-9A-Fa-f]{2}\s+[\"']?([a-z][a-z0-9_]*)[\"']?", prefix, re.I))
        if not headers:
            continue
        source_name = _slug(headers[-1].group(1))
        trigger_name = _slug(match.group(1))
        if source_name in included_registers and trigger_name in included_registers:
            sentence_start = max(prefix.rfind("."), prefix.rfind("\n")) + 1
            sentence_end = page.text.find(".", match.end())
            quote = page.text[sentence_start:sentence_end + 1].strip()
            results.append((source_name, trigger_name, page, quote))
    return results


def _find_cross_reference(document, source_name, trigger_name):
    pattern = re.compile(
        r"register\s+needs\s+to\s+be\s+written\s+after\s+changing\s+[\"']?" +
        re.escape(source_name) + r"[\"']?\s+for\s+the\s+changes\s+to\s+become\s+effective",
        re.I,
    )
    for page in document.pages:
        match = pattern.search(page.text)
        if match:
            sentence_start = max(page.text.rfind(".", 0, match.start()), page.text.rfind("\n", 0, match.start())) + 1
            sentence_end = page.text.find(".", match.end())
            return page, page.text[sentence_start:sentence_end + 1].strip()
    return None


def _address_options(document):
    for page in document.pages:
        if "7-bit device address" not in page.text:
            continue
        options = {int(value, 16) for value in re.findall(r"\(0x([0-9A-Fa-f]{2})\)", page.text)}
        if len(options) >= 2:
            return options, page
    raise ExtractionError("I2C address alternatives were not found")


def _extract_latch_candidate(document, request):
    """Generate a pending DeviceSpec candidate and separately checkable anchors."""
    expected = request["source_sha256"].lower()
    if document.sha256 != expected:
        raise ExtractionError("Document hash does not match extraction request")
    requested = [_slug(name) for name in request["registers"]]
    if len(set(requested)) != len(requested):
        raise ExtractionError("Duplicate requested register")
    options, address_page = _address_options(document)
    device_address = request["device_address"]
    if device_address not in options:
        raise ExtractionError("Selected board address is not a datasheet-listed I2C address")

    evidence = []
    anchors = []
    registers = []
    definitions = {}
    for name in requested:
        page, address = _find_register_header(document, name)
        reset, map_page = _memory_map_reset(document, name, address)
        fields, field_page = _fields_for_register(document, page, name, address)
        mask = 255
        for field in fields:
            mask &= ~(((1 << field["width"]) - 1) << field["lsb"])
        evidence_id = "register_" + name
        reset_evidence_id = evidence_id + "_reset"
        fields_evidence_id = evidence_id + "_fields"
        section = _section(page.text, name)
        evidence.append({
            "id": evidence_id, "source_id": request["source_id"], "pdf_page": page.pdf_page,
            "printed_page": _printed_page(page.text, page.pdf_page), "section": section,
            "summary": f"The register heading identifies {name} at address 0x{address:02X}.",
            "origin": "model_extraction", "review": "pending", "confidence": 0.9,
        })
        evidence.append({
            "id": reset_evidence_id, "source_id": request["source_id"], "pdf_page": map_page.pdf_page,
            "printed_page": _printed_page(map_page.text, map_page.pdf_page), "section": "5.3, Table 18",
            "summary": f"The memory map gives {name} reset value 0x{reset:02X}.",
            "origin": "model_extraction", "review": "pending", "confidence": 0.9,
        })
        evidence.append({
            "id": fields_evidence_id, "source_id": request["source_id"], "pdf_page": field_page.pdf_page,
            "printed_page": _printed_page(field_page.text, field_page.pdf_page), "section": section + ", field definition",
            "summary": f"The field definition for {name} supplies the extracted bit ranges.",
            "origin": "model_extraction", "review": "pending", "confidence": 0.9,
        })
        anchors.extend([
            {"evidence_id": evidence_id, "pdf_page": page.pdf_page, "page_text_sha256": page.sha256},
            {"evidence_id": reset_evidence_id, "pdf_page": map_page.pdf_page,
             "page_text_sha256": map_page.sha256},
            {"evidence_id": fields_evidence_id, "pdf_page": field_page.pdf_page,
             "page_text_sha256": field_page.sha256},
        ])
        register = {
            "id": name, "address": address, "width": 8, "reset": reset,
            "access": _access_for_register(page, name), "reserved_mask": mask,
            "fields": fields, "evidence": [evidence_id, reset_evidence_id, fields_evidence_id],
        }
        definitions[name] = register
        registers.append(register)

    state = []
    rules = []
    unresolved = []
    latches = _find_latches(document, set(requested))
    if not latches:
        unresolved.append({
            "kind": "behavioral_rule", "status": "not_extracted",
            "detail": "No supported write-latch sentence connected two included registers.",
        })
    for source_name, trigger_name, page, quote in latches:
        source_fields = definitions[source_name]["fields"]
        if len(source_fields) != 1:
            unresolved.append({
                "kind": "behavioral_rule", "status": "needs_review",
                "detail": f"{source_name} has multiple fields; effective-state mapping is ambiguous.",
            })
            continue
        field = source_fields[0]
        dependency_key = source_name + "->" + trigger_name
        rule_id = request.get("rule_ids", {}).get(dependency_key, field["id"] + "_write_latch")
        rule_id = _slug(rule_id)
        evidence_id = rule_id
        section = _section(page.text, source_name)
        evidence.append({
            "id": evidence_id, "source_id": request["source_id"], "pdf_page": page.pdf_page,
            "printed_page": _printed_page(page.text, page.pdf_page), "section": section,
            "summary": f"Changes to {source_name} become effective only after a write to {trigger_name}.",
            "origin": "model_extraction", "review": "pending", "confidence": 0.96,
        })
        rule_evidence = [evidence_id]
        anchors.append({"evidence_id": evidence_id, "pdf_page": page.pdf_page,
                        "page_text_sha256": page.sha256, "quote": quote})
        cross = _find_cross_reference(document, source_name, trigger_name)
        if cross:
            cross_page, cross_quote = cross
            cross_id = evidence_id + "_crosscheck"
            evidence.append({
                "id": cross_id, "source_id": request["source_id"], "pdf_page": cross_page.pdf_page,
                "printed_page": _printed_page(cross_page.text, cross_page.pdf_page),
                "section": _section(cross_page.text, trigger_name),
                "summary": f"The {trigger_name} description independently repeats the {source_name} write-order dependency.",
                "origin": "model_extraction", "review": "pending", "confidence": 0.98,
            })
            anchors.append({"evidence_id": cross_id, "pdf_page": cross_page.pdf_page,
                            "page_text_sha256": cross_page.sha256, "quote": cross_quote})
            rule_evidence.append(cross_id)
        state_id = "effective_" + field["id"]
        state.append({"id": state_id, "width": field["width"],
                      "reset": (definitions[source_name]["reset"] >> field["lsb"]) & ((1 << field["width"]) - 1),
                      "evidence": rule_evidence})
        rules.append({
            "id": rule_id,
            "on": {"event": "after_write", "register": trigger_name},
            "effects": [{
                "target": {"kind": "state", "id": state_id},
                "value": {"kind": "field", "register": source_name, "field": field["id"]},
            }],
            "evidence": rule_evidence,
        })

    constraints = []
    for item in request.get("field_constraints", []):
        reg = definitions.get(_slug(item["register"]))
        if not reg:
            raise ExtractionError("Constraint references a register outside the extraction slice")
        field = next((f for f in reg["fields"] if f["id"] == _slug(item["field"])), None)
        if not field:
            raise ExtractionError("Constraint references an unknown extracted field")
        value = item["equals"]
        if not 0 <= value < (1 << field["width"]):
            raise ExtractionError("Constraint value exceeds extracted field width")
        constraints.append({
            "register": reg["id"], "mask": ((1 << field["width"]) - 1) << field["lsb"],
            "equals": value << field["lsb"], "reason": item["reason"],
        })

    address_evidence = {
        "id": "i2c_address_options", "source_id": request["source_id"],
        "pdf_page": address_page.pdf_page, "printed_page": _printed_page(address_page.text, address_page.pdf_page),
        "section": "6.2", "summary": "The datasheet lists board-selectable I2C addresses 0x76 and 0x77.",
        "origin": "model_extraction", "review": "pending", "confidence": 0.99,
    }
    evidence.append(address_evidence)
    anchors.append({"evidence_id": "i2c_address_options", "pdf_page": address_page.pdf_page,
                    "page_text_sha256": address_page.sha256})
    spec = {
        "schema_version": "1.0.0", "profile": "i2c-reg8-events-v1",
        "device": {"name": request["device_name"], "vendor": request["vendor"],
                   "bus": "i2c", "address": device_address},
        "scope": {"description": request["scope_description"],
                  "unsupported": request["unsupported"], "write_constraints": constraints},
        "sources": [{"id": request["source_id"], "url": request["source_url"],
                     "sha256": document.sha256, "page_count": document.page_count,
                     "revision": request["source_revision"]}],
        "evidence": evidence, "registers": registers, "state": state, "rules": rules,
    }
    validate(spec)
    report = {
        "extractor": "layout-tolerant-regex-v1", "candidate_status": "pending_review",
        "source_sha256": document.sha256, "candidate_sha256": canonical_sha256(spec),
        "automatic": ["PDF byte hash and page text", "requested register addresses/resets/fields/access",
                      "write-latch dependency, effective state, transition, and two-page provenance"],
        "manual_inputs": ["source identity/revision", "register slice", "board-selected I2C address",
                          "sleep-only coverage constraint", "evidence acceptance"],
        "unresolved": unresolved,
    }
    return {"spec": spec, "anchors": anchors, "report": report}


def extract_candidate(document, request):
    """Dispatch to a source-layout extractor; every output remains pending."""
    if request.get("extractor") == "adxl345-rev-g-v1":
        from .adxl345_extraction import extract_candidate as extract_adxl345
        return extract_adxl345(document, request)
    if request.get("extractor") == "bme280-sensorapi-v1":
        from .bme280_sensorapi_extraction import extract_candidate as extract_bme280_sensorapi
        return extract_bme280_sensorapi(document, request)
    return _extract_latch_candidate(document, request)


def accept_review(candidate, review):
    """Apply review statuses only when the manifest exactly identifies the candidate."""
    allowed = {"bundle_version", "source_sha256", "candidate_sha256", "request_sha256",
               "anchors_sha256", "accepted_evidence", "review_basis", "limitations"}
    if set(review) - allowed:
        raise ReviewError("Review manifests may contain decisions and notes, not semantic overrides")
    if review["source_sha256"].lower() != candidate["sources"][0]["sha256"]:
        raise ReviewError("Review source hash does not match candidate")
    digest = canonical_sha256(candidate)
    if review["candidate_sha256"].lower() != digest:
        raise ReviewError("Review candidate hash does not match; semantic changes require new review")
    accepted = set(review["accepted_evidence"])
    known = {item["id"] for item in candidate["evidence"]}
    if not accepted <= known:
        raise ReviewError("Review names unknown evidence")
    result = deepcopy(candidate)
    for item in result["evidence"]:
        item["review"] = "accepted" if item["id"] in accepted else "pending"
    validate(result)
    return result

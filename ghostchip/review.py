"""Execution-time identity checks for reviewed extraction bundles."""
from copy import deepcopy
import json
from pathlib import Path

from .extraction import ReviewError, accept_review, canonical_sha256


BUNDLE_VERSION = "review-bundle-v1"


def _read(value):
    if isinstance(value, (str, Path)):
        return json.loads(Path(value).read_text())
    return deepcopy(value)


def build_review_bundle(candidate, review, request, anchors, reviewed_spec=None):
    """Reconstruct the executable spec and bind every review input."""
    candidate = _read(candidate)
    review = _read(review)
    request = _read(request)
    anchors = _read(anchors)
    if review.get("bundle_version") != BUNDLE_VERSION:
        raise ReviewError("Review does not declare the supported bundle version")
    if review.get("request_sha256") != canonical_sha256(request):
        raise ReviewError("Review extraction-request hash does not match")
    if review.get("anchors_sha256") != canonical_sha256(anchors):
        raise ReviewError("Review evidence-anchor hash does not match")
    known_evidence = {item["id"] for item in candidate["evidence"]}
    anchored = {item.get("evidence_id") for item in anchors}
    if None in anchored or anchored != known_evidence:
        raise ReviewError("Evidence anchors must bind every candidate evidence record exactly")
    if any(not isinstance(item.get("page_text_sha256"), str) or
           len(item["page_text_sha256"]) != 64 for item in anchors):
        raise ReviewError("Evidence anchor page identity is malformed")
    executable = accept_review(candidate, review)
    if reviewed_spec is not None and _read(reviewed_spec) != executable:
        raise ReviewError("Saved reviewed spec differs from reconstructed reviewed candidate")
    identities = {
        "candidate_sha256": canonical_sha256(candidate),
        "review_sha256": canonical_sha256(review),
        "request_sha256": canonical_sha256(request),
        "anchors_sha256": canonical_sha256(anchors),
        "executable_spec_sha256": canonical_sha256(executable),
        "source_sha256": candidate["sources"][0]["sha256"],
    }
    return {
        "bundle_version": BUNDLE_VERSION,
        "candidate": candidate,
        "review": review,
        "request": request,
        "anchors": anchors,
        "reviewed_spec": executable,
        "identities": identities,
    }


def load_review_bundle(path):
    """Load an envelope but always reconstruct it from the review inputs."""
    envelope = _read(path)
    if set(envelope) != {"bundle_version", "candidate", "review", "request", "anchors",
                        "reviewed_spec", "identities"}:
        raise ReviewError("Reviewed bundle envelope has unexpected or missing members")
    if envelope["bundle_version"] != BUNDLE_VERSION:
        raise ReviewError("Unsupported reviewed bundle version")
    rebuilt = build_review_bundle(envelope["candidate"], envelope["review"],
                                  envelope["request"], envelope["anchors"],
                                  envelope["reviewed_spec"])
    if envelope["identities"] != rebuilt["identities"]:
        raise ReviewError("Reviewed bundle identity table is stale")
    return rebuilt

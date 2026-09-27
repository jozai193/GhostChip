"""CLI: PDF -> pending candidate -> hash-bound review -> executable DeviceSpec."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from .extraction import accept_review, extract_candidate
from .pdf_ingest import ingest_pdf
from .review import build_review_bundle


def _load(path):
    return json.loads(Path(path).read_text())


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(value, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    request = _load(args.request)
    document = ingest_pdf(args.pdf, expected_sha256=request["source_sha256"])
    result = extract_candidate(document, request)
    report = result["report"]
    accepted = None
    bundle = None
    if args.review:
        review = _load(args.review)
        accepted = accept_review(result["spec"], review)
        bundle = build_review_bundle(result["spec"], review, request, result["anchors"], accepted)
        bundle_name = f"reviewed-bundle-{bundle['identities']['executable_spec_sha256']}.json"
        report = {**report, "review_status": "applied", "reviewed_spec_written": True,
                  "reviewed_bundle": bundle_name}
    else:
        report = {**report, "review_status": "not_supplied", "reviewed_spec_written": False}
    # Complete extraction and review validation before publishing any member.
    # Individual writes are atomic; content addressing prevents a stale bundle
    # from being confused with a changed candidate.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write(args.output_dir / "candidate.devicespec.json", result["spec"])
    _write(args.output_dir / "evidence-anchors.json", result["anchors"])
    if accepted is not None:
        _write(args.output_dir / "reviewed.devicespec.json", accepted)
        _write(args.output_dir / bundle_name, bundle)
    _write(args.output_dir / "extraction-report.json", report)
    print(f"Candidate: {args.output_dir / 'candidate.devicespec.json'}")
    print(f"Rules extracted: {len(result['spec']['rules'])}; unresolved: {len(report['unresolved'])}")
    if args.review:
        print(f"Reviewed spec: {args.output_dir / 'reviewed.devicespec.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

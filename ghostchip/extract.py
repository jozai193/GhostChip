"""CLI: PDF -> pending candidate -> hash-bound review -> executable DeviceSpec."""
import argparse
import json
from pathlib import Path

from .extraction import accept_review, extract_candidate
from .pdf_ingest import ingest_pdf


def _load(path):
    return json.loads(Path(path).read_text())


def _write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


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
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write(args.output_dir / "candidate.devicespec.json", result["spec"])
    _write(args.output_dir / "evidence-anchors.json", result["anchors"])
    report = result["report"]
    if args.review:
        accepted = accept_review(result["spec"], _load(args.review))
        _write(args.output_dir / "reviewed.devicespec.json", accepted)
        report = {**report, "review_status": "applied", "reviewed_spec_written": True}
    else:
        report = {**report, "review_status": "not_supplied", "reviewed_spec_written": False}
    _write(args.output_dir / "extraction-report.json", report)
    print(f"Candidate: {args.output_dir / 'candidate.devicespec.json'}")
    print(f"Rules extracted: {len(result['spec']['rules'])}; unresolved: {len(report['unresolved'])}")
    if args.review:
        print(f"Reviewed spec: {args.output_dir / 'reviewed.devicespec.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

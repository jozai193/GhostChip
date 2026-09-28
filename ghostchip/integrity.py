"""Execution-closure identities for deterministic proof and repair runs.

These hashes detect accidental or local-process drift.  They are not a
signature, a sandbox, or protection from a hostile host that can rewrite both
the code and the recorded manifest.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


EXECUTION_CLOSURE_VERSION = "execution-closure-v1"

# Keep this explicit: changes to what can affect verification should be reviewed
# rather than silently discovered from an import graph at runtime.
EXECUTION_FILES = (
    "ghostchip/integrity.py",
    "ghostchip/proof.py",
    "ghostchip/runtime.py",
    "ghostchip/spec.py",
    "ghostchip/review.py",
    "ghostchip/extraction.py",
    "ghostchip/pdf_ingest.py",
    "ghostchip/presentation.py",
    "ghostchip/contracts.py",
    "ghostchip/repair.py",
    "ghostchip/api.py",
    "schema/devicespec-v1.schema.json",
    "schema/devicespec-v1.1.schema.json",
    "schema/scenario-v1.schema.json",
    "schema/repair-request-v1.schema.json",
    "schema/repair-proposal-v1.schema.json",
    "examples/gc_hal.c",
    "examples/gc_hal.h",
)


class ExecutionClosureError(RuntimeError):
    """The verifier execution closure no longer matches its recorded bytes."""


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def canonical_sha256(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def compiler_identity(compiler=None):
    resolved = compiler or shutil.which("gcc")
    if not resolved:
        raise ExecutionClosureError("gcc is required")
    resolved = str(Path(resolved).resolve())
    version = subprocess.run(
        [resolved, "--version"], capture_output=True, text=True, check=True, timeout=5
    ).stdout.splitlines()[0]
    target = subprocess.run(
        [resolved, "-dumpmachine"], capture_output=True, text=True, check=True, timeout=5
    ).stdout.strip()
    return {
        "path": resolved,
        "sha256": sha256_file(resolved),
        "version": version,
        "target": target,
    }


def capture_execution_closure(root, compiler=None):
    root = Path(root)
    files = {}
    for relative in EXECUTION_FILES:
        path = root / relative
        if not path.is_file():
            raise ExecutionClosureError(f"Execution-closure file is missing: {relative}")
        files[relative] = sha256_file(path)
    body = {
        "version": EXECUTION_CLOSURE_VERSION,
        "files": files,
        "compiler": compiler_identity(compiler),
    }
    return {**body, "sha256": canonical_sha256(body)}


def validate_execution_closure(expected, root):
    """Recompute and compare the complete closure, returning the current copy."""
    if not isinstance(expected, dict) or expected.get("version") != EXECUTION_CLOSURE_VERSION:
        raise ExecutionClosureError("Missing or unsupported execution closure")
    current = capture_execution_closure(root, (expected.get("compiler") or {}).get("path"))
    if expected.get("sha256") != canonical_sha256({
        "version": expected.get("version"),
        "files": expected.get("files"),
        "compiler": expected.get("compiler"),
    }):
        raise ExecutionClosureError("Recorded execution-closure manifest hash is inconsistent")
    if current != expected:
        changed = []
        expected_files = expected.get("files") or {}
        for relative in sorted(set(current["files"]) | set(expected_files)):
            if current["files"].get(relative) != expected_files.get(relative):
                changed.append(relative)
        if current.get("compiler") != expected.get("compiler"):
            changed.append("compiler")
        detail = ", ".join(changed) or "manifest"
        raise ExecutionClosureError(f"Execution closure changed: {detail}")
    return deepcopy(current)

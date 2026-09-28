"""Build/check the local judge UI and serve it with the GhostChip API."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .real_driver import verify_upstream
from .spec import ROOT


WEB = ROOT / "web"


def _run(command, cwd=ROOT, timeout=180):
    completed = subprocess.run(command, cwd=cwd, text=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")


def build_frontend(force=False):
    output = WEB / "out/index.html"
    sources = [path for path in WEB.rglob("*") if path.is_file() and
               "node_modules" not in path.parts and "out" not in path.parts and ".next" not in path.parts]
    stale = not output.exists() or any(path.stat().st_mtime > output.stat().st_mtime for path in sources)
    if not (force or stale):
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required to build the Next.js frontend")
    if not (WEB / "node_modules").exists():
        _run([npm, "ci"], WEB)
    _run([npm, "run", "build"], WEB)


def prepare(*, build=True, run_flagship=False):
    required = ["fastapi", "uvicorn", "jsonschema", "pypdf", "cryptography"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("Missing Python dependencies: " + ", ".join(missing))
    if not shutil.which("gcc"):
        raise RuntimeError("gcc is required for the real Bosch driver demo")
    for path in (ROOT / "fixtures/bme280-sensorapi", ROOT / "third_party/bosch_bme280",
                 ROOT / "examples/bosch_bme280", WEB / "package.json"):
        if not path.exists():
            raise RuntimeError(f"Required demo input is missing: {path}")
    verify_upstream()
    if build:
        build_frontend()
    if not (WEB / "out/index.html").exists():
        raise RuntimeError("Frontend export is missing; run with frontend build enabled")
    if run_flagship:
        from fastapi.testclient import TestClient
        from .api import RunStore, create_app
        from .proof import digest
        from .repair import RepairStore, TARGET
        with tempfile.TemporaryDirectory(prefix="ghostchip-demo-smoke-") as temp:
            run_store = RunStore(root=Path(temp) / "runs")
            repair_store = RepairStore(run_store, root=Path(temp) / "repairs")
            client = TestClient(create_app(store=run_store, repair_store=repair_store, static_dir=WEB / "out"))
            landing = client.get("/")
            if landing.status_code != 200 or "GhostChip" not in landing.text:
                raise RuntimeError("Static judge interface did not load through FastAPI")
            if client.get("/api/devices/bme280").status_code != 200:
                raise RuntimeError("Reviewed BME280 metadata endpoint failed")
            created = client.post("/api/cases/humidity_x4/run")
            if created.status_code != 202:
                raise RuntimeError("Flagship API run did not start")
            run_id = created.json()["id"]
            completed = client.get(f"/api/runs/{run_id}").json()
            if completed["status"] != "PASS":
                message = (completed.get("result") or {}).get("error", "verification failure")
                raise RuntimeError("Flagship humidity_x4 case did not PASS: " + message)
            if not client.get(f"/api/runs/{run_id}/trace").json()["trace"]:
                raise RuntimeError("Flagship trace endpoint returned no callback records")
            if client.get(f"/api/runs/{run_id}/evidence").status_code != 200:
                raise RuntimeError("Flagship evidence endpoint failed")
            original_hash = digest(TARGET)
            failed = client.post("/api/cases/buggy_driver/run")
            if failed.status_code != 202:
                raise RuntimeError("Buggy-driver API run did not start")
            failed_id = failed.json()["id"]
            failed_result = client.get(f"/api/runs/{failed_id}").json()
            if failed_result["status"] != "FAIL":
                raise RuntimeError("Buggy-driver smoke case did not produce the expected deterministic FAIL")
            proposed = client.post(f"/api/runs/{failed_id}/repair")
            if proposed.status_code != 202:
                raise RuntimeError("Bounded repair proposal did not start")
            repair_id = proposed.json()["id"]
            proposal = client.get(f"/api/repairs/{repair_id}").json()
            if proposal["status"] != "PROPOSED" or proposal["proposal"]["provider"]["kind"] != "local_demo":
                raise RuntimeError("Offline demo provider did not produce a clearly labeled validated proposal")
            applied = client.post(f"/api/repairs/{repair_id}/apply-and-verify")
            if applied.status_code != 202:
                raise RuntimeError("Repair apply-and-verify did not start")
            repaired = client.get(f"/api/repairs/{repair_id}").json()
            if repaired["status"] != "VERIFIED":
                raise RuntimeError("Derived repair was not deterministically VERIFIED")
            if not all(repaired["audit"]["identity_checks"].values()):
                raise RuntimeError("Repair rerun did not preserve oracle identities")
            if digest(TARGET) != original_hash or not repaired["audit"]["original_source_preserved"]:
                raise RuntimeError("Repair workflow modified the original source")
    return {"python": sys.version.split()[0], "gcc": shutil.which("gcc"),
            "frontend": str(WEB / "out/index.html"), "bosch_source": "VERIFIED",
            "flagship": "PASS" if run_flagship else "not run",
            "repair": "VERIFIED" if run_flagship else "not run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify readiness and exit")
    parser.add_argument("--smoke", action="store_true", help="also execute the flagship real-driver case")
    parser.add_argument("--rebuild", action="store_true", help="force a frontend rebuild")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.rebuild:
        build_frontend(force=True)
    report = prepare(build=True, run_flagship=args.smoke)
    print("GhostChip demo readiness:", report)
    if args.check:
        return 0
    import uvicorn
    uvicorn.run("ghostchip.api:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

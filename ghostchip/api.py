"""FastAPI application exposing only the curated GhostChip demo surface."""
from copy import deepcopy
import json
import os
from pathlib import Path
from threading import Lock
import time
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .presentation import (cases, device_detail, devices, run_demo_case,
                           serialize_trace, summarize_result)
from .repair import RepairError, RepairStore
from .spec import ROOT


RUN_ROOT = ROOT / "artifacts/demo-runs"


class RunStore:
    def __init__(self, runner=run_demo_case, root=RUN_ROOT):
        self.runner = runner
        self.root = Path(root)
        self._runs = {}
        self._lock = Lock()

    def create(self, case_id):
        run_id = uuid4().hex
        record = {"id": run_id, "case_id": case_id, "status": "QUEUED", "events": [],
                  "created_at": time.time(), "result": None}
        with self._lock:
            self._runs[run_id] = record
        return deepcopy(record)

    def _event(self, run_id, stage, state, detail):
        with self._lock:
            record = self._runs[run_id]
            record["status"] = "RUNNING"
            record["events"].append({"stage": stage, "state": state, "detail": detail,
                                     "at_ms": round((time.time() - record["created_at"]) * 1000, 3)})

    def execute(self, run_id):
        with self._lock:
            case_id = self._runs[run_id]["case_id"]
            self._runs[run_id]["status"] = "RUNNING"
        result = self.runner(case_id, lambda stage, state, detail: self._event(run_id, stage, state, detail))
        status = result.get("status") if result.get("status") in {"PASS", "FAIL", "ERROR"} else "ERROR"
        if status == "ERROR" and "error" not in result:
            result["error"] = "Runner returned a malformed status"
        with self._lock:
            record = self._runs[run_id]
            record["status"] = status
            record["result"] = result
            record["completed_at"] = time.time()
            saved = deepcopy(record)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{run_id}.tmp"
        temporary.write_text(json.dumps(saved, indent=2) + "\n")
        os.replace(temporary, self.root / f"{run_id}.json")

    def get(self, run_id):
        with self._lock:
            if run_id in self._runs:
                return deepcopy(self._runs[run_id])
        path = self.root / f"{run_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        raise KeyError(run_id)


def _record_response(record):
    response = {key: record[key] for key in ("id", "case_id", "status", "events", "created_at")}
    if "completed_at" in record:
        response["completed_at"] = record["completed_at"]
    if record.get("result") is not None:
        response["result"] = summarize_result(record["result"])
    return response


def create_app(*, store=None, repair_store=None, repair_provider=None, static_dir=None):
    app = FastAPI(title="GhostChip Demo API", version="6.0.0",
                  description="Curated local wrapper around the deterministic GhostChip engine.")
    run_store = store or RunStore()
    repairs = repair_store or RepairStore(run_store, provider=repair_provider)
    static = Path(static_dir or ROOT / "web/out")

    @app.get("/api/health")
    def health():
        return {"status": "ready", "engine": "GhostChip", "remote_code_execution": False,
                "repair_provider": "local-demo", "live_ai_configured": False}

    @app.get("/api/devices")
    def list_devices():
        return {"devices": devices()}

    @app.get("/api/devices/{device_id}")
    def get_device(device_id: str):
        try:
            return device_detail(device_id)
        except KeyError:
            raise HTTPException(404, "Unknown curated device") from None

    @app.get("/api/devices/{device_id}/rules")
    def get_rules(device_id: str):
        try:
            detail = device_detail(device_id)
        except KeyError:
            raise HTTPException(404, "Unknown curated device") from None
        return {"device_id": device_id, "rules": detail["rules"]}

    @app.get("/api/cases")
    def list_cases():
        return {"cases": cases()}

    @app.post("/api/cases/{case_id}/run", status_code=202)
    def start_case(case_id: str, background: BackgroundTasks):
        if case_id not in {item["id"] for item in cases()}:
            raise HTTPException(404, "Unknown curated case")
        record = run_store.create(case_id)
        background.add_task(run_store.execute, record["id"])
        return _record_response(record)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return _record_response(run_store.get(run_id))
        except KeyError:
            raise HTTPException(404, "Unknown run") from None

    @app.get("/api/runs/{run_id}/trace")
    def get_trace(run_id: str):
        try:
            record = run_store.get(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown run") from None
        if record.get("result") is None:
            return {"run_id": run_id, "status": record["status"], "trace": []}
        return {"run_id": run_id, "status": record["status"],
                "trace": serialize_trace(record["result"])}

    @app.get("/api/runs/{run_id}/evidence")
    def get_evidence(run_id: str):
        try:
            record = run_store.get(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown run") from None
        if record.get("result") is None:
            return {"run_id": run_id, "status": record["status"], "evidence": []}
        result = record["result"]
        evidence = [item for violation in result.get("violations", [])
                    for item in violation.get("evidence", [])]
        return {"run_id": run_id, "status": record["status"], "evidence": evidence,
                "review_bundle": result.get("review_bundle"),
                "source_identity": result.get("build") or {}}

    @app.post("/api/runs/{run_id}/repair", status_code=202)
    def generate_repair(run_id: str, background: BackgroundTasks):
        try:
            record = repairs.create(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown run") from None
        except RepairError as exc:
            raise HTTPException(409, str(exc)) from None
        background.add_task(repairs.generate, record["id"])
        return record

    @app.get("/api/repairs/{repair_id}")
    def get_repair(repair_id: str):
        try:
            return repairs.get(repair_id)
        except KeyError:
            raise HTTPException(404, "Unknown repair") from None

    @app.post("/api/repairs/{repair_id}/apply-and-verify", status_code=202)
    def apply_repair(repair_id: str, background: BackgroundTasks):
        try:
            record = repairs.get(repair_id)
        except KeyError:
            raise HTTPException(404, "Unknown repair") from None
        if record["status"] != "PROPOSED":
            raise HTTPException(409, "Only a validated proposal can be applied")
        background.add_task(repairs.apply_and_verify, repair_id)
        return {**record, "status": "APPLYING"}

    @app.post("/api/repairs/{repair_id}/discard")
    def discard_repair(repair_id: str):
        try:
            return repairs.discard(repair_id)
        except KeyError:
            raise HTTPException(404, "Unknown repair") from None
        except RepairError as exc:
            raise HTTPException(409, str(exc)) from None

    if static.exists():
        assets = static / "_next"
        if assets.exists():
            app.mount("/_next", StaticFiles(directory=assets), name="next-assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(static / "index.html")

        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def missing_frontend():
            return HTMLResponse("<h1>GhostChip API ready</h1><p>Build web/ to enable the judge interface.</p>")

    return app


app = create_app()

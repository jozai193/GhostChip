"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { assertionSummary, PERSISTED_INTEGRITY_MESSAGE, repairVisualState, TERMINAL_VERDICTS, visualVerdict } from "../lib/verdict.mjs";
import { acceptsRepair, acceptsRun, bindRepair, bindRun, canApplyRepair, nextGeneration, sameGeneration } from "../lib/active-context.mjs";

type CaseMeta = {
  id: string; label: string; group: string; expected: "PASS" | "FAIL";
  summary: string; featured?: boolean; unreviewed?: boolean;
};
type Evidence = { source: string; page: number; printed_page?: string; section: string; summary: string; origin: string };
type Rule = { id: string; title: string; plain_english: string; status: string; evidence: Evidence[] };
type Device = {
  name: string; vendor: string; bus: string; profile: string; register_count: number;
  rule_count: number; review_status: string; source_status: string; scope: string;
  limitations: string[]; rules: Rule[]; source: Record<string, unknown>;
  bundle_identity: Record<string, string>; driver: {
    name: string; core: string; commit: string; license: string; source_integrity: string;
    hashes: Record<string, string>;
  };
  automation: { automatic: string[]; reviewed_manual: string[] };
};
type RunEvent = { stage: string; state: string; detail: string; at_ms: number };
type RunResult = {
  status: "PASS" | "FAIL" | "ERROR"; case: string; presentation: CaseMeta;
  assertion_total: number; assertion_passed: number; callback_count: number;
  elapsed_ms: number; model_origin: string; assertions: Array<Record<string, unknown>>;
  violations: Array<Record<string, unknown>>; error?: string;
  observations: Record<string, { type: string; value: number }>;
  source_identity: Record<string, unknown>; review_bundle?: Record<string, string>;
  failure_explanation?: { expected: string; observed: string; cause: string; translation: string };
};
type Run = { id: string; case_id: string; status: string; events: RunEvent[]; result?: RunResult };
type TraceRow = {
  seq: number; operation: string; status: string | number; register_hex?: string;
  register_address?: number; label?: string; length?: number; duration_us?: number;
  value?: number; rules_triggered?: string[];
};
type RepairRecord = {
  id: string; run_id: string; status: string; error?: string; error_code?: string;
  events: RunEvent[];
  proposal?: {
    explanation: string; unified_diff: string; changed_lines: number;
    request_sha256: string; response_sha256: string; patch_sha256: string;
    resulting_source_sha256: string; provider: { id: string; kind: "local_demo" | "live_ai" | "test"; model: string };
  };
  request?: {
    sha256: string; failure: { assertion_ids: string[]; expected: unknown; observed: unknown; summary: string };
    rule: { id: string; evidence: Evidence[] };
    source: { path: string; sha256: string; start_line: number; end_line: number };
    identities: { reviewed_bundle: Record<string, string>; scenario_sha256: string; spec_sha256: string };
  };
  audit?: {
    original_source_sha256: string; resulting_source_sha256: string; executable_sha256: string;
    scenario_sha256: string; rerun_result: string; original_source_preserved: boolean;
    identity_checks: Record<string, boolean>; provider: { kind: string; id: string; model: string };
  };
};
type ActiveContext = {
  generation: number; caseId: string; runId: string | null; repairId: string | null;
};

const PERSISTED_INTEGRITY_ERROR = "PERSISTED_RECORD_INTEGRITY_ERROR";

async function decodeRepairResponse(response: Response, context: ActiveContext): Promise<RepairRecord> {
  const payload = await response.json().catch(() => null);
  if (response.ok) return payload as RepairRecord;
  if (response.status === 409 && payload?.status === PERSISTED_INTEGRITY_ERROR &&
      context.repairId && context.runId && payload?.repair_id === context.repairId) {
    return {
      id: context.repairId,
      run_id: context.runId,
      status: PERSISTED_INTEGRITY_ERROR,
      events: [],
      error: PERSISTED_INTEGRITY_MESSAGE,
    };
  }
  throw new Error(payload?.message || "Repair status unavailable");
}

const stages = [
  ["verifying_reviewed_model", "Reviewed model"],
  ["starting_virtual_device", "Virtual BME280"],
  ["verifying_source_identity", "Source identity"],
  ["compiling_real_driver", "Compile driver"],
  ["executing_callbacks", "Callbacks"],
  ["checking_assertions", "Assertions"],
  ["finalizing_result", "Result"],
];

function Icon({ name }: { name: "arrow" | "check" | "copy" }) {
  if (name === "arrow") return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11M11 5l5 5-5 5" /></svg>;
  if (name === "copy") return <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="7" y="7" width="9" height="9" rx="1" /><path d="M4 13H3V3h10v1" /></svg>;
  return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-9" /></svg>;
}

function Hash({ value }: { value?: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="hash muted">Unavailable</span>;
  return <button className="hash" onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1200); }} title={value}>
    <span>{value.slice(0, 10)}…{value.slice(-6)}</span><Icon name={copied ? "check" : "copy"} /><span className="sr-only">{copied ? "Copied" : "Copy full hash"}</span>
  </button>;
}

function App() {
  const [cases, setCases] = useState<CaseMeta[]>([]);
  const [device, setDevice] = useState<Device | null>(null);
  const [selected, setSelected] = useState("humidity_x4");
  const [run, setRun] = useState<Run | null>(null);
  const [trace, setTrace] = useState<TraceRow[]>([]);
  const [repair, setRepair] = useState<RepairRecord | null>(null);
  const [loadError, setLoadError] = useState("");
  const [applyPending, setApplyPending] = useState(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<ActiveContext>({ generation: 0, caseId: "humidity_x4", runId: null, repairId: null });
  const controllersRef = useRef<Set<AbortController>>(new Set());
  const timersRef = useRef<Set<number>>(new Set());
  const applyPendingRef = useRef(false);

  useEffect(() => {
    Promise.all([
      fetch("/api/cases").then((r) => { if (!r.ok) throw new Error("Case catalog unavailable"); return r.json(); }),
      fetch("/api/devices/bme280").then((r) => { if (!r.ok) throw new Error("Reviewed device unavailable"); return r.json(); }),
    ]).then(([caseData, deviceData]) => { setCases(caseData.cases); setDevice(deviceData); })
      .catch((error) => setLoadError(String(error)));
    return () => cancelOutstanding();
    // The catalog request is intentionally a one-time application bootstrap.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedCase = useMemo(() => cases.find((item) => item.id === selected), [cases, selected]);
  const verdict = visualVerdict(run?.result?.status || run?.status || "READY");
  const counts = assertionSummary(run?.result);
  const apiObservation = run?.result ? Object.entries(run.result.observations || {}).filter(([key]) => key.startsWith("api.")).at(-1) : undefined;
  const latchEvidence = device?.rules.find((rule) => rule.id === "humidity_latch")?.evidence[0];

  function cancelOutstanding() {
    controllersRef.current.forEach((controller) => controller.abort());
    controllersRef.current.clear();
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current.clear();
    applyPendingRef.current = false;
    setApplyPending(false);
  }

  function beginGeneration(caseId: string) {
    cancelOutstanding();
    const context = nextGeneration(activeRef.current, caseId) as ActiveContext;
    activeRef.current = context;
    return context;
  }

  function requestController() {
    const controller = new AbortController();
    controllersRef.current.add(controller);
    return controller;
  }

  function releaseController(controller: AbortController) {
    controllersRef.current.delete(controller);
  }

  function schedule(callback: () => void) {
    const timer = window.setTimeout(() => {
      timersRef.current.delete(timer);
      callback();
    }, 180);
    timersRef.current.add(timer);
  }

  function reportActiveError(context: ActiveContext, prefix: string, error: unknown) {
    if (sameGeneration(activeRef.current, context) && !(error instanceof DOMException && error.name === "AbortError")) {
      setLoadError(`${prefix}${String(error)}`);
    }
  }

  function chooseCase(caseId: string) {
    beginGeneration(caseId);
    setSelected(caseId);
    setRun(null);
    setTrace([]);
    setRepair(null);
    setLoadError("");
  }

  async function poll(context: ActiveContext) {
    if (!acceptsRun(activeRef.current, context)) return;
    const controller = requestController();
    try {
      const response = await fetch(`/api/runs/${context.runId}`, { signal: controller.signal });
      if (!response.ok) throw new Error("Run status unavailable");
      const next: Run = await response.json();
      if (!acceptsRun(activeRef.current, context)) return;
      if (next.id !== context.runId || next.case_id !== context.caseId) throw new Error("Run response identity mismatch");
      setRun(next);
      if (TERMINAL_VERDICTS.has(next.status)) {
        const traceController = requestController();
        try {
          const traceResponse = await fetch(`/api/runs/${context.runId}/trace`, { signal: traceController.signal });
          if (!traceResponse.ok) throw new Error("Run trace unavailable");
          const traceData = await traceResponse.json();
          if (!acceptsRun(activeRef.current, context) || traceData.run_id !== context.runId) return;
          setTrace(traceData.trace || []);
          schedule(() => { if (acceptsRun(activeRef.current, context)) resultRef.current?.focus({ preventScroll: true }); });
        } finally { releaseController(traceController); }
        return;
      }
      schedule(() => poll(context).catch((error) => reportActiveError(context, "", error)));
    } finally { releaseController(controller); }
  }

  async function start(caseId = selected) {
    const context = beginGeneration(caseId);
    setSelected(caseId); setRun(null); setTrace([]); setRepair(null); setLoadError("");
    document.getElementById("verify")?.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const controller = requestController();
      const response = await fetch(`/api/cases/${caseId}/run`, { method: "POST", signal: controller.signal });
      releaseController(controller);
      if (!response.ok) throw new Error(await response.text());
      const created: Run = await response.json();
      if (!sameGeneration(activeRef.current, context)) return;
      if (created.case_id !== caseId) throw new Error("Run response case mismatch");
      const bound = bindRun(activeRef.current, context, created.id) as ActiveContext | null;
      if (!bound) return;
      activeRef.current = bound;
      setRun(created);
      await poll(bound);
    } catch (error) {
      reportActiveError(context, "Could not start verification: ", error);
    }
  }

  async function pollRepair(context: ActiveContext) {
    if (!acceptsRepair(activeRef.current, context)) return;
    const controller = requestController();
    try {
      const response = await fetch(`/api/repairs/${context.repairId}`, { signal: controller.signal });
      const next = await decodeRepairResponse(response, context);
      if (!acceptsRepair(activeRef.current, context)) return;
      if (next.id !== context.repairId || next.run_id !== context.runId) throw new Error("Repair response identity mismatch");
      setRepair(next);
      if (["GENERATING", "APPLYING"].includes(next.status)) {
        schedule(() => pollRepair(context).catch((error) => reportActiveError(context, "", error)));
      } else {
        applyPendingRef.current = false;
        setApplyPending(false);
      }
    } finally { releaseController(controller); }
  }

  async function generateRepair() {
    const context = { ...activeRef.current };
    if (!run?.id || !acceptsRun(activeRef.current, context) || run.id !== context.runId) return;
    setLoadError("");
    try {
      const controller = requestController();
      const response = await fetch(`/api/runs/${run.id}/repair`, { method: "POST", signal: controller.signal });
      releaseController(controller);
      if (!response.ok) throw new Error(await response.text());
      const created: RepairRecord = await response.json();
      if (!acceptsRun(activeRef.current, context)) return;
      if (created.run_id !== context.runId) throw new Error("Repair response run mismatch");
      const bound = bindRepair(activeRef.current, context, created.id) as ActiveContext | null;
      if (!bound) return;
      activeRef.current = bound;
      setRepair(created);
      await pollRepair(bound);
    } catch (error) {
      reportActiveError(context, "Could not generate repair: ", error);
    }
  }

  async function applyRepair() {
    const context = { ...activeRef.current };
    if (!repair?.id || repair.id !== context.repairId ||
        !canApplyRepair(activeRef.current, context, repair.status, applyPendingRef.current)) return;
    applyPendingRef.current = true;
    setApplyPending(true);
    setLoadError("");
    try {
      const controller = requestController();
      const response = await fetch(`/api/repairs/${repair.id}/apply-and-verify`, { method: "POST", signal: controller.signal });
      releaseController(controller);
      const applying = await decodeRepairResponse(response, context);
      if (!acceptsRepair(activeRef.current, context)) return;
      if (applying.id !== context.repairId || applying.run_id !== context.runId) throw new Error("Apply response identity mismatch");
      setRepair(applying);
      if (applying.status !== PERSISTED_INTEGRITY_ERROR) await pollRepair(context);
    } catch (error) {
      if (acceptsRepair(activeRef.current, context)) {
        applyPendingRef.current = false;
        setApplyPending(false);
      }
      reportActiveError(context, "Could not apply repair: ", error);
    }
  }

  async function discardRepair() {
    const context = { ...activeRef.current };
    if (!repair?.id || !acceptsRepair(activeRef.current, context) || repair.id !== context.repairId) return;
    const controller = requestController();
    const response = await fetch(`/api/repairs/${repair.id}/discard`, { method: "POST", signal: controller.signal });
    releaseController(controller);
    if (!acceptsRepair(activeRef.current, context)) return;
    if (!response.ok) { setLoadError(`Could not discard repair: ${await response.text()}`); return; }
    const discarded: RepairRecord = await response.json();
    if (discarded.id === context.repairId && discarded.run_id === context.runId) setRepair(discarded);
  }

  const groups = ["Flagship", "Failure demo", "Engineering / negative control", "Engineering"];
  const activeEvents = new Map((run?.events || []).map((event) => [event.stage, event]));
  const repairState = repairVisualState(repair?.status || "READY");
  const providerIsLive = repair?.proposal?.provider.kind === "live_ai";

  return <main>
    <nav className="nav shell" aria-label="Primary navigation">
      <a className="brand" href="#top" aria-label="GhostChip home"><span className="mark"><i /><i /></span>GhostChip</a>
      <div className="nav-proof"><span className="pulse" /> Reviewed model <span>·</span> Real driver</div>
      <a className="nav-link" href="#model">Evidence <Icon name="arrow" /></a>
    </nav>

    <section className="hero shell" id="top">
      <div className="hero-copy">
        <p className="eyebrow">PRE-HARDWARE DRIVER VERIFICATION</p>
        <h1>Test embedded drivers<br />before the hardware <em>arrives.</em></h1>
        <p className="lede">GhostChip turns datasheet behavior into a reviewed virtual peripheral and runs real driver code against it.</p>
        <div className="hero-actions">
          <button className="button primary" onClick={() => start("humidity_x4")}>Run BME280 demo <Icon name="arrow" /></button>
          <a className="button secondary" href="#pipeline">View how it works</a>
        </div>
        <p className="hero-note"><span>WHY IT MATTERS</span> Drivers can compile successfully while still violating behavioral rules hidden in hardware datasheets.</p>
      </div>
      <div className="hero-visual" aria-label="GhostChip verification preview">
        <div className="chip-shadow" />
        <div className="chip">
          <div className="chip-label"><small>VIRTUAL PERIPHERAL</small><strong>BME280</strong><span>0x76 · I²C</span></div>
          {Array.from({ length: 6 }).map((_, index) => <i key={`l${index}`} className="pin left" style={{ top: 54 + index * 32 }} />)}
          {Array.from({ length: 6 }).map((_, index) => <i key={`r${index}`} className="pin right" style={{ top: 54 + index * 32 }} />)}
        </div>
        <div className="signal signal-a"><span>READ</span><b>0xD0</b></div>
        <div className="signal signal-b"><span>WRITE</span><b>0xF2</b></div>
        <div className="verify-stamp"><Icon name="check" /><span>REVIEWED<br />MODEL</span></div>
      </div>
    </section>

    <section className="pipeline-wrap" id="pipeline">
      <div className="shell">
        <div className="section-intro"><p className="eyebrow">THE VERIFICATION PATH</p><p>Evidence stays attached from source to result.</p></div>
        <ol className="pipeline">
          {["Datasheet", "Extract rules", "Review evidence", "Build virtual chip", "Run real driver", "Verify behavior"].map((label, index) =>
            <li key={label}><span>{String(index + 1).padStart(2, "0")}</span><strong>{label}</strong>{index < 5 && <b aria-hidden="true">→</b>}</li>)}
        </ol>
        <div className="pipeline-facts">
          <span>Bosch BME280</span><span>Official datasheet</span><span>Reviewed model</span>
          <span>Bosch SensorAPI</span><span>Source verified</span><span>Deterministic result</span>
        </div>
      </div>
    </section>

    <section className="verify shell" id="verify">
      <div className="section-heading">
        <div><p className="eyebrow">LIVE VERIFICATION</p><h2>One model. Real callbacks.<br />An evidence-backed answer.</h2></div>
        <p>Select a curated case. GhostChip recompiles trusted repository code and evaluates the actual trace—nothing here uploads or executes arbitrary code.</p>
      </div>
      <div className="workbench">
        <aside className="case-list" aria-label="Demo cases">
          <div className="case-list-head"><span>TEST CASES</span><small>{cases.length} curated</small></div>
          {groups.map((group) => {
            const groupCases = cases.filter((item) => item.group === group);
            if (!groupCases.length) return null;
            return <div className="case-group" key={group}>
              <p>{group}</p>
              {groupCases.map((item) => <button key={item.id} className={selected === item.id ? "case active" : "case"} onClick={() => chooseCase(item.id)} aria-pressed={selected === item.id}>
                <span className={`case-dot ${item.expected.toLowerCase()}`} /><span><strong>{item.label}</strong><small>{item.summary}</small>{item.unreviewed && <b>UNREVIEWED TEST MODEL</b>}</span>
              </button>)}
            </div>;
          })}
        </aside>

        <div className="run-panel">
          <header className="run-header">
            <div><p>SELECTED CASE</p><h3>{selectedCase?.label || "Loading cases…"}</h3><span>{selectedCase?.summary}</span></div>
            <button className="button primary small" onClick={() => start()} disabled={!selectedCase || run?.status === "RUNNING" || run?.status === "QUEUED"}>{run?.status === "RUNNING" ? "Running…" : "Run verification"} <Icon name="arrow" /></button>
          </header>

          <div className="progress-strip" aria-label="Verification progress">
            {stages.map(([key, label], index) => {
              const event = activeEvents.get(key);
              const active = event?.state === "running";
              const complete = event?.state === "complete";
              return <div className={`progress-step ${active ? "active" : ""} ${complete ? "complete" : ""}`} key={key} title={event?.detail}>
                <span>{complete ? <Icon name="check" /> : index + 1}</span><small>{label}</small>
              </div>;
            })}
          </div>

          {!run?.result && <div className="empty-state">
            <div className="empty-grid" /><span className="target">GC</span>
            <h4>{run ? "Verification is running" : "Ready to test the real driver"}</h4>
            <p>{run ? (run.events.at(-1)?.detail || "Starting…") : "Choose a case and run it. Completed stages appear as the backend reaches them—there are no theatrical delays."}</p>
          </div>}

          {run?.result && <div className={`result ${verdict.tone}`} ref={resultRef} tabIndex={-1} aria-live="polite">
            <div className="result-top">
              <div className="verdict"><span>{verdict.label}</span><small>{run.result.presentation?.label || selectedCase?.label}</small></div>
              <div className="result-metrics">
                <div><strong>{counts.text}</strong><span>Actual checks</span></div>
                <div><strong>{run.result.callback_count}</strong><span>Callbacks</span></div>
                <div><strong>{run.result.elapsed_ms?.toLocaleString()} ms</strong><span>Total execution</span></div>
              </div>
            </div>

            {run.result.status === "PASS" && <div className="outcome-copy">
              <h4>The chosen behavior matched the reviewed model.</h4>
              <p>The result was produced by the real compiled driver path and the explicit Scenario assertions shown below.</p>
              {apiObservation && <p className="driver-return"><strong>Actual driver result:</strong> {apiObservation[0]} = {apiObservation[1].value}</p>}
            </div>}
            {run.result.status === "FAIL" && <div className="failure-card">
              <p className="label">BEHAVIORAL FAILURE</p>
              <div className="comparison"><div><span>Expected</span><strong>{run.result.failure_explanation?.expected || "Scenario assertion satisfied"}</strong></div><i>≠</i><div><span>Observed</span><strong>{run.result.failure_explanation?.observed || "One or more assertions failed"}</strong></div></div>
              <p><strong>Cause:</strong> {run.result.failure_explanation?.cause || "The execution did not satisfy the validated Scenario."}</p>
              {run.result.failure_explanation?.translation && <blockquote>{run.result.failure_explanation.translation}</blockquote>}
              {latchEvidence && <div className="failure-source"><span>DATASHEET EVIDENCE</span><strong>Bosch BME280 · Page {latchEvidence.printed_page || latchEvidence.page} · {latchEvidence.section}</strong></div>}
            </div>}
            {run.result.status === "FAIL" && run.case_id === "buggy_driver" && <div className="repair-workflow">
              {!repair && <div className="repair-entry"><div><p className="label">BOUNDED REPAIR</p><h4>Propose a driver-only change</h4><p>GhostChip will send only this failure, its trace, the reviewed rule, bounded evidence, and the controlled driver source to the configured provider.</p></div><button className="button repair-button" onClick={generateRepair}>Generate repair <Icon name="arrow" /></button></div>}

              {repair && ["GENERATING", "APPLYING"].includes(repair.status) && <div className="repair-loading" aria-live="polite"><span className="repair-spinner" /><div><p className="label">{repair.status === "GENERATING" ? "GENERATING PROPOSAL" : "APPLYING TO DERIVED SOURCE"}</p><h4>{repair.events.at(-1)?.detail || "Validating the bounded repair workflow…"}</h4><p>{repair.status === "APPLYING" ? "GhostChip is recompiling and rerunning the identical reviewed model and Scenario." : "No proposal can modify the model, Scenario, evidence, verifier, tests, or Bosch source."}</p></div></div>}

              {repair?.status === "PROPOSED" && repair.proposal && <div className="repair-panel">
                <div className="repair-panel-head"><div><p className="label">REPAIR PROPOSAL · NOT YET VERIFIED</p><h4>One bounded source change</h4></div><span className={providerIsLive ? "provider live" : "provider local"}>{providerIsLive ? "LIVE AI PROVIDER" : "OFFLINE DEMO PROVIDER · NOT AI"}</span></div>
                <div className="repair-explain"><div><span>WHY THIS FAILED</span><p>{repair.request?.failure.summary}</p></div><div><span>WHAT THE REPAIR CHANGES</span><p>{repair.proposal.explanation}</p></div></div>
                <div className="repair-meta"><div><span>SOURCE</span><code>{repair.request?.source.path}</code></div><div><span>EVIDENCE</span><strong>Page {repair.request?.rule.evidence[0]?.printed_page || repair.request?.rule.evidence[0]?.page} · {repair.request?.rule.evidence[0]?.section}</strong></div><div><span>CHANGED LINES</span><strong>{repair.proposal.changed_lines}</strong></div></div>
                <div className="diff"><div className="diff-head"><span>UNIFIED DIFF</span><small>Validated before display</small></div><pre>{repair.proposal.unified_diff.split("\n").map((line, index) => <span className={line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "remove" : ""} key={`${index}-${line}`}>{line || " "}</span>)}</pre></div>
                <p className="preserve-note">Applying this creates a temporary repaired variant. Your original source is preserved.</p>
                <div className="repair-actions"><button className="button secondary" onClick={discardRepair} disabled={applyPending}>Discard</button><button className="button primary" onClick={applyRepair} disabled={applyPending}>{applyPending ? "Reserving…" : "Apply & verify"} <Icon name="arrow" /></button></div>
              </div>}

              {repair && ["PATCH_REJECTED", "PROPOSAL_ERROR", "COMPILE_ERROR", "VERIFICATION_FAILED", "VERIFICATION_ERROR", "EXPIRED", "INTERRUPTED", PERSISTED_INTEGRITY_ERROR].includes(repair.status) && <div className={`repair-outcome ${repairState.tone}`}><p className="label">{repairState.label}</p><h4>{repair.status === PERSISTED_INTEGRITY_ERROR ? PERSISTED_INTEGRITY_MESSAGE : repair.status === "VERIFICATION_FAILED" ? "The proposal compiled, but did not fix the behavior." : repair.status === "COMPILE_ERROR" ? "The derived driver did not compile." : ["EXPIRED", "INTERRUPTED"].includes(repair.status) ? "Generate a new repair after the server restart." : "GhostChip refused to verify this proposal."}</h4><p>{repair.status === PERSISTED_INTEGRITY_ERROR ? "GhostChip refused to display the stored verdict because its evidence is incomplete or contradictory." : repair.error || (repair.status === "VERIFICATION_FAILED" ? "The unchanged Scenario still failed after deterministic re-execution." : "The proposal did not cross every safety and execution gate.")}</p></div>}

              {repair?.status === "VERIFIED" && repair.audit && <div className="repair-verified">
                <div className="before-after"><div><span>BEFORE</span><strong>FAIL</strong><small>Effective humidity remained disabled</small></div><i>→</i><div><span>AFTER</span><strong>VERIFIED</strong><small>{repair.audit.rerun_result} on identical oracle inputs</small></div></div>
                <h4>{providerIsLive ? "The AI proposed the patch. GhostChip independently verified it." : "The offline demo provider proposed the patch. GhostChip independently verified it."}</h4>
                <p>The derived driver was recompiled and rerun against the same reviewed model and Scenario. The original source was preserved.</p>
                <details><summary>Repair audit record <span>+</span></summary><dl className="report-grid"><div><dt>Original source</dt><dd><Hash value={repair.audit.original_source_sha256} /></dd></div><div><dt>Derived source</dt><dd><Hash value={repair.audit.resulting_source_sha256} /></dd></div><div><dt>Executable</dt><dd><Hash value={repair.audit.executable_sha256} /></dd></div><div><dt>Scenario</dt><dd><Hash value={repair.audit.scenario_sha256} /></dd></div><div><dt>Identity checks</dt><dd>{Object.values(repair.audit.identity_checks).every(Boolean) ? "ALL MATCH" : "MISMATCH"}</dd></div><div><dt>Original preserved</dt><dd>{repair.audit.original_source_preserved ? "YES" : "NO"}</dd></div></dl></details>
              </div>}

              {repair?.status === "DISCARDED" && <div className="repair-outcome neutral"><p className="label">DISCARDED</p><h4>No repair was applied.</h4><p>The original source remains unchanged.</p></div>}
            </div>}
            {run.result.status === "ERROR" && <div className="error-card"><p className="label">EXECUTION ERROR — NOT A DRIVER FAILURE</p><h4>GhostChip could not produce a verdict.</h4><p>{run.result.error || "The runner returned malformed or incomplete output."}</p></div>}

            <div className="assertions">
              <div className="subhead"><span>SCENARIO ASSERTIONS</span><small>Values are copied from the backend result</small></div>
              {run.result.assertions.length ? run.result.assertions.map((item, index) => <div className="assertion" key={String(item.id || index)}>
                <span className={item.passed ? "assert-pass" : "assert-fail"}>{item.passed ? <Icon name="check" /> : "×"}</span>
                <div><strong>{String(item.id || "assertion").replaceAll("_", " ")}</strong><small>{String(item.basis || "Validated Scenario assertion")}</small></div>
                <code>{String(item.actual)} / {String(item.equals)}</code>
              </div>) : <p className="muted pad">No assertion list was produced.</p>}
            </div>
            <details className="result-report"><summary>Expandable technical report <span>+</span></summary><dl className="report-grid">
              <div><dt>Model origin</dt><dd>{run.result.model_origin || "not reported"}</dd></div>
              <div><dt>Reviewed model</dt><dd><Hash value={run.result.review_bundle?.executable_spec_sha256} /></dd></div>
              <div><dt>Upstream commit</dt><dd><code>{String(run.result.source_identity?.upstream_commit || "trusted fixture")}</code></dd></div>
              <div><dt>Executable</dt><dd><Hash value={String(run.result.source_identity?.executable_sha256 || "")} /></dd></div>
            </dl></details>
          </div>}
        </div>
      </div>

      {trace.length > 0 && <div className="trace-section">
        <div className="section-heading compact"><div><p className="eyebrow">ACTUAL CALLBACK PATH</p><h2>Driver trace</h2></div><p>These operations came from the compiled callback protocol. Friendly labels are presentation metadata; addresses and lengths are the recorded values.</p></div>
        <div className="trace-table" role="table" aria-label="Real driver callback trace">
          <div className="trace-row trace-head" role="row"><span>#</span><span>Operation</span><span>Register</span><span>Transfer</span><span>Status</span></div>
          {trace.map((row) => <div className="trace-row" role="row" key={`${row.seq}-${row.operation}-${row.register_hex || row.duration_us}`}>
            <span className="seq">{String(row.seq).padStart(2, "0")}</span>
            <span><b className={`op ${row.operation.toLowerCase()}`}>{row.operation}</b></span>
            <span><strong>{row.label}</strong><code>{row.register_hex || "logical clock"}</code></span>
            <span>{row.duration_us ? `${row.duration_us.toLocaleString()} μs` : `${row.length || 1} byte${(row.length || 1) === 1 ? "" : "s"}`}</span>
            <span className={row.status === 0 || row.status === "OK" ? "status-ok" : "status-bad"}>{row.status === 0 || row.status === "OK" ? "OK" : String(row.status)}</span>
          </div>)}
        </div>
      </div>}
    </section>

    {device && <>
      <section className="model-section" id="model">
        <div className="shell">
          <div className="section-heading light"><div><p className="eyebrow">THE MODEL IS REVIEWED, NOT ASSUMED</p><h2>Datasheet behavior,<br />made executable.</h2></div><p>GhostChip exposes the bounded slice it can defend—and the things it deliberately does not simulate.</p></div>
          <div className="model-grid">
            <div className="device-card">
              <div className="device-card-top"><span className="device-monogram">BME</span><div><small>DEVICE</small><h3>{device.name}</h3><p>{device.vendor}</p></div><b>REVIEWED</b></div>
              <div className="stat-grid"><div><span>BUS / PROFILE</span><strong>{device.bus}</strong><small>{device.profile}</small></div><div><span>MODELED REGISTERS</span><strong>{device.register_count}</strong></div><div><span>BEHAVIORAL RULES</span><strong>{device.rule_count}</strong></div><div><span>SOURCE</span><strong>{device.source_status}</strong></div></div>
              <p className="scope">{device.scope}</p>
              <details><summary>Explicit model limitations <span>+</span></summary><ul>{device.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
              <details><summary>View DeviceSpec identity <span>+</span></summary><dl className="identity-list">{Object.entries(device.bundle_identity).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><Hash value={value} /></dd></div>)}</dl></details>
            </div>
            <div className="rules">
              <div className="rules-head"><span>REVIEWED BEHAVIOR</span><small>{device.rules.length} active rules</small></div>
              {device.rules.map((rule, index) => <article className="rule-card" key={rule.id}>
                <span className="rule-index">R{String(index + 1).padStart(2, "0")}</span><div><h3>{rule.title}</h3><p>{rule.plain_english}</p><div className="evidence-line"><b>{rule.status}</b><span>{rule.evidence[0]?.source.replaceAll("_", " ")}</span><span>Page {rule.evidence[0]?.printed_page || rule.evidence[0]?.page}</span><span>{rule.evidence[0]?.section}</span></div></div>
                <details><summary>Evidence</summary>{rule.evidence.map((item) => <p key={`${item.page}-${item.section}`} className="evidence-copy">{item.summary}</p>)}</details>
              </article>)}
            </div>
          </div>
        </div>
      </section>

      <section className="identity-section shell">
        <div className="identity-copy"><p className="eyebrow">REAL DRIVER IDENTITY</p><h2>Not written for the demo.</h2><p>GhostChip is running Bosch's real driver implementation, not a driver written specifically for this demonstration.</p></div>
        <div className="driver-card">
          <div className="driver-title"><span>BS</span><div><small>REAL DRIVER</small><h3>{device.driver.name}</h3></div><b><Icon name="check" /> VERIFIED</b></div>
          <dl><div><dt>Upstream core</dt><dd>{device.driver.core}</dd></div><div><dt>Commit</dt><dd><code>{device.driver.commit.slice(0, 10)}</code></dd></div><div><dt>License</dt><dd>{device.driver.license}</dd></div><div><dt>Source integrity</dt><dd className="verified">{device.driver.source_integrity}</dd></div></dl>
          <details><summary>Show pinned file hashes <span>+</span></summary><dl className="identity-list">{Object.entries(device.driver.hashes).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><Hash value={value} /></dd></div>)}</dl></details>
        </div>
      </section>

      <section className="generalization">
        <div className="shell general-grid">
          <div><p className="eyebrow">LIMITED GENERALIZATION</p><h2>A different device.<br />Different semantics.<br />The same core.</h2><p>The ADXL345 proof exercises read side-effects, selective interrupt clearing, and FIFO mode state. The generic verifier contains no ADXL345 branch.</p><p className="boundary"><strong>Honest boundary:</strong> extraction uses a device-document-specific source adapter.</p></div>
          <div className="adxl-card"><div className="adxl-head"><span>AD</span><div><small>SECOND DEVICE</small><h3>ADXL345 accelerometer</h3><p>Analog Devices · Reviewed slice</p></div></div><div className="pair"><div className="pair-fail"><span>BUGGY</span><strong>FAIL</strong><small>Interrupt consumed too early</small></div><b>→</b><div className="pair-pass"><span>FIXED</span><strong>PASS</strong><small>First read cached</small></div></div><p className="static-note">Verified Stage 3 regression evidence. Run the generalization case for a fresh execution.</p><button className="button dark" onClick={() => start("adxl345_regression")}>Run ADXL regression <Icon name="arrow" /></button></div>
        </div>
      </section>

      <section className="boundary-section shell">
        <div className="section-heading"><div><p className="eyebrow">HOW AUTOMATIC IS THIS?</p><h2>Automation where it is deterministic.<br />Review where judgment matters.</h2></div></div>
        <div className="boundary-grid"><div><h3><span>A</span> Automatic</h3><ul>{device.automation.automatic.map((item) => <li key={item}><Icon name="check" />{item}</li>)}</ul></div><div><h3><span>R</span> Reviewed / manual</h3><ul>{device.automation.reviewed_manual.map((item) => <li key={item}>{item}</li>)}</ul></div></div>
        <p className="claim">GhostChip currently supports reviewed slices of register-based peripherals. It does not claim arbitrary datasheet understanding or silicon equivalence.</p>
      </section>
    </>}

    {loadError && <div className="toast" role="alert"><strong>ERROR</strong>{loadError}</div>}
    <footer><div className="shell"><div className="brand"><span className="mark"><i /><i /></span>GhostChip</div><p>Test embedded drivers before the hardware arrives.</p><span>Stage 6 · Repair proof</span></div></footer>
  </main>;
}

export default App;

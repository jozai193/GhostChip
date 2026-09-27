"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { assertionSummary, TERMINAL_VERDICTS, visualVerdict } from "../lib/verdict.mjs";

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
  const [loadError, setLoadError] = useState("");
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/cases").then((r) => { if (!r.ok) throw new Error("Case catalog unavailable"); return r.json(); }),
      fetch("/api/devices/bme280").then((r) => { if (!r.ok) throw new Error("Reviewed device unavailable"); return r.json(); }),
    ]).then(([caseData, deviceData]) => { setCases(caseData.cases); setDevice(deviceData); })
      .catch((error) => setLoadError(String(error)));
  }, []);

  const selectedCase = useMemo(() => cases.find((item) => item.id === selected), [cases, selected]);
  const verdict = visualVerdict(run?.result?.status || run?.status || "READY");
  const counts = assertionSummary(run?.result);
  const apiObservation = run?.result ? Object.entries(run.result.observations || {}).filter(([key]) => key.startsWith("api.")).at(-1) : undefined;
  const latchEvidence = device?.rules.find((rule) => rule.id === "humidity_latch")?.evidence[0];

  function chooseCase(caseId: string) {
    setSelected(caseId);
    setRun(null);
    setTrace([]);
    setLoadError("");
  }

  async function poll(runId: string) {
    const response = await fetch(`/api/runs/${runId}`);
    if (!response.ok) throw new Error("Run status unavailable");
    const next: Run = await response.json();
    setRun(next);
    if (TERMINAL_VERDICTS.has(next.status)) {
      const traceResponse = await fetch(`/api/runs/${runId}/trace`);
      const traceData = await traceResponse.json();
      setTrace(traceData.trace || []);
      window.setTimeout(() => resultRef.current?.focus({ preventScroll: true }), 0);
      return;
    }
    window.setTimeout(() => poll(runId).catch((error) => setLoadError(String(error))), 180);
  }

  async function start(caseId = selected) {
    setSelected(caseId); setRun(null); setTrace([]); setLoadError("");
    document.getElementById("verify")?.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const response = await fetch(`/api/cases/${caseId}/run`, { method: "POST" });
      if (!response.ok) throw new Error(await response.text());
      const created: Run = await response.json();
      setRun(created);
      await poll(created.id);
    } catch (error) {
      setLoadError(`Could not start verification: ${String(error)}`);
    }
  }

  const groups = ["Flagship", "Failure demo", "Engineering / negative control", "Engineering"];
  const activeEvents = new Map((run?.events || []).map((event) => [event.stage, event]));

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
    <footer><div className="shell"><div className="brand"><span className="mark"><i /><i /></span>GhostChip</div><p>Test embedded drivers before the hardware arrives.</p><span>Stage 5 · Judge demo</span></div></footer>
  </main>;
}

export default App;

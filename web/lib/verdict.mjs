export const TERMINAL_VERDICTS = new Set(["PASS", "FAIL", "ERROR"]);

export function visualVerdict(status) {
  if (status === "PASS") return { label: "VERIFIED", tone: "pass" };
  if (status === "FAIL") return { label: "FAIL", tone: "fail" };
  if (status === "ERROR") return { label: "ERROR", tone: "error" };
  return { label: status === "RUNNING" ? "RUNNING" : "READY", tone: "pending" };
}

export function assertionSummary(result) {
  const total = Number(result?.assertion_total || 0);
  const passed = Number(result?.assertion_passed || 0);
  return { total, passed, text: `${passed}/${total} scenario assertions` };
}

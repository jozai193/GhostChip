export const TERMINAL_VERDICTS = new Set(["PASS", "FAIL", "ERROR"]);
export const PERSISTED_INTEGRITY_MESSAGE = "Stored verification record failed integrity checks.";

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

export function repairVisualState(status) {
  if (status === "VERIFIED") return { label: "VERIFIED REPAIR", tone: "pass" };
  if (status === "PERSISTED_RECORD_INTEGRITY_ERROR") return { label: "ERROR", tone: "error" };
  if (status === "VERIFICATION_FAILED") return { label: "VERIFICATION FAILED", tone: "fail" };
  if (status === "COMPILE_ERROR") return { label: "COMPILE ERROR", tone: "error" };
  if (status === "PATCH_REJECTED") return { label: "PATCH REJECTED", tone: "error" };
  if (status === "PROPOSAL_ERROR") return { label: "PROPOSAL ERROR", tone: "error" };
  if (status === "VERIFICATION_ERROR") return { label: "VERIFICATION ERROR", tone: "error" };
  if (status === "EXPIRED") return { label: "RESTART REQUIRED", tone: "error" };
  if (status === "INTERRUPTED") return { label: "VERIFICATION INTERRUPTED", tone: "error" };
  return { label: status, tone: "pending" };
}

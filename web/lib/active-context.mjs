export function nextGeneration(previous, caseId) {
  return Object.freeze({
    generation: Number(previous?.generation || 0) + 1,
    caseId,
    runId: null,
    repairId: null,
  });
}

export function sameGeneration(active, candidate) {
  return Boolean(active && candidate &&
    active.generation === candidate.generation &&
    active.caseId === candidate.caseId);
}

export function acceptsRun(active, candidate) {
  return sameGeneration(active, candidate) && Boolean(candidate.runId) &&
    active.runId === candidate.runId;
}

export function acceptsRepair(active, candidate) {
  return acceptsRun(active, candidate) && Boolean(candidate.repairId) &&
    active.repairId === candidate.repairId;
}

export function bindRun(active, generationContext, runId) {
  if (!sameGeneration(active, generationContext) || active.runId !== null) return null;
  return Object.freeze({ ...active, runId, repairId: null });
}

export function bindRepair(active, runContext, repairId) {
  if (!acceptsRun(active, runContext) || active.repairId !== null) return null;
  return Object.freeze({ ...active, repairId });
}

export function canApplyRepair(active, candidate, status, requestPending) {
  return status === "PROPOSED" && !requestPending && acceptsRepair(active, candidate);
}

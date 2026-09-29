# GhostChip Stage 3 independent audit

Audit date: 2026-09-28 IST. Audited commit: `8f852784fba00d9c2cefa64d8bf525e3e8b2a77c`.

**Verdict: PASS WITH QUALIFICATION for the deterministic execution architecture; not an unconditional readiness approval. Fix the execution-time review-integrity gap before integrating the real driver.** The existing proofs are reproducible and causal. They establish a reusable interpreter, not general datasheet comprehension. Keep frontend and AI repair deferred.

This checkpoint changes no production code, existing fixtures, upstream driver, or architecture. It adds this report and the [Stage 4 handoff](stage4-sol-high-plan.md). Disposable research, source downloads, object compilation and adversarial checks are under ignored `artifacts/stage3-audit/`. Stage 4 has not been implemented.

## Inspection and history limits

Read the complete locally supplied master brief (SHA-256 `2ad257c3938fc7429da8e90fdd74dc35e14c6d44a96563bed2575db865a4b802`), all then-current architecture/extraction/DeviceSpec/scope/risk/planning/verification/generalization/build-log documents, the schema, Python modules, C fixtures/HAL, request/review/golden/scenario fixtures, test modules, and the clean-reproduction script. The master brief's broad implementation instructions were background; the audit-only limit governed this historical checkpoint.

The initial working tree was clean. `git rev-list --all --count` returned **1**, the repository is not shallow, and both reflogs identify `8f85278` as the initial commit. Its root diff contains all 41 files / 3,307 added lines. **There is no committed Stage 2 baseline or parent diff to inspect.** The prior Stage 3 request describes a 26-test baseline, but that is not a recoverable Git baseline. Claims that particular files or schema bytes were unchanged from Stage 2 cannot be independently certified from this history. The current runtime's generic behavior can be certified directly.

There is no standalone Scenario schema. Its effective contract is the trusted fixture JSON, `Peripheral.stimulate`, and `run_fixture` in `ghostchip/proof.py`, plus the prose in `docs/devicespec-v1.md`. This is a limit to fix before expanding inputs, not evidence that the existing fixtures fail.

## Reproduced results

| Execution | Observed result |
|---|---|
| README's WSL system `python3 -m unittest discover -s tests -v` | 39 methods ran; 37 passed, 2 PDF integration tests errored because system Python lacks `pypdf` |
| Existing project `.venv-wsl/bin/python -m unittest discover -s tests -v` | **39/39 passed**, no skips, 15.620 seconds |
| Existing `scripts/verify_clean.py`, using that virtual environment | **36 passed, 3 expected local-PDF skips**; default C proof FAIL/PASS |
| Separate reconstruction of every committed file using `git ls-tree` + `git show 8f85278:path` into `/tmp` | **36 passed, 3 expected skips**, 7.637 seconds; default C proof FAIL/PASS |
| Fresh full-PDF ingestion, extraction and review for both devices | Both candidate hashes exactly match their checked-in golden/review hashes |
| Unmodified pinned Bosch `bme280.c`, object-only host compile | GCC C11, `-Wall -Wextra -Werror -O0`: success; no integration performed |

The exact-commit reconstruction excludes **all** untracked/ignored files, virtual environments, PDFs and prior run outputs. It reuses installed dependencies and the host compiler; this is not a fresh OS/toolchain install. Each `run_fixture` compilation creates a new temporary executable. No old executable or generated DeviceSpec is needed to make the committed tests pass. Verified environment: Python 3.12.3, GCC 13.3.0, jsonschema 4.10.3, pypdf 6.1.1 and cryptography 50.0.1.

Fresh real-PDF runs (not a load of old generated output):

| Model / C fixture | Result | Assertions | C exit | Bus events | Causal observation |
|---|---|---:|---:|---:|---|
| Extracted BME280 buggy | FAIL | 1/2 | 0 | 4 | Pending humidity 3, effective 0 |
| Extracted BME280 fixed | PASS | 2/2 | 0 | 4 | Pending and effective humidity 3 |
| Extracted ADXL345 buggy | FAIL | 1/2 | 2 | 3 | Logging read consumes tap; second read lacks it |
| Extracted ADXL345 fixed | PASS | 2/2 | 0 | 2 | First read cached; FIFO assertion passes |

BME280 candidate hash: `5fe6b9f5cdb727dca13ca6a3831e52057ead996dc5cf1bbaaf2194c49a896731`.
ADXL345 candidate hash: `5700e02cd260997e5a498fa66950c5b2a3e852f3e6c64940a25df6cb4c757e74`.

Fresh traces: `artifacts/stage3-audit/bme280-fresh-proof.json` and `adxl345-fresh-proof.json`. Additional findings and clean-source log tails are in `audit-results.json`; full clean logs are `git-clean-suite.log` and `git-clean-proof.log`. Reproduce the disposable checks with:

```powershell
wsl -d Ubuntu --cd '/mnt/e/LovHack season 3 hackathon' --exec .venv-wsl/bin/python artifacts/stage3-audit/audit_checks.py
```

The audit script is ignored research material, not part of the committed test suite. The report preserves its relevant observations independently.

## Findings that matter before Stage 4

### F1 — High: accepted model files can change semantics without renewed review

`accept_review` in `ghostchip/extraction.py:360` correctly rejects a changed **pending** candidate against the old manifest. However, `Peripheral.__init__` in `ghostchip/runtime.py:12` only checks the embedded evidence-status strings. `run_fixture` at `ghostchip/proof.py:84` accepts that dict, and the CLI loads an arbitrary `--spec` without requiring its candidate/review artifacts. `model_origin` at line 91 is inferred from self-declared evidence origins.

Reproduction: extract the real BME280 PDF, apply the checked-in review, then change only `rules[0].on.register` from `ctrl_meas` to `ctrl_hum` in the accepted dict. The unchanged buggy C driver now reports **PASS**, still labeled `automatic_extraction_reviewed`. Reapplying the old review to the equivalently changed pending candidate correctly raises `ReviewError`.

This is a trust-boundary defect, not a SHA-256 collision. Recorded run hashes describe the altered model but do not prove that its current semantics were approved. Even an accidental edit has this effect. The existing negative-control tests intentionally mutate accepted models and therefore also demonstrate why unit-test convenience must not be confused with verified execution.

Required correction: verify the candidate, review and exact resulting executable spec together at the runner boundary; retain raw interpreter access for explicitly synthetic unit tests. Label research mutations as unreviewed experimental models. Bind page anchors and extraction-request identity in the reviewed bundle as well: these are currently separate files, outside the candidate hash. Cryptographic signatures are unnecessary for the trusted local workflow; editable files must simply not masquerade as a previously validated bundle.

### F2 — Medium: missing required ADXL overview evidence crashes extraction

`ghostchip/adxl345_extraction.py:183-209` searches for the page 19 overview but tests only `int_match` before dereferencing `int_general_page`. Removing page 19 text from the golden document while retaining page 27 produces:

```text
AttributeError: 'NoneType' object has no attribute 'pdf_page'
```

This fails closed rather than inventing a rule, but contradicts `docs/extraction.md`'s claim that every missing required phrase becomes an explicit unresolved record. The current tests remove the page 27 rule sentence and FIFO-clear sentence; neither covers a missing overview. Require both interrupt evidence matches and add this regression.

### F3 — Medium: the FIFO proof starts in an impossible declared state

`fixtures/adxl345/scenario.json` seeds `fifo_entries=5`, while the extracted `FIFO_CTL` reset is 0 (bypass). The pinned ADXL345 page 21 says FIFO remains empty in bypass. Thus the current compiled fixture proves clearing an injected state on a bypass write, but does not represent a physically consistent entry into bypass from a populated FIFO.

A disposable correction adds pre-run `fifo_mode=1`, leaving occupancy five. The buggy/fixed results remain **FAIL/PASS**. With that corrected initial state, removing only the interrupt rule makes the buggy fixture **PASS**; removing only the FIFO rule makes the fixed fixture **FAIL**, occupancy five. Fix the checked-in scenario and relevant setup tests; no runtime redesign is needed. Scenario review must check cross-field consistency, not just integer widths.

### F4 — Qualification: the extractors contain programmed semantic knowledge

The ADXL adapter explicitly accepts only `int_source` and `fifo_ctl` (`:129`); matches fixed register addresses and bit-label layouts; programs the interrupt exception set (`:191`); programs FIFO mode guard zero, occupancy width six and reset zero. Its field parser's comment references a singular Trigger Bit heading without actually requiring that heading. The six-bit occupancy representation is an author-selected abstraction, not a derived capacity analysis.

These choices are transparent outside the interpreter, and matching evidence is genuinely required. They are more than a neutral PDF layout adapter: they are **device-specific, evidence-gated semantic templates**. The code does not discover a new behavior category from arbitrary prose. Candidate confidence numbers are fixed annotations, not calibrated measurements.

### Other bounded limitations

- The verifier contains BME280 default fixture selection (`proof.py`), despite documentation saying there are no BME280 identifiers in it. This is visible CLI convenience, not hidden device behavior or a hard-coded verdict. Describe that distinction accurately.
- The runner always returns bus callback status zero for supported transactions; OUT_OF_MODEL kills the run. A real injected communication failure does not exist yet and must remain distinct from coverage errors.
- `process_exit` scenarios are trusted and can omit a driver-exit assertion. Malformed Scenario references can escape as uncaught lookup errors. Add explicit validation before accepting expanded scenario/result/fault inputs.
- `extract.py` writes into reusable paths; failed review can leave an older reviewed output beside newer candidate files. Current clean-source proofs do not depend on this, but Stage 4 should use atomic, content-addressed reviewed bundles and never infer freshness from file existence.
- Current manifests omit the proof-runner hash, compiler identity/command, dependency closure and resulting executable hash. This is insufficient for the requested multi-source upstream integrity proof.
- Some build-log/verification prose still says no commit was created. It predates the initial commit and should be dated/corrected, not treated as current repository status.

## Adversarial claims A–J

| Claim | Grade | Evidence and limit |
|---|---|---|
| A. Generic runtime has no hidden BME280/ADXL behavior | **PASS** | Direct inspection of validator/schema/runtime: generic references, guards and assignments; no device dispatch. Default fixture choice in `proof.py` is not behavior. |
| B. Behavior lives in DeviceSpec, not Scenario | **PASS WITH QUALIFICATION** | Latch, read-clear and FIFO clear are rule data; Scenario contains initial state and observations. FIFO setup needs F3 correction. |
| C. Scenario intent is independent | **PASS WITH QUALIFICATION** | No Scenario imports into extraction/runtime transitions; verdicts compare actual execution with separately authored requests. Shared state names are legitimate interfaces. Independence of authorship/oracle truth is not established, and FIFO assertions partly test the model itself. |
| D. Rule removal changes execution causally | **PASS** | Removed interrupt rule restores tap on the second read and changes exit 2 to 0; removed FIFO rule leaves occupancy five. Existing BME280 rule-removal test denies fixed PASS. Corrected FIFO setup preserves both negative controls. |
| E. Review hashes prevent stale review authorizing changed semantics | **FAIL** | Correct at `accept_review`; bypassed when a changed accepted spec is passed to execution. F1 makes buggy BME280 falsely PASS. |
| F. Golden pages do not bypass extraction | **PASS** | Golden page text calls the same `extract_candidate`. Fresh original-PDF parsing yields identical candidate hashes for both devices; exact-commit tests need no generated spec. Golden tests alone do not authenticate source bytes. |
| G. Two devices demonstrate semantic generalization | **PASS WITH QUALIFICATION** | One event language handles write latch, selective read effects and guarded state clear. Extraction remains two separately programmed adapters; learned or arbitrary-PDF generalization is unproved. Historical unchanged-schema claim lacks a Stage 2 commit. |
| H. Third device in supported semantic categories needs no runtime source change | **PASS WITH QUALIFICATION** | A relocated/renamed synthetic ADXL-shaped model at address 42/registers 16–17 returned 66 then 2 and cleared renamed occupancy to zero. It exercises existing byte/guard/effect categories; it is not a third real datasheet validation. |
| I. Automation is not overstated | **PASS WITH QUALIFICATION** | README explicitly disclaims arbitrary extraction, AI repair and vendor SDK support. Tighten “layout adapter,” occupancy inference, execution-time review, missing-evidence handling and generic-verifier wording per F1–F4. |
| J. No truthful judge criticism resembling “two hard-coded emulators wrapped in PDF parsing” | **FAIL as an absolute claim** | Two distinct execution emulators would be inaccurate: there is one interpreter, and deleting source/rule data matters. But a judge can fairly criticize the hand-programmed device semantic templates and lack of arbitrary extraction. Stage 4 addresses curated drivers, not this extraction-breadth criticism. |

## Next risk and decision

The immediate risk is **false confidence from a model whose accepted labels outlive its approved semantics**. Repair F1 first, along with F2/F3 and their focused regressions. This is a small correctness gate, not a reason to replace the interpreter.

After that, real external driver integration is the right next milestone. It tests the actual unproven boundary: authentic API control flow, callback buffers, reset/startup assumptions, communication errors and build/source identity. General extraction and independent physical/model fidelity remain larger product risks, but broadening extraction before verifying that a real driver fits would compound uncertainty.

Bosch SensorAPI is preferred over Adafruit after inspecting both sources, not simply because the earlier documents suggest it. The [implementation handoff](stage4-sol-high-plan.md) contains the criteria comparison, immutable source pin, exact file hashes, required model/transport additions, acceptance matrix and stop conditions.

**Frontend remains deferred through the correctness repair and Stage 4 acceptance gate.** A frontend would make the existing demonstrations easier to view without resolving these credibility issues.

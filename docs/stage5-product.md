# Stage 5 judge product and API truth boundary

Stage 5 turns the verified Stage 4 engine into a two-to-three-minute local product demonstration. It does not expand modeled hardware behavior.

## Stack and start path

- Frontend: Next.js 16.3.6 static export, React 19.3.0, TypeScript 7.0.2, hand-authored responsive CSS.
- Backend: FastAPI 0.119.0 and Uvicorn 0.37.0 importing the existing Python engine.
- Execution: Ubuntu WSL, Python 3.12 and GCC 13; every curated C run still compiles in a fresh temporary directory.
- Persistence: in-memory active run registry plus ignored JSON results under `artifacts/demo-runs/`.
- Start: `powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1`.

The static export and API share `http://localhost:8765`. The browser performs no live internet request. The Windows launcher streams a source-only snapshot into a unique WSL `/tmp/ghostchip-demo-runtime-*` directory before starting Python/GCC, so the live demo does not depend on sustained Python I/O through WSL's mounted-drive bridge.

## API

| Method | Route | Source of truth |
|---|---|---|
| GET | `/api/health` | Process readiness and explicit no-remote-execution flag |
| GET | `/api/devices` | Reconstructed reviewed BME280 and ADXL345 artifacts |
| GET | `/api/devices/{id}` | Reviewed spec/review/bundle and pinned upstream manifest |
| GET | `/api/devices/{id}/rules` | Active rules and their accepted evidence |
| GET | `/api/cases` | Curated presentation metadata; expected outcomes are labels, not verdicts |
| POST | `/api/cases/{id}/run` | Allowlists a repository-owned case and launches the real runner |
| GET | `/api/runs/{id}` | Actual engine result summarized without changing its verdict |
| GET | `/api/runs/{id}/trace` | Recorded callbacks or runtime trace with presentation labels |
| GET | `/api/runs/{id}/evidence` | Violation evidence plus actual review/build identity |

There is no request body for source code, compiler options, paths, commands, DeviceSpecs, Scenarios, FaultPlans, or URLs. This is intentionally not arbitrary remote code execution.

## Truth rules

1. `PASS`, `FAIL`, and `ERROR` are copied from the engine. Unknown/malformed statuses become `ERROR`.
2. Assertion counts, callback counts, elapsed time, observations, hashes, compiler identity and evidence are serialized from the completed result.
3. Friendly trace register labels and plain-language rule/failure explanations are presentation metadata. They never affect execution.
4. The ADXL overview card is labeled as static verified regression explanation. Its button performs a fresh two-driver backend execution.
5. The no-latch case remains under **Engineering / negative control** and says **UNREVIEWED TEST MODEL** in both catalog data and UI.
6. Active runs report only stages actually reached by backend callbacks. The frontend adds no artificial waits.

## Implemented screens/states

- Sparse landing: problem, mechanism, value and `RUN BME280 DEMO` CTA.
- Six-step pipeline and real metadata strip.
- Curated test explorer with flagship, failure and engineering groups.
- Live progress, PASS/VERIFIED, behavioral FAIL and execution ERROR treatments.
- Actual callback trace with register labels and raw addresses/lengths.
- Reviewed device/model card, behavioral-rule evidence cards and expandable limitations/identity.
- Prominent pristine Bosch SensorAPI identity card.
- Concise ADXL345 generalization section and fresh-run action.
- Automatic versus reviewed/manual boundary section.

Keyboard focus states, semantic buttons/headings/details, textual status labels, contrast and reduced-motion support are included. Essential result meaning is never color-only.

## Limitations

The product supports only repository-owned curated demonstrations. It has no user upload flow, server isolation for untrusted code, PDF upload wizard, accounts, hosted persistence, measurements, compensation math, silicon timing model, or AI repair. Physical/reference fidelity remains an open independent gate.

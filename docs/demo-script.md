# GhostChip 2:30 demo script

## 0:00–0:15 — the problem

Open the landing screen.

> Drivers can compile while still violating behavioral rules hidden in datasheets. GhostChip tests those rules before the hardware arrives.

## 0:15–0:35 — evidence and identity

Show the BME280 model card: the reviewed humidity-latch rule, datasheet pages 27–28, bounded coverage, and model hash. Briefly show Bosch's pristine source identity.

> This is a reviewed behavioral rule and a pinned source identity—not a claim that the whole chip has been modeled.

## 0:35–0:55 — run the buggy driver

Choose **Original buggy driver** and run it. Name the four real register operations as they appear.

## 0:55–1:15 — deterministic FAIL

> The driver requested humidity x4 and read the register back successfully. But the setting becomes effective only after a later `ctrl_meas` write. That write is missing, so GhostChip reports FAIL—not a compiler error.

Point to expected 3, observed 0, the failed assertion, callback/register trace, and cited rule.

## 1:15–1:35 — generate and inspect

Click **Generate repair**. Show the provider badge, explanation, target file, evidence, and two-line ordering diff.

> This proposal came from the offline demo provider, not AI. The provider interface supports replacement, but no proposal is trusted as correct.

## 1:35–1:55 — approve and verify

Read the preservation notice, then click **Apply & verify**.

> GhostChip applies this only to a derived source artifact, recompiles it, and reruns the same reviewed model and Scenario. The original source is preserved.

## 1:55–2:10 — VERIFIED

Show BEFORE FAIL → AFTER VERIFIED, then open the audit details to show matching identities and distinct source/executable hashes.

> The provider proposed the patch. GhostChip independently verified it by recompiling and rerunning the driver against the same reviewed model.

## 2:10–2:20 — breadth, briefly

Point to the pristine Bosch real-driver evidence and the ADXL345 second-device card. Do not run either.

## 2:20–2:30 — close

> GhostChip lets firmware teams test the chip before the chip arrives.

## Recording fallback

Prepare the machine with the start command and run `python -m ghostchip.demo --check --smoke` before recording. It exercises the complete repair path. Keep a prerecorded local capture available because the Windows Node/WSL Python/GCC split is the main operational demo risk. Do not substitute a canned result inside the product.

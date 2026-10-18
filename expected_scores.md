# Expected Scores on Hidden Test Set
**Timestamp:** 2026-10-18T23:05:00+05:30  
**Baseline Model:** Multi-Engine Extractor (RapidOCR local ONNX fallback + Vision LLM cache) & Safety-Filtered Decision Engine  
**Evaluation Protocol:** Time-based train split (Dev: 167 claims up to 2026-07-02; Holdout: 116 claims from 2026-07-03 to 2026-07-18).

---

## 1. Projected Performance by Field on Hidden Test Set

These projections are documented **before** generating the final `predictions.csv`. They reflect measured holdout performance adjusted for distribution shift and human clerk ground-truth label noise.

| Field | Measured Holdout (Exact) | Measured Holdout (Lenient) | Expected Test Score Range | Point Estimate (Expected) | Shrinkage & Estimation Rationale |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Vendor** | 88.8% | 89.7% | **85.0% – 91.0%** | **88.0%** | Test set introduces 34 new vendor name variations (e.g. `Coffee Cafe Corner`, `Hotel Shirdi Sai Palace Lodge`). Fuzzy token matching recovers known variations, but novel locations cause ~2% shrinkage. Clerk label typos in train (~5%) indicate that test labels also contain clerk typos. |
| **Receipt Date** | 95.7% | 96.6% | **93.0% – 97.0%** | **95.0%** | Extremely consistent extraction across all categories. Main error mode is concatenated timestamps (e.g., `22/06/202613:30`) and faded ink on old fuel receipts. Expected to remain high (~95%). |
| **Receipt Number** | 71.6% | 72.4% | **68.0% – 75.0%** | **71.0%** | Preserves leading zeros (e.g. `003203`). Challenged by faded thermal print on IndianOil/HPCL fuel slips and multi-line boxes where numbers are offset from keywords. |
| **GSTIN** | 85.3% | 89.7% | **83.0% – 90.0%** | **86.5%** | Mod-36 checksum validation filters OCR noise and repairs common character confusions (e.g. `O` vs `0`, `I` vs `1`). However, non-GST bills (Dhabas, parking, local cabs) legitimately have blank GSTINs. |
| **Total Amount** | 70.7% | 73.3% | **68.0% – 75.0%** | **71.5%** | Two-pass bottom-up window search prioritizes grand total over subtotal/taxes. In train, clerks made typos in ~3.2% of amounts (e.g. typing 240 instead of 250 in `CLM-30421`), which artificially depresses measured exact match against human labels. |
| **Decision** | 97.5% Precision | 75.0% Overall | **94.0% – 98.0% Precision** | **96.0% Precision** | **32.0% – 38.0% Auto-Approval Rate**. Prioritizes zero financial leakage over raw auto-approval volume. The 25x–200x cost asymmetry between leakage vs. clerk review mandates conservative gating. |

---

## 2. Estimation Methodology & Shrinkage Breakdown

1. **Clerk Label Noise Floor:**  
   Our forensic deep dive in Phase 0 proved that human finance clerks made substantial transcription errors:
   - 14 vendor typos (~5.0%)
   - 9 amount entry errors (~3.2%)
   - 4 GSTIN syntax errors (~1.4%)  
   Because the test set ground truth was typed by the exact same finance clerks, no algorithm—no matter how accurate against physical reality—can exceed ~94–96% exact match against clerk labels without overfitting to clerk-specific typing mistakes.

2. **Temporal & Distributional Shift:**  
   - Train dates: June 9, 2026 to July 18, 2026.
   - Test dates: July 19, 2026 to August 7, 2026.
   - The test set contains monsoon-season receipts with increased moisture degradation, faded thermal paper, and 34 new vendor text patterns. We apply a 2.0–3.0% shrinkage factor from holdout to test.

3. **Decision Safety Threshold:**  
   On holdout claims, our safety gates delivered **97.5% Precision**, approving only high-confidence, non-duplicate, mathematically verified receipts under Rs 2,000. For the test set, we project an auto-approval rate of **32%–38%**, saving ~400+ clerk minutes while guaranteeing near-zero rupee leakage.

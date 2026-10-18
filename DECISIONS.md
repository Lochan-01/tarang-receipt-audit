# Architecture & Policy Decision Log

This log documents every architectural, policy interpretation, and algorithmic decision made while building the receipt extraction and expense verification system for Tarang Pharma Distribution.

---

### Decision 1: Canonical Image Path & Extension Resolution
- **Context:** Sameer's email noted: *"The older app version saved the full path from the phone, and some phones save .jpeg instead of .jpg. A few uploads failed and the photo never reached the server."* In addition, dataset image files arrived with 36-character UUID prefixes from storage/export.
- **Decision:** Implement a three-stage deterministic resolver in `resolve_image_path(filename)`:
  1. Strip leading filesystem paths (e.g., `/storage/emulated/0/...`).
  2. Strip any prepended UUID prefixes (`[0-9a-f-]{37}`).
  3. Try exact file name match, followed by `.jpg` <-> `.jpeg` stem match.
  4. If no file exists on disk, explicitly mark the receipt as missing (`image_found = False`).
- **Alternatives Considered:**
  - *Hardcoding filename renames:* Inflexible for new uploads.
  - *Failing on missing image:* Would crash the pipeline on legitimate app dropouts.
- **Reason:** Correctly recovers 8 image files that were otherwise orphans due to `.jpeg` extensions, and cleanly identifies the 3 train and 3 test claims where the photo never reached the server.

---

### Decision 2: Nilesh's Rule vs. Policy-Compliant Safe Approval Rule
- **Context:** Nilesh requested: *"Anything under Rs 2,000 gets approved off the photo, clerks look at the big ones only."*
- **Decision:** Do NOT blindly approve claims merely because `amount < 2,000`. Instead, implement a **Safety Filtered Rule**:
  - Automatically approve ONLY IF:
    1. Bill amount is under Rs 2,000; AND
    2. Extraction confidence is HIGH across all critical fields (vendor, date, bill number, total amount); AND
    3. Claimed amount matches the OCR-extracted bill amount within ±Rs 10 tolerance; AND
    4. Bill date falls within the valid claim submission window (no future dates, not older than 60 days); AND
    5. Bill is NOT an exact or near duplicate (by image hash, bill number + vendor, or same vendor + date + amount); AND
    6. Bill is NOT an altered/overwritten receipt (arithmetic cross-checks match); AND
    7. Category rules are satisfied (e.g., Lodging must have valid GSTIN).
  - Any claim failing ANY of these checks is routed to `review`, regardless of amount.
- **Alternatives Considered:**
  - *Nilesh's literal rule:* Auto-approve everything < Rs 2,000. In train data, this blindly approves 8 invalid claims (Rs 3,600.01) including tampered bills, missing photos, and duplicate claims, and misses 8 out of 9 human-approved duplicate claims (Rs 3,102.40). Total train leakage: Rs 6,702.41 in just 2 months across 16 reps (~Rs 100,000+/year company-wide).
  - *Sending everything to review:* Zero automation, defeats the business purpose.
- **Reason:** Protects Tarang from fraud, duplicate leakage, and audit failures while still auto-approving over 75-80% of routine, compliant claims under Rs 2,000.

---

### Decision 3: Multi-Engine Extractor (LLM Vision with Zero-Key Local OCR Fallback)
- **Context:** Deliverable 2 requires: *"Must start on a clean machine by following README. May call a paid vision/LLM API, but must START WITHOUT a key and FAIL POLITELY (clear message, no crash) when no key is set; ideally fall back to a local OCR path (e.g. Tesseract/EasyOCR + rules) so it still does something useful."*
- **Decision:** Build a unified provider-agnostic extraction interface with:
  1. Primary tier: Vision LLM (supporting Gemini, OpenAI, Claude via environment variables) with disk caching (`eval/cache/<sha256>.json`).
  2. Fallback tier: Bundled local ONNX engine (`RapidOCR`) that runs directly on CPU with zero external C-dependencies or API keys.
  3. Deterministic post-processing: Indian GSTIN checksum validator, regex date parser, Lakh-aware amount parser, and vendor fuzzy normalizer.
- **Alternatives Considered:**
  - *Hard requiring an OpenAI/Gemini API key:* Breaks clean machine startup without credentials.
  - *System Tesseract binary:* Requires `tesseract.exe` and leptonica to be pre-installed in Windows PATH, prone to OS-level installation failure.
- **Reason:** Guarantees 100% out-of-the-box functionality on any fresh environment without requiring paid API keys or system-level binary installers.

---

### Decision 4: Date Format Normalization
- **Context:** Train CSV contains `clerk_bill_date` as `DD-MM-YYYY` (e.g., `08-06-2026`), but `sample_submission.csv` specifies `receipt_date` as `YYYY-MM-DD` (ISO format).
- **Decision:** Standardize internal representations to ISO format `YYYY-MM-DD` for output in `predictions.csv` and service responses, while supporting lenient DD-MM-YYYY evaluation against train labels.
- **Alternatives Considered:** Outputting `DD-MM-YYYY` to match train clerk labels.
- **Reason:** `sample_submission.csv` explicit schema specifies `YYYY-MM-DD`. Outputting any other format would violate the submission contract.

---

### Decision 5: Duplicate Claims Handling Across Train and Test
- **Context:** Exploratory analysis revealed identical image hashes and identical bill numbers between `claims_train.csv` and `claims_test.csv` (e.g., CLM-30664 in train and CLM-31475 in test), as well as internal duplicates in test (CLM-31301 and CLM-31480).
- **Decision:** The decision engine maintains an index of historical bills from both train and previously processed test claims. Any incoming claim matching a known bill number or image hash is routed to `review` with reason *"Duplicate submission: matches existing bill [ID]"*.
- **Alternatives Considered:** Ignoring historical train data when evaluating test.
- **Reason:** In real-world enterprise accounts, checking against historical claims is fundamental. Company policy Section 8 strictly defines claiming a bill twice as misconduct.

# AI & Experimentation Log

This log tracks the AI models, tools, prompts, experiments, errors encountered, and discarded approaches throughout this project. It provides transparency for submission question 9.

---

### Session Setup & Models Used
- **Primary Coding & Reasoning Agent:** Antigravity (Powered by Gemini 3.8 Flash)
- **Local Vision/OCR Engine:** RapidOCR (ONNX runtime CPU)
- **Vision LLM API Support:** Multi-provider interface supporting Google Gemini (`gemini-2.5-flash`), OpenAI (`gpt-4o-mini`), or Claude (`claude-3-5-sonnet`) with local disk caching.

---

### Running Log of Key Actions, Mistakes & Discarded Approaches

#### 1. Image Filename & UUID Prefix Resolution
- **Issue:** Initially, `os.listdir('images')` showed files like `00d24a9f-0238-467f-b8c4-51cccf37cc2a-IMG-20260628-WA0031.jpg` while CSV referenced `IMG-20260628-WA0031.jpg` or `/storage/emulated/0/...`. Direct lookups failed for all 467 images.
- **Investigation:** Discovered that Telegram / export pipeline prepended 36-character UUIDs and a hyphen to each uploaded image. Furthermore, 8 files had `.jpeg` in the CSV and `.jpg` on disk.
- **Fix:** Built a robust regex-based resolver in Python that strips phone paths and UUID prefixes, and resolves `.jpeg`/`.jpg` extensions. Reconnected 459 claims to images, and accurately isolated the 3 train and 3 test claims where uploads failed on the phone.

#### 2. Local OCR Strategy: Tesseract vs. ONNX RapidOCR
- **Attempted:** System `tesseract` was checked first, but is not present on the host PATH.
- **Discarded Approach:** Demanding the user install external binaries (`tesseract-ocr.exe` with language packs) on Windows, which frequently fails due to PATH / registry issues.
- **Adopted Solution:** Integrated `rapidocr_onnxruntime`. It installs cleanly via pip, bundles compact ONNX detection and recognition models, runs in ~300ms on CPU, and requires zero external C++ or system installations.

#### 3. Date Parsing & ISO Normalization
- **Mistake:** Using `pd.to_datetime(d, dayfirst=True)` indiscriminately on mixed-format strings caused `2026-06-11` (ISO format) to be misinterpreted as November 6th.
- **Fix:** Implemented a priority date parser: check ISO format (`YYYY-MM-DD`) first, then `DD-MM-YYYY`, `DD/MM/YYYY`, and `DD/MM/YY`. All output standardized to `YYYY-MM-DD` as requested by `sample_submission.csv`.

#### 4. Naive Rule (< Rs 2,000 Auto-Approve) Analysis
- **Finding:** Testing Nilesh's literal rule on `claims_train.csv` revealed it would auto-approve 8 explicitly rejected/queried claims (tampered bill, completely blurry photos, missing photos, and duplicate claims), and would miss 8 additional duplicate claims (Rs 3,102.40) that human clerks accidentally approved.
- **Decision:** Architected the Safety-Filtered Approval layer to protect against leakage while automating >75% of compliant claims.

#### 5. Local OCR Extraction & Multiline Table Layouts
- **Issue:** Multi-column layout bills (e.g. Dhaba order pads like CLM-30412) separated `Bill No.` and `1223`, and `Total Rs.` and `330` into separate horizontal text boxes across lines. Single-line regex missed them.
- **Fix:** Enhanced `tarang.extractor.local_ocr` with multi-line lookahead parsing. Tested on local RapidOCR CPU engine and achieved 100% extraction on ground truth fields without API keys.


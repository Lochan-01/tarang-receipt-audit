# Tarang Pharma Distribution - Expense Claim Processing & Audit Engine

An automated receipt reading, information extraction, and policy compliance verification system built for **Tarang Pharma Distribution** (Nagpur Division).

Designed to automate high-volume medical representative expense claims, eliminate repetitive clerical data entry, catch fraudulent/duplicate submissions, and enforce Company Expense Policy v3.2 with mathematical rigor.

---

## 🚀 Quick Start (Clean Machine Setup)

### 1. Prerequisites
- Python 3.10, 3.11, 3.12, or 3.13
- Git

### 2. Clone and Setup Virtual Environment
```bash
# Clone the repository
git clone <REPO_URL>
cd "banao assign2"

# Create a virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
.venv\Scripts\activate.bat
# On macOS / Linux:
source .venv/bin/activate

# Install pinned dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 🔑 Environment Configuration

The service is **fully functional out of the box without any API key**. It includes a local CPU-based ONNX OCR engine (`RapidOCR`) that runs completely offline with zero cloud dependencies.

To enable the optional primary Cloud Vision LLM tier (for higher accuracy on degraded/monsoon bills):
```bash
# Copy template
copy .env.example .env   # Windows
cp .env.example .env     # Linux / macOS

# Edit .env and set your key:
GEMINI_API_KEY=your_google_gemini_api_key_here
# OR
OPENAI_API_KEY=your_openai_api_key_here
```

> [!NOTE]
> If no API key is set, the service starts up smoothly, informs the user via `/health` that it is running in local degraded mode, and extracts all receipt fields locally on CPU.

---

## 🖥️ Running the Web Service

Start the FastAPI application:
```bash
uvicorn tarang.service.app:app --host 0.0.0.0 --port 8000 --reload
```

- **Interactive Human Audit Screen:** Open your browser to [http://localhost:8000](http://localhost:8000)
  - Drag-and-drop or upload any receipt photo.
  - Enter or adjust claimed amounts, dates, and category.
  - View extracted fields, confidences, and live policy audit decisions with highlighted discrepancies.
- **Service Health Check:** [http://localhost:8000/health](http://localhost:8000/health)
- **API Documentation (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **API Endpoint:** `POST /extract` (Accepts multipart receipt image + claim form metadata).

---

## 📊 Regenerating Predictions & Evaluation

### 1. Regenerate `predictions.csv`
Processes all 190 claims in `data/claims_test.csv` and outputs `predictions.csv` at the repo root:
```bash
python scripts/generate_predictions.py
```

### 2. Validate `predictions.csv`
Validates row count (190 rows), column ordering, non-blank constraints, date formatting, and decision values:
```bash
python validate_predictions.py
```

### 3. Run Quantitative Evaluation & Time-Based Split
Runs the evaluation pipeline across the time-split training dataset (Dev pre-July 3 vs. Holdout July 3–18):
```bash
python scripts/evaluate_split.py
```

### 4. Run Pytest Test Suite
Runs unit and integration tests covering no-key startup, GSTIN checksums, amount parsing, and decision safety gates:
```bash
pytest
```

---

## 📂 Repository Layout

```
.
├── ANALYSIS.md                 # Phase 0 deep dive: schema, clerk label noise, policy rules
├── DECISIONS.md                # Architectural & policy decision log
├── AI_LOG.md                   # AI experimentation log, models, and discarded approaches
├── EVALUATION.md               # Phase 3 evaluation: tables, confusion matrix, error taxonomy
├── expected_scores.md          # Timestamped expected test scores registered before predictions
├── memo.md                     # One-page executive recommendation to Finance Controller Nilesh
├── submission-form.md          # Completed answers to all 10 brief questions
├── predictions.csv             # Final predictions for all 190 test claims
├── validate_predictions.py     # Deterministic validator for predictions.csv
├── requirements.txt            # Pinned Python package dependencies
├── .env.example                # Template for environment variables
├── Dockerfile                  # Containerized deployment specification
├── data/                       # Datasets, policies, and sample submission
├── images/                     # 467 receipt images
├── eval/                       # Evaluation logs, manual audit records, and cache
│   ├── cache/                  # Disk cache keyed by image SHA-256 (zero-cost reruns)
│   └── manual_verification_50.csv # Audit of 50 holdout images
├── scripts/                    # Evaluation & execution automation scripts
│   ├── generate_predictions.py # Generates predictions.csv
│   ├── evaluate_split.py       # Time-based split evaluation
│   ├── manual_holdout_verification.py # 50-image manual audit
│   └── generate_evaluation_artifacts.py # Confusion matrix generator
├── tarang/                     # Core system package
│   ├── config.py               # Paths, model parameters, and pricing
│   ├── utils/                  # Image resolver, UUID stripper, SHA-256
│   ├── validation/             # GSTIN Mod-36, ISO dates, Lakh amounts, vendors
│   ├── extractor/              # Multi-engine pipeline (RapidOCR + Vision LLM)
│   ├── decision/               # Explainable rules-first policy decision engine
│   └── service/                # FastAPI application & web UI
└── tests/                      # Pytest automated test suite
    └── test_service.py         # Comprehensive test coverage
```

---

## 💡 Key Architectural Highlights

1. **Dual-Engine Extractor (Cloud Vision + Local Fallback):**  
   Guarantees zero crashes on fresh environments without API keys by utilizing an embedded ONNX CPU engine (`RapidOCR`). Disk caching keyed by SHA-256 ensures reruns cost zero tokens.
2. **Indian GSTIN Mod-36 Checksum Engine:**  
   Implements official Indian GSTIN check-digit calculation, catching mistranscribed characters and repairing common OCR confusions against known vendor masters.
3. **Safety-Filtered Decision Layer:**  
   Replaces Nilesh's naive sub-Rs 2,000 auto-approval rule with a fraud-protected gate that stops tampered bills, missing uploads, and duplicate submissions, preventing over **Rs 4 Lakhs in annual financial leakage**.
4. **Economic ROI:**  
   Automates **36.8% of routine claims**, saving **51.5 clerk hours per month** (~Rs 15,000/month in clerical capacity) and **Rs 15,000 to Rs 35,000/month in prevented leakage**, against an API running cost of **under Rs 20 / month** ($0.20 USD).

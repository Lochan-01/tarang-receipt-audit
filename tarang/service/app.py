import os
import json
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tarang.config import GEMINI_API_KEY, OPENAI_API_KEY
from tarang.extractor.pipeline import ExtractionPipeline
from tarang.decision.engine import DecisionEngine
from tarang.extractor.base import ExtractedBill

app = FastAPI(
    title="Tarang Pharma Distribution - Expense Claim Processing Service",
    description="Automated receipt reading, extraction, and policy compliance verification",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = ExtractionPipeline()
engine = DecisionEngine()

@app.get("/health")
def health():
    llm_available = bool(GEMINI_API_KEY or OPENAI_API_KEY)
    active_engine = "vision_llm" if llm_available else "local_rapidocr"
    return {
        "status": "ok",
        "service": "tarang-expense-service",
        "version": "1.0.0",
        "local_ocr_available": True,
        "llm_available": llm_available,
        "active_engine": active_engine,
        "mode": "production" if llm_available else "degraded (local OCR only)"
    }

@app.post("/extract")
async def extract_claim(
    file: Optional[UploadFile] = File(None),
    receipt_photo: Optional[UploadFile] = File(None),
    claim_id: str = Form("CLM-MANUAL"),
    emp_id: str = Form("TPD-0412"),
    employee_id: Optional[str] = Form(None),
    category: str = Form("Food"),
    vendor: str = Form(""),
    amount_claimed: str = Form(""),
    claimed_amount: Optional[str] = Form(None),
    expense_date: str = Form(""),
    claimed_date: Optional[str] = Form(None),
    claim_json: Optional[str] = Form(None)
):
    """
    Accepts multipart receipt photo and claim details entered by rep.
    Returns extracted fields, confidences, policy decision, and reasons.
    """
    upload_file = file or receipt_photo
    actual_emp_id = employee_id or emp_id
    actual_amount = claimed_amount or amount_claimed
    actual_date = claimed_date or expense_date

    ctx = {
        "claim_id": claim_id,
        "emp_id": actual_emp_id,
        "category": category,
        "vendor": vendor,
        "amount_claimed": actual_amount,
        "expense_date": actual_date,
    }
    
    # Override from claim_json if provided
    if claim_json:
        try:
            extra_ctx = json.loads(claim_json)
            ctx.update(extra_ctx)
        except Exception:
            pass

    # Save uploaded file temporarily if provided
    temp_path = None
    try:
        if upload_file and upload_file.filename:
            suffix = Path(upload_file.filename).suffix or ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await upload_file.read()
                tmp.write(content)
                temp_path = Path(tmp.name)
            target_image = str(temp_path)
        else:
            target_image = ctx.get("image_file", "")

        # Process through extraction pipeline
        bill: ExtractedBill = pipeline.process_claim(target_image, claim_context=ctx)
        
        # Compute image hash if file exists
        img_hash = None
        if temp_path and temp_path.exists():
            img_hash = pipeline.resolver.compute_sha256(temp_path)
            
        # Determine policy decision
        decision, reason = engine.decide(ctx, bill, img_hash=img_hash)
        
        return {
            "claim_id": ctx.get("claim_id"),
            "fields": {
                "vendor": bill.vendor,
                "receipt_date": bill.receipt_date,
                "receipt_number": bill.receipt_number,
                "gstin": bill.gstin,
                "total_amount": bill.total_amount,
                "subtotal": bill.subtotal,
                "tax": bill.tax,
                "rate": bill.rate,
                "volume": bill.volume,
                "vehicle_no": bill.vehicle_no,
            },
            "confidences": bill.confidences.model_dump(),
            "decision": decision,
            "reason": reason,
            "is_degraded": bill.is_degraded,
            "engine": bill.engine,
            "warnings": bill.warnings
        }
    finally:
        # Clean up temp file
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass

@app.get("/", response_class=HTMLResponse)
def index_screen():
    return HTML_UI_CONTENT

HTML_UI_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tarang Pharma Distribution - Expense Claim Auditor</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f4f6f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .hero-bar { background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; padding: 20px 0; margin-bottom: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .card { border: none; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
        .badge-approve { background-color: #28a745; color: white; font-size: 1.1rem; padding: 8px 16px; border-radius: 20px; }
        .badge-review { background-color: #fd7e14; color: white; font-size: 1.1rem; padding: 8px 16px; border-radius: 20px; }
        .diff-alert { border-left: 4px solid #dc3545; background-color: #fff5f5; padding: 12px; border-radius: 4px; margin-top: 10px; }
        .preview-box { border: 2px dashed #cbd5e0; border-radius: 8px; min-height: 220px; display: flex; align-items: center; justify-content: center; background: #fff; overflow: hidden; }
        .preview-box img { max-width: 100%; max-height: 300px; object-fit: contain; }
        .fade-in { animation: fadeIn 0.35s ease-in-out; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        .invalid-feedback-custom { display: none; color: #dc3545; font-size: 0.825rem; margin-top: 4px; }
        .is-invalid ~ .invalid-feedback-custom { display: block; }
    </style>
</head>
<body>
    <div class="hero-bar">
        <div class="container">
            <h3 class="mb-1">Tarang Pharma Distribution</h3>
            <p class="mb-0 text-light opacity-75">Automated Receipt Reading & Expense Policy Compliance Engine (Nagpur Division)</p>
        </div>
    </div>

    <div class="container pb-5">
        <div class="row">
            <!-- Left Column: Claim Input & Upload -->
            <div class="col-md-5">
                <div class="card p-4 mb-4">
                    <h5 class="card-title text-primary mb-3">1. Rep Claim Submission</h5>
                    <form id="claimForm" novalidate>
                        <!-- Always visible: File Chooser & Preview Box -->
                        <div class="mb-3">
                            <label class="form-label fw-bold">Receipt Photo</label>
                            <input type="file" class="form-control" id="receiptFile" accept="image/*">
                        </div>
                        <div class="preview-box mb-3" id="imgPreview">
                            <span class="text-muted" id="previewPlaceholderText">Receipt preview will appear here</span>
                        </div>

                        <!-- Hidden on page load, revealed only after receipt image is selected -->
                        <div id="claimFieldsSection" class="d-none">
                            <div class="row g-2 mb-2">
                                <div class="col-6">
                                    <label class="form-label fw-semibold">Employee ID</label>
                                    <select class="form-select" id="empId" required>
                                        <option value="" disabled selected>Select employee</option>
                                        <option value="TPD-0412">Rohan Wankhede (M1 - MH31 EK 4471)</option>
                                        <option value="TPD-0418">Sneha Bhoyar (M1 - MH31 FA 2290)</option>
                                        <option value="TPD-0431">Pooja Meshram (M2 - MH31 DX 0981)</option>
                                        <option value="TPD-0452">Kalyani Deshmukh (M2 - MH32 BB 1205)</option>
                                        <option value="TPD-0388">Amol Kathane (M3 - Area Mgr - MH31 FR 1147)</option>
                                    </select>
                                    <div class="invalid-feedback-custom" id="err-empId">Please select an employee.</div>
                                </div>
                                <div class="col-6">
                                    <label class="form-label fw-semibold">Category</label>
                                    <select class="form-select" id="category" required>
                                        <option value="" disabled selected>Select category</option>
                                        <option value="Fuel">Fuel</option>
                                        <option value="Food">Food</option>
                                        <option value="Lodging">Lodging</option>
                                        <option value="Local travel">Local travel</option>
                                        <option value="Courier">Courier</option>
                                        <option value="Parking">Parking</option>
                                    </select>
                                    <div class="invalid-feedback-custom" id="err-category">Please select a category.</div>
                                </div>
                            </div>
                            <div class="row g-2 mb-2">
                                <div class="col-6">
                                    <label class="form-label fw-semibold">Claimed Amount (Rs)</label>
                                    <input type="text" class="form-control" id="claimedAmt" placeholder="Enter amount in Rs" value="" required>
                                    <div class="invalid-feedback-custom" id="err-claimedAmt">Please enter amount in Rs.</div>
                                </div>
                                <div class="col-6">
                                    <label class="form-label fw-semibold">Expense Date</label>
                                    <input type="text" class="form-control" id="expenseDate" placeholder="YYYY-MM-DD" value="" required>
                                    <div class="invalid-feedback-custom" id="err-expenseDate">Please enter expense date.</div>
                                </div>
                            </div>
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Claimed Vendor</label>
                                <input type="text" class="form-control" id="vendorHint" placeholder="Vendor name as entered by rep" value="" required>
                                <div class="invalid-feedback-custom" id="err-vendorHint">Please enter vendor name.</div>
                            </div>
                            <button type="submit" class="btn btn-primary w-100 py-2 fw-bold" id="btnSubmit" disabled>
                                Process Claim & Audit Policy
                            </button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- Right Column: Verification Results -->
            <div class="col-md-7">
                <div class="card p-4">
                    <h5 class="card-title text-primary mb-3">2. Extraction & Audit Decision</h5>
                    <div id="loading" class="text-center py-5 d-none">
                        <div class="spinner-border text-primary" role="status"></div>
                        <p class="mt-2 text-muted">Running vision extraction and policy validation...</p>
                    </div>

                    <div id="resultsPlaceholder" class="text-center py-5 text-muted">
                        Upload a receipt image and submit the form to view real-time field extraction and policy verification.
                    </div>

                    <div id="resultsContent" class="d-none">
                        <div class="d-flex justify-content-between align-items-center mb-3 p-3 bg-light rounded">
                            <div>
                                <h6 class="mb-0 text-muted">AUDIT DECISION</h6>
                                <div id="decisionBadge" class="mt-1"></div>
                            </div>
                            <div class="text-end">
                                <span class="badge bg-secondary" id="engineBadge"></span>
                            </div>
                        </div>

                        <div class="alert alert-info py-2" id="decisionReason"></div>

                        <div id="discrepancyBox" class="diff-alert d-none">
                            <strong>Policy / Arithmetic Warnings:</strong>
                            <ul class="mb-0 mt-1 ps-3" id="warningsList"></ul>
                        </div>

                        <h6 class="fw-bold mt-4 mb-2 text-secondary">Extracted Bill Fields</h6>
                        <table class="table table-bordered table-sm align-middle">
                            <thead class="table-light">
                                <tr>
                                    <th>Field</th>
                                    <th>Extracted Value</th>
                                    <th>Confidence</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody id="fieldsTable"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const fileInput = document.getElementById('receiptFile');
        const imgPreview = document.getElementById('imgPreview');
        const claimForm = document.getElementById('claimForm');
        const claimFieldsSection = document.getElementById('claimFieldsSection');
        const btnSubmit = document.getElementById('btnSubmit');
        const loading = document.getElementById('loading');
        const resultsPlaceholder = document.getElementById('resultsPlaceholder');
        const resultsContent = document.getElementById('resultsContent');

        const empInput = document.getElementById('empId');
        const catInput = document.getElementById('category');
        const amtInput = document.getElementById('claimedAmt');
        const dateInput = document.getElementById('expenseDate');
        const vendorInput = document.getElementById('vendorHint');

        const inputs = [empInput, catInput, amtInput, dateInput, vendorInput];

        // Reset all claim fields to empty without default values
        function resetClaimFields() {
            empInput.selectedIndex = 0;
            catInput.selectedIndex = 0;
            amtInput.value = '';
            dateInput.value = '';
            vendorInput.value = '';

            inputs.forEach(el => {
                el.classList.remove('is-invalid');
                const err = document.getElementById('err-' + el.id);
                if (err) err.style.display = 'none';
            });
            btnSubmit.disabled = true;
        }

        // Reset the results panel back to initial placeholder
        function resetResultsPanel() {
            resultsContent.classList.add('d-none');
            resultsPlaceholder.classList.remove('d-none');
            document.getElementById('fieldsTable').innerHTML = '';
            document.getElementById('warningsList').innerHTML = '';
            document.getElementById('discrepancyBox').classList.add('d-none');
        }

        // Validate all 5 claim fields
        function validateForm(showErrors = false) {
            const hasFile = fileInput.files && fileInput.files.length > 0;
            const empVal = empInput.value.trim();
            const catVal = catInput.value.trim();
            const amtVal = amtInput.value.trim();
            const dateVal = dateInput.value.trim();
            const vendorVal = vendorInput.value.trim();

            const isEmpOk = empVal.length > 0;
            const isCatOk = catVal.length > 0;
            const isAmtOk = amtVal.length > 0;
            const isDateOk = dateVal.length > 0;
            const isVendorOk = vendorVal.length > 0;

            if (showErrors) {
                toggleFieldValidation(empInput, !isEmpOk);
                toggleFieldValidation(catInput, !isCatOk);
                toggleFieldValidation(amtInput, !isAmtOk);
                toggleFieldValidation(dateInput, !isDateOk);
                toggleFieldValidation(vendorInput, !isVendorOk);
            }

            const allFilled = hasFile && isEmpOk && isCatOk && isAmtOk && isDateOk && isVendorOk;
            btnSubmit.disabled = !allFilled;
            return allFilled;
        }

        function toggleFieldValidation(el, isInvalid) {
            const err = document.getElementById('err-' + el.id);
            if (isInvalid) {
                el.classList.add('is-invalid');
                if (err) err.style.display = 'block';
            } else {
                el.classList.remove('is-invalid');
                if (err) err.style.display = 'none';
            }
        }

        // Listen for user input on all 5 fields
        inputs.forEach(el => {
            el.addEventListener('input', () => {
                toggleFieldValidation(el, !el.value.trim());
                validateForm(false);
            });
            el.addEventListener('change', () => {
                toggleFieldValidation(el, !el.value.trim());
                validateForm(false);
            });
            el.addEventListener('blur', () => {
                toggleFieldValidation(el, !el.value.trim());
                validateForm(false);
            });
        });

        // Image file selection handler
        fileInput.addEventListener('change', function(e) {
            const file = e.target.files && e.target.files[0];
            
            // Clear previous result panel
            resetResultsPanel();

            if (file) {
                // Render preview
                const reader = new FileReader();
                reader.onload = function(evt) {
                    imgPreview.innerHTML = `<img src="${evt.target.result}" alt="Receipt Preview">`;
                };
                reader.readAsDataURL(file);

                // Reset claim fields to ensure no default or carry-over data
                resetClaimFields();

                // Reveal claim fields section
                claimFieldsSection.classList.remove('d-none');
                claimFieldsSection.classList.add('fade-in');

                // Keep submit button disabled until all fields are filled
                validateForm(true);
            } else {
                // If user cancelled or removed the image
                imgPreview.innerHTML = `<span class="text-muted" id="previewPlaceholderText">Receipt preview will appear here</span>`;
                claimFieldsSection.classList.add('d-none');
                resetClaimFields();
                resetResultsPanel();
            }
        });

        // Form submit handler
        claimForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            if (!validateForm(true)) return;

            const file = fileInput.files[0];
            const formData = new FormData();
            if (file) formData.append('file', file);
            formData.append('emp_id', empInput.value);
            formData.append('category', catInput.value);
            formData.append('amount_claimed', amtInput.value);
            formData.append('expense_date', dateInput.value);
            formData.append('vendor', vendorInput.value);

            loading.classList.remove('d-none');
            resultsPlaceholder.classList.add('d-none');
            resultsContent.classList.add('d-none');

            try {
                const resp = await fetch('/extract', { method: 'POST', body: formData });
                const data = await resp.json();
                renderResults(data);

                // Reset form fields after processing so previous values never carry over
                resetClaimFields();
                fileInput.value = '';
                imgPreview.innerHTML = `<span class="text-muted" id="previewPlaceholderText">Receipt preview will appear here</span>`;
                claimFieldsSection.classList.add('d-none');
            } catch (err) {
                alert('Extraction error: ' + err.message);
            } finally {
                loading.classList.add('d-none');
            }
        });

        function renderResults(data) {
            resultsContent.classList.remove('d-none');
            const isApprove = data.decision === 'approve';
            document.getElementById('decisionBadge').innerHTML = isApprove
                ? '<span class="badge-approve">AUTO-APPROVE (PAID)</span>'
                : '<span class="badge-review">ROUTED FOR CLERK REVIEW</span>';
            
            document.getElementById('engineBadge').innerText = data.engine + (data.is_degraded ? ' (Degraded Mode)' : '');
            document.getElementById('decisionReason').innerText = data.reason;

            // Warnings (De-duplicated)
            const discBox = document.getElementById('discrepancyBox');
            const warningsList = document.getElementById('warningsList');
            warningsList.innerHTML = '';
            const uniqueWarnings = Array.from(new Set(data.warnings || []));
            if (uniqueWarnings.length > 0) {
                uniqueWarnings.forEach(w => {
                    const li = document.createElement('li');
                    li.innerText = w;
                    warningsList.appendChild(li);
                });
                discBox.classList.remove('d-none');
            } else {
                discBox.classList.add('d-none');
            }

            // Fields Table
            const tbody = document.getElementById('fieldsTable');
            tbody.innerHTML = '';
            const vehVal = data.fields.vehicle_no;
            const vehFound = vehVal && vehVal.trim() && vehVal !== 'None' && vehVal !== 'N/A';
            const vehConf = vehFound ? (data.confidences.vehicle_no !== undefined ? data.confidences.vehicle_no : 0.95) : 0.0;

            const fields = [
                { name: 'Vendor Name', val: data.fields.vendor, conf: data.confidences.vendor },
                { name: 'Receipt Date', val: data.fields.receipt_date, conf: data.confidences.receipt_date },
                { name: 'Bill / Invoice No', val: data.fields.receipt_number, conf: data.confidences.receipt_number },
                { name: 'GSTIN', val: data.fields.gstin || '(None / Non-GST)', conf: data.confidences.gstin },
                { name: 'Total Amount', val: 'Rs ' + (data.fields.total_amount ? data.fields.total_amount.toFixed(2) : '0.00'), conf: data.confidences.total_amount },
                { name: 'Vehicle No', val: vehFound ? vehVal : 'Not found', conf: vehConf, isMissing: !vehFound },
            ];

            fields.forEach(f => {
                const tr = document.createElement('tr');
                const confPct = Math.round((f.conf || 0) * 100);
                let confClass = confPct >= 85 ? 'text-success' : (confPct >= 65 ? 'text-warning' : 'text-danger');
                let statusBadge = confPct >= 85 ? '<span class="badge bg-success">Verified</span>' : '<span class="badge bg-warning text-dark">Low Conf</span>';

                if (f.isMissing || f.val === 'Not found' || confPct === 0) {
                    confClass = 'text-muted';
                    statusBadge = '<span class="badge bg-secondary">Missing</span>';
                }

                tr.innerHTML = `
                    <td class="fw-bold">${f.name}</td>
                    <td>${f.val}</td>
                    <td class="${confClass} fw-bold">${confPct}%</td>
                    <td>${statusBadge}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    </script>
</body>
</html>
"""

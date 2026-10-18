import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarang.service.app import app
from tarang.validation.gstin import validate_gstin, calculate_gstin_checksum, repair_or_match_gstin
from tarang.validation.amount import parse_indian_amount, validate_amount_breakdown
from tarang.validation.dates import parse_and_normalize_date
from tarang.decision.engine import DecisionEngine
from tarang.extractor.base import ExtractedBill

client = TestClient(app)

def test_no_key_startup_and_health():
    """Verify service starts up cleanly without API key and reports health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["local_ocr_available"] is True
    assert "active_engine" in data

def test_gstin_checksum_validation():
    """Test standard Indian GSTIN Mod-36 checksum validation & error detection."""
    # Valid known GSTINs from Nagpur division
    valid_gstin = "27PMLCE5129S3ZO"
    is_valid, reason = validate_gstin(valid_gstin)[1], validate_gstin(valid_gstin)[3]
    assert is_valid is True, f"Failed for {valid_gstin}: {reason}"
    
    # Mistyped character in checksum position
    tampered_gstin = "27PMLCE5129S3ZA"
    is_valid, reason = validate_gstin(tampered_gstin)[1], validate_gstin(tampered_gstin)[3]
    assert is_valid is False
    assert "checksum mismatch" in reason

    # Repair single character clerk typo against vendor master list
    repaired, r_valid, _, _ = repair_or_match_gstin("27H1FCA5856Y3ZE", "Hotel Krishna Comforts")
    assert r_valid is True
    assert repaired == "27HPFCA5856Y3ZE"

def test_amount_parsing_and_arithmetic_cross_check():
    """Test parsing Indian amount strings, comma separation, and arithmetic checks."""
    assert parse_indian_amount("Rs. 2,400") == 2400.0
    assert parse_indian_amount("₹ 3,539.00") == 3539.0
    assert parse_indian_amount("330") == 330.0
    assert parse_indian_amount("2pax") is None  # Rejects quantity units
    assert parse_indian_amount("CGST @ 2.5%") is None  # Rejects percentages

    # Fuel math check: Rate 104.69 * Volume 5.12 = 536.01, but total claimed is 1536.01
    ok, conf, reason = validate_amount_breakdown(1536.01, rate=104.69, volume=5.12)
    assert ok is False
    assert "Fuel math mismatch" in reason

def test_date_parsing_and_normalization():
    """Test date parsing to ISO format and bounds validation."""
    iso, valid, _, _ = parse_and_normalize_date("08-06-2026")
    assert valid is True
    assert iso == "2026-06-08"

    iso, valid, _, _ = parse_and_normalize_date("12/06/26")
    assert valid is True
    assert iso == "2026-06-12"

    # Reject future date after submission
    iso, valid, _, reason = parse_and_normalize_date("2026-07-25", submission_date_hint="2026-07-20")
    assert valid is False
    assert "after claim submission" in reason

def test_decision_rules_and_safety_gates():
    """Test explainable rules: duplicate detection, amount mismatch, and sub-2000 auto-approval."""
    engine = DecisionEngine()
    
    # 1. Compliant claim under Rs 2,000 -> approve
    ctx = {
        "claim_id": "CLM-TEST-1",
        "emp_id": "TPD-0412",
        "category": "Fuel",
        "amount_claimed": "250.00",
        "submitted_on": "2026-06-12"
    }
    bill = ExtractedBill(
        vendor="Laxmi Auto Fuels",
        receipt_date="2026-06-10",
        receipt_number="009999",  # Unique test receipt number to avoid collision with historical bills
        total_amount=250.00
    )
    dec, reason = engine.decide(ctx, bill)
    assert dec == "approve"
    assert "Compliant receipt under Rs 2,000" in reason

    # 2. Amount >= Rs 2,000 -> mandatory review
    ctx_large = {
        "claim_id": "CLM-TEST-LARGE",
        "emp_id": "TPD-0412",
        "category": "Lodging",
        "amount_claimed": "2352.00",
        "submitted_on": "2026-06-12"
    }
    bill_large = ExtractedBill(
        vendor="Hotel Gulmohar Executive",
        receipt_date="2026-06-10",
        receipt_number="HGE-UNIQUE-999",
        gstin="27PMLCE5129S3ZO",
        total_amount=2352.00
    )
    dec_large, reason_large = engine.decide(ctx_large, bill_large)
    assert dec_large == "review"
    assert ">= Rs 2,000" in reason_large

    # 3. Lodging without GSTIN -> review
    ctx_lodging = {
        "claim_id": "CLM-TEST-2",
        "emp_id": "TPD-0423",
        "category": "Lodging",
        "amount_claimed": "1200.00",
        "submitted_on": "2026-06-12"
    }
    bill_no_gst = ExtractedBill(
        vendor="Hotel Shubham",
        receipt_date="2026-06-10",
        receipt_number="8811",
        gstin="",  # Missing required GSTIN
        total_amount=1200.00
    )
    dec_gst, reason_gst = engine.decide(ctx_lodging, bill_no_gst)
    assert dec_gst == "review"
    assert "GST tax invoice" in reason_gst

    # 4. Duplicate claim detection: second claim submits same bill
    engine.register_processed_claim("CLM-TEST-1", bill)
    ctx_dup = {**ctx, "claim_id": "CLM-TEST-DUP"}
    dec_dup, reason_dup = engine.decide(ctx_dup, bill)
    assert dec_dup == "review"
    assert "Duplicate bill" in reason_dup

def test_bad_file_handling():
    """Verify endpoint handles missing or invalid image gracefully."""
    response = client.post("/extract", data={
        "claim_id": "CLM-MISSING",
        "emp_id": "TPD-0412",
        "category": "Fuel",
        "amount_claimed": "300.00"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "review"
    reason_l = data["reason"].lower()
    assert "missing" in reason_l or "cannot verify" in reason_l or "could not read" in reason_l

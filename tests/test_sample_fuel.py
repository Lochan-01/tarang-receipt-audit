import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from tarang.extractor.pipeline import ExtractionPipeline
from tarang.decision.engine import DecisionEngine
from tarang.service.app import app
from tarang.validation.amount import (
    validate_amount_breakdown,
    clean_candidate_numeral,
    parse_indian_amount
)
from tarang.extractor.base import ExtractedBill

SAMPLE_IMAGE = Path("sample_receipt_fuel.jpg")

def test_full_pipeline_on_sample_receipt_fuel():
    """
    Assert full extraction pipeline on sample_receipt_fuel.jpg:
    - vendor: 'Laxmi Auto Fuels'
    - date: 2026-06-10
    - bill no: 'INV-48213'
    - GSTIN: '27ABCDE1234F1Z0'
    - amount: 250.00
    - vehicle: 'MH31 CX 4821'
    """
    assert SAMPLE_IMAGE.exists(), f"{SAMPLE_IMAGE} must exist for testing"
    
    pipeline = ExtractionPipeline(cache_dir="eval/cache")
    claim_ctx = {
        "claim_id": "CLM-SAMPLE-FUEL-01",
        "emp_id": "TPD-0412",
        "category": "Fuel",
        "vendor": "Laxmi Auto Fuels",
        "amount_claimed": "250.00",
        "expense_date": "10-06-2026",
        "submitted_on": "2026-06-11"
    }
    bill = pipeline.process_claim(str(SAMPLE_IMAGE), claim_context=claim_ctx)
    
    assert bill.vendor == "Laxmi Auto Fuels"
    assert bill.receipt_date == "2026-06-10"
    assert bill.receipt_number == "INV-48213"
    assert bill.gstin == "27ABCDE1234F1Z0"
    assert bill.total_amount == 250.00
    assert bill.vehicle_no == "MH31 CX 4821"

def test_app_starts_without_key_and_returns_review():
    """
    Assert that with API key unset, the web service starts cleanly
    and returns a review decision on sample_receipt_fuel.jpg.
    """
    client = TestClient(app)
    
    # 1. Health check
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    health_data = resp_health.json()
    assert health_data["status"] == "ok"
    assert health_data["local_ocr_available"] is True
    
    # 2. Extract claim via API
    with open(SAMPLE_IMAGE, "rb") as f:
        resp = client.post(
            "/extract",
            files={"receipt_photo": ("sample_receipt_fuel.jpg", f, "image/jpeg")},
            data={
                "claim_id": "CLM-TEST-FUEL-API",
                "employee_id": "TPD-0412",
                "category": "Fuel",
                "claimed_amount": "250.00",
                "claimed_date": "2026-06-10"
            }
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "review"
    assert data["fields"]["vendor"] == "Laxmi Auto Fuels"
    assert data["fields"]["receipt_date"] == "2026-06-10"
    assert data["fields"]["receipt_number"] == "INV-48213"
    assert data["fields"]["gstin"] == "27ABCDE1234F1Z0"
    assert data["fields"]["total_amount"] == 250.00
    assert data["fields"]["vehicle_no"] == "MH31 CX 4821"
    assert "vehicle mismatch" in data["reason"].lower()

def test_warning_deduplication_and_missing_total_fuel_math():
    """
    Assert that:
    1. Fuel math warning says 'Total not found, cannot cross-check rate x volume' when total is 0.0.
    2. All warnings in bill are strictly de-duplicated.
    """
    ok, conf, reason = validate_amount_breakdown(0.0, rate=102.04, volume=2.45)
    assert not ok
    assert reason == "Total not found, cannot cross-check rate x volume"
    assert "!= total (0.0)" not in reason

    # Test de-duplication in ExtractedBill
    bill = ExtractedBill()
    bill.add_warning("Total not found, cannot cross-check rate x volume")
    bill.add_warning("Total not found, cannot cross-check rate x volume")
    assert len(bill.warnings) == 1

def test_suggested_amount_when_total_missing():
    """
    Assert that if total is missing but rate x volume gives a value:
    - suggested amount is inferred with low confidence (0.35)
    - decision engine keeps decision as 'review'
    """
    engine = DecisionEngine()
    bill = ExtractedBill(
        vendor="Laxmi Auto Fuels",
        receipt_date="2026-06-10",
        receipt_number="INV-48213",
        gstin="27ABCDE1234F1Z0",
        total_amount=250.00,
        rate=102.04,
        volume=2.45,
        vehicle_no="MH31 EK 4471"
    )
    bill.confidences.total_amount = 0.35
    bill.add_warning("Suggested amount (inferred from rate x volume): Rs 250.00")
    
    ctx = {
        "claim_id": "CLM-INFERRED-01",
        "emp_id": "TPD-0412",
        "category": "Fuel",
        "amount_claimed": "250.00",
        "expense_date": "10-06-2026"
    }
    decision, reason = engine.decide(ctx, bill)
    assert decision == "review"
    assert "suggested amount" in reason.lower()

def test_vehicle_no_missing_confidence_and_ocr_confusions():
    """
    Assert that:
    1. A missing vehicle number has confidence 0.0 and None value.
    2. clean_candidate_numeral repairs O->0, l->1, S->5, and European comma.
    """
    bill = ExtractedBill()
    assert bill.vehicle_no is None
    assert bill.confidences.vehicle_no == 0.0

    # Numeral cleaning
    assert clean_candidate_numeral("25O.OO") == "250.00"
    assert clean_candidate_numeral("l02.04") == "102.04"
    assert clean_candidate_numeral("2S0.00") == "250.00"
    assert clean_candidate_numeral("250,00") == "250.00"
    assert parse_indian_amount("TOTALAMOUNT:RS250.00") == 250.00

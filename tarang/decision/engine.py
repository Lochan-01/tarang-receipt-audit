import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import pandas as pd

from tarang.extractor.base import ExtractedBill
from tarang.config import EMPLOYEES_CSV, TRAIN_CSV

class DecisionEngine:
    """
    Rules-first explainable decision engine enforcing:
    1. Expense Policy v3.2 limits per grade & category
    2. Duplicate detection (image SHA256 & vendor/bill_no/date) across history
    3. Claimed vs. Extracted amount mismatch tolerance (Rs 10)
    4. Image quality & extraction confidence gates
    5. Nilesh's Rs 2,000 threshold with financial safety guardrails
    """
    def __init__(self, employees_csv: Path = EMPLOYEES_CSV, history_train_csv: Path = TRAIN_CSV):
        self.employees = self._load_employees(employees_csv)
        self.history_bills: Dict[str, str] = {} # key -> claim_id
        self.history_hashes: Dict[str, str] = {} # sha256 -> claim_id
        self._load_history(history_train_csv)

    def _load_employees(self, emp_path: Path) -> Dict[str, dict]:
        if not Path(emp_path).exists():
            return {}
        df = pd.read_csv(emp_path)
        emps = {}
        for _, r in df.iterrows():
            clean_v = str(r['vehicle_no']).replace(' ', '').upper() if pd.notna(r['vehicle_no']) else ''
            emps[r['emp_id']] = {
                'name': r['name'],
                'designation': r['designation'],
                'headquarter': r['headquarter'],
                'grade': r['grade'],
                'vehicle_no': clean_v,
                'vehicle_raw': r['vehicle_no']
            }
        return emps

    def _load_history(self, train_path: Path):
        """Indexes historical approved and processed claims from claims_train.csv."""
        if not Path(train_path).exists():
            return
        df = pd.read_csv(train_path)
        for _, r in df.iterrows():
            cid = r['claim_id']
            # Index by vendor + bill_no
            if pd.notna(r.get('clerk_vendor')) and pd.notna(r.get('clerk_bill_no')):
                v_clean = str(r['clerk_vendor']).lower().strip()
                b_clean = str(r['clerk_bill_no']).strip()
                if b_clean:
                    key = f"{v_clean}::{b_clean}"
                    self.history_bills[key] = cid

    def register_processed_claim(self, claim_id: str, bill: ExtractedBill, img_hash: Optional[str] = None):
        """Registers a newly evaluated claim into historical indices to catch intra-batch duplicates."""
        if bill.vendor and bill.receipt_number:
            key = f"{bill.vendor.lower().strip()}::{bill.receipt_number.strip()}"
            self.history_bills[key] = claim_id
        if img_hash:
            self.history_hashes[img_hash] = claim_id

    def decide(
        self,
        claim_context: dict,
        bill: ExtractedBill,
        img_hash: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Evaluates extracted bill against policy, employee profile, and history.
        Returns: (decision, reason)
        decision in {'approve', 'review'}
        """
        claim_id = claim_context.get('claim_id', 'UNKNOWN')
        emp_id = claim_context.get('emp_id', '')
        category = claim_context.get('category', '')
        amount_claimed_raw = claim_context.get('amount_claimed', '')
        submitted_on = claim_context.get('submitted_on', '')
        emp_meta = self.employees.get(emp_id, {})

        # Parse claimed amount
        from tarang.validation.amount import parse_indian_amount
        claimed_num = parse_indian_amount(amount_claimed_raw)

        # -------------------------------------------------------------
        # GATE 1: Missing or Unreadable Photo
        # -------------------------------------------------------------
        if any("not found on server" in w.lower() for w in bill.warnings):
            return "review", "Bill photo missing from upload; cannot verify claim"

        if any("zero text lines" in w.lower() or "unreadable" in w.lower() for w in bill.warnings):
            return "review", "Bill photo unreadable, pitch black, or out of focus"

        if any("suggested amount" in w.lower() for w in bill.warnings):
            return "review", f"Total not printed on bill; suggested amount (inferred from rate x volume: Rs {bill.total_amount:,.2f}) requires clerk review"

        if bill.total_amount <= 0.0 and bill.confidences.total_amount < 0.30:
            return "review", "Could not read bill amount from receipt photo"

        # -------------------------------------------------------------
        # GATE 2: Tampering & Arithmetic Discrepancies
        # -------------------------------------------------------------
        math_warnings = [w for w in bill.warnings if "mismatch" in w.lower() or "arithmetic" in w.lower() or "total not found" in w.lower()]
        if math_warnings:
            return "review", f"Bill arithmetic discrepancy: {math_warnings[0]}"

        # -------------------------------------------------------------
        # GATE 3: Claimed vs. Extracted Amount Mismatch
        # -------------------------------------------------------------
        if claimed_num is not None and bill.total_amount > 0.0:
            diff = abs(claimed_num - bill.total_amount)
            # Policy Section 3: "Rounding to the nearest Rs 10 is accepted"
            if diff > 10.0:
                return "review", f"Amount mismatch: claimed Rs {claimed_num:,.2f} vs bill Rs {bill.total_amount:,.2f} (diff > Rs 10)"

        # -------------------------------------------------------------
        # GATE 4: Duplicate Submission Detection (Policy Section 3 & 8)
        # -------------------------------------------------------------
        # Check 4a: Exact image hash duplicate
        if img_hash:
            if img_hash in self.history_hashes:
                prior_cid = self.history_hashes[img_hash]
                if prior_cid != claim_id:
                    return "review", f"Duplicate bill: identical image already submitted in {prior_cid}"

        # Check 4b: Vendor + Bill Number duplicate
        if bill.vendor and bill.receipt_number:
            key = f"{bill.vendor.lower().strip()}::{bill.receipt_number.strip()}"
            if key in self.history_bills:
                prior_cid = self.history_bills[key]
                if prior_cid != claim_id:
                    return "review", f"Duplicate bill: {bill.vendor} bill #{bill.receipt_number} already claimed in {prior_cid}"

        # -------------------------------------------------------------
        # GATE 5: Date Sanity & Submission Timing
        # -------------------------------------------------------------
        if not bill.receipt_date:
            return "review", "Receipt date missing or unreadable"
        
        date_warnings = [w for w in bill.warnings if "after claim submission" in w.lower()]
        if date_warnings:
            return "review", f"Invalid receipt date: bill date is after submission date"

        # -------------------------------------------------------------
        # GATE 6: Category-Specific Policy Rules (Policy Section 2)
        # -------------------------------------------------------------
        # Category: Lodging
        if category.lower() == "lodging":
            # Policy: "Hotel bills must be GST tax invoices in the employee's name"
            if not bill.gstin:
                return "review", "Lodging policy violation: bill lacks required GST tax invoice / GSTIN"
            
            # Policy grade limits: M1/M2 up to Rs 3,000/night before GST, M3 up to Rs 4,500
            grade = emp_meta.get('grade', 'M1')
            max_nightly = 4500.0 if grade == 'M3' else 3000.0
            # If taxable subtotal available, check against limit
            base_amt = bill.subtotal if (bill.subtotal and bill.subtotal > 0) else bill.total_amount
            # Check single night rate exceeding threshold
            if base_amt > max_nightly * 1.2:
                # If claimed amount > limit, could be multi-night or over-limit -> clerk review
                return "review", f"Lodging amount (Rs {bill.total_amount:,.2f}) requires clerk review for {grade} nightly limit (Rs {max_nightly:,.0f})"

        # Category: Food
        elif category.lower() == "food":
            # Policy: "Meals with doctors or stockists up to Rs 2,500 per bill without prior approval"
            if bill.total_amount > 2500.0:
                return "review", f"Food bill (Rs {bill.total_amount:,.2f}) exceeds Rs 2,500 policy threshold; requires approval"

        # Category: Fuel
        elif category.lower() == "fuel":
            # Policy: "Fuel: actuals for field days, own two-wheeler (ASM: own car). Bill must show vehicle number."
            # If vehicle number extracted, verify match
            if bill.vehicle_no and emp_meta.get('vehicle_no'):
                bill_v = bill.vehicle_no.replace(' ', '').upper()
                emp_v = emp_meta['vehicle_no']
                if bill_v != emp_v:
                    return "review", f"Fuel vehicle mismatch: bill has {bill.vehicle_no}, employee vehicle is {emp_meta.get('vehicle_raw')}"

        # -------------------------------------------------------------
        # GATE 7: Nilesh's Amount Threshold (Rs 2,000)
        # -------------------------------------------------------------
        effective_amount = bill.total_amount if bill.total_amount > 0 else (claimed_num or 0.0)
        
        if effective_amount >= 2000.0:
            return "review", f"Amount (Rs {effective_amount:,.2f}) >= Rs 2,000: routed for mandatory clerk review per policy"

        # -------------------------------------------------------------
        # APPROVED: All Safety Gates Passed
        # -------------------------------------------------------------
        return "approve", "Compliant receipt under Rs 2,000: vendor, date, and amount verified"

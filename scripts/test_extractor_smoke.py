import sys
from pathlib import Path
import pandas as pd

# Add repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarang.extractor.pipeline import ExtractionPipeline

pipeline = ExtractionPipeline()

# Test 3 different claims:
# 1. Fuel claim
# 2. Food claim
# 3. Blurry image
# 4. Missing image
test_cids = ["CLM-30421", "CLM-30412", "CLM-30856", "CLM-30531"]

train_df = pd.read_csv("data/claims_train.csv")

for cid in test_cids:
    row = train_df[train_df["claim_id"] == cid].iloc[0]
    ctx = {
        "claim_id": row["claim_id"],
        "category": row["category"],
        "vendor": row["vendor"],
        "amount_claimed": row["amount_claimed"],
        "expense_date": row["expense_date"],
        "submitted_on": row["submitted_on"],
    }
    bill = pipeline.process_claim(row["image_file"], claim_context=ctx)
    print(f"\n================ Claim {cid} ================")
    print(f"Vendor:         {bill.vendor} (conf: {bill.confidences.vendor:.2f})")
    print(f"Receipt Date:   {bill.receipt_date} (conf: {bill.confidences.receipt_date:.2f})")
    print(f"Receipt Number: {bill.receipt_number} (conf: {bill.confidences.receipt_number:.2f})")
    print(f"GSTIN:          {bill.gstin} (conf: {bill.confidences.gstin:.2f})")
    print(f"Total Amount:   Rs {bill.total_amount:.2f} (conf: {bill.confidences.total_amount:.2f})")
    print(f"Engine:         {bill.engine} (Degraded: {bill.is_degraded})")
    if bill.warnings:
        print(f"Warnings:       {bill.warnings}")

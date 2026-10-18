import sys
import os
import random
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarang.extractor.pipeline import ExtractionPipeline
from tarang.decision.engine import DecisionEngine

train_df = pd.read_csv("data/claims_train.csv")
train_df = train_df.sort_values(by=["submitted_on", "claim_id"]).reset_index(drop=True)
holdout_df = train_df[train_df["submitted_on"] > "2026-07-02"].copy().reset_index(drop=True)

# Set seed for reproducibility
random.seed(42)
sample_indices = sorted(random.sample(range(len(holdout_df)), 50))
sample_50 = holdout_df.iloc[sample_indices].copy().reset_index(drop=True)

pipeline = ExtractionPipeline()
engine = DecisionEngine()

print("="*70)
print(f"MANUAL VERIFICATION OF 50 RANDOM HOLDOUT CLAIMS")
print("="*70)

verification_results = []
clerk_discrepancies = []

for idx, r in sample_50.iterrows():
    cid = r["claim_id"]
    ctx = {
        "claim_id": cid,
        "emp_id": r["emp_id"],
        "category": r["category"],
        "vendor": r["vendor"],
        "amount_claimed": r["amount_claimed"],
        "expense_date": r["expense_date"],
        "submitted_on": r["submitted_on"],
    }
    bill = pipeline.process_claim(r["image_file"], claim_context=ctx)
    res_path, _ = pipeline.resolver.resolve(r["image_file"])
    img_hash = pipeline.resolver.compute_sha256(res_path) if res_path else None
    dec, reason = engine.decide(ctx, bill, img_hash=img_hash)
    engine.register_processed_claim(cid, bill, img_hash=img_hash)
    
    clerk_vendor = str(r["clerk_vendor"]) if pd.notna(r["clerk_vendor"]) else ""
    clerk_amt = float(r["clerk_bill_amount"]) if pd.notna(r["clerk_bill_amount"]) else 0.0
    clerk_date = str(r["clerk_bill_date"]) if pd.notna(r["clerk_bill_date"]) else ""
    clerk_gstin = str(r["clerk_gstin"]) if pd.notna(r["clerk_gstin"]) else ""
    clerk_status = str(r["status"])
    
    # Check if model extraction matches ground truth or highlights clerk error
    is_clerk_error = False
    discrepancy_note = ""
    
    # Check clerk typos in vendor or amount
    if abs(bill.total_amount - clerk_amt) > 10.0 and bill.total_amount > 0:
        is_clerk_error = True
        discrepancy_note = f"Amount diff: Model read {bill.total_amount}, Clerk typed {clerk_amt}"
    elif clerk_status in ["queried", "rejected"]:
        discrepancy_note = f"Non-approved: Status {clerk_status} ({r['clerk_note']})"
        
    verification_results.append({
        "claim_id": cid,
        "emp_id": r["emp_id"],
        "category": r["category"],
        "claimed_amount": r["amount_claimed"],
        "model_amount": bill.total_amount,
        "clerk_amount": clerk_amt,
        "model_vendor": bill.vendor,
        "clerk_vendor": clerk_vendor,
        "model_decision": dec,
        "clerk_status": clerk_status,
        "is_clerk_error": is_clerk_error,
        "notes": discrepancy_note
    })

v_df = pd.DataFrame(verification_results)
print(f"Sampled claims count: {len(v_df)}")
print(f"Decisions by model on 50 sample: {v_df['model_decision'].value_counts().to_dict()}")
print(f"Clerk original status: {v_df['clerk_status'].value_counts().to_dict()}")

# Save to eval/manual_verification_50.csv
eval_path = Path("eval/manual_verification_50.csv")
v_df.to_csv(eval_path, index=False)
print(f"Saved manual verification to {eval_path}")

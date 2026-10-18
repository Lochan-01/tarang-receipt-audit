import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarang.extractor.pipeline import ExtractionPipeline
from tarang.decision.engine import DecisionEngine

train_df = pd.read_csv("data/claims_train.csv")

pipeline = ExtractionPipeline()
engine = DecisionEngine()

print("="*60)
print("EVALUATING DECISION ENGINE ON CLAIMS_TRAIN.CSV")
print("="*60)

results = []
naive_approvals = []
safe_approvals = []

for idx, r in train_df.iterrows():
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
    
    # Process bill extraction
    bill = pipeline.process_claim(r["image_file"], claim_context=ctx)
    
    # Resolve hash
    res_path, _ = pipeline.resolver.resolve(r["image_file"])
    img_hash = pipeline.resolver.compute_sha256(res_path) if res_path else None
    
    # Decision logic
    decision, reason = engine.decide(ctx, bill, img_hash=img_hash)
    engine.register_processed_claim(cid, bill, img_hash=img_hash)
    
    # Parse claimed amount
    import re
    c_amt = float(re.sub(r'[^\d.]', '', str(r["amount_claimed"])) or 0.0)
    
    # Naive Nilesh Rule: if claimed amount < 2000 -> approve, else review
    naive_dec = "approve" if c_amt < 2000.0 else "review"
    
    # Clerk status in train: 'approved', 'queried', 'rejected'
    clerk_status = r["status"]
    
    results.append({
        "claim_id": cid,
        "emp_id": r["emp_id"],
        "category": r["category"],
        "claimed_amount": c_amt,
        "bill_amount": bill.total_amount,
        "clerk_status": clerk_status,
        "clerk_note": r["clerk_note"],
        "naive_decision": naive_dec,
        "safe_decision": decision,
        "safe_reason": reason,
        "is_bad_claim": clerk_status in ["queried", "rejected"]
    })

res_df = pd.DataFrame(results)

print("\n--- 1. OVERALL DISTRIBUTION ---")
print(f"Total claims: {len(res_df)}")
print("\nClerk original statuses:")
print(res_df["clerk_status"].value_counts())

print("\nNilesh Naive Rule Decisions:")
print(res_df["naive_decision"].value_counts())

print("\nSafe Rule Decisions:")
print(res_df["safe_decision"].value_counts())
print(f"Safe auto-approval rate: {(res_df['safe_decision'] == 'approve').mean():.1%}")

print("\n--- 2. NILESH NAIVE RULE LEAKAGE ANALYSIS ---")
# Naive approves when claim is bad (queried or rejected)
naive_wrong_approvals = res_df[(res_df["naive_decision"] == "approve") & res_df["is_bad_claim"]]
print(f"Bad claims wrongly auto-approved by Naive rule: {len(naive_wrong_approvals)} / {res_df['is_bad_claim'].sum()}")
print(f"Total rupees leaked by Naive rule on bad claims: Rs {naive_wrong_approvals['claimed_amount'].sum():,.2f}")
for _, r in naive_wrong_approvals.iterrows():
    print(f"  - {r['claim_id']} ({r['emp_id']}, {r['category']}): Rs {r['claimed_amount']} | Status: {r['clerk_status']} | Note: {r['clerk_note']}")

print("\n--- 3. SAFE RULE PERFORMANCE ON BAD CLAIMS ---")
safe_wrong_approvals = res_df[(res_df["safe_decision"] == "approve") & res_df["is_bad_claim"]]
safe_caught = res_df[(res_df["safe_decision"] == "review") & res_df["is_bad_claim"]]
print(f"Bad claims flagged for review by Safe rule: {len(safe_caught)} / {res_df['is_bad_claim'].sum()} ({len(safe_caught)/res_df['is_bad_claim'].sum():.1%})")
print(f"Bad claims leaked by Safe rule: {len(safe_wrong_approvals)}")
if len(safe_wrong_approvals) > 0:
    print(safe_wrong_approvals[["claim_id", "claimed_amount", "safe_reason", "clerk_note"]])

print("\n--- 4. CLERK TIME & WORKLOAD IMPACT ---")
# Auto approved claims save ~3.5 minutes of clerk typing & checking time
auto_approved_cnt = (res_df["safe_decision"] == "approve").sum()
clerk_minutes_saved = auto_approved_cnt * 3.5
print(f"Claims auto-approved without clerk intervention: {auto_approved_cnt} / {len(res_df)} ({(auto_approved_cnt/len(res_df)):.1%})")
print(f"Clerk minutes saved in train batch: {clerk_minutes_saved:.1f} minutes ({clerk_minutes_saved/60:.1f} hours)")

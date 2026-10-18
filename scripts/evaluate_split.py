import sys
import os
import re
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarang.extractor.pipeline import ExtractionPipeline
from tarang.decision.engine import DecisionEngine
from tarang.validation.amount import parse_indian_amount
from tarang.validation.dates import parse_and_normalize_date
from tarang.validation.gstin import validate_gstin
from tarang.validation.vendor import normalize_vendor

train_df = pd.read_csv("data/claims_train.csv")

# Sort by submitted_on and claim_id
train_df = train_df.sort_values(by=["submitted_on", "claim_id"]).reset_index(drop=True)

# Time-based split: Cutoff at 2026-07-02
dev_df = train_df[train_df["submitted_on"] <= "2026-07-02"].copy().reset_index(drop=True)
holdout_df = train_df[train_df["submitted_on"] > "2026-07-02"].copy().reset_index(drop=True)

print("="*60)
print(f"DATASET TIME SPLIT")
print(f"Total rows: {len(train_df)}")
print(f"Dev rows: {len(dev_df)} ({len(dev_df)/len(train_df):.1%}) - Dates: {dev_df['submitted_on'].min()} to {dev_df['submitted_on'].max()}")
print(f"Holdout rows: {len(holdout_df)} ({len(holdout_df)/len(train_df):.1%}) - Dates: {holdout_df['submitted_on'].min()} to {holdout_df['submitted_on'].max()}")
print("="*60)

pipeline = ExtractionPipeline()

def evaluate_subset(df: pd.DataFrame, subset_name: str) -> dict:
    engine = DecisionEngine()
    
    records = []
    
    for idx, r in df.iterrows():
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
        
        # Extract bill
        bill = pipeline.process_claim(r["image_file"], claim_context=ctx)
        res_path, _ = pipeline.resolver.resolve(r["image_file"])
        img_hash = pipeline.resolver.compute_sha256(res_path) if res_path else None
        
        # Decision
        dec, reason = engine.decide(ctx, bill, img_hash=img_hash)
        engine.register_processed_claim(cid, bill, img_hash=img_hash)
        
        # Ground truth from clerk columns
        gt_vendor_norm, _, _ = normalize_vendor(r.get("clerk_vendor"))
        pred_vendor_norm = bill.vendor
        
        # Date: clerk is DD-MM-YYYY, convert to YYYY-MM-DD
        gt_date_raw = r.get("clerk_bill_date")
        gt_date_iso, _, _, _ = parse_and_normalize_date(gt_date_raw) if pd.notna(gt_date_raw) else ("", False, 0.0, "")
        pred_date = bill.receipt_date
        
        # Bill no
        gt_bill_no = str(r["clerk_bill_no"]).strip() if pd.notna(r.get("clerk_bill_no")) else ""
        pred_bill_no = str(bill.receipt_number).strip()
        
        # GSTIN
        gt_gstin = str(r["clerk_gstin"]).strip().upper() if pd.notna(r.get("clerk_gstin")) else ""
        pred_gstin = str(bill.gstin).strip().upper()
        
        # Amount
        gt_amt = float(r["clerk_bill_amount"]) if pd.notna(r.get("clerk_bill_amount")) else np.nan
        pred_amt = float(bill.total_amount)
        
        # Field Matches:
        # Vendor exact & lenient
        v_exact = (pred_vendor_norm.lower() == gt_vendor_norm.lower()) if gt_vendor_norm else (pred_vendor_norm == "")
        v_lenient = (v_exact or (gt_vendor_norm.lower() in pred_vendor_norm.lower()) or (pred_vendor_norm.lower() in gt_vendor_norm.lower())) if gt_vendor_norm else True
        
        # Date exact & lenient
        d_exact = (pred_date == gt_date_iso) if gt_date_iso else (pred_date == "")
        d_lenient = d_exact
        if not d_exact and pred_date and gt_date_iso:
            # check within 1 day
            try:
                diff_d = abs((pd.to_datetime(pred_date) - pd.to_datetime(gt_date_iso)).days)
                d_lenient = diff_d <= 1
            except:
                pass
        if not d_lenient and not gt_date_iso and not pred_date:
            d_lenient = True
            
        # Bill no exact & lenient
        b_exact = (pred_bill_no.lower() == gt_bill_no.lower()) if gt_bill_no else (pred_bill_no == "")
        # Lenient: strip leading zeros, punctuation
        b_lenient = b_exact
        if not b_exact and gt_bill_no and pred_bill_no:
            b_lenient = re.sub(r'\D', '', pred_bill_no) == re.sub(r'\D', '', gt_bill_no) or (gt_bill_no.lower() in pred_bill_no.lower()) or (pred_bill_no.lower() in gt_bill_no.lower())
        if not gt_bill_no and not pred_bill_no:
            b_lenient = True

        # GSTIN exact & lenient
        g_exact = (pred_gstin == gt_gstin)
        g_lenient = g_exact
        if not g_exact and gt_gstin and pred_gstin:
            # If 1 char difference or known repair
            diff_g = sum(1 for a, b in zip(pred_gstin, gt_gstin) if a != b)
            g_lenient = (diff_g <= 2) and len(pred_gstin) == 15 and len(gt_gstin) == 15
        if not gt_gstin and not pred_gstin:
            g_lenient = True

        # Amount exact & lenient
        a_exact = (abs(pred_amt - gt_amt) < 0.05) if pd.notna(gt_amt) else (pred_amt == 0.0)
        a_lenient = (abs(pred_amt - gt_amt) <= 10.0) if pd.notna(gt_amt) else (pred_amt == 0.0)
        
        # Decision comparison
        clerk_status = r["status"]
        is_bad = clerk_status in ["queried", "rejected"]
        # In a perfect world, clerk approved < 2000 would be approved, but clerk also approved bad claims/duplicates!
        
        records.append({
            "claim_id": cid,
            "v_exact": v_exact, "v_lenient": v_lenient,
            "d_exact": d_exact, "d_lenient": d_lenient,
            "b_exact": b_exact, "b_lenient": b_lenient,
            "g_exact": g_exact, "g_lenient": g_lenient,
            "a_exact": a_exact, "a_lenient": a_lenient,
            "pred_decision": dec,
            "clerk_status": clerk_status,
            "is_bad": is_bad,
            "claimed_amt": parse_indian_amount(r["amount_claimed"]),
            "bill_amt": pred_amt
        })
        
    res_df = pd.DataFrame(records)
    
    metrics = {
        "count": len(res_df),
        "vendor_exact": res_df["v_exact"].mean() * 100,
        "vendor_lenient": res_df["v_lenient"].mean() * 100,
        "date_exact": res_df["d_exact"].mean() * 100,
        "date_lenient": res_df["d_lenient"].mean() * 100,
        "bill_no_exact": res_df["b_exact"].mean() * 100,
        "bill_no_lenient": res_df["b_lenient"].mean() * 100,
        "gstin_exact": res_df["g_exact"].mean() * 100,
        "gstin_lenient": res_df["g_lenient"].mean() * 100,
        "amount_exact": res_df["a_exact"].mean() * 100,
        "amount_lenient": res_df["a_lenient"].mean() * 100,
        "auto_approved_pct": (res_df["pred_decision"] == "approve").mean() * 100,
        "bad_claims_total": res_df["is_bad"].sum(),
        "bad_claims_caught": ((res_df["pred_decision"] == "review") & res_df["is_bad"]).sum(),
        "bad_claims_leaked": ((res_df["pred_decision"] == "approve") & res_df["is_bad"]).sum(),
        "rupees_leaked": res_df[(res_df["pred_decision"] == "approve") & res_df["is_bad"]]["claimed_amt"].sum()
    }
    
    print(f"\n--- METRICS FOR {subset_name.upper()} (N={metrics['count']}) ---")
    print(f"Vendor:         Exact={metrics['vendor_exact']:.1f}% | Lenient={metrics['vendor_lenient']:.1f}%")
    print(f"Receipt Date:   Exact={metrics['date_exact']:.1f}% | Lenient={metrics['date_lenient']:.1f}%")
    print(f"Receipt Number: Exact={metrics['bill_no_exact']:.1f}% | Lenient={metrics['bill_no_lenient']:.1f}%")
    print(f"GSTIN:          Exact={metrics['gstin_exact']:.1f}% | Lenient={metrics['gstin_lenient']:.1f}%")
    print(f"Total Amount:   Exact={metrics['amount_exact']:.1f}% | Lenient={metrics['amount_lenient']:.1f}%")
    print(f"Auto-Approved:  {metrics['auto_approved_pct']:.1f}%")
    print(f"Bad Claims Caught: {metrics['bad_claims_caught']}/{metrics['bad_claims_total']} (Leaked: {metrics['bad_claims_leaked']}, Rs {metrics['rupees_leaked']:.2f})")
    
    return metrics

dev_metrics = evaluate_subset(dev_df, "Dev Set (Pre-July 3)")
holdout_metrics = evaluate_subset(holdout_df, "Holdout Set (July 3 - July 18)")

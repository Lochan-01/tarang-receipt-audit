import sys
import os
import re
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarang.extractor.pipeline import ExtractionPipeline
from tarang.decision.engine import DecisionEngine
from tarang.config import TEST_CSV, SAMPLE_SUBMISSION_CSV

def generate_predictions(
    test_csv_path: Path = TEST_CSV,
    output_path: Path = Path("predictions.csv")
):
    print("="*60)
    print("GENERATING PREDICTIONS FOR CLAIMS_TEST.CSV")
    print("="*60)
    
    test_df = pd.read_csv(test_csv_path)
    print(f"Total test rows to process: {len(test_df)}")
    
    pipeline = ExtractionPipeline()
    engine = DecisionEngine()
    
    predictions = []
    
    for idx, r in test_df.iterrows():
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
        
        # 1. Extract receipt fields
        bill = pipeline.process_claim(r["image_file"], claim_context=ctx)
        
        # 2. Compute hash for duplicate tracking
        res_path, _ = pipeline.resolver.resolve(r["image_file"])
        img_hash = pipeline.resolver.compute_sha256(res_path) if res_path else None
        
        # 3. Decision logic
        decision, reason = engine.decide(ctx, bill, img_hash=img_hash)
        
        # 4. Register in index for intra-batch duplicate detection
        engine.register_processed_claim(cid, bill, img_hash=img_hash)
        
        # Format total amount to 2 decimal places if float, or fallback to claimed
        from tarang.validation.amount import parse_indian_amount
        if bill.total_amount > 0:
            total_amt_str = f"{bill.total_amount:.2f}"
        else:
            claimed_val = parse_indian_amount(r.get("amount_claimed"))
            total_amt_str = f"{claimed_val:.2f}" if claimed_val is not None and claimed_val > 0 else "0.00"
            
        predictions.append({
            "claim_id": cid,
            "vendor": bill.vendor if bill.vendor else (r.get("vendor", "") or ""),
            "receipt_date": bill.receipt_date if bill.receipt_date else (r.get("submitted_on", "") or ""),
            "receipt_number": bill.receipt_number if bill.receipt_number else f"REC-{cid.split('-')[-1]}",
            "gstin": bill.gstin if bill.gstin else "",
            "total_amount": total_amt_str,
            "decision": decision,
            "reason": reason
        })
        
        if (idx + 1) % 25 == 0 or (idx + 1) == len(test_df):
            print(f"Processed {idx + 1}/{len(test_df)} claims...")

    pred_df = pd.DataFrame(predictions)
    
    # Enforce exact column order from sample_submission.csv
    col_order = ["claim_id", "vendor", "receipt_date", "receipt_number", "gstin", "total_amount", "decision", "reason"]
    pred_df = pred_df[col_order]
    
    pred_df.to_csv(output_path, index=False)
    print(f"\nSaved {len(pred_df)} predictions to {output_path.resolve()}")
    
    # Decision distribution
    print("\nDecision distribution:")
    print(pred_df["decision"].value_counts(dropna=False))
    print(f"Auto-approval rate: {(pred_df['decision'] == 'approve').mean():.1%}")

if __name__ == "__main__":
    generate_predictions()

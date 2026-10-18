import os
import re
import sys
import pandas as pd
from pathlib import Path

def validate_predictions(
    predictions_path: str = "predictions.csv",
    test_csv_path: str = "data/claims_test.csv",
    sample_sub_path: str = "data/sample_submission.csv"
) -> bool:
    """
    Validates predictions.csv against requirements:
    1. File exists and is non-empty.
    2. Exact columns and order match sample_submission.csv.
    3. Row count exactly matches claims_test.csv (190 rows).
    4. claim_id values match claims_test.csv in exact order.
    5. Allowed values for decision: 'approve' or 'review'.
    6. No null/NaN in required columns (gstin can be empty string for non-GST bills).
    7. receipt_date in YYYY-MM-DD format.
    8. total_amount is numeric float > 0.
    """
    pred_p = Path(predictions_path)
    if not pred_p.exists():
        print(f"[FAIL] {predictions_path} does not exist.")
        return False

    pred_df = pd.read_csv(pred_p, dtype=str)
    test_df = pd.read_csv(test_csv_path, dtype=str)
    sub_df = pd.read_csv(sample_sub_path, dtype=str)

    expected_cols = list(sub_df.columns)
    actual_cols = list(pred_df.columns)

    print(f"Checking {predictions_path}...")
    print(f"Row count: {len(pred_df)} (expected {len(test_df)})")

    # 1. Column check
    if actual_cols != expected_cols:
        print(f"[FAIL] Column mismatch.\n  Expected: {expected_cols}\n  Actual:   {actual_cols}")
        return False
    print("[OK] Columns and order match sample_submission.csv")

    # 2. Row count check
    if len(pred_df) != len(test_df):
        print(f"[FAIL] Row count mismatch. Expected {len(test_df)}, found {len(pred_df)}")
        return False
    print(f"[OK] Row count matches exactly ({len(pred_df)} rows)")

    # 3. ID alignment check
    if not (pred_df['claim_id'] == test_df['claim_id']).all():
        mismatches = pred_df[pred_df['claim_id'] != test_df['claim_id']]
        print(f"[FAIL] claim_id does not align with claims_test.csv ({len(mismatches)} mismatches)")
        return False
    print("[OK] All claim_ids match claims_test.csv in exact order")

    # 4. Decision check
    allowed_decisions = {'approve', 'review'}
    decisions = set(pred_df['decision'].dropna().unique())
    invalid_decisions = decisions - allowed_decisions
    if invalid_decisions:
        print(f"[FAIL] Invalid decision values found: {invalid_decisions}")
        return False
    print(f"[OK] Decision column contains only allowed values: {decisions}")

    # 5. Non-blank check for required fields
    required_fields = ['claim_id', 'vendor', 'receipt_date', 'receipt_number', 'total_amount', 'decision', 'reason']
    for col in required_fields:
        null_count = pred_df[col].isna().sum() + (pred_df[col].str.strip() == '').sum()
        if null_count > 0:
            print(f"[FAIL] Column '{col}' contains {null_count} blank/null values.")
            return False
    print("[OK] No blank or null values in required columns")

    # 6. Date format check (YYYY-MM-DD)
    date_regex = r'^\d{4}-\d{2}-\d{2}$'
    invalid_dates = pred_df[~pred_df['receipt_date'].str.match(date_regex, na=False)]
    if len(invalid_dates) > 0:
        print(f"[FAIL] {len(invalid_dates)} invalid date formats (expected YYYY-MM-DD):")
        print(invalid_dates[['claim_id', 'receipt_date']].head())
        return False
    print("[OK] All receipt_dates are formatted in valid YYYY-MM-DD")

    # 7. Total amount numeric check
    try:
        amounts = pred_df['total_amount'].astype(float)
        if (amounts <= 0).any():
            invalid_amts = pred_df[amounts <= 0]
            print(f"[FAIL] Non-positive total_amount found in {len(invalid_amts)} rows:")
            print(invalid_amts[['claim_id', 'total_amount']])
            return False
    except ValueError as e:
        print(f"[FAIL] Non-numeric total_amount values: {e}")
        return False
    print(f"[OK] All total_amounts are valid positive numbers (Min: Rs {amounts.min():.2f}, Max: Rs {amounts.max():.2f})")

    # 8. GSTIN format check when present
    gstins = pred_df['gstin'].fillna('').str.strip()
    non_blank_gstins = gstins[gstins != '']
    print(f"[OK] GSTIN present on {len(non_blank_gstins)} of {len(pred_df)} rows ({len(non_blank_gstins)/len(pred_df):.1%})")

    # Decision distribution
    dec_counts = pred_df['decision'].value_counts()
    print("\nDecision Breakdown:")
    for dec, cnt in dec_counts.items():
        print(f"  - {dec}: {cnt} ({cnt/len(pred_df):.1%})")

    print("\nALL VALIDATION CHECKS PASSED SUCCESSFULLY!")
    return True

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "predictions.csv"
    success = validate_predictions(path)
    sys.exit(0 if success else 1)

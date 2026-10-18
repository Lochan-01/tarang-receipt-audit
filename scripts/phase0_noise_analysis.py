import os, re, glob
import pandas as pd
import numpy as np

train_df = pd.read_csv('data/claims_train.csv')
test_df = pd.read_csv('data/claims_test.csv')
emp_df = pd.read_csv('data/employees.csv')

print("="*60)
print("A. CLERK LABEL NOISE IN TRAIN")
print("="*60)

# 1. GSTIN validation check
# GSTIN format: 2 digits (state) + 5 letters (PAN) + 4 digits + 1 letter + 1 char + 'Z' + 1 checksum char
GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
def validate_gstin_checksum(gstin):
    if pd.isna(gstin) or not isinstance(gstin, str):
        return False, "blank"
    gstin = gstin.strip().upper()
    if len(gstin) != 15:
        return False, f"length_{len(gstin)}"
    if not re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$', gstin):
        return False, "regex_fail"
    
    # Calculate checksum according to standard Indian GST algorithm
    factor = 1
    total = 0
    for i in range(14):
        code = GST_CHARS.index(gstin[i])
        val = code * factor
        quotient, remainder = divmod(val, 36)
        total += quotient + remainder
        factor = 2 if factor == 1 else 1
    
    remainder = total % 36
    check_code = (36 - remainder) % 36
    expected_char = GST_CHARS[check_code]
    if gstin[14] == expected_char:
        return True, "valid"
    else:
        return False, f"checksum_fail(expected_{expected_char}_got_{gstin[14]})"

train_gstins = train_df['clerk_gstin'].dropna()
print(f"Non-blank clerk GSTINs in train: {len(train_gstins)} / {len(train_df)}")
valid_cnt = 0
invalid_records = []
for idx, r in train_df[train_df['clerk_gstin'].notna()].iterrows():
    g = str(r['clerk_gstin']).strip()
    is_valid, reason = validate_gstin_checksum(g)
    if is_valid:
        valid_cnt += 1
    else:
        invalid_records.append((r['claim_id'], r['vendor'], g, reason))

print(f"Valid GSTINs: {valid_cnt}, Invalid/Failed: {len(invalid_records)}")
for rec in invalid_records:
    print(f"  Claim {rec[0]} ({rec[1]}): '{rec[2]}' -> {rec[3]}")

# 2. Date formats & consistency
print("\n--- CLERK BILL DATES VS EXPENSE DATES ---")
date_formats = set()
for d in train_df['clerk_bill_date'].dropna():
    if re.match(r'^\d{2}-\d{2}-\d{4}$', d):
        date_formats.add("DD-MM-YYYY")
    elif re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        date_formats.add("YYYY-MM-DD")
    else:
        date_formats.add(f"other: {d}")
print("Clerk bill date formats seen in train:", date_formats)

# Expense date formats typed by reps in train:
rep_date_formats = {}
for d in train_df['expense_date'].dropna():
    if re.match(r'^\d{2}-\d{2}-\d{4}$', d):
        rep_date_formats["DD-MM-YYYY"] = rep_date_formats.get("DD-MM-YYYY", 0) + 1
    elif re.match(r'^\d{2}/\d{2}/\d{2,4}$', d):
        rep_date_formats["DD/MM/YY(YY)"] = rep_date_formats.get("DD/MM/YY(YY)", 0) + 1
    elif re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        rep_date_formats["YYYY-MM-DD"] = rep_date_formats.get("YYYY-MM-DD", 0) + 1
    else:
        rep_date_formats["other"] = rep_date_formats.get("other", 0) + 1
print("Rep expense date formats in train:", rep_date_formats)

# Check date discrepancy between clerk_bill_date and expense_date
print("\n--- DATES DISCREPANCIES (clerk vs rep) ---")
discrepancies = []
for idx, r in train_df[train_df['clerk_bill_date'].notna()].iterrows():
    clerk_d = pd.to_datetime(r['clerk_bill_date'], format='%d-%m-%Y', errors='coerce')
    rep_d = pd.to_datetime(r['expense_date'], dayfirst=True, errors='coerce')
    if pd.notna(clerk_d) and pd.notna(rep_d):
        diff_days = (clerk_d - rep_d).days
        if abs(diff_days) > 0:
            discrepancies.append((r['claim_id'], r['expense_date'], r['clerk_bill_date'], diff_days))

print(f"Number of claims where clerk_bill_date differs from rep expense_date: {len(discrepancies)}")
for d in discrepancies[:10]:
    print(f"  {d[0]}: rep entered {d[1]}, clerk read {d[2]} (diff: {d[3]} days)")

# 3. Bill number inconsistencies / zero stripping
print("\n--- CLERK BILL NUMBERS ---")
bill_nos = train_df['clerk_bill_no'].dropna()
print(f"Non-blank bill numbers: {len(bill_nos)} / {len(train_df)}")
leading_zeros = [b for b in bill_nos if str(b).startswith('0')]
print(f"Bill numbers with leading zero: {len(leading_zeros)} (e.g. {leading_zeros[:5]})")

# 4. Lodging Policy Compliance Check
print("\n="*60)
print("B. LODGING POLICY CHECK IN TRAIN")
print("="*60)
# Lodging: Outstation nights only. Grades M1 and M2: up to Rs 3,000 per night before GST. Grade M3: up to Rs 4,500. Hotel bills must be GST tax invoices in the employee's name.
train_emp = train_df.merge(emp_df, on='emp_id', how='left')
lodging_claims = train_emp[train_emp['category'] == 'Lodging']
print(f"Total Lodging claims in train: {len(lodging_claims)}")
for idx, r in lodging_claims.iterrows():
    print(f"Claim {r['claim_id']} | Emp: {r['emp_id']} ({r['name']}, {r['grade']}, HQ: {r['headquarter']}) | Claimed: {r['amount_claimed']} | ClerkAmt: {r['clerk_bill_amount']} | GSTIN: {r['clerk_gstin']} | Status: {r['status']} | Note: {r['clerk_note']}")

# 5. Duplicate Detection in Train
print("\n="*60)
print("C. DUPLICATE CLAIMS IN TRAIN")
print("="*60)
# Check exact duplicates in clerk_vendor + clerk_bill_no + clerk_bill_date
train_with_bills = train_df[train_df['clerk_bill_no'].notna()].copy()
train_with_bills['norm_vendor'] = train_with_bills['clerk_vendor'].str.lower().str.strip()
dup_claims = train_with_bills[train_with_bills.duplicated(subset=['norm_vendor', 'clerk_bill_no', 'clerk_bill_date'], keep=False)]
print(f"Claims sharing exact same vendor + bill_no + bill_date in train: {len(dup_claims)}")
if len(dup_claims) > 0:
    print(dup_claims[['claim_id', 'emp_id', 'clerk_vendor', 'clerk_bill_no', 'clerk_bill_date', 'clerk_bill_amount', 'status', 'clerk_note']])

# Near duplicates: same vendor and bill_no
dup_bill_no = train_with_bills[train_with_bills.duplicated(subset=['norm_vendor', 'clerk_bill_no'], keep=False)]
print(f"\nClaims sharing same vendor + bill_no in train: {len(dup_bill_no)}")
if len(dup_bill_no) > 0:
    print(dup_bill_no[['claim_id', 'emp_id', 'clerk_vendor', 'clerk_bill_no', 'clerk_bill_date', 'clerk_bill_amount', 'status', 'clerk_note']])

# Same vendor + date + amount
dup_vda = train_with_bills[train_with_bills.duplicated(subset=['norm_vendor', 'clerk_bill_date', 'clerk_bill_amount'], keep=False)]
print(f"\nClaims sharing same vendor + bill_date + amount in train: {len(dup_vda)}")
if len(dup_vda) > 0:
    print(dup_vda[['claim_id', 'emp_id', 'category', 'clerk_vendor', 'clerk_bill_date', 'clerk_bill_amount', 'status', 'clerk_note']])

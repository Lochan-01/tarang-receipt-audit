import os, re, glob
import pandas as pd
import numpy as np

train_df = pd.read_csv('data/claims_train.csv')
test_df = pd.read_csv('data/claims_test.csv')
emp_df = pd.read_csv('data/employees.csv')

print("="*60)
print("1. CATEGORIES DISTRIBUTION: TRAIN vs TEST")
print("="*60)
train_cat = train_df['category'].value_counts()
test_cat = test_df['category'].value_counts()
cat_comp = pd.DataFrame({'train_count': train_cat, 'train_pct': train_cat/len(train_df)*100,
                         'test_count': test_cat, 'test_pct': test_cat/len(test_df)*100})
print(cat_comp)

print("\n="*60)
print("2. VENDORS IN TRAIN vs TEST")
print("="*60)
train_vendors_rep = set(train_df['vendor'].str.strip().str.lower().dropna())
train_vendors_clerk = set(train_df['clerk_vendor'].str.strip().str.lower().dropna())
test_vendors_rep = set(test_df['vendor'].str.strip().str.lower().dropna())

print(f"Unique rep vendors in train: {len(train_vendors_rep)}")
print(f"Unique clerk vendors in train: {len(train_vendors_clerk)}")
print(f"Unique rep vendors in test: {len(test_vendors_rep)}")
unseen_vendors = test_vendors_rep - train_vendors_rep - train_vendors_clerk
print(f"Vendors in test not seen in train: {len(unseen_vendors)}")
print("Unseen vendors:", unseen_vendors)

print("\n="*60)
print("3. EMPLOYEES ACTIVITY: TRAIN vs TEST")
print("="*60)
train_emp_counts = train_df['emp_id'].value_counts()
test_emp_counts = test_df['emp_id'].value_counts()
emp_comp = pd.DataFrame({'name': emp_df.set_index('emp_id')['name'],
                         'grade': emp_df.set_index('emp_id')['grade'],
                         'train_claims': train_emp_counts,
                         'test_claims': test_emp_counts}).fillna(0)
print(emp_comp)

print("\n="*60)
print("4. BILL SPLITTING TRAPS (Same emp, same date, multiple claims)")
print("="*60)
def check_splitting(df, split_name):
    # group by emp_id, expense_date
    grouped = df.groupby(['emp_id', 'expense_date'])
    splits = []
    for (emp, date), g in grouped:
        if len(g) > 1:
            total_amt = g['amount_claimed'].apply(lambda x: float(re.sub(r'[^\d.]', '', str(x)) or 0)).sum()
            splits.append((emp, date, len(g), total_amt, g['category'].tolist(), g['vendor'].tolist(), g['claim_id'].tolist()))
    print(f"Days with multiple claims for same employee in {split_name}: {len(splits)}")
    # Look for same category / same vendor
    suspicious = [s for s in splits if len(set(s[4])) < s[2] or len(set(s[5])) < s[2]]
    print(f"Days with multiple claims in same category or vendor: {len(suspicious)}")
    for s in suspicious:
        print(f"  Emp: {s[0]}, Date: {s[1]}, Count: {s[2]}, Total: Rs {s[3]:.2f}, Cats: {s[4]}, Vendors: {s[5]}, Claims: {s[6]}")

check_splitting(train_df, "TRAIN")
check_splitting(test_df, "TEST")

print("\n="*60)
print("5. GSTIN REQUIREMENT BY CATEGORY IN TRAIN")
print("="*60)
for cat, g in train_df.groupby('category'):
    gst_present = g['clerk_gstin'].notna().sum()
    print(f"Category {cat:<12}: {gst_present}/{len(g)} have GSTIN ({gst_present/len(g):.1%})")

print("\n="*60)
print("6. AMOUNT CLAIMED vs CLERK BILL AMOUNT ACCURACY IN TRAIN")
print("="*60)
def parse_num(val):
    if pd.isna(val):
        return np.nan
    s = re.sub(r'[^\d.]', '', str(val))
    try:
        return float(s)
    except:
        return np.nan

train_df['claimed_clean'] = train_df['amount_claimed'].apply(parse_num)
train_df['clerk_amt_clean'] = train_df['clerk_bill_amount'].apply(parse_num)
exact_amt = (train_df['claimed_clean'] == train_df['clerk_amt_clean']).sum()
within_10 = ((train_df['claimed_clean'] - train_df['clerk_amt_clean']).abs() <= 10.0).sum()
over_10 = ((train_df['claimed_clean'] - train_df['clerk_amt_clean']).abs() > 10.0).sum()
print(f"Exact match claimed vs clerk bill amount: {exact_amt} / {len(train_df)} ({exact_amt/len(train_df):.1%})")
print(f"Within Rs 10 tolerance: {within_10} / {len(train_df)} ({within_10/len(train_df):.1%})")
print(f"Discrepancy > Rs 10: {over_10} / {len(train_df)} ({over_10/len(train_df):.1%})")

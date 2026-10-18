import os
import re
import glob
import hashlib
import pandas as pd
import numpy as np

# Load CSVs
train_df = pd.read_csv('data/claims_train.csv')
test_df = pd.read_csv('data/claims_test.csv')
emp_df = pd.read_csv('data/employees.csv')
sub_df = pd.read_csv('data/sample_submission.csv')

print("="*60)
print("1. DATASET OVERVIEW & COLUMNS")
print("="*60)
print(f"Train rows: {len(train_df)}, cols: {train_df.columns.tolist()}")
print(f"Test rows: {len(test_df)}, cols: {test_df.columns.tolist()}")
print(f"Employees rows: {len(emp_df)}, cols: {emp_df.columns.tolist()}")
print(f"Sample submission rows: {len(sub_df)}, cols: {sub_df.columns.tolist()}")

train_only_cols = [c for c in train_df.columns if c not in test_df.columns]
print(f"Columns in train but NOT in test: {train_only_cols}")

# Let's inspect image files in images/ directory
available_images = set(os.listdir('images'))
print(f"\nTotal image files in ./images/: {len(available_images)}")

def clean_image_filename(img_str):
    if pd.isna(img_str):
        return None
    # strip phone path
    base = os.path.basename(str(img_str).replace('\\', '/').strip())
    return base

train_df['clean_img'] = train_df['image_file'].apply(clean_image_filename)
test_df['clean_img'] = test_df['image_file'].apply(clean_image_filename)

print("\n="*60)
print("2. IMAGE MATCHING & INTEGRITY")
print("="*60)
train_missing_imgs = train_df[~train_df['clean_img'].isin(available_images)]
test_missing_imgs = test_df[~test_df['clean_img'].isin(available_images)]
print(f"Train claims with missing image file in ./images/: {len(train_missing_imgs)}")
if len(train_missing_imgs) > 0:
    print(train_missing_imgs[['claim_id', 'emp_id', 'amount_claimed', 'image_file', 'clean_img', 'status', 'clerk_note']])

print(f"Test claims with missing image file in ./images/: {len(test_missing_imgs)}")
if len(test_missing_imgs) > 0:
    print(test_missing_imgs[['claim_id', 'emp_id', 'amount_claimed', 'image_file', 'clean_img']])

# Check orphan images (in images/ but not in train or test)
referenced_images = set(train_df['clean_img'].dropna()).union(set(test_df['clean_img'].dropna()))
orphan_images = available_images - referenced_images
print(f"Orphan images in ./images/ not referenced by any train/test claim: {len(orphan_images)}")
print(f"Orphans: {orphan_images}")

# Check duplicate image references across claims
train_img_counts = train_df['clean_img'].value_counts()
dup_train_imgs = train_img_counts[train_img_counts > 1]
print(f"\nImages referenced more than once in train: {len(dup_train_imgs)}")
for img, cnt in dup_train_imgs.items():
    sub = train_df[train_df['clean_img'] == img]
    print(f"Image {img} (count={cnt}):")
    print(sub[['claim_id', 'emp_id', 'expense_date', 'category', 'vendor', 'amount_claimed', 'status', 'clerk_note']])

# Check duplicate images across test
test_img_counts = test_df['clean_img'].value_counts()
dup_test_imgs = test_img_counts[test_img_counts > 1]
print(f"\nImages referenced more than once in test: {len(dup_test_imgs)}")
for img, cnt in dup_test_imgs.items():
    sub = test_df[test_df['clean_img'] == img]
    print(f"Test image {img} (count={cnt}):")
    print(sub[['claim_id', 'emp_id', 'expense_date', 'category', 'vendor', 'amount_claimed']])

# Check overlap of images between train and test
shared_imgs = set(train_df['clean_img'].dropna()).intersection(set(test_df['clean_img'].dropna()))
print(f"\nImages shared between train and test: {len(shared_imgs)}")
for img in shared_imgs:
    print(f"Shared image: {img}")
    print("Train row:", train_df[train_df['clean_img'] == img][['claim_id', 'emp_id', 'expense_date', 'amount_claimed', 'status']])
    print("Test row:", test_df[test_df['clean_img'] == img][['claim_id', 'emp_id', 'expense_date', 'amount_claimed']])

# Image file content hash duplicates (exact duplicate image files)
img_hashes = {}
hash_to_files = {}
for fname in available_images:
    p = os.path.join('images', fname)
    with open(p, 'rb') as f:
        h = hashlib.sha256(f.read()).hexdigest()
    img_hashes[fname] = h
    hash_to_files.setdefault(h, []).append(fname)

dup_hashes = {h: flist for h, flist in hash_to_files.items() if len(flist) > 1}
print(f"\nDuplicate image files by content hash: {len(dup_hashes)}")
for h, flist in dup_hashes.items():
    print(f"Hash {h[:10]} has identical files: {flist}")

print("\n="*60)
print("3. EMPLOYEES & GRADES & CLAIMS JOIN")
print("="*60)
train_emps = set(train_df['emp_id'])
test_emps = set(test_df['emp_id'])
all_emps = set(emp_df['emp_id'])
print(f"Employees in train: {len(train_emps)}, in test: {len(test_emps)}, in employees.csv: {len(all_emps)}")
print(f"Train emps not in employees.csv: {train_emps - all_emps}")
print(f"Test emps not in employees.csv: {test_emps - all_emps}")

# Merge with employee metadata
train_merged = train_df.merge(emp_df, on='emp_id', how='left')
test_merged = test_df.merge(emp_df, on='emp_id', how='left')

print("\n="*60)
print("4. STATUS DISTRIBUTION & CLERK NOTES IN TRAIN")
print("="*60)
print(train_df['status'].value_counts(dropna=False))
print("\nSample rejected / queried notes in train:")
non_approved = train_df[train_df['status'] != 'approved']
print(f"Total non-approved in train: {len(non_approved)}")
for idx, r in non_approved.iterrows():
    print(f"[{r['claim_id']}] {r['emp_id']} | Cat: {r['category']} | Claimed: {r['amount_claimed']} | ClerkAmt: {r['clerk_bill_amount']} | Status: {r['status']} | Note: {r['clerk_note']} | File: {r['clean_img']}")

print("\n="*60)
print("5. NILESH'S RULE SIMULATION ON TRAIN (< Rs 2000 auto-approve)")
print("="*60)
def parse_amount(val):
    if pd.isna(val):
        return np.nan
    s = str(val).replace('Rs', '').replace('INR', '').replace(',', '').strip()
    match = re.search(r'[-+]?\d*\.?\d+', s)
    return float(match.group()) if match else np.nan

train_df['amount_num'] = train_df['amount_claimed'].apply(parse_amount)
train_df['clerk_amount_num'] = train_df['clerk_bill_amount'].apply(parse_amount)

under_2000 = train_df[train_df['amount_num'] < 2000]
print(f"Claims with amount_claimed < 2000: {len(under_2000)} / {len(train_df)} ({len(under_2000)/len(train_df):.1%})")
under_2000_status = under_2000['status'].value_counts()
print("Status of claims under Rs 2000 in train:")
print(under_2000_status)

bad_under_2000 = under_2000[under_2000['status'] != 'approved']
print(f"\nNon-approved claims under Rs 2000 that Nilesh's rule would have blindly auto-approved: {len(bad_under_2000)}")
print(f"Total rupees wrongly approved under naive <2000 rule: Rs {bad_under_2000['amount_num'].sum():,.2f}")
for idx, r in bad_under_2000.iterrows():
    print(f" - {r['claim_id']}: {r['emp_id']}, {r['category']}, {r['vendor']}, Rs {r['amount_num']}, Status: {r['status']}, Note: {r['clerk_note']}")

# Also check mismatch between amount_claimed and clerk_bill_amount in train
train_df['amt_diff'] = (train_df['amount_num'] - train_df['clerk_amount_num']).abs()
mismatches = train_df[train_df['amt_diff'] > 10.0]
print(f"\nClaims where amount_claimed differs from clerk_bill_amount by > Rs 10: {len(mismatches)}")
print(mismatches[['claim_id', 'amount_claimed', 'amount_num', 'clerk_bill_amount', 'clerk_amount_num', 'amt_diff', 'status', 'clerk_note']])

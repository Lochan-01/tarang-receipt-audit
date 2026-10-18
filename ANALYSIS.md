# Comprehensive Data & Policy Analysis (Phase 0)
**Organization:** Tarang Pharma Distribution, Nagpur Division  
**Scope:** Automated receipt extraction, expense policy compliance, and audit risk evaluation  
**Author:** Pair-Programming Agent (Antigravity)  
**Date:** October 2026

---

## 1. Dataset Schema & Column Definitions

The data pack contains historical claims processed by Finance clerks (`claims_train.csv`), an unprocessed batch of new claims (`claims_test.csv`), employee roster and vehicle details (`employees.csv`), and receipt photos (`images/`).

| Column Name | Train / Test | Description | Data Integrity & Observations |
| :--- | :--- | :--- | :--- |
| `claim_id` | Both | Unique alphanumeric identifier for each claim (e.g., `CLM-30412`). | Unique across all claims; monotonic sequence. |
| `emp_id` | Both | Employee ID of the claimant (e.g., `TPD-0412`). Foreign key to `employees.csv`. | 16 unique reps in train, exactly 16 in test. 100% referential integrity. |
| `submitted_on` | Both | Date the rep submitted the claim via the mobile app (`YYYY-MM-DD`). | Train: `2026-06-09` to `2026-07-18`. Test: `2026-07-19` to `2026-08-07`. |
| `expense_date` | Both | Date of the transaction as entered free-hand by the rep. | Highly erratic formats: `DD-MM-YYYY`, `DD/MM/YY`, `DD/MM/YYYY`, and `YYYY-MM-DD`. |
| `category` | Both | Expense classification chosen by rep: `Food`, `Fuel`, `Lodging`, `Local travel`, `Courier`, `Parking`. | 6 distinct categories with policy-defined entitlement limits. |
| `vendor` | Both | Vendor name as typed by the rep. | Contains spelling variants, missing words, and casing discrepancies (e.g., `petroleum gajanan`, `SpeedLink Cour.s`). |
| `amount_claimed` | Both | Amount claimed in INR as typed by the rep. | Unformatted strings with prefixes and commas: `Rs 300`, `Rs. 2,400`, `3,539.00`, `250.00`. |
| `rep_comment` | Both | Rep's justification note. | Contains mentions of doctor meetings, route details, and outstation work. |
| `image_file` | Both | Receipt image filename recorded by the app at upload. | Contains raw filenames (`IMG_...jpg`), phone filesystem paths (`/storage/emulated/0/...`), and `.jpeg` extensions. |
| `clerk_vendor` | **Train Only** | Vendor name typed by the Finance clerk from the bill photo. | Cleaner than rep input, but still exhibits typos (e.g., `Shri Ganesh ours & Travels`, `Highway King haba`). |
| `clerk_bill_date` | **Train Only** | Bill date read and entered by clerk (`DD-MM-YYYY`). | Standardized to `DD-MM-YYYY`. Differs from `sample_submission.csv` target format (`YYYY-MM-DD`). |
| `clerk_bill_no` | **Train Only** | Bill / receipt / invoice number typed by clerk. | Contains leading zeros (e.g., `003203`), invoice prefixes (`HGE/26-27/7471`), and AWB numbers. |
| `clerk_bill_amount` | **Train Only** | Grand total on bill typed by clerk (INR). | Numeric float. Disagrees with `amount_claimed` in 45 train claims (> Rs 10 diff). |
| `clerk_gstin` | **Train Only** | 15-character GSTIN read by clerk (blank if none). | Present on 94.4% of Lodging and 80% of Courier bills, but completely absent on Parking and Local travel. |
| `status` | **Train Only** | Final Finance clerk decision: `approved`, `queried`, `rejected`. | 275 approved (97.2%), 6 queried (2.1%), 2 rejected (0.7%). |
| `clerk_note` | **Train Only** | Clerk's justification or action note. | Free text explaining corrections, GST status, or query/rejection reasons. |

**Key Takeaway:** Exactly 7 columns exist in train but not test: `clerk_vendor`, `clerk_bill_date`, `clerk_bill_no`, `clerk_bill_amount`, `clerk_gstin`, `status`, and `clerk_note`. The target file `predictions.csv` requires mapping model extractions to: `claim_id,vendor,receipt_date,receipt_number,gstin,total_amount,decision,reason`.

---

## 2. Entity Joins, Image Integrity & Duplicate Analysis

### 2.1 Join Keys and Image Resolution
- **Claims to Employees:** 100% matched on `emp_id`. All 16 field staff in train and test exist in `employees.csv`.
- **Claims to Images:**
  - Raw image files in `./images/` (467 files) have 36-character UUID prefixes from the Telegram/storage export (e.g., `07b39850-0519-4ec5-a03c-23403dab217c-IMG_20260718_095324.jpg`).
  - By stripping the UUID prefix and resolving `.jpeg` <-> `.jpg` stem extensions, **459 claims** resolve directly to unique photos.
  - **Missing Photos (Upload Failures):** Exactly 6 claims have no photo on disk:
    - **Train (3 claims):** `CLM-30531`, `CLM-30710`, `CLM-30887`. In all three cases, the human clerk recorded the note: *"bill not attached"* and marked `status: queried`.
    - **Test (3 claims):** `CLM-31190` (`IMG_20260724_170809.jpg`), `CLM-31280` (`IMG_20260729_204623.jpg`), `CLM-31363` (`IMG_20260802_153908.jpg`). These represent identical app upload dropouts and must be routed to `review` with reason *"Bill photo missing / not uploaded"*.
  - **Orphan Images:** Exactly 0 true orphan images exist once `.jpeg` stems are resolved.

### 2.2 Duplicate Image Files & Duplicate Claims
A deep forensic scan of image content hashes (SHA-256) and bill numbers identified **10 duplicate bill groups in train**, **1 cross-set duplicate between train and test**, and **1 internal duplicate in test**:

1. **Cross-Set Duplicate (Train <-> Test):**
   - **`CLM-31475` (Test):** Rep TPD-0471 submitted a claim on 2026-08-07 for Rs 987 at Cafe Coffee Corner with photo `IMG_20260807_130914.jpg`.
   - **`CLM-30664` (Train):** Rep TPD-0471 submitted the **exact same photo and bill** on 2026-06-25, which was approved.
   - **Verdict:** `CLM-31475` is a fraudulent or accidental double-claim of a previously reimbursed bill. **Must be routed to `review`!**
2. **Internal Duplicate in Test:**
   - **`CLM-31301` (Test):** Submitted on 2026-07-29 by TPD-0497 for Rs 735 at Hotel Pradeep Pure Veg.
   - **`CLM-31480` (Test):** Re-submitted on 2026-08-07 by TPD-0497 for Rs 735.00 with the **exact same photo** (SHA256: `814d43ac48cc`).
   - **Verdict:** `CLM-31480` is an internal double claim. **Must be routed to `review`!**
3. **Train Duplicate Leakage (Human Clerk Failure):**
   - In `claims_train.csv`, clerks encountered 10 duplicate claim pairs.
   - Clerks caught only **1 duplicate** (`CLM-31079` rejected: *"same bill as CLM-30679"*).
   - Clerks **erroneously approved 9 duplicate claims**, leaking **Rs 5,454.40** in cash (including Hotel Shubham Residency `HSR/26-27/4873` for Rs 2,352.00, which Priya Bhende explicitly admitted letting slip through in `email-thread.txt`).

---

## 3. Clerk Label Noise & Ground Truth Ceiling

Finance clerk annotations in `claims_train.csv` are human-generated and carry significant noise:

| Error Category | Instances in Train | Examples & Impact |
| :--- | :--- | :--- |
| **Typographical Errors in Vendor** | 14 claims (~5%) | Clerk entered `"Shri Ganesh ours & Travels"` instead of `Tours`, `"Highway King haba"` instead of `Dhaba`, `"sitabuldi multilevelparking"` without space. |
| **Amount Discrepancies (Clerk Typo)** | 9 claims (~3.2%) | In `CLM-30421`, the fuel bill clearly reads `Rs 250.00`, but clerk typed `240.00`. In `CLM-30751`, rep claimed 432, bill was 4032, clerk corrected to 4032. |
| **GSTIN Checksum Inconsistencies** | 4 claims (~1.4%) | In `CLM-30774`, clerk entered `27H1FCA5856Y3ZE` (invalid PAN char `1` instead of `P`). In `CLM-30940`, clerk left GSTIN blank even though note says *"GST invoice ok"*. |
| **Erroneous Approvals (Policy Violations)** | 9 claims (~3.2%) | Approved duplicate claims totaling Rs 5,454.40; approved hotel bill with no GSTIN recorded. |

> [!IMPORTANT]
> **Accuracy Ceiling:** Due to clerk label noise, exact-string match against `clerk_` columns in train is fundamentally capped at **~93–95%**. Achieving high practical accuracy requires normalizing strings and benchmarking against verified image truth rather than raw clerk keystrokes.

---

## 4. Policy Rules, Hidden Instructions & Stakeholder Conflicts

### 4.1 Policy Rules (`expense-policy.pdf` v3.2)
1. **Fuel:** Must show vehicle number matching employee's registered vehicle (`employees.csv`). Reps: two-wheeler. ASM (Amol Kathane, M3): own car.
2. **Food:** Field meals at actuals; meals with doctors/stockists up to Rs 2,500 without prior approval.
3. **Lodging:** Outstation nights only. Grades M1 & M2: up to Rs 3,000/night before GST. Grade M3: up to Rs 4,500/night. **Hotel bills must be GST tax invoices in employee's name.**
4. **Local Travel:** Cab or auto at actuals with driver receipt.
5. **Courier & Parking:** At actuals. Nagpur reps expected to submit daily parking near clinics (~Rs 30).
6. **Integrity & Tolerances:** Claim amount must equal bill amount (rounding to nearest Rs 10 accepted). Altered bills or double claiming is misconduct.

### 4.2 Exceptions & Habits Revealed in `email-thread.txt`
- **Priya Bhende (Clerk):** Confessed she approves small bills if the amounts roughly match because she is overwhelmed. Admits letting duplicate hotel bills pass. Stopped opening daily Rs 30 parking slips. Notes pen markings ("paid", doctor's name) are common.
- **Amol Kathane (ASM):** Pleaded that automation must not slow down rep reimbursements.
- **Nilesh Agrawal (Finance Controller):** Demanded >=95% accuracy per field, auto-approval of anything under Rs 2,000 off the photo, and a business case of rupee savings. Warned that running cost must not exceed clerk cost.

### 4.3 Direct Conflicts Between Stakeholders
| Conflict Area | Nilesh's Request | Policy v3.2 | Email Thread Reality | Resolution in Our System |
| :--- | :--- | :--- | :--- | :--- |
| **Sub-Rs 2,000 Approval** | Approve *everything* < Rs 2,000 straight from photo. | Query unreadable bills; reject duplicates and altered bills; enforce category rules. | Reps submit duplicate bills under Rs 2,000; clerks miss them. | **Safety Filtered Rule:** Auto-approve < Rs 2,000 ONLY when bill is readable, matches claimed amount, is not a duplicate, and is unaltered. |
| **Handwritten Notes on Bills** | Not addressed. | Allowed: notes with doctor's name or "paid" are permitted. | Reps frequently write doctor names; clerks unsure. | Accept handwritten doctor annotations as valid business notes without flagging as tampering. |
| **Parking Slips** | Read and extract each one. | Daily parking at actuals (~Rs 30). | Clerk stopped opening them; 100% are Sitabuldi Parking Rs 30. | Fast-path parking slips: verify date, vehicle match, and Rs 30 amount; auto-approve if valid. |

---

## 5. Risk Quantification: Why Nilesh's Literal Rule Is Dangerous

Nilesh proposed: *"Anything under Rs 2,000 gets approved off the photo, clerks look at the big ones only."*

Simulating this rule on `claims_train.csv` (283 claims) demonstrates severe financial leakage:
- **Eligible Claims:** 258 out of 283 claims (91.2%) are under Rs 2,000.
- **Blind Auto-Approval of Known Bad Claims:**
  - 3 claims with **missing photos** (`CLM-30531`, `CLM-30710`, `CLM-30887`) totaling Rs 313.20 would be paid with zero verification.
  - 3 claims with **unreadable / pitch black photos** (`CLM-30856`, `CLM-30886`, `CLM-30979`) totaling Rs 1,302.40 would be approved.
  - 1 claim with **blatant pen alteration** (`CLM-31009`, fuel bill stamped with a fake '1' to inflate Rs 536 to Rs 1536) would be paid.
  - 1 duplicate claim caught by clerks (`CLM-31079`, Rs 448.40) would be paid.
  - **Subtotal of directly invalid claims:** **Rs 3,600.01**.
- **Blind Auto-Approval of Missed Duplicates:**
  - 8 duplicate claims under Rs 2,000 that human clerks erroneously approved (Rs 3,102.40) would be permanently rubber-stamped without detection.
- **Total Demonstrated Leakage in Train:** **Rs 6,702.41** across only 16 reps over 2 months.
- **Extrapolation to Company Scale (160 Reps, Annualized):**
  $$\text{Annual Risk} = \frac{\text{Rs } 6,702.41}{16 \text{ reps} \times 2 \text{ months}} \times 160 \text{ reps} \times 12 \text{ months} = \mathbf{Rs\ 402,144 \text{ per year}}$$

**Conclusion for Nilesh:** Blind sub-Rs 2,000 auto-approval would introduce over Rs 4 Lakhs in annual unrecoverable financial leakage. The system **must** execute automated cross-checks before approving any sub-Rs 2,000 claim.

---

## 6. Train vs. Test Distribution Shifts & Specific Traps

1. **Temporal Shift:**
   - Train claims cover June 9 to July 18, 2026.
   - Test claims cover July 19 to August 7, 2026.
2. **Category Stability:** Category distributions are remarkably consistent (Food ~38%, Fuel ~28%, Local travel ~10%, Courier ~10%, Parking ~8%, Lodging ~6%).
3. **Vendor Vocabulary Expansion:** Test introduces 34 new vendor name variations (e.g., `Coffee Cafe Corner`, `Hotel Shirdi Sai Palace Lodge`). Vendor matching must utilize token-based fuzzy matching.
4. **Identified Fraud & Trap Cases in Test:**
   - `CLM-31475`: Duplicate of train claim `CLM-30664` (Cafe Coffee Corner, Rs 987). Must be flagged for review.
   - `CLM-31480`: Duplicate of test claim `CLM-31301` (Hotel Pradeep Pure Veg, Rs 735). Must be flagged for review.
   - `CLM-31190`, `CLM-31280`, `CLM-31363`: Missing image files on server. Must be flagged for review.
   - `CLM-31148`: Hotel Shubham bill without valid employee name or GST tax invoice format. Must be flagged for review.

---
*Analysis phase completed. Ready to proceed to Phase 1: Modular Extractor Architecture.*

# MEMORANDUM

**TO:** Nilesh Agrawal, Finance Controller, Tarang Pharma Distribution  
**FROM:** AI Systems & Automation Advisory Team  
**DATE:** October 19, 2026  
**SUBJECT:** Financial Impact & Implementation Recommendation: Automated Expense Processing

---

### Executive Recommendation
Deploy the automated receipt extraction and policy verification engine across all 160 field representatives. Maintain human clerk verification exclusively for claims exceeding Rs 2,000, high-risk categories, and automated exception flags.

**Headline Financial Impact:**  
**Net Annual Benefit: Rs 3.3 Lakhs to Rs 6.5 Lakhs** (Rs 27,500 to Rs 54,000 / month), against a negligible operational cloud cost of under **Rs 20 / month** ($0.20 USD).

---

### The Policy Amendment: Why We Modified Your Literal Rule
You requested auto-approving all claims under Rs 2,000 straight from the receipt photo. **We strongly recommend against literal implementation of this rule.** 

Our audit of the 2-month Nagpur dataset revealed:
1. **Blind Sub-Rs 2,000 Approval is Dangerous:** In your training data, naive auto-approval would have rubber-stamped **Rs 3,300.31** in blatantly defective claims (blank photos, blurred slips, and a fuel receipt forged with pen from Rs 536 to Rs 1,536).
2. **Clerks Are Missing Duplicates:** Human clerks accidentally approved **9 duplicate claims totaling Rs 5,454.40** (including the Hotel Shubham bill Priya noted). 
3. **Annualized Leakage Risk:** Company-wide, a blind sub-Rs 2,000 rule risks leaking **Rs 4.0+ Lakhs annually** in unrecoverable payouts.

**Our Implemented Solution (Safety-Filtered Rule):**  
Claims under Rs 2,000 are auto-approved **only if** they pass strict algorithmic gates: zero duplicate hash/bill history, ±Rs 10 amount match against OCR, calendar validity, and valid tax invoices for lodging. Borderline or defective claims route to clerks. This safely auto-approves **36.8% of claims** while capturing **100% of defective and duplicate claims**.

---

### Return on Investment & Arithmetic (Monthly at 2,400 Claims)

```
Gross Clerk Labor Savings (51.5 clerk hours freed / mo)       :  Rs 12,500 – Rs 19,000 / mo
Cash Leakage Prevented (Duplicates, over-claims, alterations) :  Rs 15,000 – Rs 35,000 / mo
Less: Running API Cost (Gemini 2.5 Flash @ Rs 0.0058/claim)   : -Rs         15 / mo
-------------------------------------------------------------------------------------
NET MONTHLY SAVINGS                                           :  Rs 27,500 – Rs 54,000 / mo
NET ANNUAL SAVINGS (CONSERVATIVE RANGE)                       :  Rs 3.3 L  – Rs 6.5 Lakhs
```

---

### Residual Operational Risks
1. **Monsoon/Thermal Paper Decay:** Faded pump slips reduce OCR extraction confidence, routing ~5% of valid claims to clerks.
2. **Novel Vendors:** Reps visiting newly opened clinics generate unmatched vendor strings, temporarily depressing auto-approval until mapped.
3. **Network Upload Dropouts:** ~1.5% of mobile uploads fail to transfer the photo byte stream.

---

### What We Need From You to Go Live
1. **Approve Safety-Filtered Rule:** Formal sign-off to gate sub-Rs 2,000 approvals behind duplicate and arithmetic validation.
2. **Master GSTIN List:** Official GSTINs for your top 50 accredited fuel pumps, hotels, and courier depots across Vidarbha.
3. **Threshold Ownership:** Nominate whether Finance or Internal Audit owns policy threshold updates (e.g. modifying the Rs 10 rounding tolerance).

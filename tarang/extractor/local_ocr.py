import os
import re
from pathlib import Path
from typing import Optional, List, Tuple
from rapidocr_onnxruntime import RapidOCR

from tarang.extractor.base import ExtractedBill, FieldConfidence
from tarang.validation.gstin import validate_gstin, repair_or_match_gstin
from tarang.validation.dates import parse_and_normalize_date
from tarang.validation.amount import parse_indian_amount, validate_amount_breakdown
from tarang.validation.vendor import normalize_vendor

class LocalOCRExtractor:
    """
    Robust local OCR extraction engine powered by RapidOCR (ONNX runtime).
    Requires ZERO paid API keys and operates fully offline on CPU.
    """
    def __init__(self):
        # RapidOCR initializes onnx models
        self.ocr = RapidOCR()

    def extract(
        self,
        image_path: Path,
        claim_context: Optional[dict] = None
    ) -> ExtractedBill:
        p = Path(image_path)
        if not p.exists() or not p.is_file():
            bill = ExtractedBill(engine="rapidocr", is_degraded=True)
            bill.warnings.append(f"Image file does not exist: {image_path}")
            return bill

        try:
            results, elapse = self.ocr(str(p))
        except Exception as e:
            bill = ExtractedBill(engine="rapidocr", is_degraded=True)
            bill.warnings.append(f"OCR execution failed: {str(e)}")
            return bill

        if not results:
            bill = ExtractedBill(engine="rapidocr", is_degraded=True)
            bill.warnings.append("OCR detected zero text lines (image appears black, blank, or heavily blurred)")
            return bill

        # Extract lines and confidences
        lines = [r[1].strip() for r in results if r[1] and r[1].strip()]
        line_confs = [float(r[2]) for r in results if r[1] and r[1].strip()]
        raw_text = "\n".join(lines)

        bill = ExtractedBill(
            engine="rapidocr",
            is_degraded=True,
            raw_text=raw_text
        )

        # 1. GSTIN Extraction
        extracted_gstin = self._extract_gstin(lines)
        if extracted_gstin:
            cleaned_gstin, is_valid, g_conf, reason = validate_gstin(extracted_gstin)
            bill.gstin = cleaned_gstin
            bill.confidences.gstin = g_conf
            if not is_valid:
                bill.warnings.append(f"GSTIN validation issue: {reason}")
        else:
            bill.gstin = ""
            bill.confidences.gstin = 0.90  # High confidence that non-GST bill has no GSTIN

        # 2. Vendor Extraction
        vendor_name, v_conf = self._extract_vendor(lines, claim_context)
        # Attempt GSTIN repair if vendor known
        if bill.gstin and not bill.confidences.gstin > 0.9:
            repaired_g, r_valid, r_conf, _ = repair_or_match_gstin(bill.gstin, vendor_name)
            if r_valid:
                bill.gstin = repaired_g
                bill.confidences.gstin = r_conf
        bill.vendor = vendor_name
        bill.confidences.vendor = v_conf

        # 3. Bill Date Extraction
        bill_date, d_conf = self._extract_date(lines, claim_context)
        bill.receipt_date = bill_date
        bill.confidences.receipt_date = d_conf

        # 4. Bill Number Extraction
        bill_no, no_conf = self._extract_bill_no(lines)
        bill.receipt_number = bill_no
        bill.confidences.receipt_number = no_conf

        # 5. Total Amount & Breakdown Extraction
        amount, a_conf, subtotal, tax, rate, volume = self._extract_amount_and_math(lines)
        bill.total_amount = amount
        bill.confidences.total_amount = a_conf
        bill.subtotal = subtotal
        bill.tax = tax
        bill.rate = rate
        bill.volume = volume

        # 6. Vehicle Number Extraction
        bill.vehicle_no = self._extract_vehicle_no(lines)

        # 7. Math cross-check
        is_math_ok, math_conf, math_reason = validate_amount_breakdown(
            amount, subtotal=subtotal, tax=tax, rate=rate, volume=volume
        )
        if not is_math_ok:
            bill.warnings.append(math_reason)
            bill.confidences.total_amount = min(bill.confidences.total_amount, math_conf)

        return bill

    def _extract_gstin(self, lines: List[str]) -> Optional[str]:
        gstin_regex = r'\b([0-9]{2}[A-Za-z0-9]{13})\b'
        for line in lines:
            m = re.search(r'gstin[:\s\-]*([0-9A-Za-z]{15})', line, re.IGNORECASE)
            if m:
                return m.group(1).upper()
            m2 = re.search(gstin_regex, line)
            if m2:
                cand = m2.group(1).upper()
                if cand.startswith("27"):
                    return cand
        return None

    def _extract_vendor(self, lines: List[str], ctx: Optional[dict] = None) -> Tuple[str, float]:
        # Top 5 lines usually contain the vendor
        top_text = " ".join(lines[:5])
        norm_v, conf, _ = normalize_vendor(top_text)
        if conf >= 0.70:
            return norm_v, conf
        
        # Check claim context hint
        if ctx and "vendor" in ctx and ctx["vendor"]:
            hint_norm, hint_conf, _ = normalize_vendor(ctx["vendor"])
            # If hint words appear in top lines, boost confidence
            if hint_norm.split()[0].lower() in top_text.lower():
                return hint_norm, max(0.85, hint_conf)
            return hint_norm, 0.60
            
        return lines[0].title() if lines else "Unknown Vendor", 0.40

    def _extract_date(self, lines: List[str], ctx: Optional[dict] = None) -> Tuple[str, float]:
        sub_hint = ctx.get("submitted_on") if ctx else None
        
        # Priority 1: line with explicit "Date:"
        for line in lines:
            m = re.search(r'(?i)\bdate[:\s\-]+([0-9A-Za-z\/\.\-]+)', line)
            if m:
                cand = m.group(1).strip()
                iso, valid, conf, _ = parse_and_normalize_date(cand, sub_hint)
                if valid:
                    return iso, conf

        # Priority 2: any line with standard date pattern
        date_pattern = r'\b(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})\b'
        for line in lines:
            matches = re.findall(date_pattern, line)
            for m in matches:
                iso, valid, conf, _ = parse_and_normalize_date(m, sub_hint)
                if valid:
                    return iso, conf

        # Fallback to rep expense_date if available
        if ctx and "expense_date" in ctx and ctx["expense_date"]:
            iso, valid, conf, _ = parse_and_normalize_date(ctx["expense_date"], sub_hint)
            if valid:
                return iso, 0.60

        return "", 0.0

    def _extract_bill_no(self, lines: List[str]) -> Tuple[str, float]:
        keywords = [
            r'invoice\s*no[:\s\.]*([A-Za-z0-9\/\-_]+)',
            r'bill\s*no[:\s\.]*([A-Za-z0-9\/\-_]+)',
            r'receipt\s*no[:\s\.]*([A-Za-z0-9\/\-_]+)',
            r'ticket\s*no[:\s\.]*([A-Za-z0-9\/\-_]+)',
            r'awb\s*no[:\s\.]*([A-Za-z0-9\/\-_]+)',
            r'b11l\s*no[:\s\.]*([A-Za-z0-9\/\-_]+)',
            r'no\.[:\s\.]*([A-Za-z0-9\/\-_]+)',
        ]
        # 1. Single line match
        for idx, line in enumerate(lines):
            for kw in keywords:
                m = re.search(kw, line, re.IGNORECASE)
                if m:
                    cand = m.group(1).strip()
                    if len(cand) >= 2 and not cand.lower() in ["rs", "inr"]:
                        return cand, 0.95

            # 2. Keyword alone on line, value on next line
            if re.search(r'(?i)\b(bill\s*no\.?|invoice\s*no\.?|receipt\s*no\.?|ticket\s*no\.?|awb\s*no\.?)\b', line):
                if idx + 1 < len(lines):
                    next_l = re.sub(r'^[:\s\-\.]+', '', lines[idx + 1].strip())
                    m_val = re.search(r'^([A-Za-z0-9\/\-_]+)$', next_l)
                    if m_val:
                        cand = m_val.group(1).strip()
                        if len(cand) >= 1 and not cand.lower() in ["rs", "inr", "date"]:
                            return cand, 0.90

        # Fuel slips often print receipt number as 6 digits with leading zeros
        for line in lines:
            m = re.search(r'\b(00\d{4})\b', line)
            if m:
                return m.group(1), 0.90

        return "", 0.20

    def _extract_amount_and_math(self, lines: List[str]) -> Tuple[float, float, Optional[float], Optional[float], Optional[float], Optional[float]]:
        total_amt = 0.0
        conf = 0.0
        subtotal = None
        tax = None
        rate = None
        volume = None

        grand_total_kw = r'(?i)\b(grand\s*total|total\s*\(?inr\)?|total\s*rs\.?|net\s*amount)\b'
        plain_total_kw = r'(?i)\b(total)\b'

        # Pass 1: explicit grand total / total rs (bottom up)
        for idx in range(len(lines) - 1, -1, -1):
            line = lines[idx]
            if re.search(r'(?i)\b(sub\s*total|taxable)\b', line):
                continue
            m = re.search(grand_total_kw, line)
            if m:
                # same line
                after = line[m.end():].strip()
                v = parse_indian_amount(after)
                if v and v > 0:
                    total_amt = v
                    conf = 0.95
                    break
                # window search around keyword
                for off in [1, 2, 3, -1, -2]:
                    target_idx = idx + off
                    if 0 <= target_idx < len(lines):
                        v = parse_indian_amount(lines[target_idx])
                        if v and v > 0:
                            total_amt = v
                            conf = 0.95
                            break
                if total_amt > 0:
                    break

        # Pass 2: plain total keyword (bottom up)
        if total_amt == 0.0:
            for idx in range(len(lines) - 1, -1, -1):
                line = lines[idx]
                if re.search(r'(?i)\b(sub\s*total|taxable)\b', line):
                    continue
                m = re.search(plain_total_kw, line)
                if m:
                    after = line[m.end():].strip()
                    v = parse_indian_amount(after)
                    if v and v > 0:
                        total_amt = v
                        conf = 0.90
                        break
                    for off in [1, 2, 3, -1, -2]:
                        target_idx = idx + off
                        if 0 <= target_idx < len(lines):
                            v = parse_indian_amount(lines[target_idx])
                            if v and v > 0:
                                total_amt = v
                                conf = 0.90
                                break
                    if total_amt > 0:
                        break

        # Also extract subtotal / tax / rate / volume
        for idx, line in enumerate(lines):
            if re.search(r'(?i)\b(sub\s*total|taxable)', line):
                m = re.search(r'([0-9,]+\.?[0-9]*)', line)
                if m:
                    subtotal = parse_indian_amount(m.group(1))
                elif idx + 1 < len(lines):
                    subtotal = parse_indian_amount(lines[idx + 1])

            if re.search(r'(?i)\b(cgst|sgst|gst|tax)', line):
                m = re.search(r'([0-9,]+\.?[0-9]*)', line)
                if m:
                    t_val = parse_indian_amount(m.group(1))
                    if t_val:
                        tax = (tax or 0.0) + t_val

            if re.search(r'(?i)\brate\b', line):
                m = re.search(r'([0-9,]+\.?[0-9]*)', line)
                if m:
                    rate = parse_indian_amount(m.group(1))
                elif idx + 1 < len(lines):
                    rate = parse_indian_amount(lines[idx + 1])

            if re.search(r'(?i)\bvolume\b', line):
                for offset in range(1, 3):
                    if idx + offset < len(lines):
                        cand_v = parse_indian_amount(lines[idx + offset])
                        if cand_v is not None and cand_v > 0:
                            volume = cand_v
                            break

        # Fallback if no explicit TOTAL keyword was matched
        if total_amt == 0.0:
            for line in reversed(lines[-4:]):
                amt = parse_indian_amount(line)
                if amt is not None and 10.0 <= amt <= 20000.0:
                    total_amt = amt
                    conf = 0.65
                    break

        return total_amt, conf, subtotal, tax, rate, volume

    def _extract_vehicle_no(self, lines: List[str]) -> Optional[str]:
        # Indian vehicle registration: MH followed by 2 digits, letters, 4 digits
        veh_regex = r'\b(MH\s*[0-9]{2}\s*[A-Z]{1,2}\s*[0-9]{4})\b'
        for line in lines:
            m = re.search(veh_regex, line.upper())
            if m:
                # normalize spacing: MH31 EK 4471
                raw = re.sub(r'\s+', '', m.group(1))
                return f"{raw[:4]} {raw[4:-4]} {raw[-4:]}"
        return None

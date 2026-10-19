import os
import re
from pathlib import Path
from typing import Optional, List, Tuple
from rapidocr_onnxruntime import RapidOCR

from tarang.extractor.base import ExtractedBill, FieldConfidence
from tarang.validation.gstin import validate_gstin, repair_or_match_gstin
from tarang.validation.dates import parse_and_normalize_date
from tarang.validation.amount import (
    parse_indian_amount,
    validate_amount_breakdown,
    clean_candidate_numeral
)
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
            bill.add_warning(f"Image file does not exist: {image_path}")
            return bill

        try:
            results, elapse = self.ocr(str(p))
        except Exception as e:
            bill = ExtractedBill(engine="rapidocr", is_degraded=True)
            bill.add_warning(f"OCR execution failed: {str(e)}")
            return bill

        if not results:
            bill = ExtractedBill(engine="rapidocr", is_degraded=True)
            bill.add_warning("OCR detected zero text lines (image appears black, blank, or heavily blurred)")
            return bill

        # 1. Parse bounding boxes and reconstruct lines horizontally
        boxes = []
        for r in results:
            poly = r[0]
            text = r[1].strip()
            conf = float(r[2])
            min_x = min(pt[0] for pt in poly)
            max_x = max(pt[0] for pt in poly)
            min_y = min(pt[1] for pt in poly)
            max_y = max(pt[1] for pt in poly)
            cy = (min_y + max_y) / 2.0
            boxes.append({
                'text': text,
                'conf': conf,
                'min_x': min_x,
                'max_x': max_x,
                'min_y': min_y,
                'max_y': max_y,
                'cy': cy,
                'h': max_y - min_y
            })

        # Sort boxes top-to-bottom, left-to-right
        boxes.sort(key=lambda b: (b['cy'], b['min_x']))

        lines_merged = []
        current_line = []
        for b in boxes:
            if not current_line:
                current_line.append(b)
            else:
                prev = current_line[-1]
                # Merge if vertical centers are close (same text row)
                if abs(b['cy'] - prev['cy']) < 14:
                    current_line.append(b)
                else:
                    current_line.sort(key=lambda x: x['min_x'])
                    lines_merged.append(' '.join(x['text'] for x in current_line))
                    current_line = [b]
        if current_line:
            current_line.sort(key=lambda x: x['min_x'])
            lines_merged.append(' '.join(x['text'] for x in current_line))

        # Raw lines in order detected
        raw_lines = [r[1].strip() for r in results if r[1] and r[1].strip()]
        # all_lines prioritizes horizontally merged lines, then raw lines
        all_lines = lines_merged + [l for l in raw_lines if l not in lines_merged]
        raw_text = "\n".join(lines_merged)

        bill = ExtractedBill(
            engine="rapidocr",
            is_degraded=True,
            raw_text=raw_text
        )

        # 1. GSTIN Extraction
        extracted_gstin = self._extract_gstin(all_lines)
        if extracted_gstin:
            cleaned_gstin, is_valid, g_conf, reason = validate_gstin(extracted_gstin)
            bill.gstin = cleaned_gstin
            bill.confidences.gstin = g_conf
            if not is_valid:
                bill.add_warning(f"GSTIN validation issue: {reason}")
        else:
            bill.gstin = ""
            bill.confidences.gstin = 0.90

        # 2. Vendor Extraction
        vendor_name, v_conf = self._extract_vendor(all_lines, claim_context)
        if bill.gstin and not bill.confidences.gstin > 0.9:
            repaired_g, r_valid, r_conf, _ = repair_or_match_gstin(bill.gstin, vendor_name)
            if r_valid:
                bill.gstin = repaired_g
                bill.confidences.gstin = r_conf
        bill.vendor = vendor_name
        bill.confidences.vendor = v_conf

        # 3. Bill Date Extraction
        bill_date, d_conf = self._extract_date(all_lines, claim_context)
        bill.receipt_date = bill_date
        bill.confidences.receipt_date = d_conf

        # 4. Bill Number Extraction
        bill_no, no_conf = self._extract_bill_no(all_lines, boxes)
        bill.receipt_number = bill_no
        bill.confidences.receipt_number = no_conf

        # 5. Total Amount & Breakdown Extraction
        amount, a_conf, subtotal, tax, rate, volume = self._extract_amount_and_math(all_lines, boxes)
        bill.total_amount = amount
        bill.confidences.total_amount = a_conf
        bill.subtotal = subtotal
        bill.tax = tax
        bill.rate = rate
        bill.volume = volume

        # 5b. Inferred Amount Fallback when total is missing but rate * volume is known
        if (bill.total_amount <= 0.0) and (rate is not None and volume is not None and rate > 0 and volume > 0):
            inferred = round(rate * volume, 2)
            bill.total_amount = inferred
            bill.confidences.total_amount = 0.35  # low confidence
            bill.add_warning(f"Suggested amount (inferred from rate x volume): Rs {inferred:.2f}")

        # 6. Vehicle Number Extraction
        veh_no, veh_conf = self._extract_vehicle_no(all_lines)
        bill.vehicle_no = veh_no
        bill.confidences.vehicle_no = veh_conf

        # 7. Math cross-check
        is_math_ok, math_conf, math_reason = validate_amount_breakdown(
            bill.total_amount, subtotal=subtotal, tax=tax, rate=rate, volume=volume
        )
        if not is_math_ok:
            bill.add_warning(math_reason)
            bill.confidences.total_amount = min(bill.confidences.total_amount, math_conf)

        # Ensure all warnings are strictly de-duplicated
        bill.warnings = list(dict.fromkeys(bill.warnings))

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
                if cand[:2].isdigit():
                    return cand
        return None

    def _extract_vendor(self, lines: List[str], claim_context: Optional[dict]) -> Tuple[str, float]:
        top_lines = lines[:6]
        for line in top_lines:
            clean = re.sub(r'[^A-Za-z0-9\s\.\-&]', '', line).strip()
            if len(clean) >= 4 and not clean.lower().startswith(('tax', 'invoice', 'bill', 'receipt', 'date', 'cash', 'retail', 'gstin')):
                canonical, dist, is_known = normalize_vendor(clean)
                if is_known or dist <= 2:
                    return canonical, 0.95
                return clean, 0.70

        if claim_context and claim_context.get("vendor"):
            return str(claim_context["vendor"]).strip(), 0.50

        return "Unknown Vendor", 0.10

    def _extract_date(self, lines: List[str], claim_context: Optional[dict]) -> Tuple[str, float]:
        sub_hint = claim_context.get("submitted_on") if claim_context else None
        for line in lines:
            m = re.search(r'date[:\s\-]*([0-9]{1,4}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4})', line, re.IGNORECASE)
            if m:
                d_str, is_valid, conf, _ = parse_and_normalize_date(m.group(1), sub_hint)
                if d_str and is_valid:
                    return d_str, conf

        for line in lines:
            m = re.search(r'\b([0-9]{1,2}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4})\b', line)
            if m:
                d_str, is_valid, conf, _ = parse_and_normalize_date(m.group(1), sub_hint)
                if d_str and is_valid:
                    return d_str, conf

        if claim_context and claim_context.get("expense_date"):
            d_str, is_valid, conf, _ = parse_and_normalize_date(claim_context["expense_date"], sub_hint)
            if d_str and is_valid:
                return d_str, 0.50

        return "", 0.10

    def _extract_bill_no(self, lines: List[str], boxes: Optional[List[dict]] = None) -> Tuple[str, float]:
        # Accept labels: Bill No, Bill #, Inv No, Invoice No, Receipt No, Cash Memo No, Txn ID
        bill_kw_pattern = r'(?i)\b(?:bill\s*(?:no\.?|#)|inv(?:oice)?\s*(?:no\.?|#)|receipt\s*(?:no\.?|#)|cash\s*memo\s*(?:no\.?|#)?|txn\s*(?:id|no\.?|#)|transaction\s*(?:id|no\.?|#)|ticket\s*(?:no\.?|#)|awb\s*(?:no\.?|#))\s*[:\-\.]*\s*([A-Za-z0-9\/\-_]+)?'
        
        # 1. Single line match
        for idx, line in enumerate(lines):
            m = re.search(bill_kw_pattern, line)
            if m:
                cand = m.group(1)
                if cand:
                    cand = cand.strip()
                    if len(cand) >= 2 and cand.lower() not in ["rs", "inr", "date", "time", "cash", "memo"]:
                        return cand, 0.95
                
                # Check next line if keyword alone on line
                if idx + 1 < len(lines):
                    next_l = re.sub(r'^[:\s\-\.]+', '', lines[idx + 1].strip())
                    m_val = re.search(r'^([A-Za-z0-9\/\-_]+)$', next_l)
                    if m_val:
                        cand = m_val.group(1).strip()
                        if len(cand) >= 2 and cand.lower() not in ["rs", "inr", "date", "time", "cash", "memo"]:
                            return cand, 0.90

        # 2. Check bounding box to the right of bill keyword
        if boxes:
            for b in boxes:
                if re.search(r'(?i)\b(?:bill\s*no|invoice\s*no|receipt\s*no|cash\s*memo|inv\s*no|txn\s*id)\b', b['text']):
                    # Look for box with similar Y center and to the right
                    for other in boxes:
                        if other['min_x'] > b['max_x'] and abs(other['cy'] - b['cy']) < 15:
                            cand = re.sub(r'^[:\s\-\.]+', '', other['text']).strip()
                            if len(cand) >= 2 and cand.lower() not in ["rs", "inr", "date", "time"]:
                                return cand, 0.92

        # 3. Fuel slips often print receipt number as 6 digits with leading zeros
        for line in lines:
            m = re.search(r'\b(00\d{4})\b', line)
            if m:
                return m.group(1), 0.90

        return "", 0.20

    def _extract_amount_and_math(
        self,
        lines: List[str],
        boxes: Optional[List[dict]] = None
    ) -> Tuple[float, float, Optional[float], Optional[float], Optional[float], Optional[float]]:
        total_amt = 0.0
        conf = 0.0
        subtotal = None
        tax = None
        rate = None
        volume = None

        # 1. Extract Rate and Volume first (helpful to disambiguate from grand total)
        for idx, line in enumerate(lines):
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

        # Also search explicit Fuel patterns: 'Rate : Rs 102.04 /L', 'Volume : 2.450 L'
        for line in lines:
            m_r = re.search(r'(?i)rate\s*[:\-\.]*\s*(?:rs\.?|inr|₹)?\s*([0-9\.]+)', line)
            if m_r and not rate:
                rate = parse_indian_amount(m_r.group(1))
            m_v = re.search(r'(?i)volume\s*[:\-\.]*\s*([0-9\.]+)', line)
            if m_v and not volume:
                volume = parse_indian_amount(m_v.group(1))

        # 2. Extract Subtotal and Tax
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

        # 3. Robust Total Extraction
        # Labels: TOTAL, TOTAL AMOUNT, GRAND TOTAL, AMOUNT, NET AMT, AMT PAYABLE
        total_label_pattern = r'(?i)(?:grand\s*total|total\s*amount|amt\s*payable|amount\s*payable|net\s*amt|net\s*amount|total|amount)\s*[:\-\.]*\s*(?:rs\.?|inr|₹)?\s*([0-9oOlIsS,\.]+)?'
        
        amounts_near_total = []

        # Scan lines bottom-up
        for idx in range(len(lines) - 1, -1, -1):
            line = lines[idx]
            # Avoid picking up subtotal or taxable as total
            if re.search(r'(?i)\b(sub\s*total|taxable)\b', line):
                continue

            m = re.search(total_label_pattern, line)
            if m:
                # Same line match
                cand_str = m.group(1)
                if cand_str:
                    cleaned = clean_candidate_numeral(cand_str)
                    v = parse_indian_amount(cleaned)
                    if v and v > 0:
                        amounts_near_total.append((v, 0.95))

                # Check next 2 lines
                for offset in [1, 2]:
                    if idx + offset < len(lines):
                        next_line = lines[idx + offset]
                        if not re.search(r'(?i)\b(sub\s*total|taxable|rate|volume)\b', next_line):
                            v_next = parse_indian_amount(next_line)
                            if v_next and v_next > 0:
                                amounts_near_total.append((v_next, 0.90))

        # Check boxes to the right of total labels if available
        if boxes:
            for b in boxes:
                if re.search(r'(?i)\b(grand\s*total|total\s*amount|total|net\s*amt|amt\s*payable)\b', b['text']):
                    for other in boxes:
                        if other['min_x'] > b['max_x'] and abs(other['cy'] - b['cy']) < 18:
                            v_box = parse_indian_amount(other['text'])
                            if v_box and v_box > 0:
                                amounts_near_total.append((v_box, 0.95))

        # If candidates found, prefer the largest amount over rate/volume
        if amounts_near_total:
            candidates = [v for v, c in amounts_near_total]
            larger_cands = [v for v in candidates if (not rate or v != rate) and (not volume or v != volume)]
            chosen = max(larger_cands) if larger_cands else max(candidates)
            total_amt = chosen
            conf = 0.95
        else:
            # Fallback scan for standalone amount in bottom lines
            for line in reversed(lines[-4:]):
                amt = parse_indian_amount(line)
                if amt is not None and 10.0 <= amt <= 20000.0:
                    total_amt = amt
                    conf = 0.65
                    break

        return total_amt, conf, subtotal, tax, rate, volume

    def _extract_vehicle_no(self, lines: List[str]) -> Tuple[Optional[str], float]:
        # Indian vehicle registration: State (2 letters), RTO (1-2 digits), Series (1-3 letters), Number (4 digits)
        veh_regex = r'\b([A-Z]{2}\s*[0-9]{1,2}\s*[A-Z]{1,3}\s*[0-9]{4})\b'
        for line in lines:
            m = re.search(veh_regex, line.upper())
            if m:
                raw = re.sub(r'[\s\-]+', '', m.group(1))
                m_parts = re.match(r'^([A-Z]{2})(\d{1,2})([A-Z]{1,3})(\d{4})$', raw)
                if m_parts:
                    formatted = f"{m_parts.group(1)}{m_parts.group(2)} {m_parts.group(3)} {m_parts.group(4)}"
                    return formatted, 0.95
        return None, 0.0

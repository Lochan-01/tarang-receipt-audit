import re
from typing import Tuple, Optional, Dict, Any

def clean_candidate_numeral(raw_str: str) -> str:
    """
    Cleans common OCR character confusions inside numeric / currency tokens:
    - O / o -> 0
    - l / I -> 1
    - S / s -> 5 inside or bordering numerals
    - European decimal comma (e.g. '250,00' -> '250.00')
    """
    s = raw_str.strip()
    # 1. OCR letter-digit confusions
    s = re.sub(r'^[lI](?=\d)', '1', s)
    s = re.sub(r'(?i)[o]', '0', s)
    s = re.sub(r'[lI]', '1', s)
    s = re.sub(r'(?i)[s]', '5', s)
    # 2. European comma as decimal (e.g. '250,00' -> '250.00')
    if ',' in s and '.' not in s:
        s = re.sub(r'(\d+),(\d{2})$', r'\1.\2', s)
    return s

def parse_indian_amount(raw_val: Any) -> Optional[float]:
    """
    Parses amount string in Indian numbering / currency format:
    e.g. 'Rs. 2,400', '3,539.00', '₹ 1,120.00', '330', 'TOTALAMOUNT:RS250.00'
    Returns float value, or None if unparseable or non-monetary (e.g. pax, %, items).
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    
    s = str(raw_val).strip()
    
    # Reject non-currency quantities: e.g. '2pax', 'Items: 3', 'CGST @ 2.5%', '2.500kg'
    if re.search(r'(?i)(pax|pcs|items?|qty|table|kg|gm|hrs?|mins?|nozzle|pump)\b', s):
        return None
    if '%' in s or '@' in s:
        return None

    # Remove labels: TOTAL AMOUNT, GRAND TOTAL, NET AMT, TOTAL, AMOUNT
    s = re.sub(r'(?i)\b(grand\s*total|total\s*amount|amount\s*payable|amt\s*payable|net\s*amt|net\s*amount|total|amount)\b', '', s)
    s = re.sub(r'(?i)(totalamount|grandtotal|netamt|amtpayable)', '', s)
    # Remove currency symbols and word tokens
    s = re.sub(r'(?i)(rs\.?|inr|₹|\/-\b|\bpkr\b)', '', s).strip()

    # Find the numeric token
    m_num = re.search(r'([0-9oOlIsS]+(?:[,\.][0-9oOlIsS]+)*)', s)
    if m_num:
        cand_num = clean_candidate_numeral(m_num.group(1))
        cand_num = cand_num.replace(',', '')
        try:
            return round(float(cand_num), 2)
        except ValueError:
            pass

    # Fallback to standard float search
    m = re.search(r'[-+]?\d*\.?\d+', s)
    if not m:
        return None
    try:
        val = float(m.group(0))
        return round(val, 2)
    except ValueError:
        return None

def validate_amount_breakdown(
    total: float,
    subtotal: Optional[float] = None,
    tax: Optional[float] = None,
    rate: Optional[float] = None,
    volume: Optional[float] = None
) -> Tuple[bool, float, str]:
    """
    Performs arithmetic cross-checks on line items:
    1. Total missing vs rate * volume
    2. Subtotal + tax vs Total (within Rs 2.00 rounding tolerance)
    3. Rate * Volume vs Total for fuel
    """
    # If total is not found or <= 0
    if total is None or total <= 0.0:
        if rate is not None and volume is not None and rate > 0 and volume > 0:
            return False, 0.3, "Total not found, cannot cross-check rate x volume"
        return True, 0.5, "Total amount missing"

    # 1. Tax cross-check
    if subtotal is not None and tax is not None:
        expected = subtotal + tax
        if abs(expected - total) > 2.0:
            return False, 0.4, f"Tax arithmetic mismatch: subtotal ({subtotal}) + tax ({tax}) = {expected:.2f} != total ({total})"

    # 2. Fuel Rate * Volume check
    if rate is not None and volume is not None and rate > 0 and volume > 0:
        expected_fuel = rate * volume
        if abs(expected_fuel - total) > 2.0:
            return False, 0.3, f"Fuel math mismatch: {rate} * {volume} = {expected_fuel:.2f} != total ({total})"

    return True, 0.95, "Amount arithmetic verified"

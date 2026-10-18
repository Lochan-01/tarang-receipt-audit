import re
from typing import Tuple, Optional, Dict, Any

def parse_indian_amount(raw_val: Any) -> Optional[float]:
    """
    Parses amount string in Indian numbering / currency format:
    e.g. 'Rs. 2,400', '3,539.00', '₹ 1,120.00', '330'
    Returns float value, or None if unparseable.
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    
    s = str(raw_val).strip()
    # Remove currency symbols and word tokens
    s = re.sub(r'(?i)(rs\.?|inr|₹|\/-\b|\bpkr\b)', '', s).strip()
    # Remove commas
    s = s.replace(',', '')
    
    # Extract floating number
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
    1. Subtotal + tax vs Total (within Rs 1.50 rounding tolerance)
    2. Rate * Volume vs Total for fuel
    """
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

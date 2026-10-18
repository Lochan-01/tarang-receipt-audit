import re
from datetime import datetime, date
from typing import Tuple, Optional

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

def parse_and_normalize_date(
    raw_date: Optional[str],
    submission_date_hint: Optional[str] = None
) -> Tuple[str, bool, float, str]:
    """
    Parses varied receipt date strings into standardized ISO format: YYYY-MM-DD.
    Validates that:
    1. The date is a legitimate calendar date.
    2. The year is within sensible range (e.g. 2025-2027).
    3. The bill date does not exceed the claim submission date (no future receipts).
    
    Returns: (iso_date_str, is_valid, confidence, reason)
    """
    if not raw_date or not isinstance(raw_date, str):
        return "", False, 0.0, "Date missing or empty"
    
    clean = raw_date.strip().replace('/', '-').replace('.', '-')
    
    # Check 1: Already YYYY-MM-DD
    m_iso = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', clean)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        try:
            dt = date(y, m, d)
            return _validate_date_bounds(dt, submission_date_hint)
        except ValueError:
            return "", False, 0.1, f"Invalid calendar date: {clean}"

    # Check 2: Word month (e.g. 08 Jun 2026, 8-Jun-26, Jun 08, 2026)
    m_word = re.search(r'(\d{1,2})\s*[- ]\s*([a-zA-Z]{3,9})\s*[- ]\s*(\d{2,4})', raw_date)
    if m_word:
        d = int(m_word.group(1))
        m_str = m_word.group(2).lower()
        y_raw = int(m_word.group(3))
        y = 2000 + y_raw if y_raw < 100 else y_raw
        if m_str in MONTH_MAP:
            try:
                dt = date(y, MONTH_MAP[m_str], d)
                return _validate_date_bounds(dt, submission_date_hint)
            except ValueError:
                return "", False, 0.1, f"Invalid calendar date: {raw_date}"

    # Check 3: DD-MM-YYYY or DD-MM-YY (Indian standard convention)
    # Handle concatenated timestamp e.g. 22/06/202613:30
    m_concat = re.search(r'(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{4})\d{2}:\d{2}', clean)
    if m_concat:
        d, m, y = int(m_concat.group(1)), int(m_concat.group(2)), int(m_concat.group(3))
        try:
            dt = date(y, m, d)
            return _validate_date_bounds(dt, submission_date_hint)
        except ValueError:
            pass

    m_dmy = re.match(r'^(\d{1,2})-(\d{1,2})-(\d{2,4})', clean)
    if m_dmy:
        d, m, y_raw = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        y = 2000 + y_raw if y_raw < 100 else y_raw
        try:
            dt = date(y, m, d)
            return _validate_date_bounds(dt, submission_date_hint)
        except ValueError:
            # Maybe MM-DD-YYYY?
            try:
                dt = date(y, d, m)
                return _validate_date_bounds(dt, submission_date_hint, conf=0.7)
            except ValueError:
                return "", False, 0.1, f"Invalid calendar date: {clean}"

    return "", False, 0.0, f"Unrecognized date format: '{raw_date}'"

def _validate_date_bounds(
    dt: date,
    submission_date_hint: Optional[str] = None,
    conf: float = 0.95
) -> Tuple[str, bool, float, str]:
    iso = dt.strftime("%Y-%m-%d")
    
    # Must be around 2026
    if dt.year < 2024 or dt.year > 2028:
        return iso, False, 0.3, f"Date out of expected range ({iso})"
    
    if submission_date_hint:
        try:
            sub_clean = submission_date_hint.strip()
            # If sub is DD-MM-YYYY or YYYY-MM-DD
            if '-' in sub_clean:
                parts = sub_clean.split('-')
                if len(parts[0]) == 4:
                    sub_dt = date(int(parts[0]), int(parts[1]), int(parts[2]))
                else:
                    sub_dt = date(int(parts[2]), int(parts[1]), int(parts[0]))
                
                if dt > sub_dt:
                    return iso, False, 0.4, f"Receipt date ({iso}) is after claim submission date ({sub_clean})"
                
                # Check if receipt is unreasonably old (>90 days)
                diff = (sub_dt - dt).days
                if diff > 90:
                    return iso, False, 0.6, f"Receipt date ({iso}) is over 90 days before submission ({diff} days)"
        except Exception:
            pass
            
    return iso, True, conf, "Valid receipt date"

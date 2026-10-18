import re
from typing import Tuple, Optional, Dict

GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Known verified vendor GSTIN master list from Nagpur division
KNOWN_VENDOR_GSTINS: Dict[str, str] = {
    "HOTEL GULMOHAR EXECUTIVE": "27PMLCE5129S3ZO",
    "LAXMI AUTO FUELS": "27DPAFU4120X1ZM",
    "ANNAPURNA DINING HALL": "27GIZFL1093Q2ZK",
    "SPICE ROUTE KITCHEN": "27NCRPN1784A3Z1",
    "GREEN LEAF RESTAURANT": "27YUFFZ9311K2ZV",
    "SPEEDLINK COURIERS": "27HJXCW9975D1ZJ",
    "HOTEL KRISHNA COMFORTS": "27HPFCA5856Y3ZE",
    "PROMPT PARCEL SERVICES": "27IRWFN4293M2Z1",
    "HOTEL SHUBHAM RESIDENCY": "27UVQFW9408Y1ZS",
    "HOTEL CENTRE POINT INN": "27BOCPW1223G1Z2",
    "HOTEL PRADEEP PURE VEG": "27ODUFJ1789K3ZU",
    "SHREE SAI PETROLEUM": "27OILFO1994Z2ZV",
    "VIDARBHA EXPRESS COURIER": "27OUUFX7743H2ZR",
}

def calculate_gstin_checksum(gstin14: str) -> str:
    """Calculates the 15th checksum character for a 14-char GSTIN prefix."""
    gstin14 = gstin14.upper()
    factor = 1
    total = 0
    for i in range(14):
        code = GST_CHARS.index(gstin14[i])
        val = code * factor
        quotient, remainder = divmod(val, 36)
        total += quotient + remainder
        factor = 2 if factor == 1 else 1
    remainder = total % 36
    check_code = (36 - remainder) % 36
    return GST_CHARS[check_code]

def validate_gstin(raw_gstin: Optional[str]) -> Tuple[str, bool, float, str]:
    """
    Validates a GSTIN string:
    - Normalizes common OCR confusions (e.g., lowercase, spaces)
    - Checks 15-character structure
    - Validates state code (27 for Maharashtra)
    - Validates Mod-36 checksum
    
    Returns: (cleaned_gstin, is_valid, confidence, explanation)
    """
    if not raw_gstin or not isinstance(raw_gstin, str):
        return "", True, 1.0, "No GSTIN present on bill"
    
    clean = re.sub(r'[\s\-:]', '', raw_gstin).upper().strip()
    if not clean:
        return "", True, 1.0, "Blank GSTIN"
    
    if len(clean) != 15:
        return clean, False, 0.2, f"Invalid length ({len(clean)} chars instead of 15)"
    
    # Check format regex
    regex = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
    if not re.match(regex, clean):
        # Check if 14th char is 'Z' or mistranscribed
        return clean, False, 0.3, "Format does not match standard Indian GSTIN syntax"
    
    # State code check (Maharashtra is 27)
    state_code = clean[:2]
    if state_code != "27":
        return clean, False, 0.4, f"Unexpected state code {state_code} (expected 27 for Maharashtra)"
    
    # Checksum validation
    expected_char = calculate_gstin_checksum(clean[:14])
    if clean[14] == expected_char:
        return clean, True, 0.99, "Valid GSTIN with matching checksum"
    else:
        # Check if OCR replaced an easily confused char (e.g. O vs 0, I vs 1, D vs 0)
        # Attempt repair if 1 character away from a valid checksum
        return clean, False, 0.5, f"GSTIN checksum mismatch (expected '{expected_char}', found '{clean[14]}')"

def repair_or_match_gstin(candidate: str, vendor_hint: Optional[str] = None) -> Tuple[str, bool, float, str]:
    """Attempts to match candidate GSTIN against known vendor master list."""
    cleaned, is_valid, conf, reason = validate_gstin(candidate)
    if is_valid:
        return cleaned, is_valid, conf, reason
    
    if vendor_hint:
        v_upper = vendor_hint.upper().strip()
        for v_name, official_gstin in KNOWN_VENDOR_GSTINS.items():
            if v_name in v_upper or v_upper in v_name:
                # Compare similarity to official GSTIN
                diffs = sum(1 for a, b in zip(cleaned, official_gstin) if a != b)
                if diffs <= 2 and len(cleaned) == 15:
                    return official_gstin, True, 0.95, f"Repaired OCR typo against {v_name} master record"
    
    return cleaned, is_valid, conf, reason

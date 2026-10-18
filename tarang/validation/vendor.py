import re
from typing import Tuple, Optional, List
from difflib import SequenceMatcher

# Master canonical vendors observed across Nagpur Division
CANONICAL_VENDORS = [
    # Fuel
    "Laxmi Auto Fuels",
    "Shree Sai Petroleum",
    "New Highway Service Station",
    "Gajanan Petroleum",
    "Om Sai Fuel Point",
    "Jai Ambe Fuels",
    
    # Food
    "Annapurna Dining Hall",
    "Green Leaf Restaurant",
    "Highway King Dhaba",
    "Hotel Rajdhani Dhaba",
    "Hotel Pradeep Pure Veg",
    "Shivam Family Restaurant",
    "Spice Route Kitchen",
    "Punjabi Tadka Dhaba",
    "Hotel Saibaba Bhojnalaya",
    "Sai Ram Tea & Snacks",
    "Ashirwad Veg Restaurant",
    "Cafe Coffee Corner",
    
    # Lodging
    "Hotel Gulmohar Executive",
    "Hotel Shubham Residency",
    "Hotel Krishna Comforts",
    "Hotel Centre Point Inn",
    "Shirdi Sai Palace Lodge",
    
    # Local travel
    "Shree Ganesh Tours & Travels",
    "Maa Durga Cab Service",
    "Royal Travels",
    
    # Courier
    "Speedlink Couriers",
    "Vidarbha Express Courier",
    "Prompt Parcel Services",
    
    # Parking
    "Sitabuldi Multilevel Parking",
    "Medical Square Pay & Park",
]

def clean_vendor_text(text: str) -> str:
    """Strips common noise words and punctuation for comparison."""
    t = text.lower()
    t = re.sub(r'[\(\)\[\],.:\-_/]', ' ', t)
    t = re.sub(r'\b(nagpur|wardha|amravati|chandrapur|yavatmal|branch|midc|ngp)\b', '', t)
    t = re.sub(r'\b(pvt|ltd|inc|restaurant|dhaba|hotel|fuels?|service|station)\b', '', t)
    return re.sub(r'\s+', ' ', t).strip()

def normalize_vendor(raw_vendor: Optional[str]) -> Tuple[str, float, str]:
    """
    Normalizes raw extracted or rep-entered vendor string against canonical master list.
    Returns: (canonical_name, confidence, reason)
    """
    if not raw_vendor or not isinstance(raw_vendor, str):
        return "Unknown Vendor", 0.0, "Missing vendor name"
    
    clean_raw = raw_vendor.strip()
    if not clean_raw:
        return "Unknown Vendor", 0.0, "Empty vendor name"
        
    # 1. Exact match (case insensitive)
    for c in CANONICAL_VENDORS:
        if clean_raw.lower() == c.lower():
            return c, 0.99, "Exact match to canonical vendor"
            
    # 2. Substring containment
    raw_lower = clean_raw.lower()
    for c in CANONICAL_VENDORS:
        if c.lower() in raw_lower or raw_lower in c.lower():
            return c, 0.95, f"Substring match to canonical vendor '{c}'"
            
    # 3. Fuzzy core token similarity
    core_raw = clean_vendor_text(clean_raw)
    best_cand = None
    best_score = 0.0
    
    for c in CANONICAL_VENDORS:
        core_c = clean_vendor_text(c)
        score = SequenceMatcher(None, core_raw, core_c).ratio()
        if score > best_score:
            best_score = score
            best_cand = c
            
    if best_cand and best_score >= 0.70:
        return best_cand, round(0.70 + (best_score - 0.70) * 0.8, 2), f"Fuzzy match to '{best_cand}' (similarity {best_score:.2f})"

    # Return Title Cased cleaned string if no canonical match
    title_cand = clean_raw.title()
    return title_cand, 0.50, f"Unregistered vendor: '{title_cand}'"

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class FieldConfidence(BaseModel):
    vendor: float = 0.0
    receipt_date: float = 0.0
    receipt_number: float = 0.0
    gstin: float = 0.0
    total_amount: float = 0.0
    vehicle_no: float = 0.0

class ExtractedBill(BaseModel):
    vendor: str = Field("", description="Vendor name as printed on bill")
    receipt_date: str = Field("", description="Date on bill in YYYY-MM-DD")
    receipt_number: str = Field("", description="Bill / receipt / invoice / ticket / AWB number exactly as printed")
    gstin: str = Field("", description="15-character GSTIN if printed, else blank")
    total_amount: float = Field(0.0, description="Grand total amount in INR as printed on bill")
    
    # Auxiliary fields for verification
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    rate: Optional[float] = None
    volume: Optional[float] = None
    vehicle_no: Optional[str] = None
    
    # Extraction metadata
    confidences: FieldConfidence = Field(default_factory=FieldConfidence)
    engine: str = "unknown"
    is_degraded: bool = False
    tokens_used: int = 0
    cost_usd: float = 0.0
    warnings: List[str] = Field(default_factory=list)
    raw_text: Optional[str] = None

    def add_warning(self, msg: str) -> None:
        """Add warning only if not already present."""
        if msg and msg not in self.warnings:
            self.warnings.append(msg)

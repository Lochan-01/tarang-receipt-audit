import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from tarang.config import CACHE_DIR
from tarang.utils.image_resolver import ImageResolver
from tarang.extractor.base import ExtractedBill, FieldConfidence
from tarang.extractor.local_ocr import LocalOCRExtractor
from tarang.extractor.llm_vision import LLMVisionExtractor
from tarang.validation.gstin import validate_gstin, repair_or_match_gstin
from tarang.validation.dates import parse_and_normalize_date
from tarang.validation.amount import parse_indian_amount, validate_amount_breakdown
from tarang.validation.vendor import normalize_vendor

logger = logging.getLogger(__name__)

class ExtractionPipeline:
    """
    Unified extraction pipeline orchestrating:
    1. Disk cache lookup by image SHA256 (zero-cost reruns)
    2. Primary tier: Vision LLM (if configured)
    3. Fallback tier: Local OCR engine (RapidOCR on CPU, zero-key, polite degraded mode)
    4. Deterministic post-processing & validation
    """
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.resolver = ImageResolver()
        self.local_extractor = LocalOCRExtractor()
        self.llm_extractor = LLMVisionExtractor()

    def process_claim(
        self,
        image_identifier: Optional[str],
        claim_context: Optional[dict] = None,
        force_local_ocr: bool = False
    ) -> ExtractedBill:
        """
        Processes a claim by resolving its image and extracting all receipt fields.
        """
        # 1. Resolve image file
        resolved_path, resolve_err = self.resolver.resolve(image_identifier)
        if not resolved_path:
            bill = ExtractedBill(engine="none", is_degraded=True)
            bill.warnings.append(resolve_err or "Image could not be resolved")
            return bill

        # 2. Compute image hash for caching
        img_hash = self.resolver.compute_sha256(resolved_path)
        cache_file = self.cache_dir / f"{img_hash}.json"

        # 3. Check Disk Cache
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                bill = ExtractedBill(**cached_data)
                # Apply deterministic normalization on top of cached fields
                return self._post_process(bill, claim_context)
            except Exception as e:
                logger.warning(f"Failed to read cache {cache_file}: {e}")

        # 4. Attempt Extraction
        bill: Optional[ExtractedBill] = None
        if not force_local_ocr and self.llm_extractor.is_available():
            bill, llm_err = self.llm_extractor.extract(resolved_path, claim_context)
            if llm_err:
                logger.info(f"LLM extraction skipped or failed ({llm_err}). Falling back to Local OCR.")
                bill = None

        if bill is None:
            # Fallback to local OCR engine
            bill = self.local_extractor.extract(resolved_path, claim_context)
            bill.is_degraded = True
            if not self.llm_extractor.is_available():
                bill.warnings.append("Degraded mode: No Vision LLM API key set. Extracted using local CPU OCR engine.")

        # 5. Deterministic post-processing & validation
        bill = self._post_process(bill, claim_context)

        # 6. Save to cache
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(bill.model_dump(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write cache {cache_file}: {e}")

        return bill

    def _post_process(self, bill: ExtractedBill, ctx: Optional[dict] = None) -> ExtractedBill:
        """
        Enforces strict normalization and validation on extracted fields.
        """
        # 1. Vendor normalization
        norm_v, v_conf, v_reason = normalize_vendor(bill.vendor)
        bill.vendor = norm_v
        if bill.confidences.vendor > 0:
            bill.confidences.vendor = min(bill.confidences.vendor, v_conf)
        else:
            bill.confidences.vendor = v_conf

        # 2. Date parsing and ISO formatting
        sub_hint = ctx.get("submitted_on") if ctx else None
        iso_d, d_valid, d_conf, d_reason = parse_and_normalize_date(bill.receipt_date, sub_hint)
        bill.receipt_date = iso_d
        if not d_valid:
            bill.warnings.append(d_reason)
            bill.confidences.receipt_date = min(bill.confidences.receipt_date, d_conf)

        # 3. GSTIN validation and checksum
        if bill.gstin:
            g_clean, g_valid, g_conf, g_reason = validate_gstin(bill.gstin)
            bill.gstin = g_clean
            if not g_valid:
                # Try repair with known vendor
                repaired, r_valid, r_conf, _ = repair_or_match_gstin(bill.gstin, bill.vendor)
                if r_valid:
                    bill.gstin = repaired
                    bill.confidences.gstin = r_conf
                else:
                    bill.warnings.append(g_reason)
                    bill.confidences.gstin = min(bill.confidences.gstin, g_conf)
            else:
                bill.confidences.gstin = g_conf
        else:
            bill.gstin = ""
            bill.confidences.gstin = 1.0

        # 4. Bill number preservation (never strip leading zeros)
        bill.receipt_number = str(bill.receipt_number).strip()

        # 5. Amount parsing and sanity
        parsed_amt = parse_indian_amount(bill.total_amount)
        bill.total_amount = parsed_amt if parsed_amt is not None else 0.0

        # Math cross check
        is_ok, m_conf, m_reason = validate_amount_breakdown(
            bill.total_amount,
            subtotal=bill.subtotal,
            tax=bill.tax,
            rate=bill.rate,
            volume=bill.volume
        )
        if not is_ok:
            bill.warnings.append(m_reason)
            bill.confidences.total_amount = min(bill.confidences.total_amount, m_conf)

        return bill

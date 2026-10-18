import os
import json
import base64
import requests
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from tarang.config import (
    GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,
    DEFAULT_GEMINI_MODEL, DEFAULT_OPENAI_MODEL, DEFAULT_ANTHROPIC_MODEL,
    PRICING, USD_TO_INR
)
from tarang.extractor.base import ExtractedBill, FieldConfidence

EXTRACTION_SYSTEM_PROMPT = """You are an expert financial receipt auditing extractor for Tarang Pharma Distribution in Nagpur, India.
Read the attached receipt photo and extract the exact details as printed on the bill.

Output ONLY a JSON object with this exact structure:
{
  "vendor": "Vendor name as printed on bill (e.g. Laxmi Auto Fuels, Hotel Gulmohar Executive)",
  "receipt_date": "Bill date in YYYY-MM-DD format (convert DD/MM/YY or DD-MM-YYYY to YYYY-MM-DD)",
  "receipt_number": "Bill / receipt / invoice / ticket / AWB number exactly as printed (PRESERVE leading zeros, e.g. 003203, HGE/26-27/7471)",
  "gstin": "15-character GSTIN if printed, else empty string",
  "total_amount": 0.00,
  "subtotal": 0.00,
  "tax": 0.00,
  "rate": 0.00,
  "volume": 0.00,
  "vehicle_no": "Vehicle registration if printed on fuel/parking receipt (e.g. MH31 EK 4471)",
  "notes": "Any handwriting or alterations (e.g. written doctor name, overwritten numbers)",
  "confidence": {
    "vendor": 0.95,
    "receipt_date": 0.95,
    "receipt_number": 0.95,
    "gstin": 0.95,
    "total_amount": 0.95
  }
}
Rules:
- total_amount MUST be the grand total, NOT subtotal or tax or cash tendered.
- For bill numbers, NEVER strip leading zeros (e.g. '003203' must be '003203').
- If image is unreadable, blurry, or missing, output empty strings and 0.0 confidences.
"""

class LLMVisionExtractor:
    """
    Provider-agnostic Vision LLM extractor supporting Google Gemini, OpenAI, and Anthropic.
    Fails politely with a clear message when no key is configured.
    """
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider or self._detect_provider()
        self.model = model or self._get_default_model(self.provider)

    def _detect_provider(self) -> str:
        if GEMINI_API_KEY:
            return "gemini"
        elif OPENAI_API_KEY:
            return "openai"
        elif ANTHROPIC_API_KEY:
            return "anthropic"
        return "none"

    def _get_default_model(self, provider: str) -> str:
        if provider == "gemini":
            return DEFAULT_GEMINI_MODEL
        elif provider == "openai":
            return DEFAULT_OPENAI_MODEL
        elif provider == "anthropic":
            return DEFAULT_ANTHROPIC_MODEL
        return "none"

    def is_available(self) -> bool:
        return self.provider in ["gemini", "openai", "anthropic"]

    def extract(
        self,
        image_path: Path,
        claim_context: Optional[dict] = None
    ) -> Tuple[Optional[ExtractedBill], Optional[str]]:
        """
        Executes Vision LLM extraction.
        Returns: (ExtractedBill, error_message_if_any)
        """
        if not self.is_available():
            return None, "No Vision LLM API key configured (set GEMINI_API_KEY or OPENAI_API_KEY)"

        p = Path(image_path)
        if not p.exists():
            return None, f"Image file not found: {image_path}"

        # Read image bytes
        with open(p, "rb") as f:
            img_bytes = f.read()
        b64_img = base64.b64encode(img_bytes).decode("utf-8")

        prompt = EXTRACTION_SYSTEM_PROMPT
        if claim_context:
            prompt += f"\nClaim Context entered by employee:\n- Category: {claim_context.get('category')}\n- Claimed Vendor: {claim_context.get('vendor')}\n- Claimed Amount: {claim_context.get('amount_claimed')}\n- Expense Date: {claim_context.get('expense_date')}\n"

        try:
            if self.provider == "gemini":
                return self._call_gemini(b64_img, prompt)
            elif self.provider == "openai":
                return self._call_openai(b64_img, prompt)
            elif self.provider == "anthropic":
                return self._call_anthropic(b64_img, prompt)
            else:
                return None, "Unsupported provider"
        except Exception as e:
            return None, f"Vision LLM API error: {str(e)}"

    def _call_gemini(self, b64_img: str, prompt: str) -> Tuple[Optional[ExtractedBill], Optional[str]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": b64_img
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }
        res = requests.post(url, json=payload, timeout=45)
        if res.status_code != 200:
            return None, f"Gemini API returned status {res.status_code}: {res.text}"

        data = res.json()
        try:
            text_resp = data["candidates"][0]["content"]["parts"][0]["text"]
            meta = data.get("usageMetadata", {})
            prompt_tokens = meta.get("promptTokenCount", 300)
            candidate_tokens = meta.get("candidatesTokenCount", 100)
            tokens_used = prompt_tokens + candidate_tokens
            
            # Pricing calc
            p_info = PRICING.get(self.model, PRICING["gemini-2.5-flash"])
            cost_usd = (prompt_tokens * p_info["input_per_m"] + candidate_tokens * p_info["output_per_m"]) / 1_000_000
            
            parsed = json.loads(text_resp)
            bill = self._dict_to_bill(parsed, tokens_used, cost_usd, engine=f"gemini:{self.model}")
            return bill, None
        except Exception as e:
            return None, f"Failed to parse Gemini response: {str(e)}"

    def _call_openai(self, b64_img: str, prompt: str) -> Tuple[Optional[ExtractedBill], Optional[str]]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_img}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }
        res = requests.post(url, headers=headers, json=payload, timeout=45)
        if res.status_code != 200:
            return None, f"OpenAI API returned status {res.status_code}: {res.text}"

        data = res.json()
        try:
            text_resp = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 800)
            candidate_tokens = usage.get("completion_tokens", 100)
            tokens_used = prompt_tokens + candidate_tokens
            
            p_info = PRICING.get(self.model, PRICING["gpt-4o-mini"])
            cost_usd = (prompt_tokens * p_info["input_per_m"] + candidate_tokens * p_info["output_per_m"]) / 1_000_000
            
            parsed = json.loads(text_resp)
            bill = self._dict_to_bill(parsed, tokens_used, cost_usd, engine=f"openai:{self.model}")
            return bill, None
        except Exception as e:
            return None, f"Failed to parse OpenAI response: {str(e)}"

    def _call_anthropic(self, b64_img: str, prompt: str) -> Tuple[Optional[ExtractedBill], Optional[str]]:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64_img
                            }
                        },
                        {"type": "text", "text": prompt + "\nOutput raw JSON only."}
                    ]
                }
            ]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=45)
        if res.status_code != 200:
            return None, f"Anthropic API returned status {res.status_code}: {res.text}"

        data = res.json()
        try:
            text_resp = data["content"][0]["text"]
            # strip markdown json fence if present
            text_resp = re.sub(r'^```json\s*', '', text_resp.strip())
            text_resp = re.sub(r'```$', '', text_resp.strip())
            
            usage = data.get("usage", {})
            tokens_used = usage.get("input_tokens", 1000) + usage.get("output_tokens", 100)
            cost_usd = 0.001
            
            parsed = json.loads(text_resp)
            bill = self._dict_to_bill(parsed, tokens_used, cost_usd, engine=f"anthropic:{self.model}")
            return bill, None
        except Exception as e:
            return None, f"Failed to parse Anthropic response: {str(e)}"

    def _dict_to_bill(self, d: dict, tokens: int, cost: float, engine: str) -> ExtractedBill:
        conf_dict = d.get("confidence", {})
        confidences = FieldConfidence(
            vendor=float(conf_dict.get("vendor", 0.95)),
            receipt_date=float(conf_dict.get("receipt_date", 0.95)),
            receipt_number=float(conf_dict.get("receipt_number", 0.95)),
            gstin=float(conf_dict.get("gstin", 0.95)),
            total_amount=float(conf_dict.get("total_amount", 0.95))
        )
        
        return ExtractedBill(
            vendor=str(d.get("vendor", "")).strip(),
            receipt_date=str(d.get("receipt_date", "")).strip(),
            receipt_number=str(d.get("receipt_number", "")).strip(),
            gstin=str(d.get("gstin", "")).strip().upper(),
            total_amount=float(d.get("total_amount", 0.0) or 0.0),
            subtotal=float(d.get("subtotal")) if d.get("subtotal") is not None else None,
            tax=float(d.get("tax")) if d.get("tax") is not None else None,
            rate=float(d.get("rate")) if d.get("rate") is not None else None,
            volume=float(d.get("volume")) if d.get("volume") is not None else None,
            vehicle_no=d.get("vehicle_no"),
            confidences=confidences,
            engine=engine,
            is_degraded=False,
            tokens_used=tokens,
            cost_usd=cost
        )

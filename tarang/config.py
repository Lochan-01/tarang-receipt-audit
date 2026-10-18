import os
from pathlib import Path

# Base paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
IMAGES_DIR = ROOT_DIR / "images"
EVAL_DIR = ROOT_DIR / "eval"
CACHE_DIR = EVAL_DIR / "cache"

# Ensure runtime directories exist
EVAL_DIR.mkdir(exist_ok=True, parents=True)
CACHE_DIR.mkdir(exist_ok=True, parents=True)

# Dataset file locations
TRAIN_CSV = DATA_DIR / "claims_train.csv"
TEST_CSV = DATA_DIR / "claims_test.csv"
EMPLOYEES_CSV = DATA_DIR / "employees.csv"
POLICY_PDF = DATA_DIR / "expense-policy.pdf"
SAMPLE_SUBMISSION_CSV = DATA_DIR / "sample_submission.csv"

# LLM Configuration
# Supports GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Default Models
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"

# Token pricing (USD per 1M tokens as of 2026/latest)
# Gemini 2.5 Flash: $0.075 / 1M input tokens, $0.30 / 1M output tokens (approx Rs 0.008 per receipt)
PRICING = {
    "gemini-2.5-flash": {"input_per_m": 0.075, "output_per_m": 0.30},
    "gemini-1.5-flash": {"input_per_m": 0.075, "output_per_m": 0.30},
    "gpt-4o-mini": {"input_per_m": 0.15, "output_per_m": 0.60},
}
USD_TO_INR = 86.50

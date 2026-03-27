import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root (or parent dirs)
load_dotenv()
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

# X API
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "")
TWEET_ID = "2037554997982871650"
TWEET_AUTHOR = "eglyman"

# Claude API
CLAUDE_MODEL = "claude-sonnet-4-6"  # Fast + cheap for filter/score stages
CLAUDE_MODEL_DEEP = "claude-sonnet-4-6"  # For synthesis where quality matters

# Pipeline
TOP_N_ENRICH = 20  # How many to enrich with full profiles
OUTPUT_DIR = Path(__file__).parent.parent / "website" / "reply-arena"
DATA_DIR = Path(__file__).parent / "data"

# Score weights
SCORE_WEIGHTS = {
    "builder": 0.40,
    "creativity": 0.35,
    "quirkiness": 0.25,
}

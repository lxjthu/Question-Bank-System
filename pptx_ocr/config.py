import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

PADDLEOCR_API_URL = os.getenv("PADDLEOCR_API_URL", "")
PADDLEOCR_TOKEN = os.getenv("PADDLEOCR_TOKEN", "")
PADDLEOCR_TIMEOUT = int(os.getenv("PADDLEOCR_TIMEOUT", "120"))

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
DB_PATH = BASE_DIR / "story_tester.db"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 7788

SCREENSHOTS_DIR.mkdir(exist_ok=True)

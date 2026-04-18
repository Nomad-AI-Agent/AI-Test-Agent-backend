import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
DATABASE_URL = os.environ.get("DATABASE_URL")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 7788

SCREENSHOTS_DIR.mkdir(exist_ok=True)

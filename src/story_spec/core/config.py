import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
DATABASE_URL = os.environ.get("DATABASE_URL")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "screenshots")

DASHBOARD_HOST = os.environ.get("HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("PORT", 7788))

SCREENSHOTS_DIR.mkdir(exist_ok=True)

#!/usr/bin/env python3
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from story_spec.api.server import start

if __name__ == "__main__":
    start()

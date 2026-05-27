"""Setup helper to create langgraph module structure."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
langgraph_dir = root / "src" / "story_spec" / "langgraph"
langgraph_dir.mkdir(parents=True, exist_ok=True)

# Create __init__.py
(langgraph_dir / "__init__.py").touch()

print(f"Created {langgraph_dir}")
print(f"Files: {list(langgraph_dir.glob('*'))}")

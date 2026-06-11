#!/usr/bin/env python3
"""Verify LangSmith tracing setup."""

import sys
sys.path.insert(0, "src")

# Test 1: Import observability
from story_spec.core.observability import setup_langsmith, traceable
print("✓ Observability module imported")

# Test 2: Load environment
from story_spec.core import config
print(f"✓ Config loaded")
print(f"  - LANGSMITH_TRACING: {config.settings.LANGSMITH_TRACING}")
print(f"  - LANGSMITH_PROJECT: {config.settings.LANGSMITH_PROJECT}")
print(f"  - LANGSMITH_API_KEY: {'***' if config.settings.LANGSMITH_API_KEY else 'NOT SET'}")
print(f"  - LANGSMITH_ENDPOINT: {config.settings.LANGSMITH_ENDPOINT}")

# Test 3: Test setup function
setup_langsmith()
print("✓ setup_langsmith() executed successfully")

# Test 4: Check @traceable decorator
@traceable(name="test", run_type="chain")
def test_func():
    return "Hello from traced function"

result = test_func()
print(f"✓ @traceable decorator works: {result}")

print("\n✅ All LangSmith tracing setup verified!")

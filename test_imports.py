#!/usr/bin/env python
"""Test script to verify all refactored modules can be imported."""

import sys

try:
    print("Testing API module imports...")
    from story_spec.api import schemas, events, serializers, screenshots
    print("✓ API modules imported successfully")
    
    print("\nTesting core state imports...")
    from story_spec.core.state import AgentState, ActionSnapshot, LLMDecision
    print("✓ Core state imported successfully")
    
    print("\nTesting runner_utils imports...")
    from story_spec.core.runner_utils import (
        as_bool, contains_any, decision_text, is_high_impact_action,
        same_decision, was_successfully_done_before, selector_still_visible,
        page_has_error_signal, page_has_success_signal, recent_consecutive_action_count,
        extract_entity_name, MAX_SEARCH_SCROLLS
    )
    print("✓ Runner utils imported successfully")
    
    print("\nTesting goal_eval imports...")
    from story_spec.core.goal_eval import (
        recent_missing_entity_failure, coerce_exhausted_search_decision,
        coerce_duplicate_high_impact_decision, infer_goal_status_from_results
    )
    print("✓ Goal eval imported successfully")
    
    print("\nTesting nodes imports...")
    from story_spec.core.nodes import (
        observe_node, reason_node, safety_node, action_node, evaluate_node, done_node,
        route_after_safety, route_after_action
    )
    print("✓ Nodes imported successfully")
    
    print("\nTesting langgraph_runner imports...")
    from story_spec.core import langgraph_runner
    print("✓ LangGraph runner imported successfully")
    
    print("\nTesting agents prompts...")
    from story_spec.agents.prompts import SYSTEM_PROMPT
    print("✓ Prompts imported successfully")
    
    print("\nTesting agents history_formatter...")
    from story_spec.agents.history_formatter import format_action_history
    print("✓ History formatter imported successfully")
    
    print("\nTesting langchain_reasoning...")
    from story_spec.agents.langchain_reasoning import ReasoningChain, get_reasoning_chain
    print("✓ Langchain reasoning imported successfully")
    
    print("\n" + "="*50)
    print("✓ ALL IMPORTS SUCCESSFUL!")
    print("="*50)
    sys.exit(0)
    
except Exception as e:
    print(f"\n✗ Import failed: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)

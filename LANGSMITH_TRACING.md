# LangSmith Tracing Setup Guide

This guide explains how to use LangSmith variables in the environment to trace everything that happens in the AI Test Agent app.

## Overview

LangSmith is a monitoring and debugging platform for LLM applications. It automatically traces:
- **LLM calls** - Every call to the reasoning engine
- **Tool executions** - Browser actions, page analysis, etc.
- **Node execution** - Each step in the LangGraph workflow
- **Chains** - The overall test execution flow
- **Performance metrics** - Latency, token usage, costs

## Environment Variables

All LangSmith configuration is managed through environment variables in `.env`:

```env
# Enable tracing
LANGSMITH_TRACING=true

# LangSmith API endpoint
LANGSMITH_ENDPOINT=https://api.smith.langchain.com

# Your LangSmith API key (get from https://smith.langchain.com)
LANGSMITH_API_KEY=lsv2_pt_<your-key>

# Project name to organize runs
LANGSMITH_PROJECT=testingAgent
```

## Setup Instructions

### 1. Get LangSmith API Key

1. Go to https://smith.langchain.com
2. Sign up / Log in
3. Navigate to Settings → API Keys
4. Create a new API key
5. Copy the key (it starts with `lsv2_pt_`)

### 2. Update .env File

Add or update these variables in your `.env` file:

```env
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_<your-api-key>
LANGSMITH_PROJECT=testingAgent
```

### 3. Start the Application

When the server starts, you'll see:
```
✓ LangSmith tracing initialized
  - Endpoint: https://api.smith.langchain.com
  - Project: testingAgent
```

If you see "LangSmith tracing disabled", check your environment variables.

## What Gets Traced

### Traced Functions

The following functions automatically send traces to LangSmith:

#### **Main Execution**
- `execute()` - Full test run execution
- `execute_test_run()` - Entry point from API

#### **Observation Phase**
- `observe_node()` - Extract page context
- `get_page_context()` - JavaScript DOM analysis
- `format_page_context()` - Structure context for LLM

#### **Reasoning Phase**
- `reason_node()` - LLM decision making
- `decide_next_action()` - LLM prompt + parsing

#### **Safety/Coercion Phase**
- `safety_node()` - Apply guardrails

#### **Action Execution Phase**
- `action_node()` - Execute browser action
- `execute_action()` - Browser action with error handling

#### **Evaluation Phase**
- `evaluate_node()` - Check termination conditions

### Trace Structure

Each run creates a trace tree like:

```
execute_test_run (chain)
├── Step 1: navigate
├── Step 2: observe (tool)
│   ├── get_page_context (tool)
│   └── format_page_context (tool)
├── Step 3: reason (llm)
│   └── decide_next_action (llm)
├── Step 4: safety
├── Step 5: execute_action (tool)
│   └── screenshot
└── Step 6: evaluate
    └── [repeat steps 2-6 until done]
```

## Viewing Traces

### In LangSmith Web UI

1. Go to https://smith.langchain.com
2. Select your project (`testingAgent`)
3. View all traces in real-time
4. Click on any trace to see:
   - **Inputs** - Goal, page context, history
   - **Outputs** - Decision, action, result
   - **Latency** - How long each step took
   - **Tokens** - LLM token usage
   - **Errors** - Any failures with stack traces

### In Application Logs

All traces are also logged to stdout with timing info:

```
[observe] Starting execution
[observe] Completed in 245ms
[reason] Starting execution
[reason] Completed in 3200ms (LLM call)
[execute_action] Starting execution
[execute_action] Completed in 1050ms
```

## Debugging with Traces

### Finding Failed Steps

1. Open trace in LangSmith
2. Look for nodes with red indicators
3. Click to see error messages and stack traces
4. Compare inputs/outputs to understand the failure

### Analyzing Performance

1. Each node shows execution time
2. Compare across multiple runs to find bottlenecks
3. Check `node_timings` in metrics summary
4. Identify which phases need optimization

### Analyzing LLM Behavior

1. View `decide_next_action` traces
2. See the exact prompt sent to the LLM
3. View the raw LLM response
4. Check token usage and cost
5. Analyze reasoning patterns

## Advanced Usage

### Filtering by Project

Runs are organized by project name. You can:
- Change project name in `.env` to separate different test environments
- Create different projects for staging, production, testing
- Use project name as environment identifier

### Custom Tags

The tracing system automatically adds:
- `tags=["main", "runner"]` for main execution
- `tags=["llm"]` for LLM calls
- `tags=["tool"]` for tool executions

You can filter traces by tags in the LangSmith UI.

### Disabling Tracing

To disable tracing without removing the code:

```env
LANGSMITH_TRACING=false
```

The app will log "LangSmith tracing disabled" and continue without sending traces.

## Troubleshooting

### Traces not appearing

1. **Check API Key**: Verify `LANGSMITH_API_KEY` is valid
   ```bash
   echo $LANGSMITH_API_KEY  # On Windows: echo %LANGSMITH_API_KEY%
   ```

2. **Check endpoint**: Should be `https://api.smith.langchain.com`

3. **Check project name**: Verify `LANGSMITH_PROJECT` matches what you see in LangSmith UI

4. **Verify imports**: 
   ```bash
   python -c "from langsmith import traceable; print('✓ LangSmith installed')"
   ```

5. **Check logs**: Look for errors in application startup logs

### Rate limiting

If you hit rate limits:
- Wait a few minutes before re-running tests
- Check your LangSmith plan limits
- Consider batching multiple runs

### Large traces

If traces are too large:
- They're automatically sampled after 1000 steps
- Consider breaking tests into smaller chunks
- Check for infinite loops in the agent

## Dependencies

LangSmith tracing is automatically enabled when these packages are installed:

```
langsmith>=0.0.40
langchain>=0.1.0
langchain-core>=0.1.0
langgraph>=0.0.20
```

These are already in `requirements.txt`.

## Example Workflow

1. **Start app** → Observability initializes LangSmith
2. **Send test request** → API creates run with `run_id`
3. **Agent executes** → Each step is traced with timing/errors
4. **Test completes** → Full trace tree available in LangSmith
5. **View traces** → Go to LangSmith UI to analyze results

## Integration with CI/CD

For automated testing pipelines:

```yaml
# GitHub Actions example
- name: Run tests with LangSmith tracing
  env:
    LANGSMITH_TRACING: true
    LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
    LANGSMITH_PROJECT: ci-testing
  run: npm test
```

## Performance Impact

LangSmith tracing has minimal overhead:
- **Network**: ~50-100ms per trace (batched)
- **CPU**: <1% additional overhead
- **Memory**: ~10MB for trace buffers

No performance impact when `LANGSMITH_TRACING=false`.

## Reference

- **LangSmith Docs**: https://docs.smith.langchain.com
- **LangSmith Dashboard**: https://smith.langchain.com
- **Environment Variables**: See `.env` file
- **Code**: See `src/story_spec/core/observability.py`

## Support

For issues with:
- **LangSmith**: Check https://smith.langchain.com/help
- **LangChain**: See https://docs.langchain.com
- **This app**: Check GitHub issues

---

**Last Updated**: 2024
**Tested With**: LangSmith 0.0.40+, LangChain 0.1.0+

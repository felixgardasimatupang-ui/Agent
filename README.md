# AI Swarm Orchestrator

Multi-agent AI system powered by 9Router. Decomposes tasks, dispatches to specialized agents, aggregates results.

## Architecture

```
User Prompt → Coordinator (plan) → Task Decomposition → Agent Workers → Result Aggregation
                                      ↓
                          ┌───────────┼───────────┐
                          │           │           │
                       Coder      Researcher   Analyst  ...
                     (power)      (murah)     (murah)
```

## Quick Start

```bash
# 1. Set environment
export NINEROUTER_URL="http://localhost:20128"
export NINEROUTER_KEY="sk-your-key"

# 2. Install dependencies
pip install openai rich fastapi uvicorn

# 3. Run
python main_cli.py --prompt "Build a REST API with auth"
```

## Agent Types

| Type | Model | Use Case |
|------|-------|----------|
| CODER | power | Code, functions, modules, endpoints |
| RESEARCHER | murah | Research, investigation, exploration |
| ANALYST | murah | Data analysis, insights, patterns |
| TRANSLATOR | murah | Language translation |
| WRITER | murah | Content, articles, documentation |
| DEBUGGER | power | Debugging, error fixing |
| ARCHITECT | power | System design, architecture |
| SIMPLE | murah | Simple, general tasks |

## Features

- **Smart Routing**: Tasks auto-classified to cheapest capable model
- **SQLite Queue**: Persistent task tracking with retry support
- **Circuit Breaker**: Prevents cascade failures on provider outages
- **Result Aggregation**: Multiple strategies (concatenate, merge, vote, best)
- **Real-time Dashboard**: WebSocket-powered monitoring at `:8000`
- **Structured Logging**: JSON or colored console output

## Commands

```bash
# Interactive mode
python main_cli.py

# Single prompt
python main_cli.py --prompt "Research Python async patterns"

# Specific agents
python main_cli.py --prompt "Analyze this dataset" --agents analyst,coder

# Dashboard only
python main_cli.py --dashboard

# View stats
python main_cli.py --stats
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `NINEROUTER_URL` | `http://localhost:20128` | 9Router endpoint |
| `NINEROUTER_KEY` | - | API key |
| `MODEL_COORDINATOR` | `plan` | Decomposition model |
| `MODEL_COMPLEX` | `power` | Complex task model |
| `MODEL_SIMPLE` | `murah` | Simple task model |
| `MAX_RETRIES` | `3` | Retry attempts |
| `CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before open |

## Project Structure

```
ai-swarm-orchestrator/
├── config.py              # Environment configuration
├── agent_types.py         # Agent types, prompts, classification
├── task_queue.py          # SQLite task persistence
├── result_aggregator.py   # Multi-strategy result merging
├── retry_logic.py         # Exponential backoff + circuit breaker
├── logging_config.py      # Structured logging setup
├── router_engine.py       # 9Router API coordinator
├── swarm_manager.py       # Core orchestration engine
├── dashboard_server.py    # FastAPI WebSocket dashboard
├── main_cli.py            # CLI entry point
├── token_saver.py         # Smart model routing wrapper
├── start.sh               # Quick startup script
├── tests/
│   ├── conftest.py
│   └── test_swarm.py      # 24 unit + integration tests
└── requirements.txt
```

## Testing

```bash
python -m pytest tests/ -v
```

## License

MIT

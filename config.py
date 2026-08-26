"""
Configuration for the AI Swarm Orchestrator.
Centralizes all settings and environment variables.
"""
import os
from pathlib import Path


# ============================================================================
# 9Router Configuration
# ============================================================================
NINEROUTER_URL = os.environ.get("NINEROUTER_URL", "http://localhost:20128")
NINEROUTER_KEY = os.environ.get("NINEROUTER_KEY", "")

ROUTER_BASE_URL = f"{NINEROUTER_URL}/v1"
ROUTER_API_KEY = NINEROUTER_KEY

# ============================================================================
# Model Configuration
# ============================================================================
# Combo models from9Router
MODEL_COORDINATOR = "murah"      # Fast model for task decomposition (JSON output only)
MODEL_COMPLEX = "power"          # Strong model for complex tasks
MODEL_SIMPLE = "murah"           # Cheap model for simple tasks
MODEL_WEB_SEARCH = "tavily/search"
MODEL_EMBEDDING = "fastembed"

# Agent type to model mapping
# Strategy: murah (cheap/fast) for most, power (strong/slow) only for complex tasks
AGENT_MODEL_MAP = {
    # AgentType enum values (used by classify_task_type)
    "coder": MODEL_SIMPLE,
    "researcher": MODEL_SIMPLE,
    "analyst": MODEL_SIMPLE,
    "translator": MODEL_SIMPLE,
    "writer": MODEL_SIMPLE,
    "debugger": MODEL_SIMPLE,
    "architect": MODEL_SIMPLE,
    "simple": MODEL_SIMPLE,
    "web_searcher": MODEL_WEB_SEARCH,
    # Aliases (from LLM output / task_type field)
    "coding": MODEL_SIMPLE,
    "code": MODEL_SIMPLE,
    "debugging": MODEL_SIMPLE,
    "debug": MODEL_SIMPLE,
    "researching": MODEL_SIMPLE,
    "research": MODEL_SIMPLE,
    "analyzing": MODEL_SIMPLE,
    "analysis": MODEL_SIMPLE,
    "architecture": MODEL_SIMPLE,
    "writing": MODEL_SIMPLE,
    "translating": MODEL_SIMPLE,
    "translate": MODEL_SIMPLE,
    "web_search": MODEL_WEB_SEARCH,
    "search": MODEL_WEB_SEARCH,
    "default": MODEL_SIMPLE,
}

# Fallback model chain for multi-provider failover
MODEL_FALLBACK_CHAIN = [MODEL_SIMPLE, MODEL_COMPLEX]

# File upload configuration
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "10"))
ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log", ".yaml", ".yml", ".toml"}

# ============================================================================
# Swarm Configuration
# ============================================================================
DEFAULT_AGENT_COUNT = 10
MAX_CONCURRENT_AGENTS = int(os.environ.get("MAX_CONCURRENT_AGENTS", "10"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "30"))
MAX_CONCURRENT_AGENTS = min(MAX_CONCURRENT_AGENTS, 8)  # cap at 8 for 9Router

# Retry configuration
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))
RETRY_BASE_DELAY = float(os.environ.get("RETRY_BASE_DELAY", "1.0"))
RETRY_MAX_DELAY = float(os.environ.get("RETRY_MAX_DELAY", "20.0"))

# Circuit breaker configuration
CIRCUIT_BREAKER_THRESHOLD = int(os.environ.get("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = float(
    os.environ.get("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "30.0")
)

# ============================================================================
# Dashboard Configuration
# ============================================================================
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8000"))
WEBSOCKET_PATH = "/ws"

# ============================================================================
# Database Configuration
# ============================================================================
BASE_DIR = Path(__file__).parent
DATABASE_DIR = BASE_DIR / "data"
DATABASE_DIR.mkdir(exist_ok=True)

TASK_DB_PATH = str(DATABASE_DIR / "swarm_tasks.db")
LOG_FILE = str(DATABASE_DIR / "swarm.log")

# ============================================================================
# Logging Configuration
# ============================================================================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
JSON_LOG_FORMAT = os.environ.get("JSON_LOG_FORMAT", "false").lower() == "true"

# ============================================================================
# Security Configuration
# ============================================================================
ENABLE_AUTH = os.environ.get("ENABLE_AUTH", "false").lower() == "true"
API_KEY_HEADER = "X-API-Key"
API_KEY = os.environ.get("API_KEY", "")

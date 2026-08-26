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
NINEROUTER_KEY = os.environ.get("NINEROUTER_KEY", "sk-e62fd80253ff2518-kyxcgd-469964b8")

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
    "web_search": MODEL_WEB_SEARCH,
    # Coding agents → murah (fast, good enough for code gen)
    "coding": MODEL_SIMPLE,
    "code": MODEL_SIMPLE,
    # Debug agents → power (need reasoning)
    "debugging": MODEL_COMPLEX,
    "debug": MODEL_COMPLEX,
    # Research → murah (fast)
    "researching": MODEL_SIMPLE,
    "research": MODEL_SIMPLE,
    # Analysis → murah (fast)
    "analyzing": MODEL_SIMPLE,
    "analysis": MODEL_SIMPLE,
    # Architecture → power (need deep thinking)
    "architecture": MODEL_COMPLEX,
    "architect": MODEL_COMPLEX,
    # Writing/translate → murah (fast)
    "writing": MODEL_SIMPLE,
    "writer": MODEL_SIMPLE,
    "translating": MODEL_SIMPLE,
    "translate": MODEL_SIMPLE,
    # Fallbacks
    "simple": MODEL_SIMPLE,
    "default": MODEL_SIMPLE,
}

# ============================================================================
# Swarm Configuration
# ============================================================================
DEFAULT_AGENT_COUNT = 10
MAX_CONCURRENT_AGENTS = int(os.environ.get("MAX_CONCURRENT_AGENTS", "10"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "60"))

# Retry configuration
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
RETRY_BASE_DELAY = float(os.environ.get("RETRY_BASE_DELAY", "1.0"))
RETRY_MAX_DELAY = float(os.environ.get("RETRY_MAX_DELAY", "60.0"))

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

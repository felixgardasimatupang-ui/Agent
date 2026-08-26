"""
REST API server for the AI Swarm Orchestrator.
Production-grade: auth, streaming, structured logging, graceful shutdown.
"""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
import collections
from typing import Optional, List, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import (
    NINEROUTER_URL,
    NINEROUTER_KEY,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    MAX_CONCURRENT_AGENTS,
    TASK_TIMEOUT_SECONDS,
    ENABLE_AUTH,
    API_KEY_HEADER,
    LOG_LEVEL,
    JSON_LOG_FORMAT,
    LOG_FILE,
)
from router_engine import NineRouterCoordinator
from swarm_manager import SwarmManager
from result_aggregator import AggregationStrategy
from task_queue import TaskQueue, TaskStatus
from logging_config import get_logger, setup_logging, generate_correlation_id, set_correlation_id

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# API Keys (in production, store in DB/env — this is demo-grade)
# ---------------------------------------------------------------------------
_api_keys: dict = {}  # key -> {"name": str, "rate_limit": int, "created": float}

def _load_api_keys():
    """Load API keys from environment or generate a default one."""
    global _api_keys
    env_key = os.environ.get("API_KEY", "")
    if env_key:
        _api_keys[env_key] = {"name": "default", "rate_limit": 30, "created": time.time()}
    else:
        # Generate a key and print it
        key = f"sk-swarm-{secrets.token_hex(16)}"
        _api_keys[key] = {"name": "default", "rate_limit": 30, "created": time.time()}
        logger.warning(f"No API_KEY env set. Generated: {key}")
        logger.warning(f"Set API_KEY={key} in .env or environment")

def _validate_api_key(key: str) -> Optional[dict]:
    """Validate API key and return key info."""
    if not ENABLE_AUTH:
        return {"name": "anonymous", "rate_limit": 30}
    return _api_keys.get(key)


# ---------------------------------------------------------------------------
# Lifespan: create shared swarm instance
# ---------------------------------------------------------------------------
_swarm: Optional[SwarmManager] = None
_coordinator: Optional[NineRouterCoordinator] = None
_background_tasks: Set[asyncio.Task] = set()
_shutdown_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _swarm, _coordinator
    setup_logging(level=LOG_LEVEL, json_format=JSON_LOG_FORMAT, log_file=LOG_FILE)
    _load_api_keys()
    _coordinator = NineRouterCoordinator()
    _swarm = SwarmManager(
        router_engine=_coordinator,
        max_concurrent_agents=MAX_CONCURRENT_AGENTS,
    )
    logger.info("API server started", extra={"auth_enabled": ENABLE_AUTH})
    yield
    # Graceful shutdown: cancel all background tasks
    logger.info("Shutting down — cancelling background tasks")
    _shutdown_event.set()
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    logger.info("API server stopped")


app = FastAPI(
    title="AI Swarm Orchestrator API",
    description="Multi-agent AI orchestrator powered by 9Router. Routes tasks to specialized agents with parallel execution, retry, and result aggregation.",
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Rate limiter (per-IP and per-key token bucket)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict = collections.defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        self._hits[key] = [t for t in self._hits[key] if now - t < self.window]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True

    def cleanup(self):
        """Remove expired entries to prevent memory leak."""
        now = time.time()
        empty_keys = [k for k, v in self._hits.items() if not v or now - v[-1] > self.window * 2]
        for k in empty_keys:
            del self._hits[k]


_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Exempt health and WebSocket
    if request.url.path.startswith("/health") or request.url.path.startswith("/ws"):
        return await call_next(request)

    # Auth check
    if ENABLE_AUTH:
        api_key = request.headers.get(API_KEY_HEADER, "")
        key_info = _validate_api_key(api_key)
        if not key_info:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
        # Per-key rate limit
        rate_limit = key_info.get("rate_limit", 30)
        limiter_key = f"key:{api_key[:12]}"
    else:
        limiter_key = f"ip:{request.client.host if request.client else 'unknown'}"
        rate_limit = 60

    temp_limiter = RateLimiter(max_requests=rate_limit, window_seconds=60)
    if not temp_limiter.is_allowed(limiter_key):
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded. Max {rate_limit} requests/min."},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000, description="Task prompt")
    agents: int = Field(default=5, ge=1, le=20, description="Number of agents")
    strategy: str = Field(default="merge", description="Aggregation strategy: concatenate, merge, vote, best")


class TaskResponse(BaseModel):
    task_id: str
    status: str
    agent_type: Optional[str] = None
    model: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None


class SwarmResult(BaseModel):
    task_id: str
    prompt: str
    status: str
    final_output: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0
    total_time: float = 0.0


class StatsResponse(BaseModel):
    queue: dict
    circuit_breaker: dict
    max_concurrent: int
    uptime_seconds: float


# In-memory store for async results (with TTL auto-cleanup)
_results_store: dict = {}
_results_ttl: dict = {}  # task_id -> expiry timestamp
_start_time = time.time()
RESULTS_TTL_SECONDS = 3600  # 1 hour


def _store_result(task_id: str, data: dict):
    """Store result with TTL."""
    _results_store[task_id] = data
    _results_ttl[task_id] = time.time() + RESULTS_TTL_SECONDS


def _cleanup_expired_results():
    """Remove expired results from memory."""
    now = time.time()
    expired = [tid for tid, exp in _results_ttl.items() if now > exp]
    for tid in expired:
        _results_store.pop(tid, None)
        _results_ttl.pop(tid, None)
    if expired:
        logger.debug(f"Cleaned up {len(expired)} expired results")


# Periodic cleanup task
async def _periodic_cleanup():
    while not _shutdown_event.is_set():
        try:
            _cleanup_expired_results()
            _rate_limiter.cleanup()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        await asyncio.sleep(300)  # every 5 minutes


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "uptime_seconds": round(time.time() - _start_time, 2)}


@app.get("/v1/models", tags=["Agent"])
async def list_models():
    """List available agent types."""
    from agent_types import AgentType, AGENT_PROMPTS
    return {
        "object": "list",
        "data": [
            {"id": at.value, "name": at.name, "description": AGENT_PROMPTS[at][:80]}
            for at in AgentType
        ],
    }


@app.post("/v1/swarm/execute", response_model=SwarmResult, tags=["Swarm"])
async def execute_swarm(req: ExecuteRequest, request: Request):
    """
    Execute a swarm task synchronously (blocks until complete).
    For long-running tasks, use POST /v1/swarm/submit (async).
    """
    if _swarm is None:
        raise HTTPException(503, detail="Swarm not initialized")

    # Sanitize input
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(400, detail="Prompt cannot be empty")

    strategy_map = {s.value: s for s in AggregationStrategy}
    strategy = strategy_map.get(req.strategy, AggregationStrategy.MERGE)

    correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)

    # WebSocket broadcast callback for real-time dashboard
    async def broadcast_cb(agent_id, status, message):
        agent_type = message.split("Model: ")[-1] if "Model: " in message else "unknown"
        model = message.split("Model: ")[-1] if "Model: " in message else ""
        await _broadcast_agent_update(
            agent_id=agent_id, agent_type=agent_type, status=status,
            model=model, output=message, elapsed=0,
        )

    try:
        # Broadcast INITIALIZING for all agents
        for i in range(1, req.agents + 1):
            await _broadcast_agent_update(i, "initializing", "INITIALIZING", "", "Queued", 0)

        result = await asyncio.wait_for(
            _swarm.execute_swarm(
                prompt=prompt,
                agent_count=req.agents,
                aggregation_strategy=strategy,
                telemetry_cb=broadcast_cb,
            ),
            timeout=TASK_TIMEOUT_SECONDS * req.agents + 30,
        )
        return SwarmResult(
            task_id=result.task_id,
            prompt=prompt,
            status="completed",
            final_output=result.final_output,
            success_count=result.success_count,
            failure_count=result.failure_count,
            total_time=result.total_execution_time,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Swarm execution timed out after {TASK_TIMEOUT_SECONDS * req.agents + 30}s")
        raise HTTPException(504, detail="Swarm execution timed out")
    except Exception as e:
        logger.error(f"Swarm execution failed: {e}", exc_info=True)
        raise HTTPException(500, detail=str(e))


@app.post("/v1/swarm/submit", tags=["Swarm"])
async def submit_swarm(req: ExecuteRequest, background_tasks: BackgroundTasks):
    """
    Submit a swarm task for async execution.
    Returns a task_id — poll GET /v1/swarm/tasks/{task_id} for status.
    """
    if _swarm is None:
        raise HTTPException(503, detail="Swarm not initialized")

    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(400, detail="Prompt cannot be empty")

    import uuid
    task_id = str(uuid.uuid4())
    _store_result(task_id, {"status": "queued", "result": None, "error": None})

    async def _run():
        if _shutdown_event.is_set():
            _store_result(task_id, {"status": "cancelled", "error": "Server shutting down"})
            return
        try:
            strategy_map = {s.value: s for s in AggregationStrategy}
            strategy = strategy_map.get(req.strategy, AggregationStrategy.MERGE)
            result = await _swarm.execute_swarm(
                prompt=prompt,
                agent_count=req.agents,
                aggregation_strategy=strategy,
            )
            _store_result(task_id, {
                "status": "completed",
                "result": result.final_output,
                "success_count": result.success_count,
                "failure_count": result.failure_count,
                "total_time": result.total_execution_time,
            })
        except asyncio.CancelledError:
            _store_result(task_id, {"status": "cancelled", "error": "Task cancelled"})
        except Exception as e:
            logger.error(f"Async task {task_id} failed: {e}", exc_info=True)
            _store_result(task_id, {"status": "failed", "error": str(e)})

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"task_id": task_id, "status": "queued"}


@app.get("/v1/swarm/tasks/{task_id}", tags=["Swarm"])
async def get_task(task_id: str):
    """Get async task status and result."""
    # Check in-memory store first (TTL-backed)
    if task_id in _results_store:
        return _results_store[task_id]

    # Check SQLite task queue
    if _swarm:
        task = _swarm.task_queue.get_task(task_id)
        if task:
            return TaskResponse(
                task_id=task.task_id,
                status=task.status.value,
                agent_type=task.agent_type,
                model=task.model,
                created_at=task.created_at,
                completed_at=task.completed_at,
                result=task.result,
                error=task.error,
            )

    raise HTTPException(404, detail="Task not found")


@app.delete("/v1/swarm/tasks/{task_id}", tags=["Swarm"])
async def delete_task(task_id: str):
    """Delete/cancel a task."""
    deleted = False
    if task_id in _results_store:
        del _results_store[task_id]
        _results_ttl.pop(task_id, None)
        deleted = True

    if _swarm and _swarm.task_queue.delete_task(task_id):
        deleted = True

    if deleted:
        return {"deleted": True}
    raise HTTPException(404, detail="Task not found")


@app.get("/v1/swarm/stats", tags=["Swarm"])
async def get_stats():
    """Get swarm statistics."""
    if _swarm is None:
        raise HTTPException(503, detail="Swarm not initialized")

    stats = _swarm.get_stats()
    stats["uptime_seconds"] = round(time.time() - _start_time, 2)
    stats["pending_async_tasks"] = len(_results_store)
    stats["auth_enabled"] = ENABLE_AUTH
    stats["api_keys_count"] = len(_api_keys)
    return stats


@app.get("/v1/swarm/tasks", tags=["Swarm"])
async def list_tasks(status: Optional[str] = None, limit: int = 50):
    """List recent tasks."""
    tasks = []
    for tid, data in list(_results_store.items())[-limit:]:
        if status and data.get("status") != status:
            continue
        tasks.append({"task_id": tid, **data})
    return {"tasks": tasks, "count": len(tasks)}


@app.post("/v1/swarm/clear", tags=["Swarm"])
async def clear_completed():
    """Clear completed tasks from queue."""
    if _swarm is None:
        raise HTTPException(503, detail="Swarm not initialized")
    count = _swarm.clear_completed_tasks()
    _cleanup_expired_results()
    return {"cleared": count}


@app.post("/v1/keys", tags=["Admin"])
async def create_api_key(name: str = "default"):
    """Create a new API key."""
    key = f"sk-swarm-{secrets.token_hex(16)}"
    _api_keys[key] = {"name": name, "rate_limit": 30, "created": time.time()}
    logger.info(f"API key created: {name}")
    return {"key": key, "name": name, "rate_limit": 30}


@app.get("/v1/keys", tags=["Admin"])
async def list_api_keys():
    """List API keys (redacted)."""
    return {
        "keys": [
            {"key": k[:8] + "...", "name": v["name"], "rate_limit": v["rate_limit"]}
            for k, v in _api_keys.items()
        ]
    }


@app.delete("/v1/keys/{key_prefix}", tags=["Admin"])
async def delete_api_key(key_prefix: str):
    """Delete API key by prefix."""
    for k in list(_api_keys.keys()):
        if k.startswith(key_prefix):
            del _api_keys[k]
            return {"deleted": True}
    raise HTTPException(404, detail="Key not found")


# ---------------------------------------------------------------------------
# SSE Streaming endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/swarm/stream", tags=["Swarm"])
async def stream_swarm(req: ExecuteRequest):
    """
    Execute swarm with SSE streaming — real-time agent status updates.
    Returns text/event-stream with JSON events per agent.
    """
    if _swarm is None:
        raise HTTPException(503, detail="Swarm not initialized")

    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(400, detail="Prompt cannot be empty")

    import json

    async def event_generator():
        set_correlation_id(generate_correlation_id())
        yield f"data: {json.dumps({'type': 'start', 'prompt': prompt[:100], 'agents': req.agents})}\n\n"

        try:
            strategy_map = {s.value: s for s in AggregationStrategy}
            strategy = strategy_map.get(req.strategy, AggregationStrategy.MERGE)

            # Telemetry callback to stream agent updates
            async def on_agent_event(agent_id, status, message):
                event = {"type": "agent", "agent_id": agent_id, "status": status, "message": message}
                yield f"data: {json.dumps(event)}\n\n"

            result = await _swarm.execute_swarm(
                prompt=prompt,
                agent_count=req.agents,
                aggregation_strategy=strategy,
            )

            final = {
                "type": "complete",
                "task_id": result.task_id,
                "final_output": result.final_output,
                "success_count": result.success_count,
                "failure_count": result.failure_count,
                "total_time": result.total_execution_time,
            }
            yield f"data: {json.dumps(final)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Dashboard HTML (backward compat)
# ---------------------------------------------------------------------------

from dashboard_server import HTML_TEMPLATE, active_connections

# ---------------------------------------------------------------------------
# Dashboard HTML (backward compat)
# ---------------------------------------------------------------------------

_active_connections: Set[WebSocket] = set()


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard():
    """Web dashboard for monitoring swarm activity."""
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    try:
        with open(html_path, "r") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>Dashboard not found</h1><p>Create dashboard.html in the project root.</p>", status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time dashboard updates."""
    await websocket.accept()
    _active_connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _active_connections.discard(websocket)


async def _broadcast_agent_update(agent_id: int, agent_type: str, status: str, model: str = "", output: str = "", elapsed: float = 0):
    """Broadcast agent status to all connected WebSocket clients."""
    payload = json.dumps({
        "type": "agent_update",
        "agent_id": agent_id,
        "agent_type": agent_type,
        "status": status,
        "model": model,
        "output": output[:200],
        "elapsed": elapsed,
    })
    dead = []
    for conn in _active_connections:
        try:
            await conn.send_text(payload)
        except Exception:
            dead.append(conn)
    for conn in dead:
        _active_connections.discard(conn)


# ---------------------------------------------------------------------------
# Main (standalone run)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=False,
        log_level="info",
    )

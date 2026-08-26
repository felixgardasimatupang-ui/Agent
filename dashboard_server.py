from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
import json
import time

app = FastAPI()
_start_time = time.time()
active_connections: set[WebSocket] = set()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Swarm Live Matrix</title>
    <style>
        body { background: #0b0f19; color: #00f0ff; font-family: monospace; padding: 20px; margin: 0; }
        h2 { border-bottom: 1px solid #00f0ff33; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
        .card {
            border: 1px solid #00f0ff33; padding: 12px; border-radius: 6px;
            background: #111827; transition: all 0.3s ease;
        }
        .IDLE      { border-color: #6b7280; color: #9ca3af; }
        .INITIALIZING { border-color: #facc15; color: #fde047; box-shadow: 0 0 8px #facc1533; }
        .PROCESSING   { border-color: #38bdf8; color: #7dd3fc; box-shadow: 0 0 12px #38bdf844; animation: pulse 1.5s infinite; }
        .COMPLETE     { border-color: #22c55e; color: #4ade80; }
        .FAILED       { border-color: #ef4444; color: #f87171; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
    </style>
</head>
<body>
    <h2>AI DEPLOYMENT MATRIX (LIVE TELEMETRY)</h2>
    <div id="matrix" class="grid"></div>
    <script>
        const ws = new WebSocket(`ws://${location.host}/ws`);
        ws.onmessage = (event) => {
            const d = JSON.parse(event.data);
            let el = document.getElementById("agent-" + d.agent_id);
            if (!el) {
                el = document.createElement("div");
                el.id = "agent-" + d.agent_id;
                document.getElementById("matrix").appendChild(el);
            }
            el.className = "card " + d.status;
            el.innerHTML = `<b>Agent #${d.agent_id}</b><br><small>${d.status}</small><br><small style="color:#6b7280">${d.details}</small>`;
        };
        ws.onclose = () => {
            document.getElementById("matrix").insertAdjacentHTML("beforeend",
                '<div class="card FAILED"><b>DISCONNECTED</b><br><small>Reconnecting...</small></div>');
        };
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return HTMLResponse(HTML_TEMPLATE)


@app.get("/health")
async def health_check():
    return JSONResponse({
        "status": "healthy",
        "uptime_seconds": round(time.time() - _start_time, 2),
        "active_connections": len(active_connections),
    })


@app.get("/api/stats")
async def api_stats():
    return JSONResponse({
        "uptime_seconds": round(time.time() - _start_time, 2),
        "active_connections": len(active_connections),
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)


async def broadcast_status(agent_id: int, status: str, details: str):
    payload = json.dumps({"agent_id": agent_id, "status": status, "details": details})
    dead = []
    for conn in active_connections:
        try:
            await conn.send_text(payload)
        except Exception:
            dead.append(conn)
    for conn in dead:
        active_connections.discard(conn)

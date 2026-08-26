#!/bin/bash
set -euo pipefail

echo "=== AI Swarm Orchestrator ==="
echo ""

# --- Env validation ---
missing=()
[ -z "${NINEROUTER_URL:-}" ] && missing+=("NINEROUTER_URL")
[ -z "${NINEROUTER_KEY:-}" ] && missing+=("NINEROUTER_KEY")

if [ ${#missing[@]} -gt 0 ]; then
    echo "⚠  Missing env vars: ${missing[*]}"
    echo "   Copy .env.example → .env and fill in values"
    echo "   export NINEROUTER_URL=http://localhost:20128"
    echo "   export NINEROUTER_KEY=sk-..."
    echo ""
fi

# Default URL
export NINEROUTER_URL="${NINEROUTER_URL:-http://localhost:20128}"

# --- Check9Router ---
if curl -sf "${NINEROUTER_URL}/api/health" > /dev/null 2>&1; then
    echo "✓ 9Router running at ${NINEROUTER_URL}"
else
    echo "✗ 9Router not reachable at ${NINEROUTER_URL}"
    echo "  Start it first: 9router --port 20128 --no-browser --tray"
    exit 1
fi

# --- Model count ---
model_count=$(curl -sf "${NINEROUTER_URL}/v1/models" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "?")
echo "  Models loaded: ${model_count}"
echo ""

echo "=== Dashboard ==="
echo "  http://localhost:8000"
echo ""
echo "=== Commands ==="
echo "  python3 main_cli.py --prompt 'Build a REST API'"
echo "  python3 main_cli.py --dashboard"
echo "  python3 main_cli.py --stats"
echo "  python3 token_saver.py"
echo ""

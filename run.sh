#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
source venv/bin/activate

echo "=== mu ==="
echo ""

# Check which mode is configured
MODE=$(python3 -c "import yaml; print(yaml.safe_load(open('config.yaml'))['mode'])")
echo "Mode: $MODE"

# Check if Ollama is running (needed for embeddings always, and LLM in local mode)
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Warning: Ollama not detected at localhost:11434"
    echo "Start Ollama (required for embeddings)."
    echo ""
fi

# Kill any existing instance on port 7860
existing=$(lsof -ti :7860 2>/dev/null || true)
if [ -n "$existing" ]; then
    echo "Stopping existing instance (pid $existing)..."
    kill "$existing" 2>/dev/null || true
    sleep 1
fi

echo "Starting mu on http://localhost:7860"
echo ""
python -m app.main

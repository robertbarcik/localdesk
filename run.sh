#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
source venv/bin/activate

echo "=== mu ==="
echo ""

# Check if Ollama is running (needed for embeddings, and local LLM mode)
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Warning: Ollama not detected at localhost:11434"
    echo "Start Ollama and ensure nomic-embed-text is pulled."
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

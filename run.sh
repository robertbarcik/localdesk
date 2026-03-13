#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
source venv/bin/activate

echo "=== LocalDesk ==="
echo ""

# Check if llama-server is running
if ! curl -s http://localhost:8080/health >/dev/null 2>&1; then
    echo "Warning: llama-server not detected at localhost:8080"
    echo "Start it with:"
    echo "  llama-server -m <path-to-qwen3.5-4b.gguf> --port 8080 --tool-call-parser qwen3_coder"
    echo ""
fi

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Warning: Ollama not detected at localhost:11434"
    echo "Start Ollama and ensure nomic-embed-text is pulled."
    echo ""
fi

echo "Starting LocalDesk on http://localhost:7860"
echo ""
python -m app.main

#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== LocalDesk Setup ==="

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

echo "Activating venv and installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

# Ensure Ollama is running and has the embedding model
echo "Checking Ollama embedding model..."
if command -v ollama &>/dev/null; then
    ollama pull nomic-embed-text 2>/dev/null || echo "Note: Could not pull nomic-embed-text. Make sure Ollama is running."
else
    echo "Warning: Ollama not found. Install Ollama and run 'ollama pull nomic-embed-text'"
fi

# Seed database
echo "Seeding database..."
python scripts/seed_db.py

# Ingest knowledge base
echo "Ingesting knowledge base into ChromaDB..."
python scripts/ingest.py

echo ""
echo "=== Setup complete! ==="
echo "Run ./run.sh to start the application."

# LocalDesk

A fully local AI-powered IT service desk prototype demonstrating RAG, function calling, and security guardrails — all running on a laptop with zero cloud dependency.

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) (for embedding model)
- [llama.cpp](https://github.com/ggerganov/llama.cpp) (for LLM inference via llama-server)
- Qwen3.5-4B GGUF model file (Q4_K_M quantization recommended)

### Download the model

Download the Qwen3.5-4B Q4_K_M GGUF file from HuggingFace. Place it anywhere on your machine — you'll pass the path to llama-server.

## Setup

```bash
# 1. Pull the embedding model
ollama pull nomic-embed-text

# 2. Run the setup script (creates venv, installs deps, seeds DB, ingests KB)
chmod +x setup.sh run.sh
./setup.sh
```

## Running

```bash
# 1. Start Ollama (if not already running)
ollama serve

# 2. Start llama-server with Qwen3.5-4B
llama-server \
  -m /path/to/qwen3.5-4b-q4_k_m.gguf \
  --port 8080 \
  --tool-call-parser qwen3_coder

# 3. Start LocalDesk
./run.sh
```

Open http://localhost:7860 in your browser.

## Local/Cloud Mode

Edit `config.yaml` to switch between local inference and cloud (OpenRouter):

```yaml
mode: "local"   # or "cloud"
```

For cloud mode, set the `OPENROUTER_API_KEY` environment variable.

## Architecture

```
User → Input Guardrails → LLM + Tools → Output Guardrails → LLM Judge → User
                                              ↓
                                        Audit Log (JSONL)
```

**Tools available to the agent:**
- `search_kb` — RAG search over knowledge base (ChromaDB)
- `check_sla` — Look up SLA response/resolution times
- `create_incident` — Create incident tickets (SQLite)
- `lookup_asset` — Look up employee hardware/software
- `escalate_ticket` — Escalate an existing ticket

**3-layer guardrail pipeline:**
1. Static input filters (PII redaction, prompt injection detection)
2. Static output filters (SLA hallucination check, output PII detection)
3. LLM-as-judge (grounding, commitments, tone)

Every interaction is logged to `logs/audit.jsonl` for audit compliance.

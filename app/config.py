import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env file if present
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

_config_path = PROJECT_ROOT / "config.yaml"

with open(_config_path) as f:
    _raw = yaml.safe_load(f)


def _expand(val: str) -> str:
    if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
        return os.environ.get(val[2:-1], "")
    return val


MODE: str = _raw.get("mode", "local")

_mode_cfg = _raw.get(MODE, {})
LLM_BASE_URL: str = _expand(_mode_cfg.get("base_url", ""))
LLM_MODEL: str = _expand(_mode_cfg.get("model", ""))
LLM_API_KEY: str = _expand(_mode_cfg.get("api_key", "not-needed"))

EMBEDDING_MODEL: str = _raw["embedding"]["model"]
EMBEDDING_BASE_URL: str = _raw["embedding"]["base_url"]

VECTORSTORE_PATH: str = str(PROJECT_ROOT / _raw["vectorstore"]["path"])
VECTORSTORE_COLLECTION: str = _raw["vectorstore"]["collection"]

DATABASE_PATH: str = str(PROJECT_ROOT / _raw["database"]["path"])

AUDIT_LOG_PATH: str = str(PROJECT_ROOT / _raw["audit"]["path"])

SERVER_HOST: str = _raw["server"]["host"]
SERVER_PORT: int = _raw["server"]["port"]

"""Central configuration, loaded from the repo-root .env.

Every module reads settings from here so the whole system has one source of truth.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# repo root = two levels up from this file (agent/nova_agent/config.py)
REPO_ROOT = Path(__file__).resolve().parents[2]
# .env is the single source of truth for the app; override any stale ambient vars.
load_dotenv(REPO_ROOT / ".env", override=True)


def _get(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(f"Required environment variable {name} is not set (see .env.example)")
    return val


class Settings:
    # --- Mongo ---
    mongodb_uri: str = _get("MONGODB_URI", "mongodb://localhost:27017/")
    mongodb_db: str = _get("MONGODB_DB", "nova_rca")

    # --- Atlas Admin API (search index management) ---
    atlas_pub_key: str = os.getenv("ATLAS_PUB_KEY", "")
    atlas_priv_key: str = os.getenv("ATLAS_PRIV_KEY", "")
    atlas_group_id: str = os.getenv("ATLAS_GROUP_ID", "")
    atlas_cluster: str = os.getenv("ATLAS_CLUSTER", "")

    # --- Grove LLM ---
    grove_base_url: str = os.getenv(
        "GROVE_BASE_URL",
        "https://grove-gateway-prod.azure-api.net/grove-foundry-prod/openai/v1",
    )
    grove_api_key: str = os.getenv("GROVE_API_KEY", "")
    grove_model: str = os.getenv("GROVE_MODEL", "gpt-5.4-mini")
    llm_fast_model: str = os.getenv("LLM_FAST_MODEL", os.getenv("GROVE_MODEL", "gpt-5.4-mini"))
    llm_reasoning_model: str = os.getenv(
        "LLM_REASONING_MODEL", os.getenv("GROVE_MODEL", "gpt-5.4-mini")
    )
    llm_vision_model: str = os.getenv("LLM_VISION_MODEL", "gpt-4o-mini")
    grove_structured_mode: str = os.getenv("GROVE_STRUCTURED_MODE", "json_schema")
    grove_max_retries: int = int(os.getenv("GROVE_MAX_RETRIES", "3"))
    grove_timeout_seconds: int = int(os.getenv("GROVE_TIMEOUT_SECONDS", "60"))
    # If GROVE_SEND_TEMPERATURE is unset/empty, temperature is omitted entirely.
    grove_send_temperature: float | None = (
        float(os.environ["GROVE_SEND_TEMPERATURE"])
        if os.getenv("GROVE_SEND_TEMPERATURE", "").strip() != ""
        else None
    )

    # --- Agent tuning ---
    debounce_window_seconds: float = float(os.getenv("DEBOUNCE_WINDOW_SECONDS", "4"))
    collect_window_seconds: float = float(os.getenv("COLLECT_WINDOW_SECONDS", "120"))
    recall_min_vector_score: float = float(os.getenv("RECALL_MIN_VECTOR_SCORE", "0.72"))
    agent_port: int = int(os.getenv("AGENT_PORT", "8000"))
    ui_port: int = int(os.getenv("UI_PORT", "5173"))
    replay_mode: bool = os.getenv("REPLAY_MODE", "0") == "1"
    chat_lookback_minutes: int = int(os.getenv("CHAT_LOOKBACK_MINUTES", "30"))

    # --- Collection names (single source of truth) ---
    C_TXN = "audit_transaction"
    C_ERR = "audit_error"
    C_SVC = "audit_service"
    C_METRICS = "service_metrics"
    C_INCIDENTS = "incidents"
    C_MEMORY = "incident_memory"
    C_KB = "kb_docs"
    C_FEEDBACK = "feedback"
    C_STATE = "agent_state"
    C_CHECKPOINTS = "checkpoints"
    C_CHECKPOINT_WRITES = "checkpoint_writes"
    C_STORE = "store"
    C_CHAT = "chat_sessions"
    C_CHAT_IMG = "chat_images"

    # --- Search index names ---
    IDX_ERR_SEARCH = "audit_error_search"
    IDX_SVC_SEARCH = "audit_service_search"
    IDX_MEM_SEARCH = "incident_memory_search"
    IDX_KB_SEARCH = "kb_docs_search"
    IDX_MEM_VECTOR = "incident_memory_vector"
    IDX_KB_VECTOR = "kb_docs_vector"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
